"""The Hoover render of k3s/hoover/manifests.py against the Compose files of the repository."""
import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from conftest import K3S, REPO, operator_settings, site_text, write_site
import compose
import config
import manifests

REVISION = '0123456789abcdef0123456789abcdef01234567'
NFS = {'server-a': '10.43.0.10', 'worker-b': '10.43.0.11'}
# The Compose development values of the store credentials and the shared secrets. No render may hold them.
COMPOSE_SECRETS = ('hoover4-garage-blob-secret-key-0', 'cbc5a1dbd1c832a3bdcb0abff4e5ffc950035febf867de39e9b079cec8863e1d',
                   'hoover4-garage-admin-token')


def target(site_name, zone, tmp_path, overrides=None):
    """The Target of a zone of a site fixture."""
    path = write_site(tmp_path, site_name)
    t = manifests.target_from_site(path, zone, revision=REVISION, state=tmp_path / 'no-state', nfs=NFS)
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
    return items_of(target('single-node.yml', 'zone-a', tmp_path))


# The single-node installation with the local store layout -----------------------------------------------------------------------------

def test_a_zone_derives_its_storage_names_from_its_id(single):
    workers = get(single, 'StatefulSet', 'hoover-workers')
    e = env(containers(workers)[0])
    assert e['HOOVER4_CLICKHOUSE_DB_PREFIX'] == 'zone_a'
    assert e['HOOVER4_MANTICORE_TABLE_PREFIX'] == 'zone_a_'
    assert e['S3_SYSTEM_BUCKET'] == 'zone-a-system'
    assert e['S3_COLLECTION_BUCKET_PREFIX'] == 'zone-a-c-'
    assert 'HOOVER4_HISTORY_SOURCE' not in e
    # One worker pod polls the shared queues, so the open work of the Compose install keeps its queues.
    assert 'HOOVER4_HOST_QUEUE' not in e


def test_several_worker_pods_poll_their_host_queues(tmp_path):
    t = target('single-node.yml', 'zone-a', tmp_path, overrides={'budget.worker_pods': '2'})
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


def test_the_history_shard_count_follows_the_operator_setting(tmp_path):
    items = items_of(target('single-node.yml', 'zone-a', tmp_path, {'main_services.temporal_history_shards': '64'}))
    assert env(containers(get(items, 'Deployment', 'temporal'))[0])['NUM_HISTORY_SHARDS'] == '64'


def test_dataset_mounts_are_claims_below_data(single):
    worker = containers(get(single, 'StatefulSet', 'hoover-workers'))[0]
    mounts = json.loads(env(worker)['HOOVER4_DATASET_MOUNTS'])
    assert mounts == [{'name': 'testdata', 'path': '/data/testdata', 'writable': False},
                      {'name': 'uploads', 'path': '/data/uploads', 'writable': True}]
    volumes = {v['name']: v for v in get(single, 'StatefulSet', 'hoover-workers')['spec']['template']['spec']['volumes']}
    assert volumes['data-uploads']['persistentVolumeClaim'] == {'claimName': 'dataset-uploads'}
    get(single, 'PersistentVolumeClaim', 'dataset-uploads')
    assert 'chat-control' not in volumes


def test_no_pod_of_the_render_mounts_a_host_folder(single):
    """The pod policy refuses a hostPath volume in a zone namespace."""
    for item in single:
        if item['kind'] in ('Deployment', 'StatefulSet', 'Job'):
            assert not [v for v in item['spec']['template']['spec'].get('volumes', []) if 'hostPath' in v], item['metadata']['name']


def test_operations_worker_mounts_backups_and_stores(single):
    ops = get(single, 'Deployment', 'hoover-operations')
    mounts = {(m['mountPath'], m['name'], m.get('readOnly', False)) for m in containers(ops)[0]['volumeMounts']}
    assert {('/backups', 'ops-backups', False), ('/stores/clickhouse', 'clickhouse-data', True),
            ('/stores/manticore', 'manticore-data', True), ('/stores/manticore-restore', 'manticore-data', False),
            ('/stores/garage/data', 'garage-data', True), ('/stores/garage/meta', 'garage-meta', True)} <= mounts
    clickhouse = containers(get(single, 'StatefulSet', 'clickhouse'))[-1]
    assert {'name': 'ops-backups', 'mountPath': '/var/lib/clickhouse/backups'} in clickhouse['volumeMounts']
    # The claims are local volumes that more than one pod mounts, so the pods with a claim share one node through a
    # required pod affinity to the label of LOCAL_GROUP. No pod names a node.
    affinity = {'podAffinity': {'requiredDuringSchedulingIgnoredDuringExecution': [
        {'labelSelector': {'matchLabels': manifests.LOCAL_GROUP}, 'topologyKey': 'kubernetes.io/hostname'}]}}
    for name, kind in (('hoover-operations', 'Deployment'), ('clickhouse', 'StatefulSet'), ('hoover-workers', 'StatefulSet')):
        template = get(single, kind, name)['spec']['template']
        assert template['spec']['affinity'] == affinity and 'nodeSelector' not in template['spec'], name
        assert template['metadata']['labels']['hoover.dev/volumes'] == 'local', name
    # Temporal has no claim. It follows the pods with a claim, and its own pod does not start the group.
    temporal = get(single, 'Deployment', 'temporal')['spec']['template']
    assert temporal['spec']['affinity'] == affinity and 'hoover.dev/volumes' not in temporal['metadata']['labels']


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


def test_a_site_without_a_gpu_pool_renders_no_gpu_forwarder(tmp_path):
    # The forwarder names the GPU proxy, which a site without vars.gpu_pool does not install, so its pod cannot start.
    text = site_text('single-node.yml').replace('    gpu_pool:\n      address: 192.0.2.50\n', '')
    assert 'gpu_pool' not in text
    path = write_site(tmp_path, 'single-node.yml', text)
    t = manifests.target_from_site(path, 'zone-a', revision=REVISION, state=tmp_path / 'no-state', nfs=NFS)
    items = items_of(t)
    assert not [i for i in items if i['metadata']['name'] in ('gpu', 'egress-gpu')]
    assert 'gpu-proxy' not in json.dumps(items)
    ini = manifests.zone_ini_text(t)
    assert '\nenabled = false\n' in ini[ini.index('[ai_services]'):].split('\n[')[0] + '\n'


def test_zone_hosts_have_one_label_below_the_domain(single):
    ingress = get(single, 'Ingress', 'hoover')
    assert ingress['spec']['rules'][0]['host'] == 'zone-a-hoover.hoover.test'
    proxy = containers(get(single, 'Deployment', 'oauth2-proxy'))[0]
    assert '--redirect-url=https://zone-a-hoover.hoover.test/oauth2/callback' in proxy['args']
    assert '--whitelist-domain=zone-a-hoover.hoover.test' in proxy['args']
    alpha = yaml.safe_load(get(single, 'ConfigMap', 'oauth2-proxy')['data']['alpha.yaml'])
    assert alpha['providers'][0]['oidcConfig']['issuerURL'] == 'https://zone-a-id.hoover.test/realms/opendesk'


def test_internet_tools_follow_the_setting(tmp_path):
    items = items_of(target('single-node.yml', 'zone-a', tmp_path, overrides={'main_services.internet_tools_enabled': 'true'}))
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
    grown = job(items_of(target('single-node.yml', 'zone-a', tmp_path, overrides={'volume.garage-data': '25Gi'})))
    assert env(containers(first)[0])['GARAGE_CAPACITY'] != env(containers(grown)[0])['GARAGE_CAPACITY']
    assert first['metadata']['name'] != grown['metadata']['name']
    assert job(items_of(target('single-node.yml', 'zone-a', tmp_path)))['metadata']['name'] == first['metadata']['name']


def test_service_commands_and_limits_follow_compose(tmp_path, single):
    t = target('single-node.yml', 'zone-a', tmp_path)
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
    assert workers['resources']['limits'] == {'memory': '13696Mi', 'cpu': '4'}
    assert workers['resources']['requests'] == {'cpu': '50m', 'memory': '1856Mi'}
    # Elasticsearch of the cassandra backend gets the heap and the limit of its measured use, not the Compose values.
    elastic = containers(get(single, 'StatefulSet', 'temporal-elasticsearch'))[-1]
    assert elastic['resources']['limits']['memory'] == '3584Mi'
    assert env(elastic)['ES_JAVA_OPTS'] == '-Xms1536m -Xmx1536m'


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
    first = manifests.render(target('single-node.yml', 'zone-a', tmp_path))
    second = manifests.render(target('single-node.yml', 'zone-a', tmp_path))
    assert first == second
    images = sorted(set(re.findall(r'"image": "([^"]+)"', first)))
    assert all(':0123456789ab' in i for i in images if i.startswith(manifests.REGISTRY))


# The remote topology ------------------------------------------------------------------------------------------------

def test_site_zone_uses_the_shared_stores_and_temporal(tmp_path):
    items = items_of(target('remote.yml', 'zone-a', tmp_path))
    names = {(i['kind'], i['metadata']['name']) for i in items}
    # The zone runs no Temporal and no Temporal store. It uses the Temporal of the site with its own namespace.
    assert not {n for n in names if n[0] in ('Deployment', 'StatefulSet', 'Job') and n[1].startswith('temporal')}
    assert ('StatefulSet', 'clickhouse') not in names
    assert not {n for n in names if n[0] == 'StatefulSet' and n[1].startswith('manticore')}
    for name in ('clickhouse', 'garage', 'manticore', 'manticore-vectors', 'temporal'):
        assert get(items, 'Service', name)['spec'] == {'type': 'ExternalName', 'externalName': f'{name}.hoover-stores.svc.cluster.local'}
    workers = get(items, 'Deployment', 'hoover-workers')
    e = env(containers(workers)[0])
    assert e['CLICKHOUSE_USER'] == 'zone_a_worker'
    assert e['HOOVER4_MANTICORE_TABLE_PREFIX'] == 'zone_a_'
    assert workers['spec']['template']['spec'].get('topologySpreadConstraints')
    clamav = get(items, 'Deployment', 'hoover4-clamav')['spec']['template']['spec']
    assert clamav['nodeSelector'] == {'kubernetes.io/hostname': 'edge'}


def test_a_zone_of_the_earlier_store_layout_is_refused(tmp_path):
    # zone-b has no stores value: its ClickHouse and Garage are in its zone namespace, and its data does not move.
    with pytest.raises(manifests.RenderError, match='zone-b keeps its ClickHouse and Garage in its zone namespace'):
        items_of(target('remote.yml', 'zone-b', tmp_path))


def test_a_site_zone_reaches_only_the_client_ports_of_the_shared_stores(tmp_path):
    items = items_of(target('remote.yml', 'zone-a', tmp_path))
    shared_ns = {'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'hoover-stores'}}}
    rules = get(items, 'NetworkPolicy', 'egress-stores')['spec']['egress']
    manticore_ports = [{'port': p} for p in (9306, 9307, 9308, 9309)]
    assert rules == [{'to': [{**shared_ns, 'podSelector': {'matchLabels': {'hoover.dev/store': 'clickhouse'}}}],
                          'ports': [{'port': 8123}, {'port': 9000}]},
                         {'to': [{**shared_ns, 'podSelector': {'matchLabels': {'hoover.dev/store': 'garage'}}}],
                          'ports': [{'port': 3900}]},
                         {'to': [{**shared_ns, 'podSelector': {'matchLabels': {'hoover.dev/store': 'temporal'}}}],
                          'ports': [{'port': 7233}, {'port': 7243}]},
                         {'to': [{**shared_ns, 'podSelector': {'matchLabels': {'hoover.dev/store': 'manticore'}}}],
                          'ports': manticore_ports},
                         {'to': [{**shared_ns, 'podSelector': {'matchLabels': {'hoover.dev/store': 'manticore-vectors'}}}],
                          'ports': manticore_ports}]
    browser = get(items, 'NetworkPolicy', 'egress-browser-stores')['spec']['egress']
    assert [r['ports'] for r in browser] == [[{'port': 8123}], [{'port': 3900}]]
    assert all(r['to'][0]['namespaceSelector'] == shared_ns['namespaceSelector'] for r in browser)


def ref(secret, key):
    return {'secretKeyRef': {'name': secret, 'key': key}}


def test_a_site_zone_uses_the_manticore_user_of_its_role_and_the_schema_proxy(tmp_path):
    items = items_of(target('remote.yml', 'zone-a', tmp_path))
    proxy_url = 'http://manticore-schema:8080'
    for name in ('hoover-workers', 'hoover-singletons', 'hoover-operations'):
        e = env(containers(get(items, 'Deployment', name))[0])
        assert e['MANTICORE_USER'] == 'zone_a_write' and e['MANTICORE_PASSWORD'] == ref('hoover-runtime', 'manticore-write'), name
        assert e['MANTICORE_SCHEMA_URL'] == proxy_url and e['MANTICORE_SCHEMA_TOKEN'] == ref('hoover-runtime', 'manticore-proxy-token')
    for name in ('hoover-website', 'hoover4-mcp-collections'):
        e = env(containers(get(items, 'Deployment', name))[0])
        assert e['MANTICORE_USER'] == 'zone_a_read' and e['MANTICORE_PASSWORD'] == ref('hoover-runtime', 'manticore-read'), name
        # The read user reaches the read-only HTTP listeners, and gets no proxy credential.
        assert (e['MANTICORE_URL'], e['MANTICORE_VECTORS_URL']) == ('http://manticore:9309', 'http://manticore-vectors:9309')
        assert 'MANTICORE_SCHEMA_TOKEN' not in e and 'MANTICORE_SCHEMA_URL' not in e
    # The website reads the daemon counters through the operation status, with a credential that allows nothing else.
    e = env(containers(get(items, 'Deployment', 'hoover-website'))[0])
    assert e['MANTICORE_STATUS_URL'] == proxy_url and e['MANTICORE_STATUS_TOKEN'] == ref('hoover-runtime', 'manticore-status-token')
    assert 'MANTICORE_STATUS_TOKEN' not in env(containers(get(items, 'Deployment', 'hoover4-mcp-collections'))[0])
    for item in workloads(items):
        if item['metadata']['name'] == 'manticore-schema':
            continue
        for c in containers(item):
            assert not [e for e in c.get('env', []) if e.get('valueFrom', {}).get('secretKeyRef', {}).get('name') == 'manticore-schema']
    proxy = get(items, 'Deployment', 'manticore-schema')
    c = containers(proxy)[0]
    e = env(c)
    assert c['command'][-3:] == ['-m', 'database.manticore_schema', 'serve'] and c['image'].startswith(manifests.REGISTRY + '/hoover-processing:')
    assert e['MANTICORE_USER'] == 'zone_a_schema' and e['HOOVER4_MANTICORE_TABLE_PREFIX'] == 'zone_a_'
    assert e['MANTICORE_PASSWORD'] == ref('manticore-schema', 'password') and e['MANTICORE_SCHEMA_TOKEN'] == ref('manticore-schema', 'token')
    assert e['MANTICORE_STATUS_TOKEN'] == ref('manticore-schema', 'status-token')
    # The export and the restore: the backup claim of the zone, on the node of the operations worker, and the file
    # service of the text daemon.
    assert e['MANTICORE_FILES_URL'] == 'http://manticore:9318' and e['HOOVER4_BACKUP_ROOT'] == '/backups'
    assert c['volumeMounts'] == [{'name': 'ops-backups', 'mountPath': '/backups'}]
    spec = proxy['spec']['template']['spec']
    assert spec['volumes'] == [{'name': 'ops-backups', 'persistentVolumeClaim': {'claimName': 'ops-backups'}}]
    assert spec['affinity']['podAffinity']['requiredDuringSchedulingIgnoredDuringExecution'][0]['labelSelector'] == {
        'matchLabels': {'app.kubernetes.io/name': 'hoover-operations'}}
    assert spec['priorityClassName'] == 'hoover-node-bound'
    files = get(items, 'NetworkPolicy', 'egress-manticore-files')['spec']
    assert files['podSelector'] == {'matchLabels': {'app.kubernetes.io/name': 'manticore-schema'}}
    assert files['egress'][0]['ports'] == [{'port': 9318}]
    assert files['egress'][0]['to'][0]['podSelector'] == {'matchLabels': {'hoover.dev/store': 'manticore'}}
    assert 'runtimeClassName' not in proxy['spec']['template']['spec']
    assert get(items, 'Service', 'manticore-schema')['spec']['ports'][0]['port'] == 8080
    # Only the pods with the write user and the website reach the proxy.
    clients = get(items, 'NetworkPolicy', 'schema-proxy-clients')['spec']
    assert clients['podSelector'] == {'matchLabels': {'app.kubernetes.io/name': 'manticore-schema'}}
    assert clients['ingress'][0]['from'][0]['podSelector']['matchExpressions'][0]['values'] == [
        'hoover-workers', 'hoover-singletons', 'hoover-operations', 'hoover-website']
    namespace_only = get(items, 'NetworkPolicy', 'namespace-only')['spec']['podSelector']['matchExpressions'][0]
    assert 'manticore-schema' in namespace_only['values']


def test_a_site_zone_of_the_earlier_manticore_layout_is_refused(tmp_path):
    t = target('remote.yml', 'zone-a', tmp_path)
    t.hoover.manticore = 'zone'
    with pytest.raises(manifests.RenderError, match='runs its own Manticore daemons in the zone namespace'):
        items_of(t)


def test_a_local_zone_has_no_schema_proxy(single):
    assert not [i for i in single if i['metadata']['name'] == 'manticore-schema']
    e = env(containers(get(single, 'StatefulSet', 'hoover-workers'))[0])
    assert 'MANTICORE_SCHEMA_URL' not in e


def test_a_zone_pod_names_no_node_and_requests_its_measured_memory(tmp_path):
    items = items_of(target('remote.yml', 'zone-a', tmp_path))
    assert get(items, 'Namespace', 'hoover-zone-a')['metadata']['labels'] == {'hoover.dev/zone': 'true', 'hoover.dev/hoover': 'true'}
    for item in workloads(items):
        spec = item['spec']['template']['spec']
        # Only the internet services name the public node. The zone layout shares one claim: the schema proxy follows
        # the operations worker for the claim ops-backups. No other pod has an affinity.
        if item['metadata']['name'] == 'manticore-schema':
            assert list(spec['affinity']) == ['podAffinity'] and 'nodeSelector' not in spec
        elif item['metadata']['name'] not in manifests.INTERNET:
            assert 'nodeSelector' not in spec and 'affinity' not in spec, item['metadata']['name']
        for c in containers(item):
            requested = manifests.mebibytes(c['resources']['requests']['memory'])
            assert requested <= manifests.mebibytes(c['resources']['limits']['memory']), (item['metadata']['name'], c['name'])
    web = containers(get(items, 'Deployment', 'hoover-website'))[0]['resources']
    assert web['requests']['memory'] == '320Mi' and web['limits']['memory'] == '2048Mi'
    clamav = containers(get(items, 'Deployment', 'hoover4-clamav'))[0]['resources']
    assert clamav['requests']['memory'] == '2048Mi' and clamav['limits']['memory'] == '3456Mi'
    import zone_ini
    assert zone_ini.derive(zone_ini.BUDGET)[('main_services', 'mcp_browser_mem_limit')] == '10240M'
    tika = containers(get(items, 'Deployment', 'hoover4-tika'))[0]['resources']
    assert tika['limits']['memory'] == '4096Mi'
    # A service without a Compose limit gets the measured value of UNLIMITED_IN_COMPOSE, and a request never exceeds
    # the limit.
    assert manifests.limits({}, manifests.UNLIMITED_IN_COMPOSE['hoover4-full-research-agent']) == ('2560Mi', None)
    assert manifests.request('hoover4-full-research-agent', '2560Mi') == '640Mi'
    assert manifests.request('hoover-workers', '1Gi') == '1Gi'


def test_only_the_temporal_clients_of_a_site_zone_get_its_namespace_and_key(tmp_path):
    items = items_of(target('remote.yml', 'zone-a', tmp_path))
    key = {'name': 'TEMPORAL_API_KEY', 'valueFrom': {'secretKeyRef': {'name': 'hoover-runtime', 'key': 'temporal-api-key'}}}
    with_key = set()
    for item in workloads(items):
        for c in containers(item) + item['spec']['template']['spec'].get('initContainers', []):
            if key in c.get('env', []):
                with_key.add(item['metadata']['name'])
            if any(e['name'] == 'TEMPORAL_HTTP_URL' for e in c.get('env', [])):
                assert env(c)['TEMPORAL_NAMESPACE'] == 'zone-a', item['metadata']['name']
    assert with_key == {'hoover-website', 'hoover-workers', 'hoover-singletons', 'hoover-operations', 'hoover4-mcp-todo'}


def test_only_the_operations_pod_of_a_site_zone_gets_the_export_bucket(tmp_path):
    items = items_of(target('remote.yml', 'zone-a', tmp_path))
    found = {}
    for item in workloads(items):
        for c in containers(item):
            if 'CLICKHOUSE_BACKUP_S3_URL' in env(c):
                found[item['metadata']['name']] = env(c)['CLICKHOUSE_BACKUP_S3_URL']
    assert found == {'hoover-operations': 'http://garage.hoover-stores.svc.cluster.local:3900/zone-a-exports'}
    # The local store layout keeps the file of the backup root.
    (tmp_path / 'local').mkdir()
    with_local = items_of(target('single-node.yml', 'zone-a', tmp_path / 'local'))
    assert not any('CLICKHOUSE_BACKUP_S3_URL' in env(c) for item in workloads(with_local) for c in containers(item))


def test_a_site_zone_of_the_earlier_temporal_is_refused(tmp_path, monkeypatch):
    original = config.zone_hoover

    def earlier(zone, entry, site=None):
        return original(zone, {k: v for k, v in entry.items() if k != 'temporal'}, site)
    monkeypatch.setattr(config, 'zone_hoover', earlier)
    with pytest.raises(manifests.RenderError, match='zone-a runs its own Temporal on the PostgreSQL of the zone'):
        items_of(target('remote.yml', 'zone-a', tmp_path))


def test_a_local_store_zone_of_a_remote_site_has_its_own_names_and_nfs_data(tmp_path):
    items = items_of(target('remote.yml', 'zone-c', tmp_path))
    e = env(containers(get(items, 'StatefulSet', 'hoover-workers'))[0])
    assert e['HOOVER4_CLICKHOUSE_DB_PREFIX'] == 'zone_c'
    assert e['S3_SYSTEM_BUCKET'] == 'zone-c-system'
    volumes = {v['name']: v for v in get(items, 'StatefulSet', 'hoover-workers')['spec']['template']['spec']['volumes']}
    assert volumes['data-uploads']['nfs'] == {'server': '10.43.0.10', 'path': '/zone-c/uploads', 'readOnly': False}
    # A fast claim takes the first fast tier of the site. The node edge has nvme.
    assert get(items, 'PersistentVolumeClaim', 'clickhouse-data')['spec']['storageClassName'] == 'nvme-ext4'
    assert get(items, 'PersistentVolumeClaim', 'ops-backups')['spec']['storageClassName'] == 'hdd-ext4'
    get(items, 'StatefulSet', 'temporal-cassandra')


def test_missing_nfs_address_is_a_specific_error(tmp_path):
    t = target('remote.yml', 'zone-c', tmp_path)
    t.nfs = {}
    with pytest.raises(manifests.RenderError, match='NFS Service address of the data node server-a is unknown'):
        manifests.render(t)


def test_settings_that_deploy_refuses_stop_the_render(tmp_path):
    t = target('single-node.yml', 'zone-a', tmp_path, overrides={'main_services.tika_mem_limit': '1G'})
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
    t = target('single-node.yml', 'zone-a', tmp_path)

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
    path = write_site(tmp_path, 'single-node.yml')
    t = manifests.target_from_site(path, 'zone-a', revision=REVISION, state=tmp_path / 'no-state', nfs={})
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
    path = write_site(tmp_path, 'single-node.yml')
    t = manifests.target_from_site(path, 'zone-a', revision=REVISION, state=tmp_path / 'state', nfs=NFS)
    items = items_of(t)
    assert all(i['spec']['replicas'] == 0 for i in items if i['kind'] in ('Deployment', 'StatefulSet'))
    assert [i for i in items if i['kind'] == 'PersistentVolumeClaim']
    # The pinned revision 0 has no override, so the installation runs.
    t0 = manifests.target_from_site(path, 'zone-a', revision=REVISION, state=tmp_path / 'state', nfs=NFS, settings_revision=0)
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
    site = config.parse(site_text('remote.yml'))
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
            # Each GPU service reads the GPU key from HOOVER4_GPU_API_KEY and checks it.
            env = {e['name']: e for e in spec['containers'][0]['env']}
            assert env['HOOVER4_GPU_API_KEY']['valueFrom'] == {'secretKeyRef': {'name': 'gpu-pool', 'key': 'pool-key'}}
            command = ' '.join(spec['containers'][0].get('command', []))
            assert 'HOOVER4_GPU_API_KEY' in command and '/run/secrets/gpu_api_key' in command, name
            mounts = {m['mountPath']: m for m in spec['containers'][0]['volumeMounts']}
            assert mounts['/run/secrets/gpu_api_key']['name'] == 'pool-key'
    gateway = next(i for i in items if i['kind'] == 'ConfigMap' and i['metadata']['name'] == 'gateway-gpu-1')
    text = gateway['data']['default.conf.template']
    # Every port checks the pool key and sends it on, because every service checks it too.
    assert text.count('if ($http_authorization != "Bearer ${POOL_KEY}") { return 403; }') == 3
    assert text.count('proxy_set_header Authorization $http_authorization;') == 3
    ports = deployments['gateway-gpu-1']['spec']['template']['spec']['containers'][0]['ports']
    assert {(p['containerPort'], p.get('hostIP')) for p in ports} == {(21960, '10.0.0.5'), (21961, '10.0.0.5'), (21962, '10.0.0.5')}


def test_the_central_gpu_proxy_sends_the_gpu_key_on_every_port_and_derives_the_zone_tokens_from_it():
    import hashlib
    import hmac
    import gpu
    for gateway in (True, False):
        items = gpu.proxy({'address': 'gateway.gpu-pool.svc.cluster.local' if gateway else '192.0.2.50',
                           'gateway': gateway}, 'the-gpu-key')
        config_map = next(i for i in items if i['kind'] == 'ConfigMap')
        assert config_map['data']['default.conf.template'].count('proxy_set_header Authorization "Bearer ${GPU_KEY}";') == 3
        assert "createHmac('sha256', '${GPU_KEY}')" in config_map['data']['auth.js.template']
        secret = next(i for i in items if i['kind'] == 'Secret')
        assert secret['stringData'] == {'gpu-key': 'the-gpu-key'}
        deployment = next(i for i in items if i['kind'] == 'Deployment')
        assert deployment['spec']['template']['metadata']['annotations']['hoover.dev/key'] == \
            hashlib.sha256(b'the-gpu-key').hexdigest()[:12]
    assert gpu.zone_token('the-gpu-key', 'zone-a') == hmac.new(b'the-gpu-key', b'zone-a', hashlib.sha256).hexdigest()
    assert gpu.zone_token('another-key', 'zone-a') != gpu.zone_token('the-gpu-key', 'zone-a')


def test_the_gpu_key_is_one_secret_that_the_first_read_creates(monkeypatch):
    import base64
    import json as json_module
    import gpu
    stored = {}

    class Done:
        def __init__(self, stdout=''):
            self.stdout = stdout

    def kubectl(*args, input=None, check=True):
        if args[:1] == ('apply',):
            item = json_module.loads(input)
            if item['kind'] == 'Secret':
                stored.update(item)
            return Done()
        assert args[:5] == ('-n', 'operator-portal', 'get', 'secret', 'gpu-api-key')
        return Done(base64.b64encode(stored['stringData']['key'].encode()).decode() if stored else '')

    monkeypatch.setattr(gpu, 'kubectl', kubectl)
    with pytest.raises(SystemExit, match='gpu-api-key of operator-portal is missing'):
        gpu.api_key(create=False)
    first = gpu.api_key()
    assert len(first) == 64 and gpu.api_key() == first
    assert stored['metadata'] == {'name': 'gpu-api-key', 'namespace': 'operator-portal', 'labels': {'hoover.dev/secret': 'gpu-api-key'}}
    with pytest.raises(SystemExit, match='without spaces'):
        gpu.write_key('a b')


def test_gpu_nodes_reach_the_host_steps_with_their_flag(tmp_path):
    import config
    nodes = config.ansible_variables(config.parse(site_text('remote.yml')), tmp_path)['hoover4_nodes']
    assert nodes['gpu-1']['gpu'] is True and nodes['edge']['gpu'] is False


# The calls placement and the public endpoints -------------------------------------------------------------------------

def _public_endpoints():
    import importlib.util
    spec = importlib.util.spec_from_file_location('public_endpoints', REPO / 'k3s/platform/calls/public_endpoints.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_calls_node_takes_the_media_services_and_its_public_address():
    import config
    remote = config.parse(site_text('remote.yml'))
    values = config.legacy_settings(remote)
    assert values['calls_node'] == 'calls' and values['calls_public_address'] == '203.0.113.11'
    assert values['calls_turn_listen'] == ['10.0.0.4', '203.0.113.11']
    # Without a calls node the public node runs them. The local node has no public address, so the pods advertise.
    single = config.legacy_settings(config.parse(site_text('single-node.yml')))
    assert single['calls_node'] == 'dev' and single['calls_public_address'] == ''
    without = config.parse(site_text('remote.yml').replace('node_roles: calls', 'node_roles: worker\n'
                                                                                  '      storage: {hdd: tier-hdd}'))
    assert config.legacy_settings(without)['calls_node'] == 'edge'


def test_public_dns_and_firewall_name_the_frontend_and_the_media_node(tmp_path):
    import config
    module = _public_endpoints()
    remote = config.read(write_site(tmp_path, 'remote.yml'))
    records = {r['name']: r for r in module.dns(remote)}
    assert records['turn.example.org']['address'] == '203.0.113.11'
    # One wildcard covers every zone host, so the records name no zone.
    assert records['*.example.org']['address'] == records['example.org']['address'] == '203.0.113.10'
    assert set(records) == {'*.example.org', 'example.org', 'turn.example.org'}
    assert not [r for r in records.values() if r['internal']]
    rules = module.firewall(remote)
    media = {(r['protocol'], r['port']) for r in rules['calls']}
    assert {('udp', 10000), ('tcp', 7881), ('udp', 7882), ('udp', 3478), ('tcp', 3478)} <= media
    assert ('tcp', 443) not in media and ('tcp', 443) in {(r['protocol'], r['port']) for r in rules['edge']}
    assert ('udp', 51820) in media
    script = (REPO / 'k3s/ansible/roles/hoover4_public_firewall/files/public-firewall.sh').read_text()
    assert 'udp dport { 7882, 10000 } accept' in script and 'tcp dport 7881 accept' in script


@pytest.mark.parametrize('fixture,name', [('remote.yml', 'zone-a'), ('remote.yml', 'zone-c'), ('single-node.yml', 'zone-a')])
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
    path = write_site(tmp_path, 'remote.yml')
    state = json.loads(config.read(path).zone_state().read_text())
    state['zones']['zone-a']['extra_datasets'] = ['archive:worker-b:/storage/archive']
    config.read(path).zone_state().write_text(json.dumps(state))
    site = config.read(path)
    assert config.hoovers(site)['zone-a'].extra_datasets == (('archive', 'worker-b', '/storage/archive'),)
    assert config.legacy_settings(site)['hoover_data']['extra'] == {
        'zone-a': [{'name': 'archive', 'node': 'worker-b', 'path': '/storage/archive'}]}
    t = manifests.target_from_site(path, 'zone-a', revision=REVISION, state=tmp_path / 'no-state',
                                   nfs={**NFS, 'worker-b': '10.43.0.12'})
    mounts = {m['name']: m for m in manifests.dataset_mounts(t)}
    assert mounts['archive']['path'] == '/data/archive' and mounts['archive']['writable'] is False
    assert mounts['archive']['volume'] == {'nfs': {'server': '10.43.0.12', 'path': '/extra/zone-a/archive', 'readOnly': True}}
    state['zones']['zone-a']['extra_datasets'] = ['archive:edge:/storage/archive']
    assert any('not a node with the role data' in p for p in config.zones_problems(site, state))


def test_the_proxy_reaches_the_sign_in_service_on_every_frontend_address(tmp_path):
    # The zone names resolve to the first frontend bind inside the cluster, the VPN address of the public node. A policy
    # with only the public address made the token exchange of each sign-in fail with "connection refused".
    items = items_of(target('remote.yml', 'zone-a', tmp_path))
    rule = get(items, 'NetworkPolicy', 'egress-oidc')['spec']['egress'][0]
    assert [b['ipBlock']['cidr'] for b in rule['to']] == ['10.0.0.1/32', '203.0.113.10/32']
    assert rule['ports'] == [{'port': 443}]
    # The sign-in check of the deploy driver carries the same label as the proxy, so it tests the same policy.
    policy = get(items, 'NetworkPolicy', 'egress-oidc')['spec']['podSelector']['matchLabels']
    proxy = get(items, 'Deployment', 'oauth2-proxy')['spec']['template']['metadata']['labels']
    assert policy == {'hoover.dev/oidc': 'client'} and proxy['hoover.dev/oidc'] == 'client'


# The relay peers of coturn and the check of the host rule coturn_peers (k3s/platform/calls/turn_peers.py) ------------

def turn_peers_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location('turn_peers', K3S / 'platform/calls/turn_peers.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_coturn_relays_udp_only_to_the_pods_of_the_media_node_and_the_checked_public_address():
    turn_peers = turn_peers_module()
    lines = turn_peers.peer_lines('10.42.3.0/24', '')
    assert lines == ['no-tcp-relay', 'denied-peer-ip=0.0.0.0-255.255.255.255',
                     'denied-peer-ip=::-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff', 'allowed-peer-ip=10.42.3.2-10.42.3.254']
    # The bridge address .1, the pods of other nodes and the rest of the cluster range are no peers.
    assert not [line for line in lines if '10.42.0.0' in line or '10.42.3.1-' in line or line.endswith('10.42.3.1')]
    assert turn_peers.peer_lines('10.42.3.0/24', '203.0.113.7')[-1] == 'allowed-peer-ip=203.0.113.7'


def test_the_public_peer_needs_the_dropped_probe_of_the_coturn_user():
    turn_peers = turn_peers_module()
    assert turn_peers.chain_problem('edge', '203.0.113.7', 'blocked\n', 'open\n') == ''
    message = turn_peers.chain_problem('edge', '203.0.113.7', 'open\n', 'open\n')
    assert 'no host rule coturn_peers for its public address 203.0.113.7' in message
    assert 'hoover4_public_firewall' in message
    assert 'cannot verify' in turn_peers.chain_problem('edge', '203.0.113.7', 'blocked', 'blocked')
    pod = turn_peers.probe_pod('calls', 'edge', '203.0.113.7', 'python:pinned', {'runAsNonRoot': True})
    spec = pod['spec']
    assert spec['hostNetwork'] and spec['nodeSelector'] == {'kubernetes.io/hostname': 'edge'}
    users = {c['name']: c['securityContext']['runAsUser'] for c in spec['containers']}
    assert users == {'coturn': turn_peers.COTURN_UID, 'control': turn_peers.PROBE_CONTROL_UID}
    assert all(c['command'][-2:] == ['203.0.113.7', str(turn_peers.PROBE_PORT)] for c in spec['containers'])
    # On a full media node the probe preempts a pod of the default priority, so the calls step does not wait.
    assert spec['priorityClassName'] == 'hoover-node-bound'
    assert all(c['resources']['requests'] == {'cpu': '10m', 'memory': '16Mi'} for c in spec['containers'])


def test_the_probe_reports_an_open_and_a_refused_port_as_open():
    import socket
    import subprocess
    import sys
    turn_peers = turn_peers_module()
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen(1)
    port = server.getsockname()[1]
    out = subprocess.run([sys.executable, '-c', turn_peers.PROBE, '127.0.0.1', str(port)], capture_output=True, text=True)
    assert out.stdout.strip() == 'open'
    server.close()
    out = subprocess.run([sys.executable, '-c', turn_peers.PROBE, '127.0.0.1', str(port)], capture_output=True, text=True)
    assert out.stdout.strip() == 'open'
