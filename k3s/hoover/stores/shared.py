#!/usr/bin/env python3
"""The shared Hoover stores of a site: one ClickHouse, one Garage, two Manticore daemons and one Temporal in the
namespace hoover-stores.

Each zone of the store layout site (../../config.py ZONE_VALUES) is a tenant of the stores. ../setup.py adds the
tenant of a zone: in ClickHouse a settings profile, the zone user and a user for each service, with grants on the
databases of the zone prefix only, in Garage the zone key, the service keys and the zone buckets, and in both Manticore
daemons the users <prefix>_read, <prefix>_write and <prefix>_schema with rights on the tables <prefix>_* only
(service_users.py MANTICORE_GRANTS). remove takes them away when the zone goes, with the Manticore tables of the zone.
A Manticore user with the right schema can create a distributed table that names a table of another user, and then
read that table. Only the schema proxy of the zone (../manifests.py) holds the schema user, and the proxy has no
operation for a distributed table. The Temporal of the site, with
its Cassandra and OpenSearch and one Temporal namespace for each zone, is in temporal.py. apply creates it after the
other stores, ready and grow include it, and remove deletes the Temporal namespace of the zone.

The site file gives the plan (vars.stores, ../../config.py store_plan()): the nodes that can run a store pod and the
Garage node count. Each store keeps one copy of its data, and the Service of each store selects every ready pod.
apply chooses the node of each store pod with a local volume before its first start (placement.py) and writes it into
the node affinity of its StatefulSet. A pod with a claim keeps the node of its claim. The ConfigMap shared-stores
records the plan, and plan prints it. Each store pod has the PriorityClass hoover-node-bound.
- ClickHouse runs one pod.
- Manticore runs one pod for text (manticore) and one for vectors (manticore-vectors). Hoover refuses one host for
  both. Each daemon listens on 9306 (MySQL) and 9308 (HTTP), and on the read-only listeners 9307 (MySQL) and 9309
  (HTTP). A connection to a read-only listener cannot change a row or a table, and SET ro=0 is refused. The zone
  services that only search use the read user on 9309. A daemon starts with the user hoover_admin of the seed
  auth.json (creds.py manticore_seed()).
- Garage runs one pod on each of its nodes with the replication factor 1. The layout gives each node a part of the
  partitions by its capacity. A lost node loses its part until it returns, and the backups are the recovery path
  (k3s/Readme.md). A pod finds the others by their names in the headless Service garage-peers (bootstrap_peers), so
  the cluster forms again after the pods restart with new addresses. A new node gets a role in the layout, and Garage
  moves a part of the data to it. apply refuses fewer nodes than at the last apply.
Each store pod runs in Kata on a TopoLVM block volume (hoover.py statefulset()). The claim of a store holds the size of
one zone (hoover.SIZES) times the number of site zones, at least one. apply and grow make the claims larger when a
zone is added. A claim never becomes smaller. A store pod sees a grown claim at its next start. The memory limits and requests are those of one zone store
(memory-limits.json and hoover.REQUESTS), the R6 minimums. The CPU request of each store workload is its measured
value (part site of ../../zones/cpu-requests.json, hoover.site_cpu()). Each zone user of ClickHouse has the profile of its zone,
which limits the memory of one user to half of the ClickHouse limit.
The network policies of the namespace admit the Hoover namespaces (label hoover.dev/hoover) on the client ports of
ClickHouse (8123, 9000), Manticore (9306 to 9309) and Garage (3900) only. The Garage RPC port takes connections only from the Garage pods, and
the admin port takes none.
The ConfigMap shared-stores records the applied plan, the nodes of the store pods, the Garage node ids, the node counts of Cassandra and OpenSearch
and the Temporal history shard count. The deploy check reads it (problems()). The stores of an earlier version kept
several copies, and apply and the deploy check refuse them with the steps to create the stores again.
The Secret hoover-stores of the namespace holds the ClickHouse admin password, the Manticore admin password and seed,
the Garage RPC secret and the Garage admin token. The script never prints a credential.

Usage: shared.py apply             create or update the stores and Temporal, wait for them, join the Garage nodes and
                                   record the plan
       shared.py show              print the objects of ClickHouse and Garage (temporal.py show prints Temporal)
       shared.py grow              make the claims large enough for the zones of the zone state
       shared.py ready             exit 1 when a store or Temporal has no ready pod
       shared.py check             print the problems of the plan against the cluster as JSON
       shared.py plan              print the placement plan of the store pods and the problems of vars.replicas as JSON
       shared.py remove <zone>     delete the ClickHouse databases, users and profile, the Manticore tables and users, the
                                   Garage buckets and keys and the Temporal namespace of a zone.
                                   The operations pod of the zone empties the buckets. Without it, a non-empty bucket
                                   and the zone keys stay, and the log names them.
"""
import base64, hashlib, json, math, re, secrets, subprocess, sys, time
from pathlib import Path
import common, creds, hoover, podspec, service_users, temporal
import config  # noqa: E402  (common puts the k3s folder on the path)
import zonestate  # noqa: E402

NS = 'hoover-stores'
SECRET = 'hoover-stores'
STATE = 'shared-stores'
PEERS = 'garage-peers'
# The label of a Hoover namespace (../manifests.py objects()). Only these namespaces reach the stores.
HOOVER_LABEL = 'hoover.dev/hoover'
# The Manticore daemons, and the ports of each daemon: MySQL and HTTP, and the read-only MySQL and HTTP listeners.
MANTICORE = ('manticore', 'manticore-vectors')
MANTICORE_PORTS = (('sql', 9306), ('http', 9308), ('sql-ro', 9307), ('http-ro', 9309))
# Manticore reads searchd settings from searchd_* variables (hoover.MANTICORE_ENV). The listeners replace the default
# list of the image, which also opens the replication ports.
MANTICORE_LISTEN = '9306:mysql|9308:http|9307:mysql_readonly|9309:http_readonly'
# The file service of the text daemon (manticore_file_service.py): its port, its image and its script.
FILES_PORT = 9318
FILES_IMAGE = 'docker.io/library/python:3.14-alpine@sha256:7f2ec713f0436c59df2362d973b6a05af9e87ba78f0e94f5245c302984a7a1fd'
FILES_SCRIPT = (Path(__file__).resolve().parent / 'manticore_file_service.py').read_text()
# The schema proxies of the zones, the only clients of the file service (../manifests.py SCHEMA_PROXY).
SCHEMA_PROXY_LABEL = {'app.kubernetes.io/name': 'manticore-schema'}
GARAGE_CONFIG = (common.LAB / 'config' / 'garage' / 'garage.toml').read_text()
# The Python of the operations image, which has an S3 client (../../platform/backups/backups.py PYTHON).
OPS_PYTHON = '/opt/pysetup/.venv/bin/python3'
PURGE = """
import os, sys
from minio import Minio
from minio.deleteobjects import DeleteObject
client = Minio(os.environ['S3_ENDPOINT'].split('://')[-1], os.environ['S3_ACCESS_KEY'], os.environ['S3_SECRET_KEY'], secure=False)
for bucket in sys.argv[1:]:
    errors = list(client.remove_objects(bucket, (DeleteObject(o.object_name) for o in client.list_objects(bucket, recursive=True))))
    # A bucket that Hoover created has a local alias of the zone key, which owns it, so the key deletes it. The
    # admin deletes a bucket with a global alias.
    try:
        client.remove_bucket(bucket)
    except Exception:
        pass
    print(bucket, len(errors))
"""


def site():
    return common.settings.SITE


def site_zones(data=None):
    """The zones of the zone state that use the shared stores."""
    try:
        data = zonestate.load() if data is None else data
    except zonestate.ZoneStateError:
        return []
    return [z for z, e in data['zones'].items() if e.get('stores') == 'site']


def size(store, zones):
    """The claim of a store: the size of one zone times the zone count, at least one zone."""
    return f'{math.ceil(hoover.gibibytes(hoover.SIZES[store]) * max(1, zones))}Gi'


def tier(s, nodes, store, count=1):
    """(tier, nodes): the first preferred tier of the store (../../zones/zonestate.py TIERS) that at least count store
    nodes have, and the store nodes with that tier. Each pod of a store then gets its volume on its own node."""
    wanted = zonestate.TIERS.get(store, zonestate.TIERS['default'])
    for name in [t for w in wanted for t in (zonestate.TIER_ORDER if w == '*' else [w])]:
        holders = tuple(n for n in nodes if name in s.nodes[n].tiers)
        if len(holders) >= count:
            return name, holders
    raise SystemExit(f'fewer than {count} store nodes have one tier of {", ".join(wanted)} for the shared {store}.')


def affinity(nodes, store, spread):
    out = {'nodeAffinity': {'requiredDuringSchedulingIgnoredDuringExecution': {'nodeSelectorTerms': [{'matchExpressions': [
        {'key': 'kubernetes.io/hostname', 'operator': 'In', 'values': list(nodes)}]}]}}}
    if spread:
        out['podAntiAffinity'] = {'requiredDuringSchedulingIgnoredDuringExecution': [
            {'labelSelector': {'matchLabels': {'hoover.dev/store': store}}, 'topologyKey': 'kubernetes.io/hostname'}]}
    return out


def configmap(name, files):
    return {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': name, 'namespace': NS, 'labels': {common.LABEL: 'config'}},
            'data': files}


def garage_toml(peers):
    """The Garage configuration: one copy of each object, and the peer names of the recorded node ids."""
    names = [f'"{node_id}@{pod}.{PEERS}.{NS}.svc.cluster.local:3901"' for pod, node_id in sorted(peers.items())]
    return (GARAGE_CONFIG.replace('REPLICATION_FACTOR', '1')
            .replace('BOOTSTRAP_PEERS', '[' + ', '.join(names) + ']'))


def clickhouse(s, plan, zones, placed=None):
    files = {p.name: p.read_text() for p in sorted((common.LAB / 'config' / 'clickhouse').iterdir()) if p.is_file()}
    container = {
        'name': 'clickhouse', 'image': hoover.IMAGES['clickhouse'], 'env': [hoover.secret_env('CH_ADMIN_PASSWORD', 'clickhouse-admin')],
        'ports': [{'name': 'http', 'containerPort': 8123}, {'name': 'native', 'containerPort': 9000}],
        'volumeMounts': [{'name': 'config', 'mountPath': '/etc/clickhouse-server/config.d/hoover.xml', 'subPath': 'server.xml', 'readOnly': True},
                         {'name': 'config', 'mountPath': '/etc/clickhouse-server/users.d/hoover.xml', 'subPath': 'users.xml', 'readOnly': True}],
        'readinessProbe': {'httpGet': {'path': '/ping', 'port': 8123}, 'periodSeconds': 2, 'failureThreshold': 3},
        'resources': hoover.resources('clickhouse')}
    name, nodes = tier(s, plan['nodes'], 'clickhouse')
    nodes = (placed or {}).get('clickhouse', nodes)
    return [configmap('clickhouse-config', files),
            hoover.service('clickhouse', NS, [('http', 8123), ('native', 9000)], {'app.kubernetes.io/name': 'clickhouse'}),
            hoover.statefulset('clickhouse', 'clickhouse', NS, container, ['/entrypoint.sh'], '/var/lib/clickhouse',
                               name, size('clickhouse', zones), affinity=affinity(nodes, 'clickhouse', False),
                               extra_volumes=[{'name': 'config', 'configMap': {'name': 'clickhouse-config'}}])]


def garage(s, plan, zones, peers, placed=None):
    container = {
        'name': 'garage', 'image': hoover.IMAGES['garage'],
        'env': [hoover.secret_env('GARAGE_RPC_SECRET', 'garage-rpc-secret'), hoover.secret_env('GARAGE_ADMIN_TOKEN', 'garage-admin-token')],
        'ports': [{'name': 's3', 'containerPort': 3900}, {'name': 'rpc', 'containerPort': 3901}, {'name': 'admin', 'containerPort': 3903}],
        'volumeMounts': [{'name': 'config', 'mountPath': '/etc/garage.toml', 'subPath': 'garage.toml', 'readOnly': True}],
        'readinessProbe': {'tcpSocket': {'port': 3900}, 'periodSeconds': 2, 'failureThreshold': 3},
        'resources': hoover.resources('garage')}
    name, nodes = tier(s, plan['nodes'], 'garage', plan['garage'])
    nodes = (placed or {}).get('garage', nodes)
    return [configmap('garage-config', {'garage.toml': garage_toml(peers)}),
            hoover.service('garage', NS, [('s3', 3900)], {'app.kubernetes.io/name': 'garage'}),
            hoover.service(PEERS, NS, [('rpc', 3901)], {'app.kubernetes.io/name': 'garage'}, headless=True),
            hoover.statefulset('garage', 'garage', NS, container, ['/garage', 'server'], '/var/lib/garage',
                               name, size('garage', zones), replicas=plan['garage'],
                               service_name=PEERS, affinity=affinity(nodes, 'garage', True),
                               extra_volumes=[{'name': 'config', 'configMap': {'name': 'garage-config'}}])]


def manticore(s, plan, zones, name, placed=None):
    """One Manticore daemon of the site, with the admin of the seed and the read-only listeners."""
    container = {
        'name': 'manticore', 'image': hoover.IMAGES['manticore'],
        'env': [{'name': k, 'value': v} for k, v in {**hoover.MANTICORE_ENV, 'searchd_listen': MANTICORE_LISTEN}.items()]
               + [hoover.secret_env('MT_ADMIN_PASSWORD', 'manticore-admin')],
        'ports': [{'name': n, 'containerPort': p} for n, p in MANTICORE_PORTS],
        'readinessProbe': {'tcpSocket': {'port': 9306}, 'periodSeconds': 2, 'failureThreshold': 3},
        'resources': hoover.resources(name),
        'volumeMounts': [{'name': 'seed', 'mountPath': '/seed', 'readOnly': True}]}
    # With authentication on, searchd starts with the users of auth.json in its data folder. A new daemon gets the
    # seed with the user hoover_admin, and ../setup.py adds the users of each zone. searchd writes an auth.json without
    # users when none exists, so that file also gets the seed.
    start = ('grep -q username /var/lib/manticore/auth.json 2>/dev/null || '
             '{ cp /seed/auth.json /var/lib/manticore/auth.json && chmod 600 /var/lib/manticore/auth.json; }; '
             'exec /usr/local/bin/docker-entrypoint.sh searchd -c /etc/manticoresearch/manticore.conf.sh --nodetach')
    seed = {'name': 'seed', 'secret': {'secretName': SECRET, 'items': [{'key': 'manticore-seed', 'path': 'auth.json'}]}}
    tier_name, nodes = tier(s, plan['nodes'], name)
    nodes = (placed or {}).get(name, nodes)
    statefulset = hoover.statefulset(name, name, NS, container, ['sh', '-c', start], '/var/lib/manticore', tier_name,
                                     size(name, zones), user='999:999', affinity=affinity(nodes, name, False), extra_volumes=[seed])
    if name != 'manticore':
        return [hoover.service(name, NS, MANTICORE_PORTS, {'app.kubernetes.io/name': name}), statefulset]
    return [configmap('manticore-files', {'manticore_file_service.py': FILES_SCRIPT}),
            hoover.service(name, NS, MANTICORE_PORTS + (('files', FILES_PORT),), {'app.kubernetes.io/name': name}),
            file_service(statefulset)]


def file_service(statefulset):
    """Add the container files to the pod of the text daemon: the file service of manticore_file_service.py.

    The data folder is a block volume inside the Kata guest of the pod, so the export and the restore of a collection
    read and write the table files through this container. It mounts the same file system as the daemon. On a new
    volume it waits until the daemon container has made the file system, so only one container runs mke2fs. A loop
    starts the service again after a failure, so the container keeps running and the daemon pod stays ready.
    """
    spec = statefulset['spec']['template']['spec']
    spec['containers'].append({
        'name': 'files', 'image': FILES_IMAGE, 'imagePullPolicy': 'IfNotPresent',
        'env': [{'name': 'FILES_PORT', 'value': str(FILES_PORT)}],
        'ports': [{'name': 'files', 'containerPort': FILES_PORT}],
        'resources': {'requests': {'cpu': '10m', 'memory': '32Mi'}, 'limits': {'cpu': '500m', 'memory': '128Mi'}},
        'volumeMounts': [{'name': 'files-script', 'mountPath': '/service', 'readOnly': True}]})
    spec['volumes'].append({'name': 'files-script', 'configMap': {'name': 'manticore-files'}})
    spec = podspec.blockmount(spec, 'files', ['/bin/sh', '-c', 'while :; do python3 -I /service/manticore_file_service.py; sleep 5; done'],
                              [('data', None, '/var/lib/manticore')], '999:999')
    files = next(c for c in spec['containers'] if c['name'] == 'files')
    b = '/tools/busybox'
    wait = (f'until [ "$({b} dd if=/dev/block-data bs=1 skip=1080 count=2 2>/dev/null | {b} od -An -tx1 | {b} tr -d " \\n")" = 53ef ]; '
            f'do {b} sleep 2; done; {b} sleep 5; exec {b} sh /tools/run.sh "$@"')
    files['command'] = [b, 'sh', '-c', wait, 'files']
    statefulset['spec']['template']['spec'] = spec
    # A new script replaces the pod once (wait_current), so the running service matches the ConfigMap.
    statefulset['spec']['template']['metadata'].setdefault('annotations', {})['hoover.dev/files-script'] = \
        hashlib.sha256(FILES_SCRIPT.encode()).hexdigest()[:16]
    return statefulset


def network():
    def policy(name, spec):
        return {'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy', 'metadata': {'name': name, 'namespace': NS}, 'spec': spec}
    hoover_ns = {'namespaceSelector': {'matchLabels': {HOOVER_LABEL: 'true'}}}
    dns = {'to': [{'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'kube-system'}},
                   'podSelector': {'matchLabels': {'k8s-app': 'kube-dns'}}}],
           'ports': [{'port': 53, 'protocol': 'UDP'}, {'port': 53, 'protocol': 'TCP'}]}
    return [
        # Every pod takes only the connections that a later policy admits, and reaches only DNS and the namespace.
        policy('closed', {'podSelector': {}, 'policyTypes': ['Ingress', 'Egress'], 'ingress': [],
                          'egress': [dns, {'to': [{'podSelector': {}}]}]}),
        policy('clickhouse-clients', {'podSelector': {'matchLabels': {'hoover.dev/store': 'clickhouse'}}, 'policyTypes': ['Ingress'],
                                      'ingress': [{'from': [hoover_ns], 'ports': [{'port': 8123}, {'port': 9000}]}]}),
        policy('manticore-clients', {'podSelector': {'matchExpressions': [
            {'key': 'hoover.dev/store', 'operator': 'In', 'values': list(MANTICORE)}]}, 'policyTypes': ['Ingress'],
            'ingress': [{'from': [hoover_ns], 'ports': [{'port': p} for _, p in MANTICORE_PORTS]}]}),
        # The file service of the text daemon takes connections from the schema proxies of the zones only.
        policy('manticore-files-clients', {'podSelector': {'matchLabels': {'hoover.dev/store': 'manticore'}}, 'policyTypes': ['Ingress'],
                                           'ingress': [{'from': [{**hoover_ns, 'podSelector': {'matchLabels': SCHEMA_PROXY_LABEL}}],
                                                        'ports': [{'port': FILES_PORT}]}]}),
        policy('garage-clients', {'podSelector': {'matchLabels': {'hoover.dev/store': 'garage'}}, 'policyTypes': ['Ingress'],
                                  'ingress': [{'from': [hoover_ns], 'ports': [{'port': 3900}]},
                                              {'from': [{'podSelector': {'matchLabels': {'hoover.dev/store': 'garage'}}}],
                                               'ports': [{'port': 3901}]}]}),
    ]


def objects(s, plan, zones, peers, placed=None):
    """The objects of the stores. placed: {store: nodes} of the placement plan. Without it, each store may use every
    store node with its tier."""
    namespace = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': NS}}
    return hoover.site_cpu([namespace, *network(), *clickhouse(s, plan, zones, placed),
                            *[o for name in MANTICORE for o in manticore(s, plan, zones, name, placed)],
                            *garage(s, plan, zones, peers, placed)])


def store_counts(plan):
    """{store: pod count} of the stores that keep a local volume (placement.VOLUME_STORES)."""
    return {'clickhouse': 1, 'manticore': 1, 'manticore-vectors': 1, 'garage': plan['garage'],
            'temporal-cassandra': plan['cassandra'], 'temporal-opensearch': plan['opensearch']}


def placement_report(s, plan):
    """The placement plan of the store pods (placement.py) for the cluster and the site file, as a dict. Raise
    placement.NoFit when a new store pod fits no node."""
    import manifests, placement
    zones = len(site_zones())
    rendered = objects(s, plan, zones, {}) + temporal.objects(s, plan, zones, '{"keys": []}')
    requests = placement.store_requests(rendered, placement.runtime_overhead())
    stores_found = common.kubectl('get', 'namespace', NS, '--ignore-not-found', '-o', 'name').strip()
    claims = common.kubectl_json('-n', NS, 'get', 'pvc') if stores_found else {'items': []}
    planned = max(plan['zones'], zones, 1)
    replicas = {f'hoover4-{k}': v for k, v in s.replicas.items()}
    nodes, fixed, zone_memory, zone_cpu, details = placement.inputs(
        s, common.kubectl_json('get', 'nodes'), common.kubectl_json('get', 'pods', '-A'), claims, planned, replicas,
        manifests.scaled_pods(), s.with_role('public')[0].name)
    stores = [placement.Store(store, count, *requests[store], candidates=tier(s, plan['nodes'], store, count)[1],
                              fixed=fixed.get(store, ())) for store, count in store_counts(plan).items()]
    out = placement.report(nodes, stores, zone_memory, zone_cpu)
    out['inputs'] = dict(details, store_requests={k: {'memory': round(v[0]), 'cpu': round(v[1])} for k, v in requests.items()},
                         claims={k: list(v) for k, v in fixed.items()})
    return out


def placement_problems(s, out):
    """The problems of the replica counts of vars.replicas against a placement report, as messages."""
    scaled = {k: v for k, v in s.replicas.items() if v > 1}
    if not scaled:
        return []
    asked = ', '.join(f'{k} {v}' for k, v in sorted(scaled.items()))
    problems = []
    if not out['zones_fit']:
        share = out['requested_share']
        problems.append(f'vars.replicas ({asked}) does not fit: the zones and stores request {share["memory"]:.0%} of the '
                        f'memory and {share["cpu"]:.0%} of the CPU of the nodes. Lower the counts or add a node.')
    public = s.with_role('public')[0].name
    node = out['nodes'].get(public)
    if 'clamav' in scaled and node and any(node['base_and_stores'][k] > node['capacity'][k] for k in ('memory', 'cpu')):
        problems.append(f'vars.replicas clamav {scaled["clamav"]} does not fit the public node {public}: its pods, the '
                        f'stores and the pods bound to it request {node["base_and_stores"]["memory"]}Mi and '
                        f'{node["base_and_stores"]["cpu"]}m of {node["capacity"]["memory"]}Mi and {node["capacity"]["cpu"]}m.')
    return problems


# ----------------------------------------------------------------------------------------------------------------------
# Cluster state
# ----------------------------------------------------------------------------------------------------------------------

def recorded():
    """The recorded plan of the ConfigMap shared-stores, or None before the first apply."""
    found = common.kubectl('-n', NS, 'get', 'configmap', STATE, '--ignore-not-found', '-o', 'json').strip()
    return json.loads(json.loads(found)['data']['plan']) if found else None


def problems(s=None):
    """The problems of the plan of the site file against the cluster."""
    s = s or site()
    try:
        before = recorded()
    except subprocess.CalledProcessError:
        before = None
    return config.store_change_problems(before, config.store_plan(s))


def credentials():
    """Create the Secret of the namespace, or add its missing keys. A present key keeps its value."""
    found = common.kubectl('-n', NS, 'get', 'secret', SECRET, '--ignore-not-found', '-o', 'json').strip()
    current = {k: base64.b64decode(v).decode() for k, v in json.loads(found).get('data', {}).items()} if found else {}
    data = {'clickhouse-admin': secrets.token_hex(24), 'manticore-admin': secrets.token_hex(24),
            'garage-rpc-secret': secrets.token_hex(32), 'garage-admin-token': secrets.token_hex(24), **current}
    data.setdefault('manticore-seed', creds.manticore_seed(data['manticore-admin']))
    if data != current:
        common.apply({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': SECRET, 'namespace': NS, 'labels': {common.LABEL: 'credentials'}},
                      'type': 'Opaque', 'stringData': data})


def pods(store):
    return common.kubectl_json('-n', NS, 'get', 'pods', '-l', f'hoover.dev/store={store}')['items']


def is_ready(pod):
    return not pod['metadata'].get('deletionTimestamp') and any(
        c['type'] == 'Ready' and c['status'] == 'True' for c in pod.get('status', {}).get('conditions', []))


def ready_pod(store):
    """The first ready pod of a store. A SystemExit names the step that creates the store when it has none."""
    for pod in sorted(pods(store), key=lambda p: p['metadata']['name']):
        if is_ready(pod):
            return pod['metadata']['name']
    raise SystemExit(f'the shared {store} has no ready pod in {NS}. Run deploy-k3s up --steps stores.')


def wait_current(store, timeout=900):
    """Replace the outdated pods of a store one at a time, and wait until each pod is ready and current."""
    deadline = time.monotonic() + timeout
    while True:
        controller = common.kubectl_json('-n', NS, 'get', 'statefulset', store)
        revision = controller.get('status', {}).get('updateRevision')
        found = sorted(pods(store), key=lambda p: p['metadata']['name'])
        if controller['spec']['replicas'] == 0:
            return
        current = controller.get('status', {}).get('observedGeneration', 0) >= controller['metadata']['generation']
        if current and len(found) == controller['spec']['replicas'] and all(is_ready(p) for p in found):
            stale = [p['metadata']['name'] for p in found if p['metadata']['labels'].get('controller-revision-hash') != revision]
            if not stale:
                return
            # One pod at a time, so only the part of one node is out of reach.
            common.kubectl('-n', NS, 'delete', 'pod', stale[0], '--wait=false')
            common.log('stores.jsonl', step='replace-stale-pod', namespace=NS, pod=stale[0])
            time.sleep(5)
        if time.monotonic() >= deadline:
            raise SystemExit(f'the shared {store} did not become ready with its current template in {timeout} s')
        time.sleep(3)


def clickhouse_sql(sql, check=True):
    """Run SQL from stdin as the ClickHouse admin. The password stays in the pod environment."""
    r = subprocess.run(common.K + ['-n', NS, 'exec', '-i', ready_pod('clickhouse'), '-c', 'clickhouse', '--', 'sh', '-c',
                                   'exec clickhouse-client --user hoover_admin --password "$CH_ADMIN_PASSWORD" --multiquery'],
                       input=sql, capture_output=True, text=True, timeout=3600)
    if check and r.returncode:
        raise SystemExit(f'ClickHouse refused the statements: {r.stderr.strip()[-600:]}')
    return r.stdout


def manticore_sql(store, sql, check=True):
    """Run SQL from stdin as the Manticore admin in a daemon of MANTICORE. The password stays in the pod environment."""
    r = subprocess.run(common.K + ['-n', NS, 'exec', '-i', ready_pod(store), '-c', 'manticore', '--', 'sh', '-c',
                                   'exec mysql -h0 -P9306 -uhoover_admin -p"$MT_ADMIN_PASSWORD" --batch --skip-column-names'],
                       input=sql, capture_output=True, text=True, timeout=3600)
    err = '\n'.join(l for l in r.stderr.splitlines() if 'Using a password' not in l)
    if check and r.returncode:
        raise SystemExit(f'Manticore {store} refused the statements: {err.strip()[-600:]}')
    return r.stdout


def manticore_rows(text):
    """The rows of a mysql client answer, which prints tab-separated lines or a table with borders."""
    rows = []
    for line in text.splitlines():
        if not line.strip() or line.startswith('+'):
            continue
        rows.append([c.strip() for c in (line.strip().strip('|').split('|') if line.startswith('|') else line.split('\t'))])
    return rows


def manticore_users(store):
    """The user names of a Manticore daemon."""
    return {row[0] for row in manticore_rows(manticore_sql(store, 'SHOW USERS\n')) if row and row[0] != 'username'}


def garage_cli(*args, pod=None, check=True):
    r = subprocess.run(common.K + ['-n', NS, 'exec', pod or ready_pod('garage'), '-c', 'garage', '--', '/garage', *args],
                       capture_output=True, text=True, timeout=300)
    if check and r.returncode:
        raise SystemExit(f'garage {" ".join(args[:2])} failed: {r.stderr.strip()[-400:]}')
    return r.stdout


def table(text):
    """The rows of a table that the Garage CLI prints, as lists of columns, without the header row."""
    lines = [l for l in text.splitlines() if l.strip() and not l.startswith('==')]
    return [l.split() for l in lines[1:]]


def join_garage(plan, sizes):
    """Connect the Garage nodes by their peer names and give each node a role in the layout. Return {pod: node id}."""
    found = sorted(pods('garage'), key=lambda p: p['metadata']['name'])
    ids = {p['metadata']['name']: garage_cli('node', 'id', '-q', pod=p['metadata']['name']).strip().split('@')[0] for p in found}
    first = found[0]['metadata']['name']
    for pod, node_id in ids.items():
        if pod != first:
            garage_cli('node', 'connect', f'{node_id}@{pod}.{PEERS}.{NS}.svc.cluster.local:3901', pod=first)
    layout = garage_cli('layout', 'show', pod=first)
    version = int(re.search(r'Current cluster layout version: (\d+)', layout).group(1))
    staged = False
    for p in found:
        node_id = ids[p['metadata']['name']]
        if node_id[:16] not in layout.split('==== STAGED')[0]:
            garage_cli('layout', 'assign', '-z', p['spec']['nodeName'], '-c', sizes.replace('Gi', 'G'), node_id[:16], pod=first)
            staged = True
    if staged:
        garage_cli('layout', 'apply', '--version', str(version + 1), pod=first)
        common.log('stores.jsonl', step='garage-layout', version=version + 1, nodes=sorted(ids))
    return ids


def apply():
    s = site()
    plan = config.store_plan(s)
    before = recorded() if common.kubectl('get', 'namespace', NS, '--ignore-not-found', '-o', 'name').strip() else None
    refused = config.store_change_problems(before, plan)
    if refused:
        raise SystemExit('; '.join(refused))
    zones = len(site_zones())
    peers = (before or {}).get('garage_nodes', {})
    report = placement_report(s, plan)
    placed = report['stores']
    common.log('stores.jsonl', step='placement', stores=placed, score=report['score'], changes=report['changes'],
               zones_fit=report['zones_fit'])
    items = objects(s, plan, zones, peers, placed)
    common.apply(items[0])
    credentials()
    hoover.apply(items[1:], keep_replicas=False)
    for store in ('clickhouse', *MANTICORE, 'garage'):
        wait_current(store)
    ids = join_garage(plan, size('garage', zones))
    if ids != peers:
        hoover.apply([o for o in garage(s, plan, zones, ids, placed) if o['kind'] == 'ConfigMap'])
    temporal.apply(s, plan, zones, placed)
    record = {'nodes': list(plan['nodes']), 'placement': placed, 'garage_replication_factor': 1, 'garage_nodes': ids,
              'cassandra_nodes': plan['cassandra'], 'opensearch_nodes': plan['opensearch'], 'temporal_pods': plan['temporal'],
              'temporal_history_shards': (before or {}).get('temporal_history_shards', plan['history_shards'])}
    common.apply(configmap(STATE, {'plan': json.dumps(record, sort_keys=True)}))
    common.log('stores.jsonl', step='shared-stores', namespace=NS, nodes=list(plan['nodes']), garage=plan['garage'],
               cassandra=plan['cassandra'], opensearch=plan['opensearch'], temporal=plan['temporal'], zones=zones)


def grow():
    """Make the claims of the stores and of the Temporal stores large enough for the zones of the zone state."""
    zones = len(site_zones())
    sizes = {'clickhouse': size('clickhouse', zones), 'garage': size('garage', zones),
             **{store: size(store, zones) for store in MANTICORE},
             **{store: temporal.size(store, zones) for store in temporal.SIZES}}
    for store, wanted in sizes.items():
        current = common.kubectl('-n', NS, 'get', 'statefulset', store, '--ignore-not-found', '-o', 'json').strip()
        if not current:
            raise SystemExit(f'the shared {store} does not exist in {NS}. Run deploy-k3s up --steps stores.')
        hoover.grow_claims(NS, json.loads(current), wanted)


def remove(zone):
    """Delete the tenant of a zone from ClickHouse, Garage and Temporal. A bucket that the zone cannot empty stays, and
    the log names it."""
    prefix = zone.replace('-', '_')
    rows = clickhouse_sql(
        f"SELECT 'database', name FROM system.databases WHERE name = '{prefix}' OR startsWith(name, '{prefix}_') "
        f"UNION ALL SELECT 'user', name FROM system.users WHERE name = '{prefix}' OR startsWith(name, '{prefix}_') "
        "FORMAT TSV\n")
    found = [line.split('\t') for line in rows.splitlines() if line.strip()]
    sql = [f'DROP DATABASE IF EXISTS `{name}` SYNC;' for kind, name in found if kind == 'database']
    sql += [f'DROP USER IF EXISTS `{name}`;' for kind, name in found if kind == 'user']
    sql += [f'DROP SETTINGS PROFILE IF EXISTS `{prefix}`;']
    clickhouse_sql('\n'.join(sql) + '\n')
    common.log('stores.jsonl', step='clickhouse-tenant-removed', zone=zone, databases=sum(k == 'database' for k, _ in found),
               users=sum(k == 'user' for k, _ in found))
    for store in MANTICORE:
        # The table prefix of a zone is <prefix>_, and a zone id has no _, so the prefix of one zone never starts the
        # table names of another zone. Manticore 29.9 stops searchd on a DROP USER of an unknown user, so only the
        # present users are dropped. Without a ready daemon the tables and users of the zone stay, and the log names
        # the daemon.
        if not any(is_ready(p) for p in pods(store)):
            common.log('stores.jsonl', step='manticore-tenant-kept', zone=zone, store=store, reason='no ready pod')
            continue
        tables = [row[0] for row in manticore_rows(manticore_sql(store, 'SHOW TABLES\n')) if row]
        tables = [t for t in tables if t.startswith(f'{prefix}_')]
        users = sorted({service_users.manticore_user(zone, r) for r in service_users.MANTICORE_ROLES} & manticore_users(store))
        sql = [f'DROP TABLE IF EXISTS {t};' for t in tables] + [f"DROP USER '{u}';" for u in users]
        if sql:
            manticore_sql(store, '\n'.join(sql) + '\n')
        common.log('stores.jsonl', step='manticore-tenant-removed', zone=zone, store=store, tables=len(tables), users=len(users))
    keys = {row[0]: row[2] for row in table(garage_cli('key', 'list')) if len(row) > 2 and (row[2] == zone or row[2].startswith(f'{zone}-'))}

    def zone_buckets():
        """{name: global}: the buckets with a global alias <zone>-*, and the buckets with a local alias of a zone key.
        Hoover creates each collection bucket through S3, which gives it a local alias of the zone key."""
        out = {}
        for row in table(garage_cli('bucket', 'list')):
            for alias in row[2:]:
                key, _, name = alias.rpartition(':')
                if (key in keys) if key else alias.startswith(f'{zone}-'):
                    out[name] = not key
        return out
    buckets = zone_buckets()
    ops = common.kubectl('-n', f'hoover-{zone}', 'get', 'pods', '-l', 'app.kubernetes.io/name=hoover-operations',
                         '--field-selector=status.phase=Running', '-o', 'jsonpath={.items[0].metadata.name}', check=False).strip()
    if buckets and ops:
        # The operations pod holds the zone key, which reaches every bucket of the zone.
        common.kubectl('-n', f'hoover-{zone}', 'exec', ops, '--', OPS_PYTHON, '-c', PURGE, *sorted(buckets))
    for bucket, is_global in zone_buckets().items():
        if is_global:
            garage_cli('bucket', 'cleanup-incomplete-uploads', '--older-than', '0s', bucket, check=False)
            garage_cli('bucket', 'delete', '--yes', bucket, check=False)
    kept = sorted(zone_buckets())
    # A kept bucket keeps the zone keys, because a bucket loses its local alias with its key, and then no name reaches it.
    for key_id in ([] if kept else keys):
        garage_cli('key', 'delete', '--yes', key_id)
    common.log('stores.jsonl', step='garage-tenant-removed', zone=zone, buckets=len(buckets) - len(kept), kept=kept,
               keys_kept=sorted(keys.values()) if kept else [])
    temporal.remove(zone)


def main(argv):
    if not argv or argv[0] not in ('apply', 'show', 'grow', 'ready', 'check', 'plan', 'remove') or (argv[0] == 'remove') != (len(argv) == 2):
        sys.exit(__doc__)
    if argv[0] == 'show':
        s = site()
        print(json.dumps(objects(s, config.store_plan(s), len(site_zones()), {}), indent=1))
    elif argv[0] == 'apply':
        apply()
    elif argv[0] == 'grow':
        grow()
    elif argv[0] == 'ready':
        for store in ('clickhouse', *MANTICORE, 'garage', 'temporal-cassandra', 'temporal-opensearch', 'temporal'):
            ready_pod(store)
    elif argv[0] == 'check':
        found = problems()
        print(json.dumps({'problems': found}))
        sys.exit(1 if found else 0)
    elif argv[0] == 'plan':
        import placement
        s = site()
        try:
            out = placement_report(s, config.store_plan(s))
            found = placement_problems(s, out)
        except placement.NoFit as error:
            out, found = {}, [str(error)]
        print(json.dumps({'placement': out, 'problems': found}, sort_keys=True))
    else:
        remove(argv[1])


if __name__ == '__main__':
    main(sys.argv[1:])
