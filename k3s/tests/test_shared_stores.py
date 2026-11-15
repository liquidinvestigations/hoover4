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
    assert plan == {'nodes': ('server-a', 'worker-b', 'edge'), 'history_shards': 128, 'garage': 3, 'cassandra': 1,
                    'cassandra_data_gib': 2, 'opensearch': 1, 'temporal': 1}
    stores = ('{nodes: [server-a, worker-b], history_shards: 512, garage: {nodes: 1}, cassandra: {nodes: 2, data_gib: 5}, '
              'opensearch: {nodes: 2}, temporal: {pods: 3}}')
    assert config.store_plan(remote(stores)) == {'nodes': ('server-a', 'worker-b'), 'history_shards': 512, 'garage': 1,
                                                 'cassandra': 2, 'cassandra_data_gib': 5, 'opensearch': 2, 'temporal': 3}


def test_the_site_file_refuses_impossible_store_plans():
    for stores, message in (('{garage: {nodes: 4}}', 'vars.stores.garage nodes = 4 is more than the 3 store nodes'),
                            ('{nodes: [server-a], cassandra: {nodes: 2}}', 'vars.stores.cassandra nodes = 2 is more than the 1 store nodes'),
                            ('{nodes: [calls]}', 'vars.stores nodes names calls, which has no storage tier'),
                            ('{nodes: [nowhere]}', 'vars.stores nodes names nowhere, which is not a node'),
                            ('{opensearch: {nodes: 0}}', 'vars.stores.opensearch nodes = 0 must be a whole number of at least 1'),
                            ('{temporal: {nodes: 2}}', 'vars.stores.temporal nodes is not a known key'),
                            ('{garage: 2}', 'vars.stores.garage is not a mapping'),
                            ('{replicas: 2}', 'vars.stores replicas is not a known key'),
                            ('{failover: true}', 'vars.stores failover is not a known key')):
        with pytest.raises(config.SiteError, match=message):
            remote(stores)


def test_stores_with_copies_are_refused_and_node_counts_do_not_shrink():
    plan = config.store_plan(remote('{nodes: [server-a, worker-b]}'))
    assert config.store_change_problems(None, plan) == []
    # A plan recorded by the earlier version with copies: the stores must be created again.
    for before in ({'failover': False, 'replicas': 3, 'garage_replication_factor': 3}, {'garage_replication_factor': 2}):
        problems = config.store_change_problems(before, plan)
        assert len(problems) == 1 and 'from an earlier version' in problems[0] and 'delete the namespace hoover-stores' in problems[0]
    # One copy recorded by the earlier version on one node is the layout of this version.
    assert config.store_change_problems({'failover': False, 'replicas': 1, 'garage_replication_factor': 1}, plan) == []
    current = {'garage_replication_factor': 1, 'garage_nodes': {'garage-0': 'a', 'garage-1': 'b'}, 'cassandra_nodes': 1,
               'opensearch_nodes': 1}
    assert config.store_change_problems(current, plan) == []
    assert config.store_change_problems(current, dict(plan, garage=1, cassandra=2)) == [
        'the shared garage has 2 nodes, and each node holds a part of its data. Set vars.stores.garage nodes to 2 or more.']
    assert config.store_change_problems(dict(current, opensearch_nodes=2), plan) == [
        'the shared opensearch has 2 nodes, and each node holds a part of its data. Set vars.stores.opensearch nodes to 2 or more.']


def test_the_site_file_round_trip_keeps_the_store_keys():
    site = remote('{nodes: [server-a, worker-b], garage: {nodes: 2}, cassandra: {data_gib: 4}, temporal: {pods: 2}}')
    assert config.parse(config.dump(site)).stores == {'nodes': ('server-a', 'worker-b'), 'garage': {'nodes': 2},
                                                      'cassandra': {'data_gib': 4}, 'temporal': {'pods': 2}}


def test_garage_shards_one_copy_over_separate_nodes_and_serves_from_every_pod():
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
    assert 'replication_factor = 1' in toml
    assert f'"{"a" * 64}@garage-0.garage-peers.hoover-stores.svc.cluster.local:3901"' in toml
    assert by(items, 'Service', 'garage')['spec']['selector'] == {'app.kubernetes.io/name': 'garage'}
    assert by(items, 'Service', 'clickhouse')['spec']['selector'] == {'app.kubernetes.io/name': 'clickhouse'}
    peers = by(items, 'Service', 'garage-peers')['spec']
    assert peers['clusterIP'] == 'None' and peers['publishNotReadyAddresses'] is True
    clickhouse = by(items, 'StatefulSet', 'clickhouse')
    assert clickhouse['spec']['replicas'] == 1
    assert clickhouse['spec']['volumeClaimTemplates'][0]['spec']['resources']['requests']['storage'] == '60Gi'
    one = shared.objects(site, dict(plan, garage=1), 0, {})
    assert by(one, 'StatefulSet', 'garage')['spec']['replicas'] == 1
    # A site without a zone still sizes the stores for one zone.
    assert by(one, 'StatefulSet', 'garage')['spec']['volumeClaimTemplates'][0]['spec']['resources']['requests']['storage'] == '20Gi'
    assert 'bootstrap_peers = []' in by(one, 'ConfigMap', 'garage-config')['data']['garage.toml']


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


def test_the_site_runs_one_manticore_for_text_and_one_for_vectors_with_read_only_listeners():
    site = remote('{nodes: [server-a, worker-b]}')
    items = shared.objects(site, config.store_plan(site), 2, {})
    for name in ('manticore', 'manticore-vectors'):
        daemon = by(items, 'StatefulSet', name)
        assert daemon['metadata']['namespace'] == 'hoover-stores' and daemon['spec']['replicas'] == 1
        spec = daemon['spec']['template']['spec']
        assert spec['runtimeClassName'] == 'kata'
        assert spec['affinity']['nodeAffinity']['requiredDuringSchedulingIgnoredDuringExecution']['nodeSelectorTerms'][0][
            'matchExpressions'][0]['values'] == list(shared.tier(site, ('server-a', 'worker-b'), name)[1])
        c = next(c for c in spec['containers'] if c['name'] == 'manticore')
        env = {e['name']: e.get('value', e.get('valueFrom')) for e in c['env']}
        assert env['searchd_listen'] == '9306:mysql|9308:http|9307:mysql_readonly|9309:http_readonly'
        assert env['searchd_auth'] == '1'
        assert env['MT_ADMIN_PASSWORD'] == {'secretKeyRef': {'name': 'hoover-stores', 'key': 'manticore-admin'}}
        assert {v['name']: v.get('secret', {}).get('items') for v in spec['volumes']}['seed'] == [
            {'key': 'manticore-seed', 'path': 'auth.json'}]
        claim = daemon['spec']['volumeClaimTemplates'][0]['spec']['resources']['requests']['storage']
        assert claim == shared.size(name, 2)
        assert [p['port'] for p in by(items, 'Service', name)['spec']['ports']] == [9306, 9308, 9307, 9309]
    assert shared.size('manticore', 2) == '32Gi'
    ingress = by(items, 'NetworkPolicy', 'manticore-clients')['spec']
    assert ingress['podSelector']['matchExpressions'][0]['values'] == ['manticore', 'manticore-vectors']
    assert ingress['ingress'] == [{'from': [{'namespaceSelector': {'matchLabels': {'hoover.dev/hoover': 'true'}}}],
                                   'ports': [{'port': 9306}, {'port': 9308}, {'port': 9307}, {'port': 9309}]}]


def test_each_zone_has_three_manticore_users_and_only_the_schema_user_can_change_a_table():
    assert [service_users.manticore_user('zone-a', r) for r in service_users.MANTICORE_ROLES] == [
        'zone_a_read', 'zone_a_write', 'zone_a_schema']
    assert service_users.MANTICORE_GRANTS == {'read': ('read',), 'write': ('read', 'write'),
                                              'schema': ('read', 'write', 'schema')}
    # No service holds the schema user. The website and the collections server only search.
    roles = {s: u['manticore'] for s, u in service_users.SERVICES.items() if 'manticore' in u}
    assert roles == {'website': 'read', 'worker': 'write', 'ops': 'write', 'mcp-collections': 'read'}


def test_mysql_answers_are_read_with_and_without_borders():
    assert shared.manticore_rows('zone_a_read\nhoover_admin\n') == [['zone_a_read'], ['hoover_admin']]
    bordered = '+----+----+\n| username | action |\n+----+----+\n| zone_a_read | read |\n+----+----+\n'
    assert shared.manticore_rows(bordered) == [['username', 'action'], ['zone_a_read', 'read']]
    assert shared.manticore_rows('zone_a_read\tread\tzone_a_*\t1\t\n')[0][:4] == ['zone_a_read', 'read', 'zone_a_*', '1']
