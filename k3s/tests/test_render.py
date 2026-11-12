"""The Hoover render of k3s/hoover/manifests.py against the Compose files of the repository."""
import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from conftest import K3S, REPO, operator_settings, site_text
import compose
import config
import manifests

REVISION = '0123456789abcdef0123456789abcdef01234567'
NFS = {'server-a': '10.43.0.10', 'worker-b': '10.43.0.11'}
# The Compose development values of the store credentials and the shared secrets. No render may hold them.
COMPOSE_SECRETS = ('hoover4-garage-blob-secret-key-0', 'cbc5a1dbd1c832a3bdcb0abff4e5ffc950035febf867de39e9b079cec8863e1d',
                   'hoover4-garage-admin-token')


def target(site_name, installation, tmp_path, overrides=None, source_text=None):
    text = site_text(site_name)
    if source_text is not None:
        source = tmp_path / 'source.ini'
        source.write_text(source_text)
        text = re.sub(r'source_ini = .*', f'source_ini = {source}', text)
    path = tmp_path / site_name
    path.write_text(text)
    t = manifests.target_from_site(path, installation, revision=REVISION, state=tmp_path / 'no-state', nfs=NFS)
    if overrides:
        t.values.update(overrides)
    return t


def items_of(t):
    return json.loads(manifests.render(t))['items']


def get(items, kind, name):
    found = [i for i in items if i['kind'] == kind and i['metadata']['name'] == name]
    assert found, f'{kind} {name} is missing'
    return found[0]


def containers(item):
    spec = item['spec']['template']['spec'] if item['kind'] != 'Job' else item['spec']['template']['spec']
    return spec.get('initContainers', []) + spec['containers']


def env(container):
    return {e['name']: e.get('value', e.get('valueFrom')) for e in container.get('env', [])}


def workloads(items):
    return [i for i in items if i['kind'] in ('Deployment', 'StatefulSet', 'Job')]


@pytest.fixture
def single(tmp_path):
    return items_of(target('single-node.ini', 'main', tmp_path))


# The single-node migrated installation ----------------------------------------------------------------------------

def test_single_node_keeps_the_compose_storage_identity_and_history_source(single):
    workers = get(single, 'StatefulSet', 'hoover-workers')
    e = env(containers(workers)[0])
    assert e['HOOVER4_CLICKHOUSE_DB_PREFIX'] == 'Hoover4'
    assert e['HOOVER4_MANTICORE_TABLE_PREFIX'] == ''
    assert e['S3_SYSTEM_BUCKET'] == 'hoover4-system'
    assert e['S3_COLLECTION_BUCKET_PREFIX'] == 'hoover4-c-'
    assert e['HOOVER4_HISTORY_SOURCE'] == 'compose'
    # One worker pod polls the shared queues, so the open work of the Compose install keeps its queues.
    assert 'HOOVER4_HOST_QUEUE' not in e


def test_several_worker_pods_poll_their_host_queues(tmp_path):
    t = target('single-node.ini', 'main', tmp_path, overrides={'budget.worker_pods': '2'})
    e = env(containers(get(items_of(t), 'StatefulSet', 'hoover-workers'))[0])
    assert e['HOOVER4_HOST_QUEUE'] == {'fieldRef': {'fieldPath': 'metadata.name'}}


def test_every_credential_comes_from_a_secret(single):
    text = json.dumps(single)
    for value in COMPOSE_SECRETS:
        assert value not in text
    names = set(manifests.STORE_CREDENTIALS) | {'HOOVER4_PROXY_SECRET', 'OAUTH2_PROXY_COOKIE_SECRET'}
    for item in workloads(single):
        for c in containers(item):
            for e in c.get('env', []):
                if e['name'] in names:
                    assert 'secretKeyRef' in e.get('valueFrom', {}), (item['metadata']['name'], e['name'])
    for name in ('hoover-website', 'hoover-operations', 'hoover-singletons'):
        e = env(containers(get(single, 'Deployment', name))[-1])
        for variable in ('CLICKHOUSE_USER', 'CLICKHOUSE_PASSWORD', 'MANTICORE_USER', 'MANTICORE_PASSWORD',
                         'S3_ACCESS_KEY', 'S3_SECRET_KEY'):
            assert variable in e, (name, variable)


def test_identity_proxy_and_administrator_groups(single):
    website = containers(get(single, 'Deployment', 'hoover-website'))[0]
    assert env(website)['HOOVER4_PROXY_SECRET'] == {'secretKeyRef': {'name': 'hoover-runtime', 'key': 'proxy-secret'}}
    assert env(website)['HOOVER4_ADMIN_GROUPS'] == 'Domain Admins'
    alpha = json.loads(get(single, 'ConfigMap', 'oauth2-proxy')['data']['alpha.yaml'])
    headers = {h['name']: h for h in alpha['injectRequestHeaders']}
    assert headers['X-Hoover-Proxy']['values'] == [{'fromFile': '/secrets/proxy-secret'}]
    assert all(h['preserveRequestValue'] is False for h in headers.values())


def test_single_writer_processes_run_once(single):
    processes = []
    for item in workloads(single):
        for c in item['spec']['template']['spec']['containers']:
            selected = env(c).get('HOOVER4_WORKERS')
            if selected:
                processes += [(p, item['spec'].get('replicas', 1)) for p in selected.split(',')]
    for single_writer in ('index-planner', 'email-graph'):
        assert [r for p, r in processes if p == single_writer] == [1]
    assert get(single, 'Deployment', 'hoover-singletons')['spec']['replicas'] == 1


def test_worker_plan_files_have_one_claim_per_pod(single):
    workers = get(single, 'StatefulSet', 'hoover-workers')
    assert [c['metadata']['name'] for c in workers['spec']['volumeClaimTemplates']] == ['worker-temp-files']
    mount = [m for m in containers(workers)[0]['volumeMounts'] if m['mountPath'] == '/tmp/hoover4']
    assert mount == [{'name': 'worker-temp-files', 'mountPath': '/tmp/hoover4'}]
    assert workers['spec']['replicas'] == 1
    assert get(single, 'Service', 'hoover-workers')['spec']['clusterIP'] == 'None'


def test_temporal_on_cassandra_and_elasticsearch(single):
    temporal = containers(get(single, 'Deployment', 'temporal'))[0]
    e = env(temporal)
    assert temporal['image'] == 'docker.io/temporalio/auto-setup:1.23.1'
    assert e['CASSANDRA_SEEDS'] == 'temporal-cassandra' and e['ES_SEEDS'] == 'temporal-elasticsearch'
    assert e['NUM_HISTORY_SHARDS'] == '128'
    assert e['DYNAMIC_CONFIG_FILE_PATH'] == '/etc/temporal/config/dynamicconfig/generated.yaml'
    dynamic = get(single, 'ConfigMap', 'temporal-dynamicconfig')['data']
    assert 'limit.historyCount.warn' in dynamic['generated.yaml']
    for store, path, claim in (('temporal-cassandra', '/var/lib/cassandra', 'temporal-cassandra'),
                               ('temporal-elasticsearch', '/usr/share/elasticsearch/data', 'temporal-elasticsearch')):
        item = get(single, 'StatefulSet', store)
        main = containers(item)[-1]
        assert {'name': claim, 'mountPath': path} in main['volumeMounts']
        get(single, 'PersistentVolumeClaim', claim)
    assert containers(get(single, 'StatefulSet', 'temporal-cassandra'))[-1]['image'] == 'docker.io/library/cassandra:3.11.9'
    assert containers(get(single, 'StatefulSet', 'temporal-elasticsearch'))[-1]['image'] == 'docker.io/library/elasticsearch:7.17.27'
    job = [i for i in single if i['kind'] == 'Job' and i['metadata']['name'].startswith('temporal-retention-')]
    assert job and '--retention 168h' in containers(job[0])[0]['command'][-1]


def test_migrated_install_keeps_its_shard_count(tmp_path):
    source = (REPO / 'scripts/deploy.py_tests/fixtures/source-ini/compose-with-serena.ini').read_text()
    source = source.replace('[main_services]', '[main_services]\ntemporal_history_shards = 64')
    items = items_of(target('single-node.ini', 'main', tmp_path, source_text=source))
    assert env(containers(get(items, 'Deployment', 'temporal'))[0])['NUM_HISTORY_SHARDS'] == '64'


def test_dataset_mounts_keep_their_container_paths(single):
    worker = containers(get(single, 'StatefulSet', 'hoover-workers'))[0]
    mounts = json.loads(env(worker)['HOOVER4_DATASET_MOUNTS'])
    assert mounts == [{'name': 'testdata', 'path': '/testdata', 'writable': False},
                      {'name': 'uploads', 'path': '/uploads', 'writable': True}]
    volumes = {v['name']: v for v in get(single, 'StatefulSet', 'hoover-workers')['spec']['template']['spec']['volumes']}
    assert volumes['data-testdata']['persistentVolumeClaim'] == {'claimName': 'host-dataset-testdata', 'readOnly': True}
    assert volumes['data-uploads']['persistentVolumeClaim'] == {'claimName': 'dataset-uploads'}
    get(single, 'PersistentVolumeClaim', 'dataset-uploads')
    assert volumes['chat-control']['persistentVolumeClaim'] == {'claimName': 'host-chat-control', 'readOnly': True}


def test_host_folders_are_volumes_of_the_admin_render(single):
    """The pod policy refuses a hostPath volume in a zone namespace, so a host folder is a PersistentVolume."""
    for item in single:
        if item['kind'] in ('Deployment', 'StatefulSet', 'Job'):
            assert not [v for v in item['spec']['template']['spec'].get('volumes', []) if 'hostPath' in v], item['metadata']['name']
    for claim_name, path in (('host-dataset-testdata', '/srv/hoover4-testdata'), ('host-chat-control', '/srv/hoover4-chat-control')):
        pv = get(single, 'PersistentVolume', f'hoover-zone-a-{claim_name}')
        assert pv['spec']['hostPath'] == {'path': path, 'type': 'Directory'}
        assert pv['spec']['accessModes'] == ['ReadOnlyMany']
        assert pv['spec']['claimRef'] == {'namespace': 'hoover-zone-a', 'name': claim_name}
        assert pv['spec']['persistentVolumeReclaimPolicy'] == 'Retain'
        pvc = get(single, 'PersistentVolumeClaim', claim_name)
        assert pvc['spec']['volumeName'] == pv['metadata']['name'] and pvc['spec']['storageClassName'] == ''


def test_operations_worker_mounts_backups_and_stores(single):
    ops = get(single, 'Deployment', 'hoover-operations')
    mounts = {(m['mountPath'], m['name'], m.get('readOnly', False)) for m in containers(ops)[0]['volumeMounts']}
    assert {('/backups', 'ops-backups', False), ('/stores/clickhouse', 'clickhouse-data', True),
            ('/stores/manticore', 'manticore-data', True), ('/stores/manticore-restore', 'manticore-data', False),
            ('/stores/garage/data', 'garage-data', True), ('/stores/garage/meta', 'garage-meta', True)} <= mounts
    clickhouse = containers(get(single, 'StatefulSet', 'clickhouse'))[-1]
    assert {'name': 'ops-backups', 'mountPath': '/var/lib/clickhouse/backups'} in clickhouse['volumeMounts']
    # The claims are local volumes, so every pod that shares one runs on the home node.
    for name, kind in (('hoover-operations', 'Deployment'), ('clickhouse', 'StatefulSet')):
        assert get(single, kind, name)['spec']['template']['spec']['nodeSelector'] == {'kubernetes.io/hostname': 'dev'}


def test_store_owners_follow_deploy_py(single):
    init = containers(get(single, 'StatefulSet', 'manticore'))[0]
    assert 'auth.json.seed' in init['command'][-1]
    assert containers(get(single, 'StatefulSet', 'clickhouse'))[0]['command'][-1] == 'chown 101:101 /d'
    assert get(single, 'ConfigMap', 'manticore-seed')


def test_current_services_are_present_and_stale_ones_absent(single):
    names = {i['metadata']['name'] for i in single}
    for name in ('hoover4-pdf-search', 'hoover4-mcp-collections', 'hoover4-mcp-todo', 'temporal-ui', 'clickhouse-monitoring',
                 'ch-ui', 'zookeeper', 'garage', 'clickhouse', 'manticore', 'manticore-vectors'):
        assert name in names
    for name in ('hoover4-ner-spacy', 'serena', 'redis', 'hoover4-processing-pdf-to-html', 'hoover4-development-auth-backdoor'):
        assert name not in names
    assert get(single, 'Service', 'hoover4-pdf-search')['spec']['ports'][0]['port'] == 13500


def test_gpu_forwarder_keeps_the_three_gpu_interfaces(single):
    service = get(single, 'Service', 'gpu')
    assert [p['port'] for p in service['spec']['ports']] == [21960, 21961, 21962]
    website = env(containers(get(single, 'Deployment', 'hoover-website'))[0])
    assert website['NER_URL'] == 'http://gpu:21961/v1'
    assert website['OCR_EASYOCR_URL'] == 'http://gpu:21962/ocr'


def test_internet_tools_follow_the_setting(tmp_path):
    items = items_of(target('single-node.ini', 'main', tmp_path, overrides={'main_services.internet_tools_enabled': 'true'}))
    for name in ('hoover4-mcp-whois', 'hoover4-mcp-metasearch', 'hoover4-mcp-browser', 'hoover4-web-tor'):
        item = get(items, 'Deployment', name)
        assert item['spec']['template']['metadata']['labels']['hoover.dev/egress'] == 'internet'
    browser = get(items, 'Deployment', 'hoover4-mcp-browser')['spec']['template']['spec']
    assert {'name': 'shm', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '2Gi'}} in browser['volumes']
    tor = containers(get(items, 'Deployment', 'hoover4-web-tor'))[0]
    assert tor['securityContext']['readOnlyRootFilesystem'] is True


def test_garage_init_job_name_follows_its_spec(tmp_path, single):
    """A Job template cannot change, so a new Garage size gives a new Job name and the same size the same name."""
    def job(items):
        jobs = [i for i in items if i['kind'] == 'Job' and i['metadata']['name'].startswith('garage-init-')]
        assert len(jobs) == 1
        return jobs[0]
    first = job(single)
    grown = job(items_of(target('single-node.ini', 'main', tmp_path, overrides={'volume.garage-data': '25Gi'})))
    assert env(containers(first)[0])['GARAGE_CAPACITY'] != env(containers(grown)[0])['GARAGE_CAPACITY']
    assert first['metadata']['name'] != grown['metadata']['name']
    assert job(items_of(target('single-node.ini', 'main', tmp_path)))['metadata']['name'] == first['metadata']['name']


def test_service_commands_and_limits_follow_compose(tmp_path, single):
    t = target('single-node.ini', 'main', tmp_path)
    ini = tmp_path / 'hoover4.ini'
    ini.write_text(manifests.zone_ini_text(t))
    _, _, _, services = compose.load(ini, REPO)
    tika = containers(get(single, 'Deployment', 'hoover4-tika'))[0]
    assert tika['args'] == services['hoover4-tika']['command']
    cassandra = containers(get(single, 'StatefulSet', 'temporal-cassandra'))[-1]
    assert cassandra['command'] == services['temporal-cassandra']['entrypoint']
    clickhouse = containers(get(single, 'StatefulSet', 'clickhouse'))[-1]
    assert clickhouse['resources']['limits']['memory'] == manifests.quantity(services['clickhouse']['mem_limit'], '')
    assert clickhouse['securityContext']['capabilities']['add'] == sorted(services['clickhouse']['cap_add'])
    workers = containers(get(single, 'StatefulSet', 'hoover-workers'))[0]
    assert workers['resources']['limits'] == {'memory': '6144Mi', 'cpu': '4'}


def test_network_policy_keeps_internet_services_away_from_stores(single):
    policy = get(single, 'NetworkPolicy', 'egress-internet-local')
    assert policy['spec']['podSelector'] == {'matchLabels': {'hoover.dev/egress': 'internet'}}
    rules = policy['spec']['egress'][1]['to'][0]['podSelector']['matchExpressions']
    assert rules == [{'key': 'hoover.dev/store', 'operator': 'DoesNotExist'}]
    website = get(single, 'NetworkPolicy', 'website-from-proxy')['spec']['ingress'][0]
    assert website['from'][0] == {'podSelector': {'matchLabels': {'app.kubernetes.io/name': 'oauth2-proxy'}}}
    assert website['from'][1]['podSelector']['matchExpressions'][0]['values'] == manifests.AGENT_API_CLIENTS
    for store in ('clickhouse', 'garage'):
        assert get(single, 'StatefulSet', store)['spec']['template']['metadata']['labels']['hoover.dev/store'] == store


def test_agent_api_callers_reach_the_cluster_website(single):
    names = {i['metadata']['name'] for i in workloads(single)}
    present = [n for n in manifests.AGENT_API_CLIENTS if n in names]
    assert {'hoover-workers', 'hoover-singletons', 'hoover4-mcp-collections'} <= set(present)
    for name in present:
        item = get(single, next(i['kind'] for i in workloads(single) if i['metadata']['name'] == name), name)
        for c in item['spec']['template']['spec']['containers']:
            assert env(c).get('AGENT_API_BASE_URL') == 'http://hoover-website:8080', (name, c['name'])
    for item in workloads(single):
        for c in containers(item):
            assert not any('//hoover4-website' in str(v) for v in env(c).values()), item['metadata']['name']


def test_second_render_is_equal(tmp_path):
    first = manifests.render(target('single-node.ini', 'main', tmp_path))
    second = manifests.render(target('single-node.ini', 'main', tmp_path))
    assert first == second
    images = sorted(set(re.findall(r'"image": "([^"]+)"', first)))
    assert all(':0123456789ab' in i for i in images if i.startswith(manifests.REGISTRY))


# The remote topology ------------------------------------------------------------------------------------------------

def test_existing_remote_zone_keeps_postgresql_and_zone_stores(tmp_path):
    items = items_of(target('remote.ini', 'zone-a', tmp_path))
    temporal = containers(get(items, 'Deployment', 'temporal'))[0]
    assert env(temporal)['DB'] == 'postgres12'
    names = {(i['kind'], i['metadata']['name']) for i in items}
    assert ('StatefulSet', 'temporal-cassandra') not in names and ('StatefulSet', 'clickhouse') not in names
    assert get(items, 'Service', 'clickhouse')['spec'] == {'type': 'ExternalName', 'externalName': 'clickhouse.zone-a.svc.cluster.local'}
    workers = get(items, 'Deployment', 'hoover-workers')
    e = env(containers(workers)[0])
    assert e['HOOVER4_HISTORY_SOURCE'] == 'k3s-branch'
    assert e['CLICKHOUSE_USER'] == 'zone_a_worker'
    assert e['HOOVER4_MANTICORE_TABLE_PREFIX'] == 'zone_a_'
    assert workers['spec']['template']['spec'].get('topologySpreadConstraints')
    clamav = get(items, 'Deployment', 'hoover4-clamav')['spec']['template']['spec']
    assert clamav['nodeSelector'] == {'kubernetes.io/hostname': 'edge'}


def test_new_remote_install_with_its_own_identity_and_nfs_data(tmp_path):
    items = items_of(target('remote.ini', 'research', tmp_path))
    e = env(containers(get(items, 'StatefulSet', 'hoover-workers'))[0])
    assert e['HOOVER4_CLICKHOUSE_DB_PREFIX'] == 'Research'
    assert e['S3_SYSTEM_BUCKET'] == 'research-system'
    assert e['HOOVER4_HISTORY_SOURCE'] == 'compose'
    volumes = {v['name']: v for v in get(items, 'StatefulSet', 'hoover-workers')['spec']['template']['spec']['volumes']}
    assert volumes['data-uploads']['nfs'] == {'server': '10.43.0.10', 'path': '/zone-c/uploads', 'readOnly': False}
    assert get(items, 'PersistentVolumeClaim', 'clickhouse-data')['spec']['storageClassName'] == 'hdd-ext4'
    get(items, 'StatefulSet', 'temporal-cassandra')


def test_missing_nfs_address_is_a_specific_error(tmp_path):
    t = target('remote.ini', 'research', tmp_path)
    t.nfs = {}
    with pytest.raises(manifests.RenderError, match='NFS Service address of the data node server-a is unknown'):
        manifests.render(t)


def test_settings_that_deploy_refuses_stop_the_render(tmp_path):
    t = target('single-node.ini', 'main', tmp_path, overrides={'main_services.tika_mem_limit': '1G'})
    with pytest.raises(manifests.RenderError, match='deploy.py refuses'):
        manifests.render(t)


# Parity ---------------------------------------------------------------------------------------------------------------

def fake_tree(tmp_path, extra):
    tree = tmp_path / 'tree'
    for pattern in ('main_services/ops/docker/docker-compose.yaml', 'main_services/ops/docker/compose/*.yaml',
                    'ai_services/docker-compose.yaml', 'ai_services/compose/*.yaml'):
        for path in REPO.glob(pattern):
            target_path = tree / path.relative_to(REPO)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(path, target_path)
    (tree / 'main_services/ops/docker/compose/extra.yaml').write_text(yaml.safe_dump({'services': {extra: {'image': 'x'}}}))
    return tree


def test_unknown_compose_service_stops_the_render(tmp_path):
    tree = fake_tree(tmp_path, 'hoover4-new-service')
    with pytest.raises(manifests.RenderError) as caught:
        manifests.check_services(tree)
    assert 'hoover4-new-service in main_services/ops/docker/compose/extra.yaml' in str(caught.value)
    assert 'Compose_Parity.md' in str(caught.value)


def test_every_compose_service_has_a_row():
    found = compose.compose_service_names(REPO)
    assert set(found) <= set(manifests.SERVICES)
    assert set(manifests.SERVICES) <= set(found), 'SERVICES names a service that no Compose file has'


def parity_rows():
    text = (K3S / 'Compose_Parity.md').read_text()
    rows = {}
    for line in text.splitlines():
        m = re.match(r'\| `([^`]+)` \| ([^|]+) \|', line)
        if m:
            rows[m.group(1)] = m.group(2).strip()
    return rows


def test_parity_table_lists_every_service_with_its_role():
    rows = parity_rows()
    for name, row in manifests.SERVICES.items():
        assert name in rows, f'{name} has no row in k3s/Compose_Parity.md'
        assert rows[name] == row['role'], name


def test_parity_table_lists_every_volume_folder():
    text = (K3S / 'Compose_Parity.md').read_text()
    deploy = compose.deploy_module(REPO)
    for row in deploy.VOLUMES:
        assert f'`{row.name}`' in text, row.name


# The registry against the render ------------------------------------------------------------------------------------

def changed_value(setting):
    default = setting.default
    if setting.kind == 'bool':
        return 'false' if default == 'true' else 'true'
    if setting.kind == 'int':
        return str(int(default or '1') + 1)
    if setting.kind == 'size':
        return f'{int(operator_settings().size_bytes(default) * 2 // 1024 ** 2) or 2048}M'
    return None


def test_registry_services_cover_the_changed_compose_services(tmp_path):
    """A changed ini setting changes only the services that the registry names."""
    registry = operator_settings().REGISTRY
    t = target('single-node.ini', 'main', tmp_path)

    def services_with(values):
        ini = tmp_path / 'probe.ini'
        ini.write_text(manifests.zone_ini_text(manifests.Target(**{**t.__dict__, 'values': values})))
        return compose.load(ini, REPO)[3]

    base = services_with(t.values)
    checked, wrong = 0, {}
    for setting in registry.values():
        if not setting.ini or setting.services == ('gpu-pool',) or setting.ini[0] == 'storage':
            continue
        value = changed_value(setting)
        if value is None or setting.apply != 'restart':
            continue
        try:
            changed = services_with({**t.values, setting.key: value})
        except BaseException:  # noqa: B036  deploy.py refuses a value that breaks a rule between two keys.
            continue
        differs = {n for n in base if json.dumps(base[n], sort_keys=True, default=str) != json.dumps(changed.get(n), sort_keys=True, default=str)}
        if not differs <= set(setting.services):
            wrong[setting.key] = sorted(differs - set(setting.services))
        checked += 1
    assert wrong == {}, json.dumps(wrong, indent=0)
    assert checked > 80


# A new installation of a single-node site, and the application switch ------------------------------------------------

def test_a_new_single_node_installation_keeps_its_datasets_on_claims(tmp_path):
    text = re.sub(r'source_ini = .*\n', '', site_text('single-node.ini'))
    path = tmp_path / 'new.ini'
    path.write_text(text)
    t = manifests.target_from_site(path, 'main', revision=REVISION, state=tmp_path / 'no-state', nfs={})
    items = items_of(t)
    claims = {i['metadata']['name'] for i in items if i['kind'] == 'PersistentVolumeClaim'}
    assert {'dataset-testdata', 'dataset-uploads'} <= claims
    volumes = {v['name']: v for v in get(items, 'StatefulSet', 'hoover-workers')['spec']['template']['spec']['volumes']}
    sources = [v.get('persistentVolumeClaim') for v in volumes.values() if v.get('persistentVolumeClaim', {}).get('claimName', '').startswith('dataset-')]
    assert {'claimName': 'dataset-testdata'} in sources
    mounts = [m for c in get(items, 'StatefulSet', 'hoover-workers')['spec']['template']['spec']['containers'] for m in c.get('volumeMounts', [])]
    assert any(m['mountPath'] == '/data/testdata' and m.get('readOnly') for m in mounts)
    assert not [v for v in volumes.values() if 'nfs' in v or 'hostPath' in v and 'dataset' in v['name']]


def test_a_disabled_hoover_renders_zero_replicas_and_keeps_its_claims(tmp_path):
    S = operator_settings()
    state = S.State(tmp_path / 'state')
    state.save(0, {'zone:zone-a': {'app.hoover': 'false'}})
    path = tmp_path / 'single.ini'
    path.write_text(site_text('single-node.ini'))
    t = manifests.target_from_site(path, 'main', revision=REVISION, state=tmp_path / 'state', nfs=NFS)
    items = items_of(t)
    assert all(i['spec']['replicas'] == 0 for i in items if i['kind'] in ('Deployment', 'StatefulSet'))
    assert [i for i in items if i['kind'] == 'PersistentVolumeClaim']
    # The pinned revision 0 has no override, so the installation runs.
    t0 = manifests.target_from_site(path, 'main', revision=REVISION, state=tmp_path / 'state', nfs=NFS, settings_revision=0)
    assert t0.enabled


# The GPU pool of a site with GPU nodes -------------------------------------------------------------------------------

def _gpu_pool():
    import importlib.util
    spec = importlib.util.spec_from_file_location('gpu_pool', REPO / 'k3s/platform/gpu/gpu_pool.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gpu_pool_runs_every_gpu_service_on_its_node_with_the_selected_runtime():
    import config
    pool = _gpu_pool()
    site = config.parse(site_text('remote.ini'))
    for runtime, runtime_class in (('runsc', 'gvisor-gpu'), ('runc', 'nvidia')):
        items = pool.objects(site, runtime, REVISION)
        deployments = {i['metadata']['name']: i for i in items if i['kind'] == 'Deployment'}
        assert set(deployments) == {'vllm-gpu-1', 'ai-server-gpu-1', 'easyocr-gpu-1', 'gateway-gpu-1'}
        for name in ('vllm-gpu-1', 'ai-server-gpu-1', 'easyocr-gpu-1'):
            spec = deployments[name]['spec']['template']['spec']
            assert spec['runtimeClassName'] == runtime_class
            assert spec['nodeSelector'] == {'kubernetes.io/hostname': 'gpu-1'}
            assert {'key': 'hoover.dev/gpu', 'operator': 'Equal', 'value': 'true', 'effect': 'NoSchedule'} in spec['tolerations']
            assert not [v for v in spec['volumes'] if 'hostPath' in v and not v['hostPath']['path'].startswith('/srv/hoover-data/gpu/')]
    gateway = next(i for i in items if i['kind'] == 'ConfigMap' and i['metadata']['name'] == 'gateway-gpu-1')
    text = gateway['data']['default.conf.template']
    # Every port checks the pool key, and only the model server receives it.
    assert text.count('if ($http_authorization != "Bearer ${POOL_KEY}") { return 403; }') == 3
    assert text.count('proxy_set_header Authorization $http_authorization;') == 1
    ports = deployments['gateway-gpu-1']['spec']['template']['spec']['containers'][0]['ports']
    assert {(p['containerPort'], p.get('hostIP')) for p in ports} == {(21960, '10.0.0.5'), (21961, '10.0.0.5'), (21962, '10.0.0.5')}


def test_the_central_gpu_proxy_sends_the_pool_key_on_every_port_of_a_site_pool(tmp_path):
    import gpu
    key = tmp_path / 'key'
    key.write_text('pool-key')
    for gateway, keyed in ((True, 3), (False, 1)):
        items = gpu.proxy({'address': 'gateway.gpu-pool.svc.cluster.local' if gateway else '192.0.2.50',
                           'api_key_file': str(key), 'gateway': gateway})
        config_map = next(i for i in items if i['kind'] == 'ConfigMap')
        assert config_map['data']['default.conf.template'].count('Bearer ${VLLM_KEY}') == keyed


def test_gpu_nodes_reach_the_host_scripts_with_their_flag():
    import config
    hosts = config.legacy_hosts(config.parse(site_text('remote.ini')))['hosts']
    assert hosts['gpu-1']['gpu'] is True and hosts['edge']['gpu'] is False


# The calls placement and the public endpoints -------------------------------------------------------------------------

def _public_endpoints():
    import importlib.util
    spec = importlib.util.spec_from_file_location('public_endpoints', REPO / 'k3s/platform/calls/public_endpoints.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_calls_node_takes_the_media_services_and_its_public_address():
    import config
    remote = config.parse(site_text('remote.ini'))
    values = config.legacy_settings(remote)
    assert values['calls_node'] == 'calls' and values['calls_public_address'] == '203.0.113.11'
    assert values['calls_turn_listen'] == ['10.0.0.4', '203.0.113.11']
    # Without a calls node the public node runs them. The local node has no public address, so the pods advertise.
    single = config.legacy_settings(config.parse(site_text('single-node.ini')))
    assert single['calls_node'] == 'dev' and single['calls_public_address'] == ''
    without = config.parse(site_text('remote.ini').replace('[node.calls]\nroles = calls', '[node.calls]\nroles = worker\nstorage_tiers = hdd\nlvm_volume_group = tier-hdd'))
    assert config.legacy_settings(without)['calls_node'] == 'edge'


def test_public_dns_and_firewall_name_the_frontend_and_the_media_node():
    import config
    module = _public_endpoints()
    remote = config.parse(site_text('remote.ini'))
    records = {r['name']: r for r in module.dns(remote)}
    assert records['turn.example.org']['address'] == '203.0.113.11'
    assert records['hoover.zone-a.example.org']['address'] == '203.0.113.10'
    assert records['sfu.zone-a.example.org']['address'] == '203.0.113.10'
    assert not [r for r in records.values() if r['internal']]
    rules = module.firewall(remote)
    media = {(r['protocol'], r['port']) for r in rules['calls']}
    assert {('udp', 10000), ('tcp', 7881), ('udp', 7882), ('udp', 3478), ('tcp', 3478)} <= media
    assert ('tcp', 443) not in media and ('tcp', 443) in {(r['protocol'], r['port']) for r in rules['edge']}
    script = (REPO / 'k3s/hosts/root-install-public-firewall.sh').read_text()
    assert 'udp dport { 7882, 10000 } accept' in script and 'tcp dport 7881 accept' in script


@pytest.mark.parametrize('fixture,name', [('remote.ini', 'zone-a'), ('remote.ini', 'research'), ('single-node.ini', 'main')])
def test_no_workload_names_a_volume_or_mount_twice(tmp_path, fixture, name):
    import collections
    for item in items_of(target(fixture, name, tmp_path)):
        if item['kind'] not in ('Deployment', 'StatefulSet'):
            continue
        spec = item['spec']['template']['spec']
        volumes = [v['name'] for v in spec.get('volumes', [])]
        assert not [v for v, n in collections.Counter(volumes).items() if n > 1], item['metadata']['name']
        for c in spec['containers'] + spec.get('initContainers', []):
            paths = [m['mountPath'] for m in c.get('volumeMounts', [])]
            assert not [p for p, n in collections.Counter(paths).items() if n > 1], (item['metadata']['name'], c['name'])


def test_an_extra_dataset_folder_is_a_read_only_export_of_its_data_node(tmp_path):
    text = site_text('remote.ini').replace('collection_bucket_prefix = zone-a-c-',
                                           'collection_bucket_prefix = zone-a-c-\nextra_datasets = archive:worker-b:/storage/archive')
    site = config.parse(text)
    assert site.hoovers['zone-a'].extra_datasets == (('archive', 'worker-b', '/storage/archive'),)
    assert config.parse(config.dump(site)) == site
    assert config.legacy_settings(site)['hoover_data']['extra'] == {
        'zone-a': [{'name': 'archive', 'node': 'worker-b', 'path': '/storage/archive'}]}
    path = tmp_path / 'site.ini'
    path.write_text(text)
    t = manifests.target_from_site(path, 'zone-a', revision=REVISION, state=tmp_path / 'no-state',
                                   nfs={**NFS, 'worker-b': '10.43.0.12'})
    mounts = {m['name']: m for m in manifests.dataset_mounts(t)}
    assert mounts['archive']['path'] == '/data/archive' and mounts['archive']['writable'] is False
    assert mounts['archive']['volume'] == {'nfs': {'server': '10.43.0.12', 'path': '/extra/zone-a/archive', 'readOnly': True}}
    with pytest.raises(config.SiteError, match='not a node with the role data'):
        config.parse(text.replace('archive:worker-b:', 'archive:edge:'))
