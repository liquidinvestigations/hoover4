"""The shared Hoover stores of a site: the site file keys, the plan checks and the render of shared.py."""
import json

import pytest

from conftest import site_text

import config  # noqa: E402
import service_users  # noqa: E402
import shared  # noqa: E402


def remote(stores=''):
    """The remote fixture site with an optional vars.stores mapping."""
    text = site_text('remote.yml')
    if stores:
        text = text.replace('    gpu_pool:\n', f'    stores: {stores}\n    gpu_pool:\n')
    return config.parse(text)


def by(items, kind, name):
    return next(i for i in items if i['kind'] == kind and i['metadata']['name'] == name)


def test_the_plan_defaults_come_from_the_worker_nodes():
    plan = config.store_plan(remote())
    # The worker nodes with a storage tier, in the order of the site file. The calls and GPU nodes hold no store.
    assert plan == {'nodes': ('server-a', 'worker-b', 'edge'), 'replicas': 3, 'failover': False, 'history_shards': 128}
    assert config.store_plan(remote('{nodes: [server-a, worker-b], failover: true, history_shards: 512}')) == {
        'nodes': ('server-a', 'worker-b'), 'replicas': 2, 'failover': True, 'history_shards': 512}


def test_the_site_file_refuses_impossible_store_plans():
    for stores, message in (('{replicas: 4}', 'vars.stores replicas = 4 is more than its 3 nodes'),
                            ('{nodes: [calls]}', 'vars.stores nodes names calls, which has no storage tier'),
                            ('{nodes: [nowhere]}', 'vars.stores nodes names nowhere, which is not a node'),
                            ('{replicas: 0}', 'vars.stores replicas = 0 must be a whole number of at least 1'),
                            ('{copies: 2}', 'vars.stores copies is not a known key')):
        with pytest.raises(config.SiteError, match=message):
            remote(stores)


def test_two_nodes_warn_that_failover_needs_three():
    warnings = config.store_warnings(remote('{nodes: [server-a, worker-b]}'))
    assert any('Automatic failover needs 3 nodes' in w for w in warnings)
    assert any('ClickHouse runs one copy' in w for w in warnings)
    assert config.store_warnings(remote('{nodes: [server-a], replicas: 1}')) == []


def test_failover_cannot_be_turned_off_and_garage_keeps_its_replication_factor():
    plan = config.store_plan(remote('{nodes: [server-a, worker-b]}'))
    assert config.store_change_problems(None, plan) == []
    assert config.store_change_problems({'failover': False, 'garage_replication_factor': 2}, plan) == []
    problems = config.store_change_problems({'failover': True, 'garage_replication_factor': 3}, plan)
    assert problems == ['the shared stores run with failover. vars.stores failover cannot change back to false.',
                        'Garage keeps the replication factor 3 of its creation. Set vars.stores replicas to 3.']
    # Failover can be turned on.
    on = dict(plan, failover=True)
    assert config.store_change_problems({'failover': False, 'garage_replication_factor': 2}, on) == []


def test_the_site_file_round_trip_keeps_the_store_keys():
    site = remote('{nodes: [server-a, worker-b], replicas: 2, failover: true}')
    assert config.parse(config.dump(site)).stores == {'nodes': ('server-a', 'worker-b'), 'replicas': 2, 'failover': True}


def test_garage_replicates_on_separate_nodes_and_failover_off_pins_the_clients():
    site = remote('{nodes: [server-a, worker-b]}')
    plan = config.store_plan(site)
    items = shared.objects(site, plan, 3, {'garage-0': 'a' * 64, 'garage-1': 'b' * 64})
    garage = by(items, 'StatefulSet', 'garage')
    spec = garage['spec']['template']['spec']
    assert garage['metadata']['namespace'] == 'hoover-stores' and garage['spec']['replicas'] == 2
    assert garage['spec']['serviceName'] == 'garage-peers' and spec['runtimeClassName'] == 'kata'
    anti = spec['affinity']['podAntiAffinity']['requiredDuringSchedulingIgnoredDuringExecution'][0]
    assert anti['topologyKey'] == 'kubernetes.io/hostname' and anti['labelSelector'] == {'matchLabels': {'hoover.dev/store': 'garage'}}
    nodes = spec['affinity']['nodeAffinity']['requiredDuringSchedulingIgnoredDuringExecution']['nodeSelectorTerms'][0]
    assert nodes['matchExpressions'][0]['values'] == ['server-a', 'worker-b']
    # Both nodes have the tier hdd, the first preferred tier of Garage. The claim grows with the zone count.
    claim = garage['spec']['volumeClaimTemplates'][0]['spec']
    assert claim['storageClassName'] == 'hdd-block' and claim['resources']['requests']['storage'] == '60Gi'
    toml = by(items, 'ConfigMap', 'garage-config')['data']['garage.toml']
    assert 'replication_factor = 2' in toml
    assert f'"{"a" * 64}@garage-0.garage-peers.hoover-stores.svc.cluster.local:3901"' in toml
    assert by(items, 'Service', 'garage')['spec']['selector'] == {'app.kubernetes.io/name': 'garage',
                                                                   'statefulset.kubernetes.io/pod-name': 'garage-0'}
    peers = by(items, 'Service', 'garage-peers')['spec']
    assert peers['clusterIP'] == 'None' and peers['publishNotReadyAddresses'] is True
    clickhouse = by(items, 'StatefulSet', 'clickhouse')
    assert clickhouse['spec']['replicas'] == 1
    assert clickhouse['spec']['volumeClaimTemplates'][0]['spec']['resources']['requests']['storage'] == '60Gi'
    on = shared.objects(site, dict(plan, failover=True), 0, {})
    assert by(on, 'Service', 'garage')['spec']['selector'] == {'app.kubernetes.io/name': 'garage'}
    # A site without a zone still sizes the stores for one zone.
    assert by(on, 'StatefulSet', 'garage')['spec']['volumeClaimTemplates'][0]['spec']['resources']['requests']['storage'] == '20Gi'
    assert 'bootstrap_peers = []' in by(on, 'ConfigMap', 'garage-config')['data']['garage.toml']


def test_garage_needs_a_tier_on_as_many_nodes_as_copies():
    # Only server-a and worker-b have hdd, and edge has only nvme, so three copies find no common tier.
    site = remote()
    with pytest.raises(SystemExit, match='fewer than 3 store nodes have one tier'):
        shared.objects(site, config.store_plan(site), 1, {})


def test_only_hoover_namespaces_reach_the_client_ports():
    site = remote('{nodes: [server-a, worker-b]}')
    items = shared.objects(site, config.store_plan(site), 1, {})
    closed = by(items, 'NetworkPolicy', 'closed')['spec']
    assert closed['podSelector'] == {} and closed['ingress'] == [] and set(closed['policyTypes']) == {'Ingress', 'Egress'}
    clickhouse = by(items, 'NetworkPolicy', 'clickhouse-clients')['spec']['ingress']
    assert clickhouse == [{'from': [{'namespaceSelector': {'matchLabels': {'hoover.dev/hoover': 'true'}}}],
                           'ports': [{'port': 8123}, {'port': 9000}]}]
    garage = by(items, 'NetworkPolicy', 'garage-clients')['spec']['ingress']
    assert garage[0]['ports'] == [{'port': 3900}]
    # The RPC port takes only the Garage pods, and no rule names the admin port 3903.
    assert garage[1] == {'from': [{'podSelector': {'matchLabels': {'hoover.dev/store': 'garage'}}}], 'ports': [{'port': 3901}]}
    assert '3903' not in json.dumps([i for i in items if i['kind'] == 'NetworkPolicy'])


def test_zone_grants_name_only_the_databases_of_the_zone():
    grants = service_users.zone_grants('zone-a')
    assert [g.split(' ON ')[1] for g in grants] == ['zone_a.*', 'zone_a_*.*']
    # The browser user gets single tables of its zone.
    assert all(' ON zone_a_Processing.' in g for g in service_users.clickhouse_grants('zone-a', 'mcp-browser'))
    assert service_users.clickhouse_grants('zone-b', 'worker') == service_users.zone_grants('zone-b')


def test_the_store_size_grows_with_the_site_zones():
    assert shared.size('clickhouse', 0) == '20Gi' and shared.size('garage', 4) == '80Gi'
    data = {'zones': {'zone-a': {'stores': 'site'}, 'zone-b': {}, 'zone-c': {'stores': 'local'}, 'zone-d': {'stores': 'site'}}}
    assert shared.site_zones(data) == ['zone-a', 'zone-d']
