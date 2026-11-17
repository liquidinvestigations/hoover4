#!/usr/bin/env python3
"""The processing pools of a site: ClamAV and the stateless Hoover file processors in the namespace hoover-pools.

The services of manifests.SCALABLE (Tika, Tesseract, the searchable-PDF builder, the PDF search, the regex scanner and
ClamAV) keep no state between requests. A site of the store layout site runs them once, here, and every Hoover
installation of that layout reaches them by its Compose names: the render of the installation (manifests.py) gives
each name an ExternalName Service <name>.hoover-pools.svc.cluster.local and renders no own copy. The local store layout
keeps its own copies.
- Each service runs vars.replicas.<service> pods of the site file (default 1) behind its Service, in gVisor, with the
  container of its Compose service. The settings of the pools are the default values of the Hoover settings
  (platform/operator/settings.py, scope hoover). An override of a zone does not change a pool.
- A pool holds no zone identity and no store credential. Its environment has no store address and no key, and the
  namespace reaches no store. The searchable-PDF builder gets the source in the request and answers with the PDF
  (main_services/ocr_pdf, field inline). The workers of the installations set OCR_PDF_TRANSFER=inline, so they read
  the source object and write the result object with their own key.
- ClamAV runs on the public node (manifests.INTERNET), from where it loads its signature updates.
- Memory and CPU requests are the measured values of the workloads deployment/<name> of the part hoover of
  ../zones/memory-requests.json and cpu-requests.json. The concurrency settings of each service limit the requests
  that one pod works on, so the pod of one installation was measured under the same limit.
- With a GPU pool, the searchable-PDF builder reaches EasyOCR through the forwarder gpu of this namespace, with the
  token of the name hoover-pools (gpu.py).
Network policies (network()): every pod reaches the cluster DNS only, and takes no connection, unless a rule below admits
it. Each pool takes connections on its own ports from the pods of CALLERS in the Hoover namespaces (label
hoover.dev/hoover). The searchable-PDF builder reaches Tesseract. ClamAV reaches public addresses. The pools reach no
store, no zone namespace and no other pool.
A site without a zone of the store layout site runs no pool: apply and ensure then remove the objects of the namespace.

Usage: pools.py show      print the objects
       pools.py apply     apply the objects, delete the objects of an earlier apply that the render no longer has, and
                          wait until each pool is ready. deploy-k3s up runs it in the step stores.
       pools.py ensure    create the pools only when the namespace has none, and wait until they are ready. A pool that
                          runs stays as it is, so a zone create or delete changes no pool pod. ../zones/zone.py runs it.
       pools.py ready     exit 1 when a pool has no ready pod
"""
import base64
import json
import subprocess
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / 'zones'))
sys.path.insert(0, str(HERE))
import config as site_config  # noqa: E402
import settings as k3s_settings  # noqa: E402
import compose  # noqa: E402
import gpu  # noqa: E402
import manifests  # noqa: E402
import zone_ini  # noqa: E402

NS = 'hoover-pools'
# The settings scope of the pools. The scope has no saved override, so every value is the default.
SCOPE = 'hoover:pools'
# The name in the GPU token of the forwarder of this namespace (gpu.py).
GPU_NAME = 'hoover-pools'
# The pods of a Hoover namespace that call the pools: the workers, the singletons (the database migrations and the
# single writers) and the website (PDF search, OCR status, regex scanner).
CALLERS = ('hoover-workers', 'hoover-singletons', 'hoover-website')
# The pool label of each pod.
POOL = 'hoover.dev/pool'


class PoolError(SystemExit):
    """The pools cannot be rendered or applied. The message names the cause."""


def kubectl(*args, input=None, check=True):
    r = subprocess.run(['kubectl', '--kubeconfig', k3s_settings.KUBECONFIG, *args], input=input, capture_output=True,
                       text=True)
    if check and r.returncode:
        raise PoolError(f'kubectl {" ".join(args[:4])} failed: {(r.stderr or r.stdout).strip()[-500:]}')
    return r.stdout


def site_zones(state=None):
    """The zones of the zone state that use the shared stores of the site, and so the pools."""
    import zonestate
    try:
        state = zonestate.load() if state is None else state
    except zonestate.ZoneStateError:
        return []
    return [z for z, e in state['zones'].items() if e.get('stores') == 'site']


def services(site, tree=site_config.REPO):
    """(deploy module, Config, {name: Compose service}) of the pools: the ini of the default Hoover settings."""
    values = manifests.operator_settings.effective(SCOPE, {})
    ini_values = manifests.operator_settings.ini_values(values)
    ini_values[('storage', 'garage_capacity')] = values['volume.garage-data'].removesuffix('i')
    mounts = [{'name': 'testdata', 'path': '/data/testdata', 'writable': False}]
    text = zone_ini.render(ini_values, mounts, bool(site.gpu_pool), title='the processing pools of the site')
    with tempfile.TemporaryDirectory() as folder:
        ini = Path(folder) / 'hoover4.ini'
        ini.write_text(text)
        deploy, cfg, _, found = compose.load(ini, tree)
    return deploy, cfg, {n: found[n] for n in sorted(manifests.SCALABLE) if n in found}


def target(site, revision, tree):
    """The part of a manifests.Target that the builders of manifests.py read."""
    return types.SimpleNamespace(ns=NS, local=False, enabled=True, revision=revision, tree=tree, site=site)


def pool(t, site, name, svc):
    """The Deployment and the Service of one pool."""
    key = manifests.SCALABLE[name]
    # The environment of the Compose service, without the object store of an installation.
    env = {k: manifests.renamed_hosts(v) for k, v in svc.get('environment', {}).items() if not k.startswith('S3_')}
    pod_volumes, mounted, _ = manifests.volumes(t, name, svc, [])
    memory, cpu = manifests.limits(svc, manifests.UNLIMITED_IN_COMPOSE.get(name, '512Mi'))
    c = manifests.container(name, svc, manifests.image_of(t, name, svc), env, memory, mounted, cpu=cpu)
    labels = {POOL: key}
    node = None
    if name in manifests.INTERNET:
        labels['hoover.dev/egress'] = 'internet'
        node = {'kubernetes.io/hostname': site.with_role('public')[0].name}
    spec = manifests.pod_spec(t, [c], pod_volumes, runtime='gvisor', node=node)
    items = [manifests.workload(t, 'Deployment', name, spec, replicas=site.replicas.get(key, 1), labels=labels)]
    ports = manifests.ports(name, svc)
    if ports:
        items.append(manifests.service(t, name, ports))
    return items


def ports_of(found):
    return {name: manifests.ports(name, svc) for name, svc in found.items()}


def network(site, found):
    """The network policies of the namespace (see the module docstring)."""
    def policy(name, spec):
        return {'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy', 'metadata': {'name': name, 'namespace': NS},
                'spec': spec}

    def pod(name):
        return {'matchLabels': {'app.kubernetes.io/name': name}}
    dns = {'to': [{'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'kube-system'}},
                   'podSelector': {'matchLabels': {'k8s-app': 'kube-dns'}}}],
           'ports': [{'port': 53, 'protocol': 'UDP'}, {'port': 53, 'protocol': 'TCP'}]}
    callers = {'namespaceSelector': {'matchLabels': {'hoover.dev/hoover': 'true'}},
               'podSelector': {'matchExpressions': [{'key': 'app.kubernetes.io/name', 'operator': 'In', 'values': list(CALLERS)}]}}
    ports = ports_of(found)
    # The policy type Ingress without ingress rules admits no connection.
    items = [policy('closed', {'podSelector': {}, 'policyTypes': ['Ingress', 'Egress'], 'egress': [dns]})]
    for name in found:
        items.append(policy(f'{name}-clients', {'podSelector': pod(name), 'policyTypes': ['Ingress'],
                                                'ingress': [{'from': [callers], 'ports': [{'port': p} for p in ports[name]]}]}))
    if 'hoover4-ocr-pdf' in found and 'hoover4-tesseract-cpu' in found:
        tesseract = [{'port': p} for p in ports['hoover4-tesseract-cpu']]
        items += [policy('tesseract-from-ocr-pdf', {'podSelector': pod('hoover4-tesseract-cpu'), 'policyTypes': ['Ingress'],
                                                    'ingress': [{'from': [{'podSelector': pod('hoover4-ocr-pdf')}], 'ports': tesseract}]}),
                  policy('ocr-pdf-to-tesseract', {'podSelector': pod('hoover4-ocr-pdf'), 'policyTypes': ['Egress'],
                                                  'egress': [{'to': [{'podSelector': pod('hoover4-tesseract-cpu')}], 'ports': tesseract}]})]
    items.append(policy('egress-internet', {'podSelector': {'matchLabels': {'hoover.dev/egress': 'internet'}}, 'policyTypes': ['Egress'],
                                            'egress': [{'to': [{'ipBlock': {'cidr': '0.0.0.0/0', 'except': manifests.PRIVATE_RANGES}}]}]}))
    if site.gpu_pool and 'hoover4-ocr-pdf' in found:
        gpu_ports = [{'port': p} for p in gpu.PORTS]
        items += [policy('gpu-from-ocr-pdf', {'podSelector': pod('gpu'), 'policyTypes': ['Ingress'],
                                              'ingress': [{'from': [{'podSelector': pod('hoover4-ocr-pdf')}], 'ports': gpu_ports}]}),
                  policy('ocr-pdf-to-gpu', {'podSelector': pod('hoover4-ocr-pdf'), 'policyTypes': ['Egress'],
                                            'egress': [{'to': [{'podSelector': pod('gpu')}], 'ports': gpu_ports}]}),
                  policy('gpu-to-proxy', {'podSelector': pod('gpu'), 'policyTypes': ['Egress'],
                                          'egress': [{'to': [{'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': gpu.NS}}}],
                                                      'ports': gpu_ports}]})]
    return items


def objects(site, revision=None, tree=site_config.REPO, zones=None):
    """Every object of the pools, in apply order. zones: the zones of the store layout site. Without one, the list is
    empty."""
    if zones is not None and not zones:
        return []
    revision = revision or manifests.resolve_revision(tree)
    deploy, cfg, found = services(site, tree)
    t = target(site, revision, tree)
    configs = set()
    workloads = []
    for name, svc in found.items():
        items = pool(t, site, name, svc)
        for item in items:
            if item['kind'] == 'Deployment':
                configs |= {v['configMap']['name'] for v in item['spec']['template']['spec'].get('volumes', [])
                            if 'configMap' in v}
        workloads += items
    namespace = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': NS, 'labels': {POOL: 'true'}}}
    forwarder = gpu.forwarder(GPU_NAME, NS) if site.gpu_pool and 'hoover4-ocr-pdf' in found else []
    return [namespace, *manifests.config_maps(t, deploy, cfg, configs), *forwarder, *workloads, *network(site, found)]


# ----------------------------------------------------------------------------------------------------------------------
# Cluster
# ----------------------------------------------------------------------------------------------------------------------

def runtime_secret():
    """Write the Secret hoover-runtime of the namespace when its value differs: the GPU token of GPU_NAME, which the
    searchable-PDF builder mounts as its GPU key file and the forwarder gpu sends."""
    wanted = {'gpu-token': gpu.token(GPU_NAME)}
    found = kubectl('-n', NS, 'get', 'secret', 'hoover-runtime', '--ignore-not-found', '-o', 'json').strip()
    current = {k: base64.b64decode(v).decode() for k, v in json.loads(found).get('data', {}).items()} if found else {}
    if current != wanted:
        kubectl('apply', '-f', '-', input=json.dumps({'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
                                                      'metadata': {'name': 'hoover-runtime', 'namespace': NS},
                                                      'stringData': wanted}))


def deployments():
    """The names of the Deployments of the namespace: the pools and the forwarder gpu."""
    found = kubectl('-n', NS, 'get', 'deployments', '-o', 'json', check=False)
    try:
        return sorted(i['metadata']['name'] for i in json.loads(found)['items'])
    except (ValueError, KeyError):
        return []


def namespace_present():
    return bool(kubectl('get', 'namespace', NS, '--ignore-not-found', '-o', 'name').strip())


def remove():
    """Delete every pool object of the namespace. The namespace stays, because the zone runner has rights in it."""
    for resource in manifests.PRUNED + ('secrets',):
        kubectl('-n', NS, 'delete', resource, '--all', '--ignore-not-found', '--wait=false')


def wait(timeout=900):
    for name in deployments():
        out = subprocess.run(['kubectl', '--kubeconfig', k3s_settings.KUBECONFIG, '-n', NS, 'rollout', 'status',
                              f'deployment/{name}', f'--timeout={timeout}s'], capture_output=True, text=True)
        if out.returncode:
            raise PoolError(f'the pool {name} did not become ready: {(out.stderr or out.stdout).strip()[-300:]}')


def apply(only_missing=False):
    """Apply the pools and wait for them (see the module docstring). only_missing: the command ensure."""
    site = site_config.read(k3s_settings.SITE_FILE)
    zones = site_zones()
    if not zones:
        if namespace_present():
            remove()
        print(json.dumps({'pools': [], 'zones': 0}))
        return
    if only_missing and deployments():
        wait()
        print(json.dumps({'pools': deployments(), 'changed': False}))
        return
    items = objects(site, zones=zones)
    # The zone runner (ensure) cannot change a namespace outside the zones. install-runner.sh creates this one.
    if not only_missing or not namespace_present():
        kubectl('apply', '--server-side', '--force-conflicts', '--field-manager=hoover', '-f', '-', input=json.dumps(items[0]))
    runtime_secret()
    kubectl('apply', '--server-side', '--force-conflicts', '--field-manager=hoover', '-f', '-',
            input=json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': items[1:]}))
    manifests.prune(['kubectl', '--kubeconfig', k3s_settings.KUBECONFIG], NS, items)
    wait()
    print(json.dumps({'pools': deployments(), 'zones': len(zones)}))


def ready():
    missing = []
    for name in deployments():
        found = json.loads(kubectl('-n', NS, 'get', 'deployment', name, '-o', 'json'))
        if not (found.get('status') or {}).get('readyReplicas'):
            missing.append(name)
    if missing:
        raise PoolError(f'these pools of {NS} have no ready pod: {", ".join(missing)}. Run deploy-k3s up --steps stores.')


def main(argv):
    if len(argv) != 1 or argv[0] not in ('show', 'apply', 'ensure', 'ready'):
        sys.exit(__doc__)
    if argv[0] == 'show':
        site = site_config.read(k3s_settings.SITE_FILE)
        print(json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': objects(site, zones=site_zones())}, indent=1))
    elif argv[0] == 'ready':
        ready()
    else:
        apply(only_missing=argv[0] == 'ensure')


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except site_config.SiteError as error:
        raise SystemExit(str(error))
