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
                    'cassandra_data_gib': 2, 'opensearch': 1, 'temporal': 1, 'zones': 0}
    stores = ('{nodes: [server-a, worker-b], history_shards: 512, garage: {nodes: 1}, cassandra: {nodes: 2, data_gib: 5}, '
              'opensearch: {nodes: 2}, temporal: {pods: 3}, zones: 2}')
    assert config.store_plan(remote(stores)) == {'nodes': ('server-a', 'worker-b'), 'history_shards': 512, 'garage': 1,
                                                 'cassandra': 2, 'cassandra_data_gib': 5, 'opensearch': 2, 'temporal': 3,
                                                 'zones': 2}


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
    assert closed['podSelector'] == {'matchExpressions': [{'key': 'hoover.dev/store', 'operator': 'NotIn', 'values': ['clickhouse']}]}
    assert 'ingress' not in closed and set(closed['policyTypes']) == {'Ingress', 'Egress'}
    # ClickHouse reaches DNS and the S3 port of Garage only, so a BACKUP or RESTORE cannot name another address.
    own = by(items, 'NetworkPolicy', 'clickhouse-closed')['spec']
    assert own['podSelector'] == {'matchLabels': {'hoover.dev/store': 'clickhouse'}} and 'ingress' not in own
    assert own['egress'][1] == {'to': [{'podSelector': {'matchLabels': {'hoover.dev/store': 'garage'}}}], 'ports': [{'port': 3900}]}
    assert [p['port'] for p in own['egress'][0]['ports']] == [53, 53]
    clickhouse = by(items, 'NetworkPolicy', 'clickhouse-clients')['spec']['ingress']
    assert clickhouse == [{'from': [{'namespaceSelector': {'matchLabels': {'hoover.dev/hoover': 'true'}}}],
                           'ports': [{'port': 8123}, {'port': 9000}]}]
    garage = by(items, 'NetworkPolicy', 'garage-clients')['spec']['ingress']
    assert garage[0]['ports'] == [{'port': 3900}]
    assert garage[0]['from'][1] == {'podSelector': {'matchLabels': {'hoover.dev/store': 'clickhouse'}}}
    # The ingress controller sends the requests of the object storage hosts of the zones (../zones/objectstore.py).
    assert garage[0]['from'][2] == {'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'ingress'}}}
    assert len(garage[0]['from']) == 3
    # The RPC port takes only the Garage pods, and no rule names the admin port 3903.
    assert garage[1] == {'from': [{'podSelector': {'matchLabels': {'hoover.dev/store': 'garage'}}}], 'ports': [{'port': 3901}]}
    assert '3903' not in json.dumps([i for i in items if i['kind'] == 'NetworkPolicy'])


def test_zone_grants_name_only_the_databases_of_the_zone():
    grants = service_users.zone_grants('zone-a')
    assert [g.split(' ON ')[1] for g in grants] == ['zone_a.*', 'zone_a_*.*']
    # The browser user gets single tables of its zone.
    assert all(' ON zone_a_Processing.' in g for g in service_users.clickhouse_grants('zone-a', 'mcp-browser'))
    assert service_users.clickhouse_grants('zone-b', 'worker') == service_users.zone_grants('zone-b')


def test_only_the_operations_user_backs_up_and_reads_its_own_backup_rows():
    statements = service_users.backup_grants('zone-a')
    assert statements[0] == 'GRANT BACKUP ON zone_a_*.* TO `zone_a_ops`;'
    assert statements[1] == 'GRANT SELECT ON system.backups TO `zone_a_ops`;'
    assert statements[2] == ("CREATE ROW POLICY OR REPLACE `zone_a_backups` ON system.backups USING "
                             "startsWith(id, 'zone_a-') AS permissive TO `zone_a_ops`;")
    assert service_users.export_bucket('zone-a') == 'zone-a-exports'
    # The ClickHouse server of the site writes no backup into its own volume.
    server = (shared.common.LAB / 'config' / 'clickhouse' / 'server.xml').read_text()
    assert '<allowed_path remove="1"/>' in server


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
        ports = [9306, 9308, 9307, 9309] + ([9318] if name == 'manticore' else [])
        assert [p['port'] for p in by(items, 'Service', name)['spec']['ports']] == ports
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


USERS_XML = """<?xml version="1.0"?>

<resultset statement="SHOW USERS" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <row>
	<field name="username">hoover_admin</field>
  </row>

  <row>
	<field name="username">zone_a_read</field>
  </row>
</resultset>
"""


def test_manticore_listings_must_be_complete():
    assert shared.manticore_xml_rows(USERS_XML, 'SHOW USERS') == [{'username': 'hoover_admin'}, {'username': 'zone_a_read'}]
    empty = '<?xml version="1.0"?>\n\n<resultset statement="SHOW TABLES" xmlns:xsi="x"></resultset>\n'
    assert shared.manticore_xml_rows(empty, 'SHOW TABLES') == []
    # An answer that kubectl exec cut, an empty answer and the answer to another statement are errors.
    for text, statement in ((USERS_XML[:-40], 'SHOW USERS'), (USERS_XML[:150], 'SHOW USERS'), ('', 'SHOW USERS'),
                            ('username\nzone_a_read\n', 'SHOW USERS'), (USERS_XML, 'SHOW TABLES')):
        with pytest.raises(SystemExit):
            shared.manticore_xml_rows(text, statement)


def test_manticore_tenant_reads_the_xml_answers(monkeypatch):
    answers = {'SHOW TABLES': [{'Table': 'zone_a_demo_vfs', 'Type': 'rt'}, {'Table': 'zone_ab_x_vfs', 'Type': 'rt'},
                               {'Table': 'zone_b_demo_vfs', 'Type': 'rt'}],
               'SHOW USERS': [{'username': 'zone_a_read'}, {'username': 'zone_a_schema'}, {'username': 'zone_b_read'}]}
    monkeypatch.setattr(shared, 'manticore_list', lambda store, statement: answers[statement])
    assert shared.manticore_tenant('zone-a', 'manticore') == (['zone_a_demo_vfs'], ['zone_a_read', 'zone_a_schema'])

    def cut(store, statement):
        raise SystemExit('Manticore manticore gave an incomplete answer to SHOW TABLES')
    monkeypatch.setattr(shared, 'manticore_list', cut)
    with pytest.raises(SystemExit):
        shared.manticore_tenant('zone-a', 'manticore')


def test_the_text_daemon_pod_runs_the_file_service_on_its_volume():
    site = remote('{nodes: [server-a, worker-b]}')
    items = shared.objects(site, config.store_plan(site), 2, {})
    spec = by(items, 'StatefulSet', 'manticore')['spec']['template']
    files = next(c for c in spec['spec']['containers'] if c['name'] == 'files')
    assert files['image'] == shared.FILES_IMAGE and files['ports'] == [{'name': 'files', 'containerPort': 9318}]
    assert files['resources']['limits'] == {'cpu': '500m', 'memory': '128Mi'}
    env = {e['name']: e['value'] for e in files['env']}
    assert env['BLOCK_MOUNTS'] == '/dev/block-data:/var/lib/manticore' and env['BLOCK_USER'] == '999:999'
    assert files['volumeDevices'] == [{'name': 'data', 'devicePath': '/dev/block-data'}]
    # The container waits for the file system of the daemon container, then mounts it with the wrapper.
    assert files['command'][:3] == ['/tools/busybox', 'sh', '-c'] and '53ef' in files['command'][3]
    assert files['command'][3].endswith('exec /tools/busybox sh /tools/run.sh "$@"')
    assert 'manticore_file_service.py' in files['args'][-1]
    assert spec['metadata']['annotations']['hoover.dev/files-script']
    assert by(items, 'ConfigMap', 'manticore-files')['data']['manticore_file_service.py'] == shared.FILES_SCRIPT
    # Only one init container mounts the tools, and the vectors daemon has no file service.
    assert [i['name'] for i in spec['spec']['initContainers']].count('blockmount-tools') == 1
    vectors = by(items, 'StatefulSet', 'manticore-vectors')['spec']['template']['spec']
    assert [c['name'] for c in vectors['containers']] == ['manticore']
    policy = by(items, 'NetworkPolicy', 'manticore-files-clients')['spec']
    assert policy['podSelector'] == {'matchLabels': {'hoover.dev/store': 'manticore'}}
    assert policy['ingress'] == [{'from': [{'namespaceSelector': {'matchLabels': {'hoover.dev/hoover': 'true'}},
                                            'podSelector': {'matchLabels': {'app.kubernetes.io/name': 'manticore-schema'}}}],
                                  'ports': [{'port': 9318}]}]


def test_the_file_service_gives_a_schema_user_only_its_own_tables_and_stage(tmp_path, monkeypatch):
    """The service with the Manticore check replaced: zone_a_schema sees the table zone_a_t only."""
    import base64, http.server, importlib.util, threading, urllib.error, urllib.request
    spec = importlib.util.spec_from_file_location('manticore_file_service', shared.Path(shared.__file__).parent / 'manticore_file_service.py')
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    data = tmp_path / 'data'
    for table in ('zone_a_t', 'zone_b_t'):
        (data / table).mkdir(parents=True)
        (data / table / f'{table}.meta').write_bytes(b'{"t": "%s"}' % table.encode())
    (data / 'zone_a_t' / 'zone_a_t.link').symlink_to(data / 'zone_b_t' / 'zone_b_t.meta')
    monkeypatch.setattr(service, 'DATA', str(data))

    def caller(header):
        user = base64.b64decode(header[6:]).decode().split(':')[0] if header.startswith('Basic ') else ''
        if not service.USER.match(user):
            raise service.Refused(403, 'only the schema user of a zone uses this service')
        return user, {f'{user[:-len("_schema")]}_t'}
    monkeypatch.setattr(service, 'caller', caller)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), service.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_address[1]}'

    def call(method, path, user='zone_a_schema', body=None):
        request = urllib.request.Request(base + path, method=method, data=body,
                                         headers={'Authorization': 'Basic ' + base64.b64encode(f'{user}:p'.encode()).decode()})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()
    try:
        assert call('GET', '/tables/zone_a_t/zone_a_t.meta') == (200, b'{"t": "zone_a_t"}')
        assert call('GET', '/tables/zone_b_t/zone_b_t.meta')[0] == 403
        assert call('GET', '/tables/zone_a_t/zone_b_t.meta')[0] == 400
        assert call('GET', '/tables/zone_a_t/zone_a_t.link')[0] in (403, 500)
        assert call('GET', '/tables/zone_a_t/..%2Fzone_b_t%2Fzone_b_t.meta')[0] in (400, 404)
        assert call('GET', '/tables/zone_a_t/zone_a_t.meta', user='zone_a_read')[0] == 403
        assert call('PUT', '/stage/ab12/zone_a_t/zone_a_t.meta', body=b'{}')[0] == 200
        assert (data / 'import' / 'zone_a_schema' / 'ab12' / 'zone_a_t' / 'zone_a_t.meta').read_bytes() == b'{}'
        assert call('PUT', '/stage/../zone_a_t/zone_a_t.meta', body=b'{}')[0] in (400, 404)
        assert call('PUT', '/stage/ab12/zone_a_t/other.meta', body=b'{}')[0] == 400
        # zone_b_schema cannot remove the stage of zone_a_schema: the stage folder belongs to the caller.
        assert call('DELETE', '/stage/ab12', user='zone_b_schema')[0] == 200
        assert (data / 'import' / 'zone_a_schema' / 'ab12').is_dir()
        assert call('DELETE', '/stage/ab12')[0] == 200
        assert not (data / 'import' / 'zone_a_schema' / 'ab12').exists()
        # The removal of a zone removes the whole import folder of its schema user, and only that folder.
        assert call('PUT', '/stage/cd34/zone_a_t/zone_a_t.meta', body=b'{}')[0] == 200
        assert call('PUT', '/stage/cd34/zone_b_t/zone_b_t.meta', user='zone_b_schema', body=b'{}')[0] == 200
        assert call('DELETE', '/import', user='zone_b_schema')[0] == 200
        assert not (data / 'import' / 'zone_b_schema').exists()
        assert (data / 'import' / 'zone_a_schema' / 'cd34').is_dir()
        assert call('DELETE', '/import')[0] == 200
        assert not (data / 'import' / 'zone_a_schema').exists()
        assert call('DELETE', '/import')[0] == 200
    finally:
        server.shutdown()


# The removal of a zone tenant and the refusal of a new zone with objects of an earlier one --------------------------

import importlib.util  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402

import garage_client  # noqa: E402
import temporal  # noqa: E402


@pytest.mark.parametrize('module', [shared, temporal])
@pytest.mark.parametrize('name', ['zone', 'zone-', 'zone-a-b', 'zone-A', 'zone-a ', 'zone_a', 'zone-abcdefghijklm'])
def test_remove_refuses_a_partial_zone_id_before_any_store_call(monkeypatch, module, name):
    calls = []
    monkeypatch.setattr(shared, 'remove', lambda zone: calls.append(zone))
    monkeypatch.setattr(temporal, 'remove', lambda zone: calls.append(zone))
    monkeypatch.setattr(shared, 'clickhouse_sql', lambda *a, **k: calls.append(a))
    monkeypatch.setattr(temporal, 'cli', lambda *a, **k: calls.append(a))
    with pytest.raises(SystemExit) as error:
        module.main(['remove', name])
    assert 'is not a zone id' in str(error.value) and calls == []
    module.main(['remove', 'zone-a1'])
    assert calls == ['zone-a1']


def remove_parts(monkeypatch, failing=(), left=None):
    calls = []

    def part(name):
        def run(*args):
            calls.append(name if not args[1:] else f'{name}:{args[1]}')
            if name in failing or (args[1:] and args[1] in failing):
                raise SystemExit(f'{args[1] if args[1:] else name} has no ready pod')
        return run
    monkeypatch.setattr(shared, 'remove_clickhouse', part('clickhouse'))
    monkeypatch.setattr(shared, 'remove_manticore', part('manticore'))
    monkeypatch.setattr(shared, 'remove_garage', part('garage'))
    monkeypatch.setattr(temporal, 'remove', part('temporal'))
    monkeypatch.setattr(shared, 'remove_ingress', part('ingress'))
    monkeypatch.setattr(shared, 'leftovers', lambda zone: calls.append('check') or (left or {}))
    monkeypatch.setattr(shared.common, 'log', lambda *a, **k: None)
    return calls


def test_a_complete_removal_ends_after_the_check(monkeypatch):
    calls = remove_parts(monkeypatch)
    shared.remove('zone-a')
    assert calls == ['clickhouse', 'manticore:manticore', 'manticore:manticore-vectors', 'garage', 'temporal', 'ingress', 'check']


def test_a_failed_part_or_a_remaining_object_ends_the_removal_with_an_error(monkeypatch):
    # A stopped Manticore daemon: the other parts still run, and the command fails and names the daemon.
    calls = remove_parts(monkeypatch, failing=('manticore',), left={'manticore': ['manticore table zone_a_demo_vfs']})
    with pytest.raises(SystemExit) as error:
        shared.remove('zone-a')
    assert calls == ['clickhouse', 'manticore:manticore', 'manticore:manticore-vectors', 'garage', 'temporal', 'ingress', 'check']
    message = str(error.value)
    assert 'manticore: manticore has no ready pod' in message and 'zone_a_demo_vfs' in message
    assert 'run shared.py remove zone-a again' in message
    # An object that stays without a failed part also fails the command.
    remove_parts(monkeypatch, left={'temporal': ['namespace zone-a']})
    with pytest.raises(SystemExit, match='temporal keeps namespace zone-a'):
        shared.remove('zone-a')


def test_only_the_answer_not_found_counts_as_an_absent_temporal_namespace(monkeypatch):
    answers = []
    monkeypatch.setattr(temporal, 'cli', lambda *a, check=True: answers.pop(0))
    done = subprocess.CompletedProcess
    answers[:] = [done([], 0, 'NamespaceInfo.Name zone-a', '')]
    assert temporal.namespace_present('zone-a') is True
    answers[:] = [done([], 1, '', 'unable to describe namespace zone-a: Namespace zone-a is not found.')]
    assert temporal.namespace_present('zone-a') is False
    answers[:] = [done([], 1, '', 'context deadline exceeded')]
    with pytest.raises(SystemExit, match='context deadline exceeded'):
        temporal.namespace_present('zone-a')


class FakeGarage:
    """The Garage CLI and the client pod of garage_client.py over a dictionary of keys and buckets."""

    def __init__(self, keys, buckets, stuck=()):
        self.keys, self.buckets, self.stuck, self.calls = dict(keys), dict(buckets), set(stuck), []

    def cli(self, *args, pod=None, check=True):
        self.calls.append(args)
        if args[:2] == ('key', 'list'):
            return 'ID  Created  Name  Expiration\n' + ''.join(f'{i}  2026-11-16  {n}  never\n' for i, n in self.keys.items())
        if args[:2] == ('bucket', 'list'):
            rows = [f'b{i}  2026-11-16  {"" if k else n}  {f"{k}:{n}" if k else ""}' for i, (n, k) in enumerate(self.buckets.items())]
            return 'ID  Created  Global aliases  Local aliases\n' + ''.join(f'{r}\n' for r in rows)
        if args[:2] == ('key', 'create'):
            self.keys['GKpurge'] = args[2]
            return 'Key ID: GKpurge\nSecret key: s-purge\n'
        if args[:2] == ('key', 'info'):
            return f'Key ID: {args[3]}\nSecret key: s-{args[3]}\n'
        if args[:2] == ('key', 'delete'):
            self.keys.pop(args[3], None)
        if args[:2] == ('bucket', 'delete') and args[3] not in self.stuck:
            self.buckets.pop(args[3], None)
        return ''

    def run(self, pod, key, command, *buckets, **kw):
        self.calls.append(('s3', key['access_key'], command, *buckets))
        for bucket in buckets:
            if bucket not in self.stuck:
                self.buckets.pop(bucket, None)
        return '', []


@pytest.fixture
def garage(monkeypatch):
    def make(keys, buckets, stuck=()):
        fake = FakeGarage(keys, buckets, stuck)
        monkeypatch.setattr(shared, 'garage_cli', fake.cli)
        monkeypatch.setattr(garage_client, 'run', fake.run)
        monkeypatch.setattr(garage_client, 'client', lambda: __import__('contextlib').nullcontext('garage-client-1'))
        monkeypatch.setattr(shared.common, 'log', lambda *a, **k: None)
        return fake
    return make


ZONE_A_KEYS = {'GKa': 'zone-a', 'GKab': 'zone-a-mcp-browser', 'GKb': 'zone-b', 'GKx': 'zone-ab'}
ZONE_A_BUCKETS = {'zone-a-system': '', 'zone-a-exports': '', 'zone-a-c-new': 'GKa', 'zone-b-system': '', 'zone-ab-system': '',
                  'zone-b-c-new': 'GKb'}


def test_each_garage_pod_has_the_s3_client_of_the_operator_tools():
    site = remote('{nodes: [server-a, worker-b]}')
    statefulset = by(shared.objects(site, config.store_plan(site), 1, {}), 'StatefulSet', 'garage')
    client = next(c for c in statefulset['spec']['template']['spec']['containers'] if c['name'] == 's3')
    assert client['image'] == garage_client.IMAGE and 'volumeMounts' not in client and 'ports' not in client
    assert client['securityContext']['runAsNonRoot'] and client['securityContext']['capabilities'] == {'drop': ['ALL']}
    assert client['resources']['limits']['memory'] == '128Mi'
    # The client reaches Garage inside its own pod, so no network policy names it.
    assert garage_client.ENDPOINT == '127.0.0.1:3900'


def test_the_garage_tenant_holds_only_the_keys_and_buckets_of_the_zone(garage):
    garage(ZONE_A_KEYS, ZONE_A_BUCKETS)
    keys, buckets = shared.garage_tenant('zone-a')
    assert keys == {'GKa': 'zone-a', 'GKab': 'zone-a-mcp-browser'}
    assert buckets == {'zone-a-system': '', 'zone-a-exports': '', 'zone-a-c-new': 'GKa'}


def test_the_garage_removal_needs_no_pod_of_the_zone(garage):
    fake = garage(ZONE_A_KEYS, ZONE_A_BUCKETS)
    shared.remove_garage('zone-a')
    s3 = [c for c in fake.calls if c[0] == 's3']
    # The owner key empties and deletes the collection bucket. A purge key with all rights empties the global buckets.
    assert s3 == [('s3', 'GKa', 'purge', 'zone-a-c-new'), ('s3', 'GKpurge', 'purge', 'zone-a-exports', 'zone-a-system')]
    assert ('bucket', 'allow', '--read', '--write', '--owner', 'zone-a-system', '--key', 'GKpurge') in fake.calls
    assert set(fake.keys) == {'GKb', 'GKx'} and set(fake.buckets) == {'zone-b-system', 'zone-ab-system', 'zone-b-c-new'}


def test_a_garage_bucket_that_stays_keeps_the_zone_keys_and_fails(garage):
    fake = garage(ZONE_A_KEYS, ZONE_A_BUCKETS, stuck={'zone-a-c-new'})
    with pytest.raises(SystemExit, match='zone-a-c-new stay'):
        shared.remove_garage('zone-a')
    assert {'GKa', 'GKab'} <= set(fake.keys) and 'GKpurge' not in fake.keys


def setup_module_for(monkeypatch, zone='zone-a'):
    """../hoover/setup.py reads the zone from its arguments at import."""
    monkeypatch.setattr(sys, 'argv', ['setup.py', zone])
    spec = importlib.util.spec_from_file_location('hoover_setup', shared.common.SOURCE / 'hoover' / 'setup.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_new_zone_with_objects_of_an_earlier_zone_is_refused_with_their_names(monkeypatch):
    setup = setup_module_for(monkeypatch)
    secrets = {('zone-a', 'garage-tenants'): {}}
    monkeypatch.setattr(setup, 'secret', lambda ns, name: secrets.get((ns, name), {}))
    left = {'garage': ['bucket zone-a-system', 'key zone-a'], 'clickhouse': ['database zone_a_Processing'],
            'temporal': ['namespace zone-a']}
    monkeypatch.setattr(setup.shared, 'leftovers', lambda zone: left)
    with pytest.raises(SystemExit) as error:
        setup.refuse_leftovers()
    message = str(error.value)
    for name in ('bucket zone-a-system', 'key zone-a', 'database zone_a_Processing', 'namespace zone-a',
                 'shared.py remove zone-a'):
        assert name in message
    # A new zone without objects of an earlier zone passes.
    left = {}
    setup.refuse_leftovers()
    # An existing zone has its key in garage-tenants, and its own objects are no reason to stop.
    secrets[('zone-a', 'garage-tenants')] = {'tenants.json': json.dumps({'zone-a': {'access_key': 'GKa'}})}
    monkeypatch.setattr(setup.shared, 'leftovers', lambda zone: pytest.fail('an existing zone is not checked'))
    setup.refuse_leftovers()


def test_the_schema_password_moves_out_of_the_zone_namespace(monkeypatch):
    import creds
    assert 'manticore-schema' not in creds.KEYS and {'manticore-read', 'manticore-write'} <= set(creds.KEYS)
    setup = setup_module_for(monkeypatch)
    stores = {k: f'v-{k}' for k in creds.KEYS}
    stores['manticore-schema'] = 'legacy'
    secrets = {('zone-a', 'hoover-stores'): stores, ('zone-a', 'garage-tenants'): {'tenants.json': json.dumps(
        {name: {'access_key': f'a-{name}', 'secret_key': f's-{name}'} for name in
         {'zone-a'} | {service_users.garage_key('zone-a', s) for s in service_users.using('garage')}})}}
    written, patched = {}, []
    monkeypatch.setattr(setup, 'secret', lambda ns, name: dict(secrets.get((ns, name), {})))
    monkeypatch.setattr(setup, 'ensure_secret', lambda name, wanted, follow=(), drop=(): written.setdefault(name, (wanted, follow)) and wanted)
    monkeypatch.setattr(setup, 'kubectl', lambda *a, **k: patched.append(a))
    monkeypatch.setattr(setup, 'ZONES', type('P', (), {'read_text': lambda self: json.dumps({'zone-a': {'hoover_oidc_secret': 'x'}})})())
    monkeypatch.setattr(setup.site_temporal, 'token', lambda zone: 'jwt')
    monkeypatch.setattr(setup.gpu, 'token', lambda zone: 'gpu')
    setup.runtime_secrets()
    wanted, follow = written['manticore-schema']
    # A zone of an earlier version keeps its schema password, which leaves hoover-stores of the zone namespace.
    assert wanted['password'] == 'legacy' and 'password' not in follow
    assert patched == [('-n', 'zone-a', 'patch', 'secret', 'hoover-stores', '--type=json',
                        '-p', json.dumps([{'op': 'remove', 'path': '/data/manticore-schema'}]))]
    assert 'manticore-schema' not in written['hoover-runtime'][0]
    # A new zone gets a random schema password, and no patch is needed.
    del stores['manticore-schema']
    written.clear(), patched.clear()
    setup.runtime_secrets()
    assert len(written['manticore-schema'][0]['password']) == 48 and patched == []


def test_the_clickhouse_tenant_is_one_answer_row_and_a_cut_answer_is_an_error(monkeypatch):
    row = {'database': ['zone_a_Processing'], 'user': ['zone_a', 'zone_a_ops'], 'profile': ['zone_a'], 'row policy': ['zone_a_backups']}
    sent = []
    monkeypatch.setattr(shared, 'clickhouse_sql', lambda sql: sent.append(sql) or json.dumps(row) + '\n')
    assert shared.clickhouse_tenant('zone-a') == [('database', 'zone_a_Processing'), ('user', 'zone_a'), ('user', 'zone_a_ops'),
                                                  ('profile', 'zone_a'), ('row policy', 'zone_a_backups')]
    assert "startsWith(name, 'zone_a_')" in sent[0] and 'FORMAT JSONEachRow' in sent[0]
    monkeypatch.setattr(shared, 'clickhouse_sql', lambda sql: json.dumps(row)[:30])
    with pytest.raises(SystemExit, match='incomplete answer'):
        shared.clickhouse_tenant('zone-a')


def test_podexec_call_keeps_the_input_open_and_returns_the_complete_output(tmp_path):
    import podexec
    # A local stand-in for kubectl exec: the argv after `--` runs on this host.
    fake = tmp_path / 'kubectl'
    fake.write_text('#!/bin/sh\nwhile [ "$1" != "--" ]; do shift; done; shift; exec "$@"\n')
    fake.chmod(0o755)
    r = podexec.call([str(fake), 'exec', '-i', 'pod'], ['sh', '-c', 'wc -c; head -c 2000000 /dev/zero | tr "\\000" a'],
                     'SELECT 1;\n')
    assert r.returncode == 0 and r.stdout.startswith('10\n') and len(r.stdout) == 3 + 2000000
    with pytest.raises(__import__('subprocess').TimeoutExpired):
        podexec.call([str(fake), 'exec', '-i', 'pod'], ['sleep', '5'], timeout=0.5)


def test_the_store_sql_readers_keep_the_input_open(monkeypatch):
    import podexec
    import subprocess as sp
    calls = []
    monkeypatch.setattr(shared, 'ready_pod', lambda store: f'{store}-0')
    monkeypatch.setattr(podexec, 'call', lambda argv, command, data=b'', timeout=None:
                        calls.append((argv, command, data)) or sp.CompletedProcess(argv, 0, 'x' * 100000, ''))
    assert len(shared.clickhouse_sql('SELECT 1\n')) == 100000
    assert len(shared.manticore_sql('manticore', 'SHOW TABLES;\n')) == 100000
    assert [c[0][-5:] for c in calls] == [['exec', '-i', 'clickhouse-0', '-c', 'clickhouse'],
                                          ['exec', '-i', 'manticore-0', '-c', 'manticore']]
    assert [c[2] for c in calls] == ['SELECT 1\n', 'SHOW TABLES;\n']


def _store_pod(name, revision, ready):
    return {'metadata': {'name': name, 'labels': {'controller-revision-hash': revision}},
            'status': {'conditions': [{'type': 'Ready', 'status': 'True' if ready else 'False'}]}}


def _fake_rollout(monkeypatch, replicas, pods_by_round):
    """wait_current() against a StatefulSet at revision new, with the pods of each poll from pods_by_round."""
    deleted, polls = [], iter(pods_by_round)
    controller = {'spec': {'replicas': replicas}, 'metadata': {'generation': 2},
                  'status': {'observedGeneration': 2, 'updateRevision': 'new'}}
    monkeypatch.setattr(shared.common, 'kubectl_json', lambda *a: controller)
    monkeypatch.setattr(shared, 'pods', lambda store: next(polls))
    monkeypatch.setattr(shared.common, 'kubectl', lambda *a, **k: deleted.append(a[-2]))
    monkeypatch.setattr(shared.common, 'log', lambda *a, **k: None)
    monkeypatch.setattr(shared.time, 'sleep', lambda s: None)
    return deleted


def test_an_outdated_pod_that_is_not_ready_is_replaced(monkeypatch):
    # After a power loss the pod crashes with its old template. The new template corrects the start, so the pod is
    # replaced although no pod of the store is ready.
    deleted = _fake_rollout(monkeypatch, 1, [[_store_pod('manticore-0', 'old', False)],
                                             [_store_pod('manticore-0', 'new', True)]])
    shared.wait_current('manticore', timeout=60)
    assert deleted == ['manticore-0']


def test_a_ready_outdated_pod_waits_while_another_pod_is_not_ready(monkeypatch):
    waiting = [_store_pod('garage-0', 'new', False), _store_pod('garage-1', 'old', True)]
    deleted = _fake_rollout(monkeypatch, 2, [waiting, [_store_pod('garage-0', 'new', True), _store_pod('garage-1', 'old', True)],
                                             [_store_pod('garage-0', 'new', True), _store_pod('garage-1', 'new', True)]])
    shared.wait_current('garage', timeout=60)
    assert deleted == ['garage-1']
