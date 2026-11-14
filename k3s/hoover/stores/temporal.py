#!/usr/bin/env python3
"""The Temporal of a site: one Temporal, one Cassandra and one OpenSearch in the namespace hoover-stores.

Each zone of the store layout site (../../config.py ZONE_VALUES) has its own Temporal namespace, with the name of the
zone. register creates it with the retention of the zone and adds the search attribute CollectionDataset, and remove
deletes it. The Hoover services of a zone connect with the namespace and the key of the zone (TEMPORAL_NAMESPACE and
TEMPORAL_API_KEY, ../manifests.py).

Access: the Temporal frontend checks a JWT on each request (authorizer and claim mapper default). The key of a zone is
a JWT with the permission <zone>:write, signed with the RSA key of the Secret temporal-auth. The write role starts,
reads, signals and cancels workflows and polls task queues of its own namespace only. It cannot create, change or
delete a namespace, and it cannot change a search attribute, because the attributes of the shared visibility index
apply to every namespace. A request without a key, or for another namespace, gets PERMISSION_DENIED. The frontend reads
the public key from a sidecar of its own pod (nginx on 127.0.0.1:7299, ConfigMap temporal-jwks). The key carries no
expiry. A new signing key replaces every zone key: delete the Secret temporal-auth, run apply, then apply each zone.
The Temporal worker service uses the internal frontend on port 7236, which checks no key. Only the Temporal pods
reach that port (network()), and the commands of this script use it inside a Temporal pod.

Plan (vars.stores, ../../config.py store_plan()). Each store keeps one copy of each part of its data. A lost node
loses its part until it returns, and the backups are the recovery path (k3s/Readme.md).
- Cassandra runs one pod on each of its nodes (cassandra), and the nodes share the token ranges. The keyspace temporal
  has the replication factor 1 (SimpleStrategy), and Temporal reads and writes with the consistency LOCAL_ONE.
- OpenSearch runs one pod on each of its nodes (opensearch), and every pod can be the cluster manager. The visibility
  index has one primary shard for each node of its creation and no replica shard.
- Temporal runs temporal pods of every service (frontend, internal frontend, history, matching, worker), preferably
  on different nodes. Each pod announces its pod address to the others. Temporal holds no data.
- history_shards is the history shard count. Temporal keeps the count of its creation, and apply refuses a change.
The Services of Temporal and OpenSearch select every ready pod.
Sizes: the Cassandra heap follows the live data (cassandra_values()). The Cassandra request is the heap plus the
measured memory outside the heap, and its limit adds a margin for the page cache of the live data. OpenSearch has the
heap of the Elasticsearch of the local layout (../manifests.py) and a request of its measured use. Temporal has the
limit of ../../zones/memory-limits.json. The claims hold the first size of the Compose import
(../../platform/operator/settings.py VOLUMES) times the zone count, at least one zone.
Cassandra, OpenSearch and Temporal run in gVisor. Cassandra and OpenSearch use file system volumes of TopoLVM.
The schema Job creates the keyspace, the tables, the index template and the index, and sets the replica shards. Each
of its commands keeps present data, so the Job can run again.

Usage: temporal.py show               print the objects
       temporal.py register <zone>    create or update the namespace of a zone with the retention of its setting
       temporal.py remove <zone>      delete the namespace of a zone
"""
import base64, hashlib, json, math, os, subprocess, sys, time
import common, hoover
import config  # noqa: E402  (common puts the k3s folder on the path)
import zonestate  # noqa: E402

sys.path.insert(0, str(common.SOURCE / 'hoover'))
import compose  # noqa: E402

NS = 'hoover-stores'
AUTH = 'temporal-auth'
KEY_ID = 'hoover-temporal-1'
HOOVER_LABEL = 'hoover.dev/hoover'
# The label of the pods that reach Cassandra and OpenSearch: the Temporal pods and the schema Job.
CLIENT = {'hoover.dev/temporal-client': 'true'}
TEMPORAL_IMAGE = 'docker.io/temporalio/auto-setup:1.23.1@sha256:a73792b9289ac504ee6c49fb0dfb430626bc4f422f15cf885503de49e4ae283b'
CASSANDRA_IMAGE = 'docker.io/library/cassandra:3.11.9@sha256:c59186c4e1b446dc7ef85da7acab6ee561a8191f79fd6e34d81ee465633a2acb'
OPENSEARCH_IMAGE = ('docker.io/opensearchproject/opensearch:2.19.3'
                    '@sha256:e96cc6ae1500a073d973c0906f30f7cf4d9c461f32f855f9242a2da933660cdd')
NGINX = 'docker.io/library/nginx:1.29.3-alpine@sha256:b3c656d55d7ad751196f21b7fd2e8d4da9cb430e32f646adcf92441b72f82b14'
INDEX = 'temporal_visibility_v1'
# The Temporal ports: frontend gRPC and HTTP (the zone clients), internal frontend, history, matching, worker, and the
# membership port of each service.
CLIENT_PORTS = (7233, 7243)
INTERNAL = '127.0.0.1:7236'
# The memory request of Temporal (../manifests.py REQUESTS). The OpenSearch heap and limit of the Elasticsearch of the
# local layout: 1.5 times the largest measured heap use, and twice the heap plus 512 MiB. The OpenSearch request is
# its measured use with that heap.
REQUESTS = {'temporal': '448Mi', 'temporal-opensearch': '2176Mi'}
OPENSEARCH_HEAP = '1536m'
OPENSEARCH_LIMIT = '3584Mi'
# Cassandra: the memory outside the heap in a running pod (direct buffers, metaspace, threads, the gVisor sandbox),
# the direct memory cap, and the CPU limit, which sets the new generation (100 MiB for each CPU).
CASSANDRA_OFF_HEAP_MIB = 1024
CASSANDRA_DIRECT = '1G'
CASSANDRA_CPUS = 2
SIZES = {'temporal-cassandra': '20Gi', 'temporal-opensearch': '10Gi'}
# The search attributes that the Hoover workflows set (main_services/processing/tasks/visibility.py).
SEARCH_ATTRIBUTES = {'CollectionDataset': 'Keyword'}


def cassandra_values(data_gib):
    """Heap, new generation, direct memory, memory request and limit and chunk cache of a Cassandra node.

    The heap is 2 GiB plus 0.4 GiB for each GiB of live data, at least 2 GiB and at most 8 GiB, rounded up to 64 MiB.
    The request is the heap plus CASSANDRA_OFF_HEAP_MIB. The limit adds 1 GiB and the live data, because the page
    cache of the data files is memory of the gVisor sandbox. The chunk cache is the Compose default.
    """
    heap = math.ceil(min(8192, max(2048, 2048 + 0.4 * 1024 * data_gib)) / 64) * 64
    request = heap + CASSANDRA_OFF_HEAP_MIB
    chunk_cache = compose.deploy_module().DEFAULTS['main_services']['cassandra_chunk_cache_mb']
    return {'heap': f'{heap}M', 'heap_new': f'{100 * CASSANDRA_CPUS}M', 'direct': CASSANDRA_DIRECT,
            'request': f'{request}Mi', 'limit': f'{request + 1024 + 1024 * data_gib}Mi', 'chunk_cache_mb': chunk_cache}


def size(store, zones):
    return f'{int(hoover.gibibytes(SIZES[store]) * max(1, zones))}Gi'


def peers(store, replicas):
    return [f'{store}-{i}.{store}-peers.{NS}.svc.cluster.local' for i in range(replicas)]


# One copy of each row, so one node answers each read and write.
CONSISTENCY = 'LOCAL_ONE'


def config_template(plan):
    """The Temporal configuration. The image renders it with dockerize at each start, which fills in POD_IP."""
    return f'''log:
    stdout: true
    level: info
persistence:
    numHistoryShards: {int(plan['history_shards'])}
    defaultStore: default
    visibilityStore: es-visibility
    datastores:
        default:
            cassandra:
                hosts: "{','.join(peers('temporal-cassandra', plan['cassandra'])[:2])}"
                keyspace: temporal
                port: 9042
                maxConns: 20
                consistency:
                    default:
                        consistency: {CONSISTENCY}
                        serialConsistency: LOCAL_SERIAL
        es-visibility:
            elasticsearch:
                version: v7
                url:
                    scheme: http
                    host: "temporal-opensearch:9200"
                indices:
                    visibility: {INDEX}
global:
    membership:
        maxJoinDuration: 30s
        broadcastAddress: "{{{{ .Env.POD_IP }}}}"
    authorization:
        jwtKeyProvider:
            keySourceURIs:
                - http://127.0.0.1:7299/jwks.json
            refreshInterval: 1m
        permissionsClaimName: permissions
        authorizer: default
        claimMapper: default
services:
    frontend:
        rpc: {{grpcPort: 7233, membershipPort: 6933, bindOnIP: 0.0.0.0, httpPort: 7243}}
    internal-frontend:
        rpc: {{grpcPort: 7236, membershipPort: 6936, bindOnIP: 0.0.0.0}}
    matching:
        rpc: {{grpcPort: 7235, membershipPort: 6935, bindOnIP: 0.0.0.0}}
    history:
        rpc: {{grpcPort: 7234, membershipPort: 6934, bindOnIP: 0.0.0.0}}
    worker:
        rpc: {{grpcPort: 7239, membershipPort: 6939, bindOnIP: 0.0.0.0}}
clusterMetadata:
    enableGlobalNamespace: false
    failoverVersionIncrement: 10
    masterClusterName: active
    currentClusterName: active
    clusterInformation:
        active:
            enabled: true
            initialFailoverVersion: 1
            rpcName: frontend
            rpcAddress: 127.0.0.1:7233
dcRedirectionPolicy:
    policy: noop
dynamicConfigClient:
    filepath: /etc/temporal/config/dynamicconfig/docker.yaml
    pollInterval: 60s
'''


def schema_script(plan):
    """The schema Job: keyspace, tables, index template, index and replica shards. Each command keeps present data. A new
    index gets one primary shard for each OpenSearch node."""
    return f'''set -eu
seed=temporal-cassandra-0.temporal-cassandra-peers.{NS}.svc.cluster.local
until temporal-cassandra-tool --ep "$seed" validate-health; do sleep 5; done
temporal-cassandra-tool --ep "$seed" create -k temporal --rf 1
temporal-cassandra-tool --ep "$seed" -k temporal setup-schema -v 0.0
temporal-cassandra-tool --ep "$seed" -k temporal update-schema -d /etc/temporal/schema/cassandra/temporal/versioned
es=http://temporal-opensearch:9200
until curl -sf "$es/_cluster/health?wait_for_status=yellow&timeout=5s" >/dev/null; do sleep 5; done
schema=/etc/temporal/schema/elasticsearch/visibility
curl -sf -X PUT "$es/_cluster/settings" -H 'Content-Type: application/json' --data-binary @$schema/cluster_settings_v7.json
curl -sf -X PUT "$es/_template/temporal_visibility_v1_template" -H 'Content-Type: application/json' \\
  --data-binary @$schema/index_template_v7.json
curl -sf -o /dev/null -I "$es/{INDEX}" || curl -sf -X PUT "$es/{INDEX}" -H 'Content-Type: application/json' \\
  -d '{{"settings": {{"index": {{"number_of_shards": {plan['opensearch']}}}}}}}'
curl -sf -X PUT "$es/{INDEX}/_settings" -H 'Content-Type: application/json' \\
  -d '{{"index": {{"auto_expand_replicas": false, "number_of_replicas": 0}}}}'
echo
'''


def jwks(public_numbers):
    def b64(number):
        raw = number.to_bytes((number.bit_length() + 7) // 8, 'big')
        return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()
    return json.dumps({'keys': [{'kty': 'RSA', 'alg': 'RS256', 'use': 'sig', 'kid': KEY_ID,
                                 'n': b64(public_numbers.n), 'e': b64(public_numbers.e)}]})


NGINX_CONF = 'server { listen 127.0.0.1:7299; access_log off; location = /jwks.json { root /jwks; } }\n'


def configmap(name, files):
    return {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': name, 'namespace': NS, 'labels': {common.LABEL: 'config'}},
            'data': files}


def headless(store, ports):
    out = hoover.service(f'{store}-peers', NS, ports, {'app.kubernetes.io/name': store}, headless=True)
    return out


def anti_affinity(store, required):
    term = {'labelSelector': {'matchLabels': {'hoover.dev/store': store}}, 'topologyKey': 'kubernetes.io/hostname'}
    if required:
        return {'requiredDuringSchedulingIgnoredDuringExecution': [term]}
    return {'preferredDuringSchedulingIgnoredDuringExecution': [{'weight': 100, 'podAffinityTerm': term}]}


def store_statefulset(store, container, tier, claim_size, replicas, nodes, security=None, init=()):
    """A gVisor StatefulSet with one file system claim data for each pod, one pod per node of nodes."""
    spec = {'runtimeClassName': 'gvisor', 'terminationGracePeriodSeconds': 120, 'enableServiceLinks': False,
            'containers': [container], 'initContainers': list(init), 'volumes': [],
            'affinity': {'nodeAffinity': {'requiredDuringSchedulingIgnoredDuringExecution': {'nodeSelectorTerms': [{'matchExpressions': [
                {'key': 'kubernetes.io/hostname', 'operator': 'In', 'values': list(nodes)}]}]}},
                'podAntiAffinity': anti_affinity(store, True)}}
    if security:
        spec['securityContext'] = security
    labels = {'app.kubernetes.io/name': store, common.LABEL: 'store', 'hoover.dev/store': store}
    claim = {'metadata': {'name': 'data'}, 'spec': {'accessModes': ['ReadWriteOnce'], 'storageClassName': f'{tier}-ext4',
                                                    'resources': {'requests': {'storage': claim_size}}}}
    return {'apiVersion': 'apps/v1', 'kind': 'StatefulSet',
            'metadata': {'name': store, 'namespace': NS, 'labels': {common.LABEL: 'store', 'hoover.dev/store': store}},
            'spec': {'replicas': replicas, 'serviceName': f'{store}-peers', 'podManagementPolicy': 'OrderedReady',
                     'selector': {'matchLabels': {'hoover.dev/store': store}}, 'updateStrategy': {'type': 'OnDelete'},
                     'template': {'metadata': {'labels': labels}, 'spec': spec}, 'volumeClaimTemplates': [claim]}}


def resources(request, limit, cpu='2'):
    return {'requests': {'cpu': '50m', 'memory': request}, 'limits': {'cpu': cpu, 'memory': limit}}


def cassandra(s, plan, zones):
    import shared
    values = cassandra_values(plan['cassandra_data_gib'])
    seeds = ','.join(peers('temporal-cassandra', plan['cassandra'])[:2])
    env = {'CASSANDRA_CLUSTER_NAME': 'hoover-temporal', 'CASSANDRA_SEEDS': seeds, 'CASSANDRA_DC': 'dc1', 'CASSANDRA_RACK': 'rack1',
           'CASSANDRA_ENDPOINT_SNITCH': 'GossipingPropertyFileSnitch', 'MAX_HEAP_SIZE': values['heap'],
           'HEAP_NEWSIZE': values['heap_new'], 'JVM_EXTRA_OPTS': f'-XX:MaxDirectMemorySize={values["direct"]}',
           'CASSANDRA_CHUNK_CACHE_MB': values['chunk_cache_mb']}
    container = {
        'name': 'cassandra', 'image': CASSANDRA_IMAGE, 'command': ['sh', '/usr/local/bin/hoover4-cassandra-entrypoint.sh'],
        'env': [{'name': k, 'value': str(v)} for k, v in env.items()],
        'ports': [{'name': 'cql', 'containerPort': 9042}, {'name': 'gossip', 'containerPort': 7000}],
        'volumeMounts': [{'name': 'data', 'mountPath': '/var/lib/cassandra'},
                         {'name': 'entrypoint', 'mountPath': '/usr/local/bin/hoover4-cassandra-entrypoint.sh',
                          'subPath': 'entrypoint.sh', 'readOnly': True}],
        # CQL opens after the node joined the ring, so the next pod starts after this one joined.
        'readinessProbe': {'tcpSocket': {'port': 9042}, 'periodSeconds': 5, 'failureThreshold': 3},
        'resources': resources(values['request'], values['limit'], str(CASSANDRA_CPUS))}
    tier, nodes = shared.tier(s, plan['nodes'], 'temporal-cassandra', plan['cassandra'])
    entrypoint = (common.SOURCE.parent / 'main_services/ops/docker/cassandra-entrypoint.sh').read_text()
    workload = store_statefulset('temporal-cassandra', container, tier, size('temporal-cassandra', zones), plan['cassandra'], nodes)
    workload['spec']['template']['spec']['volumes'].append({'name': 'entrypoint', 'configMap': {'name': 'temporal-cassandra-entrypoint'}})
    return [configmap('temporal-cassandra-entrypoint', {'entrypoint.sh': entrypoint}),
            headless('temporal-cassandra', [('cql', 9042), ('gossip', 7000)]), workload]


def opensearch(s, plan, zones):
    import shared
    names = [f'temporal-opensearch-{i}' for i in range(plan['opensearch'])]
    env = {'cluster.name': 'hoover-temporal', 'network.host': '0.0.0.0', 'DISABLE_SECURITY_PLUGIN': 'true',
           'DISABLE_INSTALL_DEMO_CONFIG': 'true', 'OPENSEARCH_JAVA_OPTS': f'-Xms{OPENSEARCH_HEAP} -Xmx{OPENSEARCH_HEAP}',
           # gVisor gives no mmap count check and no system call filter, so OpenSearch uses neither.
           'node.store.allow_mmap': 'false', 'bootstrap.system_call_filter': 'false',
           'cluster.routing.allocation.disk.watermark.low': '512mb', 'cluster.routing.allocation.disk.watermark.high': '256mb',
           'cluster.routing.allocation.disk.watermark.flood_stage': '128mb'}
    if plan['opensearch'] == 1:
        env['discovery.type'] = 'single-node'
    else:
        env['discovery.seed_hosts'] = 'temporal-opensearch-peers'
        env['cluster.initial_cluster_manager_nodes'] = ','.join(names)
    container = {
        'name': 'opensearch', 'image': OPENSEARCH_IMAGE,
        'env': [{'name': 'node.name', 'valueFrom': {'fieldRef': {'fieldPath': 'metadata.name'}}}] +
               [{'name': k, 'value': v} for k, v in env.items()],
        'ports': [{'name': 'http', 'containerPort': 9200}, {'name': 'transport', 'containerPort': 9300}],
        'volumeMounts': [{'name': 'data', 'mountPath': '/usr/share/opensearch/data'}],
        'readinessProbe': {'httpGet': {'path': '/_cluster/health?local=true', 'port': 9200}, 'periodSeconds': 5, 'failureThreshold': 3},
        'resources': resources(REQUESTS['temporal-opensearch'], OPENSEARCH_LIMIT)}
    tier, nodes = shared.tier(s, plan['nodes'], 'temporal-opensearch', plan['opensearch'])
    workload = store_statefulset('temporal-opensearch', container, tier, size('temporal-opensearch', zones), plan['opensearch'], nodes,
                                 security={'fsGroup': 1000})
    # The nodes find each other before they are ready, so the StatefulSet starts its pods together.
    workload['spec']['podManagementPolicy'] = 'Parallel'
    return [headless('temporal-opensearch', [('http', 9200), ('transport', 9300)]),
            hoover.service('temporal-opensearch', NS, [('http', 9200)], {'app.kubernetes.io/name': 'temporal-opensearch'}),
            workload]


def schema_job(plan):
    script = schema_script(plan)
    digest = hashlib.sha256((TEMPORAL_IMAGE + script).encode()).hexdigest()[:10]
    c = {'name': 'schema', 'image': TEMPORAL_IMAGE, 'command': ['bash', '-c', script],
         'resources': {'requests': {'cpu': '50m', 'memory': '64Mi'}, 'limits': {'cpu': '1', 'memory': '256Mi'}}}
    spec = {'runtimeClassName': 'gvisor', 'restartPolicy': 'OnFailure', 'enableServiceLinks': False, 'containers': [c]}
    return {'apiVersion': 'batch/v1', 'kind': 'Job',
            'metadata': {'name': f'temporal-schema-{digest}', 'namespace': NS, 'labels': {common.LABEL: 'temporal-schema'}},
            'spec': {'backoffLimit': 30, 'ttlSecondsAfterFinished': 7 * 86400,
                     'template': {'metadata': {'labels': {'app.kubernetes.io/name': 'temporal-schema', **CLIENT}}, 'spec': spec}}}


def temporal(plan, public_jwks, tree=common.SOURCE.parent):
    dynamic = (tree / 'main_services/ops/docker/temporal-dynamicconfig/docker.yaml').read_text()
    files = {'config_template.yaml': config_template(plan)}
    server = {
        'name': 'temporal', 'image': TEMPORAL_IMAGE,
        'env': [{'name': 'POD_IP', 'valueFrom': {'fieldRef': {'fieldPath': 'status.podIP'}}},
                {'name': 'SERVICES', 'value': 'frontend:internal-frontend:history:matching:worker'}],
        'ports': [{'name': 'grpc', 'containerPort': 7233}, {'name': 'http', 'containerPort': 7243}],
        'volumeMounts': [{'name': 'config', 'mountPath': '/etc/temporal/config/config_template.yaml',
                          'subPath': 'config_template.yaml', 'readOnly': True},
                         {'name': 'dynamic', 'mountPath': '/etc/temporal/config/dynamicconfig', 'readOnly': True}],
        'readinessProbe': {'exec': {'command': ['temporal', 'operator', 'cluster', 'health', '--address', INTERNAL]},
                           'periodSeconds': 5, 'timeoutSeconds': 5, 'failureThreshold': 3},
        'resources': resources(REQUESTS['temporal'], hoover.LIMITS['temporal'])}
    # A sidecar that starts before Temporal: Temporal reads the public key once at its start and stops without it.
    keys = {'name': 'jwks', 'image': NGINX, 'restartPolicy': 'Always',
            'startupProbe': {'exec': {'command': ['wget', '-q', '-O', '/dev/null', 'http://127.0.0.1:7299/jwks.json']},
                             'periodSeconds': 1, 'failureThreshold': 60},
            'volumeMounts': [{'name': 'jwks', 'mountPath': '/etc/nginx/conf.d/default.conf', 'subPath': 'default.conf', 'readOnly': True},
                             {'name': 'jwks', 'mountPath': '/jwks/jwks.json', 'subPath': 'jwks.json', 'readOnly': True}],
            'resources': {'requests': {'cpu': '10m', 'memory': '16Mi'}, 'limits': {'cpu': '200m', 'memory': '64Mi'}}}
    digest = hashlib.sha256(json.dumps([files, dynamic, public_jwks], sort_keys=True).encode()).hexdigest()[:12]
    spec = {'runtimeClassName': 'gvisor', 'enableServiceLinks': False, 'terminationGracePeriodSeconds': 30,
            'initContainers': [keys], 'containers': [server],
            'affinity': {'podAntiAffinity': anti_affinity('temporal', False)},
            'volumes': [{'name': 'config', 'configMap': {'name': 'temporal-config'}},
                        {'name': 'dynamic', 'configMap': {'name': 'temporal-dynamicconfig'}},
                        {'name': 'jwks', 'configMap': {'name': 'temporal-jwks'}}]}
    labels = {'app.kubernetes.io/name': 'temporal', 'hoover.dev/store': 'temporal', **CLIENT}
    deployment = {'apiVersion': 'apps/v1', 'kind': 'Deployment',
                  'metadata': {'name': 'temporal', 'namespace': NS, 'labels': {common.LABEL: 'temporal'}},
                  'spec': {'replicas': plan['temporal'], 'selector': {'matchLabels': {'app.kubernetes.io/name': 'temporal'}},
                           'strategy': {'type': 'RollingUpdate', 'rollingUpdate': {'maxUnavailable': 1, 'maxSurge': 0}},
                           'template': {'metadata': {'labels': labels, 'annotations': {'hoover.dev/config': digest}}, 'spec': spec}}}
    return [configmap('temporal-config', files), configmap('temporal-dynamicconfig', {'docker.yaml': dynamic}),
            configmap('temporal-jwks', {'jwks.json': public_jwks, 'default.conf': NGINX_CONF}),
            hoover.service('temporal', NS, [('grpc', 7233), ('http', 7243)], {'app.kubernetes.io/name': 'temporal'}),
            deployment]


def network():
    """The policies of the Temporal pods and their stores, beside the closed policy of shared.py network()."""
    def policy(name, spec):
        return {'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy', 'metadata': {'name': name, 'namespace': NS}, 'spec': spec}

    def pods(store):
        return {'podSelector': {'matchLabels': {'hoover.dev/store': store}}}
    hoover_ns = {'namespaceSelector': {'matchLabels': {HOOVER_LABEL: 'true'}}}
    clients = {'podSelector': {'matchLabels': CLIENT}}
    return [
        # The zones reach the frontend only. The internal frontend, history, matching, worker and membership ports
        # take connections only from the Temporal pods.
        policy('temporal-clients', {'podSelector': {'matchLabels': {'hoover.dev/store': 'temporal'}}, 'policyTypes': ['Ingress'],
                                    'ingress': [{'from': [hoover_ns], 'ports': [{'port': p} for p in CLIENT_PORTS]},
                                                {'from': [pods('temporal')]}]}),
        policy('temporal-cassandra-clients', {'podSelector': {'matchLabels': {'hoover.dev/store': 'temporal-cassandra'}},
                                              'policyTypes': ['Ingress'],
                                              'ingress': [{'from': [clients], 'ports': [{'port': 9042}]},
                                                          {'from': [pods('temporal-cassandra')], 'ports': [{'port': 7000}, {'port': 9042}]}]}),
        policy('temporal-opensearch-clients', {'podSelector': {'matchLabels': {'hoover.dev/store': 'temporal-opensearch'}},
                                               'policyTypes': ['Ingress'],
                                               'ingress': [{'from': [clients], 'ports': [{'port': 9200}]},
                                                           {'from': [pods('temporal-opensearch')], 'ports': [{'port': 9200}, {'port': 9300}]}]}),
    ]


def objects(s, plan, zones, public_jwks):
    return [*network(), *cassandra(s, plan, zones), *opensearch(s, plan, zones), schema_job(plan), *temporal(plan, public_jwks)]


# ----------------------------------------------------------------------------------------------------------------------
# Keys
# ----------------------------------------------------------------------------------------------------------------------

def signing_key():
    """The RSA key of the Secret temporal-auth. apply creates it once."""
    from cryptography.hazmat.primitives import serialization
    found = common.kubectl('-n', NS, 'get', 'secret', AUTH, '--ignore-not-found', '-o', 'json').strip()
    if not found:
        raise SystemExit(f'the Secret {AUTH} does not exist in {NS}. Run deploy-k3s up --steps stores.')
    pem = base64.b64decode(json.loads(found)['data']['signing-key.pem'])
    return serialization.load_pem_private_key(pem, password=None)


def ensure_signing_key():
    """Create the Secret temporal-auth with a new RSA key, unless it exists. Return the public key set."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    found = common.kubectl('-n', NS, 'get', 'secret', AUTH, '--ignore-not-found', '-o', 'name').strip()
    if not found:
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        common.apply({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': AUTH, 'namespace': NS, 'labels': {common.LABEL: 'credentials'}},
                      'type': 'Opaque', 'stringData': {'signing-key.pem': pem}})
    return jwks(signing_key().public_key().public_numbers())


def token(zone, key=None):
    """The key of a zone: a JWT with the permission <zone>:write. The same signing key gives the same token."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    def b64(data):
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode()
    key = key or signing_key()
    header = b64(json.dumps({'alg': 'RS256', 'typ': 'JWT', 'kid': KEY_ID}, separators=(',', ':')).encode())
    claims = b64(json.dumps({'sub': f'hoover-{zone}', 'permissions': [f'{zone}:write']}, separators=(',', ':')).encode())
    signature = key.sign(f'{header}.{claims}'.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f'{header}.{claims}.{b64(signature)}'


# ----------------------------------------------------------------------------------------------------------------------
# Cluster state
# ----------------------------------------------------------------------------------------------------------------------

def ready_pod():
    import shared
    for pod in sorted(common.kubectl_json('-n', NS, 'get', 'pods', '-l', 'app.kubernetes.io/name=temporal')['items'],
                      key=lambda p: p['metadata']['name']):
        if shared.is_ready(pod):
            return pod['metadata']['name']
    raise SystemExit(f'the Temporal of the site has no ready pod in {NS}. Run deploy-k3s up --steps stores.')


def cli(*args, check=True):
    """Run the Temporal CLI in a Temporal pod against the internal frontend."""
    r = subprocess.run(common.K + ['-n', NS, 'exec', ready_pod(), '-c', 'temporal', '--', 'temporal', *args, '--address', INTERNAL],
                       capture_output=True, text=True, timeout=300)
    if check and r.returncode:
        raise SystemExit(f'temporal {" ".join(args[:3])} failed: {(r.stderr or r.stdout).strip()[-400:]}')
    return r


def wait_job(name, timeout=1800):
    deadline = time.monotonic() + timeout
    while True:
        job = common.kubectl_json('-n', NS, 'get', 'job', name)
        if job.get('status', {}).get('succeeded'):
            return
        if any(c['type'] == 'Failed' and c['status'] == 'True' for c in job.get('status', {}).get('conditions', [])):
            raise SystemExit(f'the Job {name} failed. Read: kubectl -n {NS} logs job/{name}')
        if time.monotonic() >= deadline:
            raise SystemExit(f'the Job {name} did not finish in {timeout} s')
        time.sleep(5)


def wait_deployment(name, timeout=900):
    deadline = time.monotonic() + timeout
    while True:
        d = common.kubectl_json('-n', NS, 'get', 'deployment', name)
        status, want = d.get('status', {}), d['spec'].get('replicas', 1)
        if (status.get('observedGeneration', 0) >= d['metadata']['generation'] and status.get('updatedReplicas', 0) == want
                and status.get('readyReplicas', 0) == want and status.get('replicas', 0) == want):
            return
        if time.monotonic() >= deadline:
            raise SystemExit(f'the Deployment {name} in {NS} did not become ready in {timeout} s')
        time.sleep(5)


def apply(s, plan, zones):
    """Create or update the Temporal of the site and wait until it serves. shared.py apply calls it."""
    import shared
    public_jwks = ensure_signing_key()
    items = objects(s, plan, zones, public_jwks)
    job = next(o for o in items if o['kind'] == 'Job')
    present = common.kubectl('-n', NS, 'get', 'job', job['metadata']['name'], '--ignore-not-found', '-o', 'name').strip()
    hoover.apply([o for o in items if o['kind'] not in ('Job', 'Deployment')], keep_replicas=False)
    for store in ('temporal-cassandra', 'temporal-opensearch'):
        shared.wait_current(store, timeout=1800)
    if not present:
        common.apply(job)
    wait_job(job['metadata']['name'])
    hoover.apply([o for o in items if o['kind'] == 'Deployment'])
    wait_deployment('temporal')
    common.log('stores.jsonl', step='temporal', namespace=NS, cassandra=plan['cassandra'], opensearch=plan['opensearch'],
               pods=plan['temporal'], history_shards=plan['history_shards'], consistency=CONSISTENCY, zones=zones)


def register(zone, retention):
    """Create the namespace of a zone with its retention, or set the retention of the present namespace, and add the
    search attributes. Each command keeps present workflows."""
    if cli('operator', 'namespace', 'describe', '-n', zone, check=False).returncode:
        cli('operator', 'namespace', 'create', '-n', zone, '--retention', retention, '--description', f'Hoover {zone}')
    else:
        cli('operator', 'namespace', 'update', '-n', zone, '--retention', retention)
    listed = ''
    for _ in range(60):
        found = cli('operator', 'search-attribute', 'list', '-n', zone, check=False)
        if found.returncode == 0:
            listed = found.stdout
            break
        time.sleep(2)
    missing = [name for name in SEARCH_ATTRIBUTES if name not in listed.split()]
    if missing:
        args = [a for name in missing for a in ('--name', name, '--type', SEARCH_ATTRIBUTES[name])]
        cli('operator', 'search-attribute', 'create', '-n', zone, *args)
    common.log('stores.jsonl', step='temporal-namespace', zone=zone, retention=retention, attributes_added=missing)


def remove(zone):
    """Delete the namespace of a zone. Temporal deletes its workflows in the background."""
    if cli('operator', 'namespace', 'describe', '-n', zone, check=False).returncode:
        common.log('stores.jsonl', step='temporal-namespace-removed', zone=zone, present=False)
        return
    cli('operator', 'namespace', 'delete', '-n', zone, '--yes')
    common.log('stores.jsonl', step='temporal-namespace-removed', zone=zone, present=True)


def main(argv):
    if not argv or argv[0] not in ('show', 'register', 'remove') or (argv[0] != 'show') != (len(argv) == 2):
        sys.exit(__doc__)
    if argv[0] == 'show':
        import shared
        s = shared.site()
        print(json.dumps(objects(s, config.store_plan(s), len(shared.site_zones()), '{"keys": []}'), indent=1))
    elif argv[0] == 'register':
        zone = argv[1]
        if zone not in zonestate.load()['zones']:
            raise SystemExit(f'the zone state has no zone {zone}')
        register(zone, retention_of(zone))
    else:
        remove(argv[1])


def retention_of(zone):
    """The setting main_services.temporal_retention of the Hoover installation of a zone, from the saved operator
    settings of HOOVER4_SETTINGS_REVISION, else of the newest revision (../manifests.py target_from_site())."""
    import manifests
    revision = os.environ.get('HOOVER4_SETTINGS_REVISION')
    target = manifests.target_from_site(str(common.settings.SITE_FILE), zone, revision='settings',
                                        settings_revision=int(revision) if revision else None)
    return target.values['main_services.temporal_retention']


if __name__ == '__main__':
    main(sys.argv[1:])
