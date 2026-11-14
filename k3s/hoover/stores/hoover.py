#!/usr/bin/env python3
"""Build and apply the Manticore daemons of a zone in Kata, and the pod parts that the shared stores reuse.

The two Manticore daemons of a zone (text and vectors) run in the zone namespace. ClickHouse and Garage are the shared
stores of the site (shared.py). Manticore stays in the zone, because a Manticore user with the right schema on its own
tables can read the tables of another user through a distributed table.
Each daemon gets a Service and a one-replica StatefulSet in the zone namespace. Its data is a raw TopoLVM block volume
of the store tier of the site (../../zones/zonestate.py). The scheduler places the store pod by its requests, and the
pod then stays on the node of its volume.
The block mount wrapper of podspec.py makes the file system and mounts it inside the guest.
Credentials come from the hoover-stores Secret of the zone (creds.py). The memory limits come from
../../zones/memory-limits.json.
The StatefulSets use the OnDelete update strategy. zone.py replaces outdated pods after applying their templates.
A direct run of this tool keeps existing pods until an operator deletes them.
The memory requests (REQUESTS) are the measured working sets, so the scheduler balances the nodes by real use.
The claim template of an existing StatefulSet cannot change. An apply keeps the template of the cluster and grows the
claim of each pod to the wanted size when that is larger. A grown volume reaches the Kata guest at the next pod
start, and the block mount wrapper then grows the file system.
Usage: hoover.py apply|show <manticore|manticore-vectors> <zone>
"""
import json, subprocess, sys
import common, podspec
import zonestate  # noqa: E402  (common puts ../../zones on the path)

SECRET = 'hoover-stores'
CONFIG = common.LAB / 'config'
LIMITS = json.loads((common.SOURCE / 'zones' / 'memory-limits.json').read_text())['hoover']
# The claim of each store, for one zone. The Manticore text claim holds at least the 14.1 GiB of Manticore text data of
# the 64 GB reference site. The shared stores multiply their size by the zone count (shared.py size()).
SIZES = {'clickhouse': '20Gi', 'manticore': '16Gi', 'manticore-vectors': '10Gi', 'garage': '20Gi'}
# The memory request of each store: the current request plus 0.33 times the distance to the largest working set (anon
# memory) of the 64 GB reference site, rounded up to 64 MiB.
REQUESTS = {'clickhouse': '640Mi', 'manticore': '448Mi', 'manticore-vectors': '704Mi', 'garage': '128Mi'}
IMAGES = {
    'clickhouse': 'docker.io/clickhouse/clickhouse-server:25.8',
    'manticore': 'docker.io/manticoresearch/manticore:29.9.0',
    'garage': 'docker.io/dxflrs/garage:v2.3.0',
}
# Manticore reads searchd settings from searchd_* variables. Small caches, no pseudo sharding, memory-mapped attributes.
MANTICORE_ENV = {'TELEMETRY': '0', 'searchd_auth': '1', 'searchd_rt_flush_period': '900', 'searchd_qcache_max_bytes': '0',
                 'searchd_pseudo_sharding': '0', 'searchd_docstore_cache_size': '4m', 'searchd_threads': '2',
                 'searchd_access_plain_attrs': 'mmap', 'searchd_access_blob_attrs': 'mmap', 'searchd_access_doclists': 'file',
                 'searchd_access_hitlists': 'file'}


def resources(store):
    return {'requests': {'cpu': '50m', 'memory': REQUESTS[store]}, 'limits': {'cpu': '2', 'memory': LIMITS[store]}}


def secret_env(name, key):
    return {'name': name, 'valueFrom': {'secretKeyRef': {'name': SECRET, 'key': key}}}


def prefix(zone):
    return zone.replace('-', '_')


def service(store, namespace, ports, selector=None, headless=False):
    spec = {'selector': selector or {'app.kubernetes.io/name': store},
            'ports': [{'name': n, 'port': p, 'targetPort': p} for n, p in ports]}
    if headless:
        # The peer names of a StatefulSet resolve before its pods are ready.
        spec.update(clusterIP='None', publishNotReadyAddresses=True)
    return {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': store, 'namespace': namespace, 'labels': {common.LABEL: 'service'}},
            'spec': spec}


def statefulset(name, store, namespace, container, entrypoint, directory, tier, size, replicas=1, service_name=None,
                user=None, extra_volumes=(), affinity=None):
    """A Kata StatefulSet of a store with one block volume claim data of size in the tier tier for each pod."""
    spec = {'runtimeClassName': 'kata', 'terminationGracePeriodSeconds': 60, 'enableServiceLinks': False,
            'containers': [container], 'volumes': list(extra_volumes)}
    if affinity:
        spec['affinity'] = affinity
    spec = podspec.blockmount(spec, container['name'], entrypoint, [('data', None, directory)], user)
    labels = {'app.kubernetes.io/name': store, common.LABEL: 'store', 'hoover.dev/store': store}
    claim = {'metadata': {'name': 'data'}, 'spec': {'accessModes': ['ReadWriteOnce'], 'volumeMode': 'Block',
             'storageClassName': f'{tier}-block', 'resources': {'requests': {'storage': size}}}}
    return {'apiVersion': 'apps/v1', 'kind': 'StatefulSet',
            'metadata': {'name': name, 'namespace': namespace, 'labels': {common.LABEL: 'store', 'hoover.dev/store': store}},
            'spec': {'replicas': replicas, 'serviceName': service_name or store,
                     'selector': {'matchLabels': {'hoover.dev/store': store}}, 'updateStrategy': {'type': 'OnDelete'},
                     'template': {'metadata': {'labels': labels}, 'spec': spec}, 'volumeClaimTemplates': [claim]}}


def manticore(zone, name='manticore'):
    """A Manticore daemon. Hoover refuses one host for text and vectors, so a zone has two of them."""
    container = {
        'name': 'manticore', 'image': IMAGES['manticore'],
        'env': [{'name': k, 'value': v} for k, v in MANTICORE_ENV.items()] + [
            secret_env('MT_ADMIN_PASSWORD', 'manticore-admin'), secret_env('MT_ZONE_PASSWORD', 'manticore-zone')],
        'ports': [{'name': 'sql', 'containerPort': 9306}, {'name': 'http', 'containerPort': 9308}],
        'readinessProbe': {'tcpSocket': {'port': 9306}, 'periodSeconds': 2, 'failureThreshold': 3},
        'resources': resources(name)}
    container['volumeMounts'] = [{'name': 'seed', 'mountPath': '/seed', 'readOnly': True}]
    # With authentication on, searchd starts with the users of auth.json in its data folder. A new daemon gets the
    # seed of creds.py with the user hoover_admin, and ../setup.py adds the zone user and the service users.
    # searchd writes an auth.json without users when none exists, so that file also gets the seed.
    start = ('grep -q username /var/lib/manticore/auth.json 2>/dev/null || '
             '{ cp /seed/auth.json /var/lib/manticore/auth.json && chmod 600 /var/lib/manticore/auth.json; }; '
             'exec /usr/local/bin/docker-entrypoint.sh searchd -c /etc/manticoresearch/manticore.conf.sh --nodetach')
    seed = {'name': 'seed', 'secret': {'secretName': SECRET, 'items': [{'key': 'manticore-seed', 'path': 'auth.json'}]}}
    tier = zonestate.tier(zone, name, zonestate.site_tiers(common.settings.KUBECONFIG))
    return [service(name, zone, [('sql', 9306), ('http', 9308)]),
            statefulset(f'{name}-kata', name, zone, container, ['sh', '-c', start], '/var/lib/manticore', tier, SIZES[name],
                        replicas=1 if common.namespace_enabled(zone) else 0, user='999:999', extra_volumes=[seed])]


BUILDERS = {'manticore': manticore, 'manticore-vectors': lambda z: manticore(z, 'manticore-vectors')}


def grow_claims(namespace, current, size):
    """Keep the claim template of an existing StatefulSet, and grow the claim of each of its pods to size."""
    found_template = current['spec']['volumeClaimTemplates'][0]
    template = {'metadata': {'name': found_template['metadata']['name']}, 'spec': found_template['spec']}
    for index in range(current['spec'].get('replicas') or 1):
        claim = f"{template['metadata']['name']}-{current['metadata']['name']}-{index}"
        found = common.kubectl('-n', namespace, 'get', 'pvc', claim, '--ignore-not-found', '-o', 'json').strip()
        if not found:
            continue
        if gibibytes(size) > gibibytes(json.loads(found)['spec']['resources']['requests']['storage']):
            common.kubectl('-n', namespace, 'patch', 'pvc', claim, '--type', 'merge', '-p',
                           json.dumps({'spec': {'resources': {'requests': {'storage': size}}}}))
            common.log('stores.jsonl', step='claim-grown', claim=claim, namespace=namespace, size=size)
    return template


def gibibytes(text):
    units = {'Ki': 2 ** -20, 'Mi': 2 ** -10, 'Gi': 1, 'Ti': 2 ** 10}
    return float(text[:-2]) * units[text[-2:]] if text[-2:] in units else float(text) / 2 ** 30


def apply(objects, keep_replicas=True):
    """Apply each object that differs from the cluster. A StatefulSet keeps its claim template and grows its claims.

    An apply does not start a store that an operator stopped: an existing StatefulSet with zero replicas keeps them.
    keep_replicas: an existing StatefulSet also keeps any other replica count.
    """
    for o in objects:
        if o['kind'] == 'StatefulSet':
            namespace = o['metadata']['namespace']
            current = common.kubectl('-n', namespace, 'get', 'statefulset', o['metadata']['name'], '--ignore-not-found', '-o', 'json').strip()
            found = json.loads(current)['spec'].get('replicas', 1) if current else None
            if current and o['spec']['replicas'] and (keep_replicas or found == 0):
                o['spec']['replicas'] = found
            if current:
                size = o['spec']['volumeClaimTemplates'][0]['spec']['resources']['requests']['storage']
                o['spec']['volumeClaimTemplates'] = [grow_claims(namespace, json.loads(current), size)]
        # kubectl apply reports some unchanged StatefulSets as configured, so only a difference in kubectl diff applies.
        diff = subprocess.run(common.K + ['diff', '-f', '-'], input=json.dumps(o), capture_output=True, text=True)
        if diff.returncode == 0:
            continue
        if diff.returncode != 1:
            raise SystemExit(f'kubectl diff failed: {diff.stderr.strip()[-500:]}')
        result = common.kubectl('apply', '-f', '-', input=json.dumps(o)).strip()
        common.log('stores.jsonl', step='applied', object=result)


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in ('apply', 'show') or sys.argv[2] not in BUILDERS:
        sys.exit(__doc__)
    command, store, zone = sys.argv[1:]
    objects = BUILDERS[store](zone)
    if command == 'show':
        print(json.dumps(objects, indent=1))
        return
    apply(objects)


if __name__ == '__main__':
    main()
