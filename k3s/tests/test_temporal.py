"""The Temporal of a site: the history shard key, the render of temporal.py, the zone key and the network policies."""
import base64
import json

import pytest

from test_shared_stores import by, remote

import config  # noqa: E402
import cpu_requests  # noqa: E402
import temporal  # noqa: E402


def site_request(key):
    """The measured CPU request of a shared store workload (part site of cpu-requests.json)."""
    return cpu_requests.TABLE['site'][key]['request']


def objects(stores='{nodes: [server-a, worker-b]}', zones=2):
    site = remote(stores)
    return temporal.objects(site, config.store_plan(site), zones, '{"keys": []}')


def test_the_history_shard_count_keeps_its_value_of_creation():
    plan = config.store_plan(remote('{nodes: [server-a, worker-b], history_shards: 256}'))
    assert config.store_change_problems({'temporal_history_shards': 256, 'garage_replication_factor': 1}, plan) == []
    # A plan recorded before the key existed takes the value of the site file.
    assert config.store_change_problems({'garage_replication_factor': 1}, plan) == []
    problems = config.store_change_problems({'temporal_history_shards': 128, 'garage_replication_factor': 1}, plan)
    assert problems == ['Temporal keeps the history shard count 128 of its creation. Set vars.stores history_shards to 128.']
    with pytest.raises(config.SiteError, match='history_shards = 0 must be a whole number of at least 1'):
        remote('{history_shards: 0}')


def test_the_stores_of_temporal_shard_one_copy_over_their_nodes():
    items = objects('{nodes: [server-a, worker-b], cassandra: {nodes: 2}, opensearch: {nodes: 2}, temporal: {pods: 2}}')
    for store in ('temporal-cassandra', 'temporal-opensearch'):
        workload = by(items, 'StatefulSet', store)
        spec = workload['spec']['template']['spec']
        assert workload['spec']['replicas'] == 2 and spec['runtimeClassName'] == 'gvisor'
        anti = spec['affinity']['podAntiAffinity']['requiredDuringSchedulingIgnoredDuringExecution'][0]
        assert anti == {'labelSelector': {'matchLabels': {'hoover.dev/store': store}}, 'topologyKey': 'kubernetes.io/hostname'}
        nodes = spec['affinity']['nodeAffinity']['requiredDuringSchedulingIgnoredDuringExecution']['nodeSelectorTerms'][0]
        assert nodes['matchExpressions'][0]['values'] == ['server-a', 'worker-b']
        claim = workload['spec']['volumeClaimTemplates'][0]['spec']
        assert claim['storageClassName'] == 'hdd-ext4'
    assert by(items, 'StatefulSet', 'temporal-cassandra')['spec']['volumeClaimTemplates'][0]['spec']['resources'] == {
        'requests': {'storage': '40Gi'}}
    search = by(items, 'StatefulSet', 'temporal-opensearch')['spec']['template']['spec']['containers'][0]
    env = {e['name']: e.get('value') for e in search['env']}
    assert env['OPENSEARCH_JAVA_OPTS'] == '-Xms1280m -Xmx1280m' and env['DISABLE_SECURITY_PLUGIN'] == 'true'
    assert env['cluster.initial_cluster_manager_nodes'] == 'temporal-opensearch-0,temporal-opensearch-1'
    assert search['resources'] == {'requests': {'cpu': site_request('statefulset/temporal-opensearch'), 'memory': '1920Mi'},
                                   'limits': {'cpu': '2', 'memory': '3584Mi'}}
    assert by(items, 'Service', 'temporal-opensearch')['spec']['selector'] == {'app.kubernetes.io/name': 'temporal-opensearch'}
    assert by(items, 'Deployment', 'temporal')['spec']['replicas'] == 2
    template = by(items, 'ConfigMap', 'temporal-config')['data']['config_template.yaml']
    assert 'temporal-cassandra-0.temporal-cassandra-peers.hoover-stores.svc.cluster.local,temporal-cassandra-1.' in template
    # The defaults: one pod of each store and of Temporal, and OpenSearch as a single node.
    items = objects()
    assert [by(items, k, n)['spec']['replicas'] for k, n in (('StatefulSet', 'temporal-cassandra'),
                                                            ('StatefulSet', 'temporal-opensearch'), ('Deployment', 'temporal'))] == [1, 1, 1]
    env = {e['name']: e.get('value') for e in by(items, 'StatefulSet', 'temporal-opensearch')['spec']['template']['spec']['containers'][0]['env']}
    assert env['discovery.type'] == 'single-node' and 'cluster.initial_cluster_manager_nodes' not in env


def test_the_cassandra_heap_follows_the_live_data():
    def container(stores):
        workload = by(objects(stores), 'StatefulSet', 'temporal-cassandra')
        c = workload['spec']['template']['spec']['containers'][0]
        return {e['name']: e.get('value') for e in c['env']}, c['resources']
    # 2 GiB of data by default: 1.5 GiB + 0.4 x 2 GiB = 2.3 GiB, rounded up to 64 MiB.
    env, resources = container('{nodes: [server-a]}')
    assert env['MAX_HEAP_SIZE'] == '2368M' and env['HEAP_NEWSIZE'] == '200M'
    assert env['JVM_EXTRA_OPTS'] == '-XX:MaxDirectMemorySize=1G'
    assert resources == {'requests': {'cpu': site_request('statefulset/temporal-cassandra'), 'memory': '3392Mi'},
                         'limits': {'cpu': '2', 'memory': '6464Mi'}}
    # The heap stops at 8 GiB.
    env, resources = container('{nodes: [server-a], cassandra: {data_gib: 40}}')
    assert env['MAX_HEAP_SIZE'] == '8192M' and resources['requests']['memory'] == '9216Mi'
    assert temporal.cassandra_values(1)['heap'] == '1984M'


def test_the_schema_job_keeps_one_copy_and_temporal_reads_one_node():
    items = objects('{nodes: [server-a, worker-b], opensearch: {nodes: 2}}')
    script = by(items, 'Job', next(i['metadata']['name'] for i in items if i['kind'] == 'Job'))['spec']['template']['spec'][
        'containers'][0]['command'][-1]
    assert 'create -k temporal --rf 1' in script and '"number_of_replicas": 0' in script
    assert '"number_of_shards": 2' in script
    template = by(items, 'ConfigMap', 'temporal-config')['data']['config_template.yaml']
    assert 'numHistoryShards: 128' in template and 'consistency: LOCAL_ONE' in template
    assert 'authorizer: default' in template and 'claimMapper: default' in template
    spec = by(items, 'Deployment', 'temporal')['spec']['template']['spec']
    assert [c['name'] for c in spec['containers']] == ['temporal']
    assert [(c['name'], c['restartPolicy']) for c in spec['initContainers']] == [('jwks', 'Always')]


def test_only_hoover_namespaces_reach_the_frontend_and_only_temporal_reaches_its_stores():
    items = objects()
    clients = by(items, 'NetworkPolicy', 'temporal-clients')['spec']['ingress']
    assert clients == [{'from': [{'namespaceSelector': {'matchLabels': {'hoover.dev/hoover': 'true'}}}],
                        'ports': [{'port': 7233}, {'port': 7243}]},
                       {'from': [{'podSelector': {'matchLabels': {'hoover.dev/store': 'temporal'}}}]}]
    for store, port in (('temporal-cassandra', 9042), ('temporal-opensearch', 9200)):
        rules = by(items, 'NetworkPolicy', f'{store}-clients')['spec']['ingress']
        assert rules[0] == {'from': [{'podSelector': {'matchLabels': {'hoover.dev/temporal-client': 'true'}}}], 'ports': [{'port': port}]}
        assert 'namespaceSelector' not in json.dumps(rules)


def test_the_zone_key_permits_writes_in_the_zone_namespace_only():
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives import hashes
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = temporal.token('zone-a', key)
    assert token == temporal.token('zone-a', key)
    header, claims, signature = token.split('.')

    def decode(part):
        return base64.urlsafe_b64decode(part + '=' * (-len(part) % 4))
    assert json.loads(decode(header)) == {'alg': 'RS256', 'typ': 'JWT', 'kid': temporal.KEY_ID}
    assert json.loads(decode(claims)) == {'sub': 'hoover-zone-a', 'permissions': ['zone-a:write']}
    key.public_key().verify(decode(signature), f'{header}.{claims}'.encode(), padding.PKCS1v15(), hashes.SHA256())
    published = json.loads(temporal.jwks(key.public_key().public_numbers()))['keys'][0]
    assert published['kid'] == temporal.KEY_ID and int.from_bytes(decode(published['n']), 'big') == key.public_key().public_numbers().n
