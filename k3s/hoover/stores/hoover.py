#!/usr/bin/env python3
"""The pod parts of the Kata stores of a site, which shared.py and temporal.py use.

The shared stores of the site (ClickHouse, Garage, both Manticore daemons and the Temporal stores) run in the namespace
hoover-stores (shared.py, temporal.py). Each store gets a Service and a StatefulSet. Its data is a raw TopoLVM block
volume of the store tier of the site (../../zones/zonestate.py). The scheduler places the store pod by its requests,
and the pod then stays on the node of its volume. The block mount wrapper of podspec.py makes the file system and
mounts it inside the guest.
The memory limits come from ../../zones/memory-limits.json. The memory requests (REQUESTS) are the measured working
sets, so the scheduler balances the nodes by real use.
The StatefulSets use the OnDelete update strategy. shared.py replaces outdated pods after applying their templates.
The claim template of an existing StatefulSet cannot change. An apply keeps the template of the cluster and grows the
claim of each pod to the wanted size when that is larger. A grown volume reaches the Kata guest at the next pod
start, and the block mount wrapper then grows the file system.
"""
import json, subprocess
import common, podspec

SECRET = 'hoover-stores'
# The PriorityClass of the pods that can run on one node only (../../cluster/priorityclasses.yaml).
NODE_BOUND = 'hoover-node-bound'
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


def site_cpu(items):
    """Write the measured CPU request and its basis into each shared store workload of the site.

    The values are the part site of ../../zones/cpu-requests.json (../../zones/cpu_requests.py). A workload without a
    measurement keeps the request of resources().
    """
    import cpu_requests
    for o in items:
        if o['kind'] in ('Deployment', 'StatefulSet'):
            cpu_requests.apply(o, f"{o['kind'].lower()}/{o['metadata']['name']}", 'site')
    return items


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
    # The pod stays on the node of its volume, so it preempts a stateless pod when that node is full.
    spec['priorityClassName'] = NODE_BOUND
    spec = podspec.blockmount(spec, container['name'], entrypoint, [('data', None, directory)], user)
    labels = {'app.kubernetes.io/name': store, common.LABEL: 'store', 'hoover.dev/store': store}
    claim = {'metadata': {'name': 'data'}, 'spec': {'accessModes': ['ReadWriteOnce'], 'volumeMode': 'Block',
             'storageClassName': f'{tier}-block', 'resources': {'requests': {'storage': size}}}}
    return {'apiVersion': 'apps/v1', 'kind': 'StatefulSet',
            'metadata': {'name': name, 'namespace': namespace, 'labels': {common.LABEL: 'store', 'hoover.dev/store': store}},
            'spec': {'replicas': replicas, 'serviceName': service_name or store,
                     'selector': {'matchLabels': {'hoover.dev/store': store}}, 'updateStrategy': {'type': 'OnDelete'},
                     'template': {'metadata': {'labels': labels}, 'spec': spec}, 'volumeClaimTemplates': [claim]}}


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
