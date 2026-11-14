#!/usr/bin/env python3
"""The shared Hoover stores of a site: one ClickHouse, one Garage and one Temporal in the namespace hoover-stores.

Each zone of the store layout site (../../config.py ZONE_VALUES) is a tenant of both stores. ../setup.py adds the
tenant of a zone: in ClickHouse a settings profile, the zone user and a user for each service, with grants on the
databases of the zone prefix only, and in Garage the zone key, the service keys and the zone buckets. remove takes them
away when the zone goes. The Manticore daemons stay in each zone namespace (hoover.py). The Temporal of the site, with
its Cassandra and OpenSearch and one Temporal namespace for each zone, is in temporal.py. apply creates it after the
other stores, ready and grow include it, and remove deletes the Temporal namespace of the zone.

The site file gives the plan (vars.stores, ../../config.py store_plan()): the nodes that can run a store pod and the
Garage node count. Each store keeps one copy of its data, and the Service of each store selects every ready pod.
- ClickHouse runs one pod.
- Garage runs one pod on each of its nodes with the replication factor 1. The layout gives each node a part of the
  partitions by its capacity. A lost node loses its part until it returns, and the backups are the recovery path
  (k3s/Readme.md). A pod finds the others by their names in the headless Service garage-peers (bootstrap_peers), so
  the cluster forms again after the pods restart with new addresses. A new node gets a role in the layout, and Garage
  moves a part of the data to it. apply refuses fewer nodes than at the last apply.
Each store pod runs in Kata on a TopoLVM block volume (hoover.py statefulset()). The claim of a store holds the size of
one zone (hoover.SIZES) times the number of site zones, at least one. apply and grow make the claims larger when a
zone is added. A claim never becomes smaller. A store pod sees a grown claim at its next start. The memory limits and requests are those of one zone store
(memory-limits.json and hoover.REQUESTS), the R6 minimums. Each zone user of ClickHouse has the profile of its zone,
which limits the memory of one user to half of the ClickHouse limit.
The network policies of the namespace admit the Hoover namespaces (label hoover.dev/hoover) on the client ports of
ClickHouse (8123, 9000) and Garage (3900) only. The Garage RPC port takes connections only from the Garage pods, and
the admin port takes none.
The ConfigMap shared-stores records the applied plan, the Garage node ids, the node counts of Cassandra and OpenSearch
and the Temporal history shard count. The deploy check reads it (problems()). The stores of an earlier version kept
several copies, and apply and the deploy check refuse them with the steps to create the stores again.
The Secret hoover-stores of the namespace holds the ClickHouse admin password, the Garage RPC secret and the Garage
admin token. The script never prints a credential.

Usage: shared.py apply             create or update the stores and Temporal, wait for them, join the Garage nodes and
                                   record the plan
       shared.py show              print the objects of ClickHouse and Garage (temporal.py show prints Temporal)
       shared.py grow              make the claims large enough for the zones of the zone state
       shared.py ready             exit 1 when a store or Temporal has no ready pod
       shared.py check             print the problems of the plan against the cluster as JSON
       shared.py remove <zone>     delete the ClickHouse databases, users and profile, the Garage buckets and keys and the
                                   Temporal namespace of a zone.
                                   The operations pod of the zone empties the buckets. Without it, a non-empty bucket
                                   and the zone keys stay, and the log names them.
"""
import base64, json, math, re, secrets, subprocess, sys, time
import common, hoover, temporal
import config  # noqa: E402  (common puts the k3s folder on the path)
import zonestate  # noqa: E402

NS = 'hoover-stores'
SECRET = 'hoover-stores'
STATE = 'shared-stores'
PEERS = 'garage-peers'
# The label of a Hoover namespace (../manifests.py objects()). Only these namespaces reach the stores.
HOOVER_LABEL = 'hoover.dev/hoover'
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


def clickhouse(s, plan, zones):
    files = {p.name: p.read_text() for p in sorted((common.LAB / 'config' / 'clickhouse').iterdir()) if p.is_file()}
    container = {
        'name': 'clickhouse', 'image': hoover.IMAGES['clickhouse'], 'env': [hoover.secret_env('CH_ADMIN_PASSWORD', 'clickhouse-admin')],
        'ports': [{'name': 'http', 'containerPort': 8123}, {'name': 'native', 'containerPort': 9000}],
        'volumeMounts': [{'name': 'config', 'mountPath': '/etc/clickhouse-server/config.d/hoover.xml', 'subPath': 'server.xml', 'readOnly': True},
                         {'name': 'config', 'mountPath': '/etc/clickhouse-server/users.d/hoover.xml', 'subPath': 'users.xml', 'readOnly': True}],
        'readinessProbe': {'httpGet': {'path': '/ping', 'port': 8123}, 'periodSeconds': 2, 'failureThreshold': 3},
        'resources': hoover.resources('clickhouse')}
    name, nodes = tier(s, plan['nodes'], 'clickhouse')
    return [configmap('clickhouse-config', files),
            hoover.service('clickhouse', NS, [('http', 8123), ('native', 9000)], {'app.kubernetes.io/name': 'clickhouse'}),
            hoover.statefulset('clickhouse', 'clickhouse', NS, container, ['/entrypoint.sh'], '/var/lib/clickhouse',
                               name, size('clickhouse', zones), affinity=affinity(nodes, 'clickhouse', False),
                               extra_volumes=[{'name': 'config', 'configMap': {'name': 'clickhouse-config'}}])]


def garage(s, plan, zones, peers):
    container = {
        'name': 'garage', 'image': hoover.IMAGES['garage'],
        'env': [hoover.secret_env('GARAGE_RPC_SECRET', 'garage-rpc-secret'), hoover.secret_env('GARAGE_ADMIN_TOKEN', 'garage-admin-token')],
        'ports': [{'name': 's3', 'containerPort': 3900}, {'name': 'rpc', 'containerPort': 3901}, {'name': 'admin', 'containerPort': 3903}],
        'volumeMounts': [{'name': 'config', 'mountPath': '/etc/garage.toml', 'subPath': 'garage.toml', 'readOnly': True}],
        'readinessProbe': {'tcpSocket': {'port': 3900}, 'periodSeconds': 2, 'failureThreshold': 3},
        'resources': hoover.resources('garage')}
    name, nodes = tier(s, plan['nodes'], 'garage', plan['garage'])
    return [configmap('garage-config', {'garage.toml': garage_toml(peers)}),
            hoover.service('garage', NS, [('s3', 3900)], {'app.kubernetes.io/name': 'garage'}),
            hoover.service(PEERS, NS, [('rpc', 3901)], {'app.kubernetes.io/name': 'garage'}, headless=True),
            hoover.statefulset('garage', 'garage', NS, container, ['/garage', 'server'], '/var/lib/garage',
                               name, size('garage', zones), replicas=plan['garage'],
                               service_name=PEERS, affinity=affinity(nodes, 'garage', True),
                               extra_volumes=[{'name': 'config', 'configMap': {'name': 'garage-config'}}])]


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
        policy('garage-clients', {'podSelector': {'matchLabels': {'hoover.dev/store': 'garage'}}, 'policyTypes': ['Ingress'],
                                  'ingress': [{'from': [hoover_ns], 'ports': [{'port': 3900}]},
                                              {'from': [{'podSelector': {'matchLabels': {'hoover.dev/store': 'garage'}}}],
                                               'ports': [{'port': 3901}]}]}),
    ]


def objects(s, plan, zones, peers):
    namespace = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': NS}}
    return [namespace, *network(), *clickhouse(s, plan, zones), *garage(s, plan, zones, peers)]


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
    data = {'clickhouse-admin': secrets.token_hex(24), 'garage-rpc-secret': secrets.token_hex(32),
            'garage-admin-token': secrets.token_hex(24), **current}
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
    items = objects(s, plan, zones, peers)
    common.apply(items[0])
    credentials()
    hoover.apply(items[1:], keep_replicas=False)
    for store in ('clickhouse', 'garage'):
        wait_current(store)
    ids = join_garage(plan, size('garage', zones))
    if ids != peers:
        hoover.apply([o for o in garage(s, plan, zones, ids) if o['kind'] == 'ConfigMap'])
    temporal.apply(s, plan, zones)
    record = {'nodes': list(plan['nodes']), 'garage_replication_factor': 1, 'garage_nodes': ids,
              'cassandra_nodes': plan['cassandra'], 'opensearch_nodes': plan['opensearch'], 'temporal_pods': plan['temporal'],
              'temporal_history_shards': (before or {}).get('temporal_history_shards', plan['history_shards'])}
    common.apply(configmap(STATE, {'plan': json.dumps(record, sort_keys=True)}))
    common.log('stores.jsonl', step='shared-stores', namespace=NS, nodes=list(plan['nodes']), garage=plan['garage'],
               cassandra=plan['cassandra'], opensearch=plan['opensearch'], temporal=plan['temporal'], zones=zones)


def grow():
    """Make the claims of the stores and of the Temporal stores large enough for the zones of the zone state."""
    zones = len(site_zones())
    sizes = {'clickhouse': size('clickhouse', zones), 'garage': size('garage', zones),
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
    if not argv or argv[0] not in ('apply', 'show', 'grow', 'ready', 'check', 'remove') or (argv[0] == 'remove') != (len(argv) == 2):
        sys.exit(__doc__)
    if argv[0] == 'show':
        s = site()
        print(json.dumps(objects(s, config.store_plan(s), len(site_zones()), {}), indent=1))
    elif argv[0] == 'apply':
        apply()
    elif argv[0] == 'grow':
        grow()
    elif argv[0] == 'ready':
        for store in ('clickhouse', 'garage', 'temporal-cassandra', 'temporal-opensearch', 'temporal'):
            ready_pod(store)
    elif argv[0] == 'check':
        found = problems()
        print(json.dumps({'problems': found}))
        sys.exit(1 if found else 0)
    else:
        remove(argv[1])


if __name__ == '__main__':
    main(sys.argv[1:])
