#!/usr/bin/env python3
"""Render the Kubernetes objects of one Hoover installation as one List.

The installation is a [hoover.<name>] section of the site file (../config.py). Its operator settings
(../platform/operator/settings.py) give the hoover4.ini of zone_ini.py, and compose.py reads the Compose services of
that ini with deploy.py of the source tree. This file translates each service into Kubernetes objects. It keeps the
command, environment, memory and CPU limits, health check, user and capabilities of each service, and maps its volumes
(see volumes()). SERVICES classifies every Compose service of both sides. A Compose service that SERVICES does not
name stops the render with an error that names the service and its file.

Store layouts (the stores key of the site file):
- local: the stores of the Compose files run in the Hoover namespace on file system claims of the home node:
  ClickHouse, both Manticore daemons, Garage with its init job, and ZooKeeper, which the ClickHouse configuration
  names. The operations worker mounts the store claims as in Compose, so store backup and restore work. A migrated
  install keeps the claims of its copied store folders.
- zone: ClickHouse, both Manticore daemons and Garage run in Kata on block volumes in the zone namespace
  (stores/hoover.py), and ExternalName Services keep the Compose names. setup.py creates the Garage buckets.
Temporal backends (the temporal_backend key):
- cassandra: Temporal, Cassandra and Elasticsearch as in Compose, with the dynamic configuration of deploy.py, the
  history shard count of the operator settings, a retention job for the default namespace, and claims for both stores.
- postgresql: Temporal on the PostgreSQL of the zone, as an existing remote zone runs it. setup.py creates the
  databases. No conversion between the two backends exists.
Placement and runtimes:
- Every pod runs in gVisor, which the zone pod policy sets, except the workers and the operations worker in Kata,
  because they parse untrusted files.
- hoover-workers has budget.worker_pods replicas. Each pod polls its own host queues (HOOVER4_HOST_QUEUE is the pod
  name). In the local layout it is a StatefulSet on the home node: a pod keeps its name after a restart and keeps its
  plan files on its own claim worker-temp-files-hoover-workers-<n>. A migrated install fills the claim of pod 0 with
  the plan files of its Compose worker. In the zone layout it is a Deployment spread over the nodes, with the plan
  files in an emptyDir: a new pod has a new name, so the plans of a lost pod claim another host.
  The index planner, the email graph and the chat worker are single writers and run in the one pod of
  hoover-singletons, which also runs the database migrations first.
- The services that reach the internet (INTERNET) run on a public node, so their traffic leaves from its address.
- Every pod with a claim of the local layout runs on the home node, because the claims are local volumes there.
The GPU services and the LLM are behind the forwarder gpu (gpu.py). The network policies are in network().
The ingress sends every request to oauth2-proxy. It removes client identity headers, adds the verified claims and the
proxy secret, and forwards to the website. The website accepts identity headers only with that secret.
Every store credential, the proxy secret and every shared secret comes from a Secret. The render holds no secret value.
apply also deletes the objects of an earlier apply that the render no longer has (prune()).
Usage: manifests.py <installation or zone> [show|apply|diff] [--site FILE] [--revision REV]
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
K3S = HERE.parent
sys.path.insert(0, str(K3S))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / 'stores'))
import importlib.util  # noqa: E402
import settings as k3s_settings  # noqa: E402
import config as site_config  # noqa: E402
import compose  # noqa: E402
import zone_ini  # noqa: E402
import gpu  # noqa: E402
import service_users  # noqa: E402


def _operator_settings():
    # k3s/settings.py holds the module name settings, so the operator settings load under their own name.
    name = 'operator_settings'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, K3S / 'platform/operator/settings.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


operator_settings = _operator_settings()

PART = 'hoover.dev/part'
REGISTRY = 'registry.hoover.internal/hoover'
TEMPORAL_PG = 'docker.io/temporalio/auto-setup:1.23.1@sha256:a73792b9289ac504ee6c49fb0dfb430626bc4f422f15cf885503de49e4ae283b'
OAUTH2_PROXY = 'quay.io/oauth2-proxy/oauth2-proxy:v7.12.0@sha256:786bed0f000c0f8a7b31619244ebab02406a8856a4faf3f5fb1df61fbd6c30ed'

# Every Compose service and its cluster form. image names the key of compose.IMAGES for a service that the image
# build makes, or None for an upstream image. role decides the form:
#   app         a Deployment and a Service in every layout
#   store       a StatefulSet in the local layout. The zone layout runs the store of stores/hoover.py instead.
#   store-init  a Job in the local layout. setup.py does its work in the zone layout.
#   temporal    the Compose Temporal with the cassandra backend, or the PostgreSQL Temporal of temporal_pg().
#   temporal-store  a StatefulSet with the cassandra backend. The postgresql backend has no such store.
#   ui          an operator interface, a Deployment and a Service without ingress
#   gpu         a GPU service. The forwarder gpu reaches it in the shared GPU pool (gpu.py).
#   excluded    not rendered. reason says why.
SERVICES = {
    'hoover4-website': {'role': 'app', 'image': 'website'},
    'hoover4-worker': {'role': 'app', 'image': 'processing'},
    'hoover4-ops': {'role': 'app', 'image': 'processing'},
    'hoover4-pdf-search': {'role': 'app', 'image': 'pdf-search'},
    'hoover4-tika': {'role': 'app', 'image': None},
    'hoover4-regex-entity-scanner': {'role': 'app', 'image': 'regex'},
    'hoover4-tesseract-cpu': {'role': 'app', 'image': 'tesseract'},
    'hoover4-ocr-pdf': {'role': 'app', 'image': 'ocr-pdf'},
    'hoover4-clamav': {'role': 'app', 'image': 'clamav'},
    'hoover4-mcp-collections': {'role': 'app', 'image': 'mcp-collections'},
    'hoover4-mcp-todo': {'role': 'app', 'image': 'mcp-todo'},
    'hoover4-mcp-whois': {'role': 'app', 'image': 'mcp-whois'},
    'hoover4-mcp-metasearch': {'role': 'app', 'image': 'mcp-metasearch'},
    'hoover4-mcp-browser': {'role': 'app', 'image': 'mcp-browser'},
    'hoover4-web-tor': {'role': 'app', 'image': 'web-tor'},
    'hoover4-internal-search-agent': {'role': 'app', 'image': 'research-agent'},
    'hoover4-full-research-agent': {'role': 'app', 'image': 'research-agent'},
    'clickhouse': {'role': 'store', 'image': None},
    'manticore': {'role': 'store', 'image': None},
    'manticore-vectors': {'role': 'store', 'image': None},
    'garage': {'role': 'store', 'image': None},
    'zookeeper': {'role': 'store', 'image': None},
    'garage-init': {'role': 'store-init', 'image': 'garage-init'},
    'temporal': {'role': 'temporal', 'image': None},
    'temporal-cassandra': {'role': 'temporal-store', 'image': None},
    'temporal-elasticsearch': {'role': 'temporal-store', 'image': None},
    'temporal-ui': {'role': 'ui', 'image': None},
    'clickhouse-monitoring': {'role': 'ui', 'image': None},
    'ch-ui': {'role': 'ui', 'image': None},
    'hoover4-vllm': {'role': 'gpu', 'image': None},
    'hoover4-ai-server': {'role': 'gpu', 'image': None},
    'hoover4-easyocr-gpu': {'role': 'gpu', 'image': None},
    'redis': {'role': 'excluded', 'reason': 'No Hoover service connects to Redis.'},
    'hoover4-processing-pdf-to-html': {'role': 'excluded',
                                       'reason': 'No Hoover service calls it. The website names its address only.'},
    'hoover4-development-auth-backdoor': {'role': 'excluded',
                                          'reason': 'oauth2-proxy with Keycloak signs in every user (D12).'},
}
# The services that reach the internet. ClamAV loads its signatures from the internet.
INTERNET = {'hoover4-mcp-whois', 'hoover4-mcp-metasearch', 'hoover4-mcp-browser', 'hoover4-web-tor', 'hoover4-clamav'}
# Container ports of the services that publish none in Compose.
PORTS = {'hoover4-tika': [9998], 'hoover4-clamav': [8000], 'hoover4-web-tor': [9050, 9051], 'hoover4-pdf-search': [13500],
         'zookeeper': [2181], 'temporal-ui': [8080], 'clickhouse-monitoring': [3000], 'ch-ui': [5521]}
# The Kubernetes names of the services that keep another name in the cluster.
NAMES = {'hoover4-website': 'hoover-website', 'hoover4-ops': 'hoover-operations'}
# The Secret items of the key files. A file without an item stays absent, and its feature stays off.
SECRET_FILES = {'llm_api_key': 'gpu-token', 'mcp_shared_secret': 'mcp-shared-secret',
                'browser_fetch_token': 'browser-fetch-token', 'factcheck_api_key': 'factcheck-api-key'}
# The volume folders of deploy.py and their claims (settings.VOLUMES). A folder without a claim is a cache or scratch
# space and becomes an emptyDir. A folder in UNUSED is left out.
CLAIMS = {'clickhouse_data': 'clickhouse-data', 'manticore_data_v14': 'manticore-data',
          'manticore_vectors_data_v14': 'manticore-vectors-data', 'garage_meta': 'garage-meta', 'garage_data': 'garage-data',
          'temporal_cassandra': 'temporal-cassandra', 'temporal_elasticsearch': 'temporal-elasticsearch',
          'ops_backups': 'ops-backups', 'hoover4-upload-tmp': 'upload-tmp', 'worker_temp_files': 'worker-temp-files',
          'clickhouse_monitoring': 'clickhouse-monitoring'}
# The claims of the zone layout. Its stores keep their own volumes in the zone namespace.
ZONE_CLAIMS = {'ops-backups', 'upload-tmp', 'worker-temp-files'}
UNUSED = {'hoover4-website-target'}
# The tiers of the claims, in order of preference (../zones/zonestate.py).
FAST = ('clickhouse-data', 'manticore-data', 'manticore-vectors-data', 'temporal-cassandra', 'temporal-elasticsearch')
# Bind mounts of files of the source tree, and the ConfigMap item that replaces each. The image of a built service
# holds its source, so a bind of a source folder of that service is left out (SOURCE_BINDS).
CONFIG_FILES = {
    '/tika-config.json': ('tika-config', 'tika-config.json'),
    '/etc/clickhouse-server/config.d/clickhouse-server-config-override.xml': ('clickhouse-config', 'config-override.xml'),
    '/etc/clickhouse-server/users.d/clickhouse-users-override.xml': ('clickhouse-config', 'users-override.xml'),
    '/usr/local/bin/hoover4-cassandra-entrypoint.sh': ('cassandra-entrypoint', 'entrypoint.sh'),
    '/etc/garage.toml': ('garage-config', 'garage.toml'),
}
CONFIG_DIRS = {'/etc/temporal/config/dynamicconfig': 'temporal-dynamicconfig',
               '/mirror/processing-tasks': 'mirror', '/mirror/website-backend-src': 'mirror'}
SOURCE_BINDS = {'/app', '/app/frontend', '/app/common', '/app/backend', '/app/Cargo.toml', '/app/Cargo.lock', '/app/main.py'}
# The memory limits that ../zones/memory-limits.json measured for the zone layout. Other limits come from Compose.
MEASURED = {'hoover4-website': 'hoover-website', 'hoover4-ops': 'hoover-operations'}
# The worker processes of the worker pods and of the singleton pod (main.py worker, HOOVER4_WORKERS).
WORKERS = 'tika,clamav,ocr,nlp,embed,indexing,common'
SINGLETONS = 'index-planner,email-graph,chat'
# The Compose store credential variables. A service gets them from a Secret, never as a literal.
STORE_CREDENTIALS = ('CLICKHOUSE_USER', 'CLICKHOUSE_PASSWORD', 'MANTICORE_USER', 'MANTICORE_PASSWORD', 'S3_ACCESS_KEY',
                     'S3_SECRET_KEY', 'GARAGE_RPC_SECRET', 'GARAGE_ADMIN_TOKEN', 'VITE_CLICKHOUSE_USER', 'VITE_CLICKHOUSE_PASS')
# The Secret items of the local layout. hoover-runtime holds them, and setup.py local-secrets writes them.
LOCAL_CREDENTIALS = {'CLICKHOUSE_USER': 'clickhouse-user', 'CLICKHOUSE_PASSWORD': 'clickhouse-password',
                     'MANTICORE_USER': 'manticore-user', 'MANTICORE_PASSWORD': 'manticore-password',
                     'S3_ACCESS_KEY': 's3-access-key', 'S3_SECRET_KEY': 's3-secret-key',
                     'GARAGE_RPC_SECRET': 'garage-rpc-secret', 'GARAGE_ADMIN_TOKEN': 'garage-admin-token',
                     'VITE_CLICKHOUSE_USER': 'clickhouse-user', 'VITE_CLICKHOUSE_PASS': 'clickhouse-password'}
# The stores of the zone namespace that the zone layout uses.
ZONE_STORES = ('clickhouse', 'manticore', 'manticore-vectors', 'garage', 'postgresql')
LOCAL_STORES = ('clickhouse', 'manticore', 'manticore-vectors', 'garage', 'zookeeper', 'temporal-cassandra',
                'temporal-elasticsearch')
PRIVATE_RANGES = ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '100.64.0.0/10', '169.254.0.0/16', '127.0.0.0/8']


class RenderError(SystemExit):
    """The render cannot produce the objects. The message names the cause."""


@dataclass
class Target:
    """Everything that one render reads. The render runs no command and reads no cluster state."""
    site: object
    hoover: object
    values: dict
    revision: str
    nfs: dict = field(default_factory=dict)
    source: object = None
    tree: Path = site_config.REPO
    # The zone setting app.hoover. A disabled installation renders zero replicas and keeps its claims and Secrets.
    enabled: bool = True

    @property
    def ns(self):
        return self.hoover.namespace

    @property
    def zone(self):
        return self.hoover.zone

    @property
    def host(self):
        return f'hoover.{self.zone}.{self.site.suffix}'

    @property
    def local(self):
        return self.hoover.stores == 'local'

    @property
    def cassandra(self):
        return self.hoover.temporal_backend == 'cassandra'

    @property
    def budget(self):
        return {k: int(self.values[f'budget.{k}']) for k in zone_ini.BUDGET}


def resolve_revision(tree=site_config.REPO):
    """The commit of the images. ../deploy-k3s resolves it once per deployment and passes it in HOOVER4_REVISION.
    Without the variable it is the commit of the source tree. The images hold this commit, without the local changes
    of the checkout."""
    if os.environ.get('HOOVER4_REVISION'):
        return os.environ['HOOVER4_REVISION']
    return subprocess.run(['git', '-C', str(tree), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()


def find_hoover(site, name):
    for hoover in site.hoovers.values():
        if name in (hoover.name, hoover.zone):
            return hoover
    raise RenderError(f'the site file has no [hoover.<name>] section with the name or zone {name}.')


def target_from_site(site_path, name, revision=None, state=None, nfs=None, settings_revision=None):
    """The Target of an installation, with the saved operator settings of its desired revision.

    settings_revision names another saved revision, for example the revision that an apply operation pinned.
    """
    site = site_config.read(site_path)
    hoover = find_hoover(site, name)
    folder = Path(state) if state else site.operator_state()
    overrides = operator_settings.State(folder).overrides(settings_revision) if (folder / 'desired.json').exists() else {}
    values = operator_settings.effective(f'hoover:{hoover.name}', overrides.get(f'hoover:{hoover.name}', {}))
    zone_values = operator_settings.effective(f'zone:{hoover.zone}', overrides.get(f'zone:{hoover.zone}', {}))
    enabled = zone_values['app.hoover'] == 'true' and zone_values['zone.enabled'] == 'true'
    source = site_config.read_source_ini(hoover.source_ini, check_paths=False) if hoover.source_ini else None
    return Target(site=site, hoover=hoover, values=values, revision=revision or resolve_revision(), nfs=nfs or {},
                  source=source, enabled=enabled)


# ----------------------------------------------------------------------------------------------------------------------
# Small builders
# ----------------------------------------------------------------------------------------------------------------------

def value(name, v):
    return {'name': name, 'value': v}


def from_secret(name, key, secret='hoover-runtime'):
    return {'name': name, 'valueFrom': {'secretKeyRef': {'name': secret, 'key': key}}}


def quantity(text, default):
    """A Compose size as a Kubernetes quantity: 6144M is 6144Mi, 6G is 6Gi, 2gb is 2Gi."""
    m = re.fullmatch(r'(\d+)\s*([kKmMgGtT])?[bB]?', str(text or '').strip())
    if not m:
        return default
    return m.group(1) + {'k': 'Ki', 'm': 'Mi', 'g': 'Gi', 't': 'Ti', '': ''}[(m.group(2) or '').lower()]


def kube_name(name):
    return NAMES.get(name, name)


def tier(target, claim):
    """The storage tier of a claim on the home node: the first preferred tier that the node has."""
    tiers = target.site.nodes[target.hoover.home_node].storage_tiers
    preferred = ('nvme', 'ssd', 'hdd') if claim in FAST else ('hdd', 'ssd', 'nvme')
    for name in preferred:
        if name in tiers:
            return name
    raise RenderError(f'the home node {target.hoover.home_node} has no storage tier for the claim {claim}.')


def claim_spec(target, claim, size=None):
    return {'accessModes': ['ReadWriteOnce'], 'storageClassName': f'{tier(target, claim)}-ext4',
            'resources': {'requests': {'storage': size or target.values[f'volume.{claim}']}}}


def claim(target, name):
    return {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': name, 'namespace': target.ns},
            'spec': claim_spec(target, name)}


def home_selector(target):
    return {'kubernetes.io/hostname': target.hoover.home_node}


def pod_spec(target, containers, pod_volumes=(), runtime=None, grace=30, init=(), node=None, security=None):
    spec = {'enableServiceLinks': False, 'automountServiceAccountToken': False, 'terminationGracePeriodSeconds': grace,
            'containers': containers}
    if runtime:
        spec['runtimeClassName'] = runtime
    if pod_volumes:
        spec['volumes'] = list(pod_volumes)
    if init:
        spec['initContainers'] = list(init)
    if node:
        spec['nodeSelector'] = node
    if security:
        spec['securityContext'] = security
    return spec


def workload(target, kind, name, spec, replicas=1, labels=None, spread=False, claims=(), annotations=None):
    labels = {'app.kubernetes.io/name': name, PART: name, **(labels or {})}
    if spread:
        spec['topologySpreadConstraints'] = [{'maxSkew': 1, 'topologyKey': 'kubernetes.io/hostname', 'whenUnsatisfiable': 'ScheduleAnyway',
                                              'labelSelector': {'matchLabels': {'app.kubernetes.io/name': name}}}]
    template = {'metadata': {'labels': labels}, 'spec': spec}
    if annotations:
        template['metadata']['annotations'] = annotations
    body = {'replicas': replicas if target.enabled else 0, 'selector': {'matchLabels': {'app.kubernetes.io/name': name}}, 'template': template}
    if kind == 'Deployment':
        body['strategy'] = {'type': 'Recreate'}
    else:
        body['serviceName'] = name
        body['podManagementPolicy'] = 'Parallel'
        if claims:
            body['volumeClaimTemplates'] = [{'metadata': {'name': c}, 'spec': claim_spec(target, c)} for c in claims]
    return {'apiVersion': 'apps/v1', 'kind': kind, 'metadata': {'name': name, 'namespace': target.ns,
                                                                'labels': {'app.kubernetes.io/name': name, PART: name}},
            'spec': body}


def service(target, name, port_list, selector=None):
    return {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': name, 'namespace': target.ns},
            'spec': {'selector': {'app.kubernetes.io/name': selector or name},
                     'ports': [{'name': f'p{p}', 'port': p, 'targetPort': p} for p in port_list]}}


def external(target, name):
    return {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': name, 'namespace': target.ns},
            'spec': {'type': 'ExternalName', 'externalName': f'{name}.{target.zone}.svc.cluster.local'}}


def config_map(target, name, data):
    return {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': name, 'namespace': target.ns}, 'data': data}


def ports(name, service_def):
    found = []
    for p in service_def.get('ports') or []:
        text = str(p.get('target') if isinstance(p, dict) else p)
        found.append(int(text.rsplit(':', 1)[-1].split('/')[0]))
    return found or PORTS.get(name, [])


def probe(service_def):
    test = (service_def.get('healthcheck') or {}).get('test')
    if not test or (isinstance(test, list) and test[0] == 'NONE'):
        return None
    if isinstance(test, str):
        command = ['sh', '-c', test]
    else:
        command = ['sh', '-c', test[1]] if test[0] == 'CMD-SHELL' else list(test[1:])
    return {'exec': {'command': command}, 'periodSeconds': 15, 'timeoutSeconds': 13, 'failureThreshold': 6}


# ----------------------------------------------------------------------------------------------------------------------
# Volumes
# ----------------------------------------------------------------------------------------------------------------------

def dataset_mounts(target):
    """The dataset mounts: name, container path, writable flag and the pod volume.

    A migrated install keeps the container paths of its source ini, because the dataset rows store them. Its
    read-only folders stay in place as host folders of the home node. Its writable folders are claims, which the
    migration fills. A new install of a single-node site has the claims dataset-testdata and dataset-uploads below
    /data, because its pods share the one node and need no NFS server. Another install has the NFS folders of
    ../platform/hoover-data/hoover_data.py below /data.
    """
    if target.source:
        out = []
        for m in target.source.dataset_mounts:
            volume = ({'persistentVolumeClaim': {'claimName': f"dataset-{m['name'].replace('_', '-')}"}} if m['writable'] else
                      {'hostPath': {'path': m['host_path'], 'type': 'Directory'}})
            out.append({'name': m['name'], 'path': m['container_path'], 'writable': m['writable'], 'volume': volume})
        return out
    if target.site.single:
        return [{'name': n, 'path': f'/data/{n}', 'writable': w,
                 'volume': {'persistentVolumeClaim': {'claimName': f'dataset-{n}', 'readOnly': not w}}}
                for n, w in (('testdata', False), ('uploads', True))]
    data_nodes = [n.name for n in target.site.with_role('data')]
    node = target.hoover.home_node if target.hoover.home_node in data_nodes else data_nodes[0]
    server = target.nfs.get(node)
    if not server:
        raise RenderError(f'the NFS Service address of the data node {node} is unknown. Run '
                          'k3s/platform/hoover-data/install-hoover-data.py, or give the address to the render.')
    rows = [('testdata', f'/{target.zone}/testdata', False), ('uploads', f'/{target.zone}/uploads', True)]
    return [{'name': n, 'path': f'/data/{n}', 'writable': w, 'volume': {'nfs': {'server': server, 'path': e, 'readOnly': not w}}}
            for n, e, w in rows]


def volumes(target, name, service_def, mounts):
    """The pod volumes, the container mounts and the claims of a service.

    - A bind of a source folder of a built service is left out: the image of the same revision holds it.
    - A key file under /run/secrets is an item of the Secret hoover-runtime (SECRET_FILES), or absent.
    - A bind of a configuration file or folder of the source tree is a ConfigMap (CONFIG_FILES, CONFIG_DIRS).
    - A volume folder is a claim (CLAIMS) or an emptyDir. The zone layout has no store folders, so the operations
      worker mounts no store there.
    - /control is the chat_control_dir of the site file, as a read-only host folder, or absent.
    - The worker, the operations worker and the website get the dataset mounts.
    Any other bind stops the render.
    """
    pod, mounted, claims = [], [], []
    names = set()

    def add(volume_name, volume, mount):
        if volume_name not in names:
            pod.append({'name': volume_name, **volume})
            names.add(volume_name)
        mounted.append({'name': volume_name, **mount})

    root = '/volumes/'
    for spec in service_def.get('volumes') or []:
        source, target_path, read_only = compose.volume_parts(spec)
        mount = {'mountPath': target_path, **({'readOnly': True} if read_only else {})}
        if target_path in SOURCE_BINDS and SERVICES[name].get('image'):
            continue
        if target_path.startswith('/run/secrets/'):
            item = SECRET_FILES.get(target_path.rsplit('/', 1)[1])
            if item:
                add(f'secret-{item}', {'secret': {'secretName': 'hoover-runtime', 'items': [{'key': item, 'path': 'value'}]}},
                    {'mountPath': target_path, 'subPath': 'value', 'readOnly': True})
            continue
        if target_path in CONFIG_FILES:
            config, item = CONFIG_FILES[target_path]
            add(config, {'configMap': {'name': config}}, {'mountPath': target_path, 'subPath': item, 'readOnly': True})
            continue
        if target_path in CONFIG_DIRS:
            add(CONFIG_DIRS[target_path], {'configMap': {'name': CONFIG_DIRS[target_path]}}, {'mountPath': target_path, 'readOnly': True})
            continue
        if target_path == '/control':
            if target.hoover.chat_control_dir:
                add('chat-control', {'hostPath': {'path': target.hoover.chat_control_dir, 'type': 'Directory'}},
                    {'mountPath': '/control', 'readOnly': True})
            continue
        if source.startswith(root):
            folder = source[len(root):].split('/')[0]
            if folder in UNUSED:
                continue
            claim_name = CLAIMS.get(folder)
            if target_path.startswith('/stores/') and not target.local:
                continue
            if claim_name and (target.local or claim_name in ZONE_CLAIMS):
                if claim_name == 'worker-temp-files' and name == 'hoover4-worker':
                    if target.local:
                        claims.append(claim_name)
                        mounted.append({'name': claim_name, **mount})
                    else:
                        # The worker pods of the zone layout spread over nodes with different tiers. A pod keeps
                        # its plan files until it ends, and a new pod has a new name, so its plans move to it.
                        add(claim_name, {'emptyDir': {}}, mount)
                else:
                    add(claim_name, {'persistentVolumeClaim': {'claimName': claim_name}}, mount)
            else:
                add(f"cache-{folder.replace('_', '-')}", {'emptyDir': {}}, mount)
            continue
        raise RenderError(f'the Compose service {name} binds {source} at {target_path}, and manifests.py has no rule for it.')
    if name in ('hoover4-worker', 'hoover4-ops', 'hoover4-website'):
        for m in mounts:
            volume_name = f"data-{m['name'].replace('_', '-')}"
            add(volume_name, m['volume'], {'mountPath': m['path'], **({} if m['writable'] else {'readOnly': True})})
    if service_def.get('shm_size'):
        add('shm', {'emptyDir': {'medium': 'Memory', 'sizeLimit': quantity(service_def['shm_size'], '1Gi')}}, {'mountPath': '/dev/shm'})
    for i, spec in enumerate(service_def.get('tmpfs') or []):
        size = re.search(r'size=(\w+)', spec)
        add(f'tmpfs-{i}', {'emptyDir': {'medium': 'Memory', 'sizeLimit': quantity(size.group(1) if size else '', '256Mi')}},
            {'mountPath': spec.split(':')[0]})
    return pod, mounted, claims


# ----------------------------------------------------------------------------------------------------------------------
# Containers
# ----------------------------------------------------------------------------------------------------------------------

def store_env(target):
    """The store addresses and the storage identity of the installation."""
    env = {'CLICKHOUSE_URL': 'http://clickhouse:8123', 'MANTICORE_HOST': 'manticore', 'MANTICORE_URL': 'http://manticore:9308',
           'MANTICORE_VECTORS_HOST': 'manticore-vectors', 'MANTICORE_VECTORS_URL': 'http://manticore-vectors:9308',
           'S3_ENDPOINT': 'http://garage:3900', 'TEMPORAL_HTTP_URL': 'http://temporal:7243',
           'HOOVER4_HISTORY_SOURCE': target.hoover.history_source}
    env.update(target.hoover.identity())
    # The telemetry of the agent servers writes into CLICKHOUSE_DATABASE.
    env['CLICKHOUSE_DATABASE'] = f'{target.hoover.clickhouse_database_prefix}_Processing'
    return env


def store_secrets(target, service_key, wanted):
    """The store credential variables of one service, each from a Secret.

    The local layout has one set of credentials (LOCAL_CREDENTIALS). The zone layout has a ClickHouse and Manticore
    user and a Garage key for each service (stores/service_users.py).
    """
    if target.local:
        return [from_secret(k, LOCAL_CREDENTIALS[k]) for k in STORE_CREDENTIALS if k in wanted]
    used = service_users.SERVICES.get(service_key, {})
    env = []
    if 'clickhouse' in used:
        env += [value('CLICKHOUSE_USER', service_users.user(target.zone, service_key)), from_secret('CLICKHOUSE_PASSWORD', f'clickhouse-{service_key}')]
    if 'manticore' in used:
        env += [value('MANTICORE_USER', service_users.user(target.zone, service_key)), from_secret('MANTICORE_PASSWORD', f'manticore-{service_key}')]
    if 'garage' in used:
        env += [from_secret('S3_ACCESS_KEY', f's3-access-key-{service_key}'), from_secret('S3_SECRET_KEY', f's3-secret-key-{service_key}')]
    return env


def container(name, service_def, image, env, memory, mounted, cpu=None, command=None, extra_env=()):
    # A Secret value in extra_env replaces the Compose value of the same name.
    secret = {e['name'] for e in extra_env}
    c = {'name': name, 'image': image, 'imagePullPolicy': 'IfNotPresent',
         'env': [value(k, str(v)) for k, v in sorted(env.items()) if k not in secret and k not in STORE_CREDENTIALS] + list(extra_env),
         'ports': [{'name': f'p{p}', 'containerPort': p} for p in ports(name, service_def)],
         'resources': {'requests': {'cpu': '50m', 'memory': '128Mi'},
                       'limits': {'memory': memory, **({'cpu': str(cpu)} if cpu else {})}},
         'volumeMounts': mounted}
    if command is not None:
        c['command'] = command
    elif service_def.get('entrypoint'):
        c['command'] = service_def['entrypoint'] if isinstance(service_def['entrypoint'], list) else ['sh', '-c', service_def['entrypoint']]
        if service_def.get('command'):
            c['args'] = service_def['command'] if isinstance(service_def['command'], list) else ['sh', '-c', service_def['command']]
    elif service_def.get('command'):
        cmd = service_def['command']
        c['args'] = cmd if isinstance(cmd, list) else ['sh', '-c', cmd]
    if service_def.get('working_dir'):
        c['workingDir'] = service_def['working_dir']
    check = probe(service_def)
    if check:
        c['readinessProbe'] = check
    security = {}
    if service_def.get('read_only'):
        security['readOnlyRootFilesystem'] = True
    if service_def.get('cap_add'):
        security['capabilities'] = {'add': sorted(service_def['cap_add'])}
    if service_def.get('user'):
        uid, _, gid = str(service_def['user']).partition(':')
        security['runAsUser'] = int(uid)
        if gid:
            security['runAsGroup'] = int(gid)
    if security:
        c['securityContext'] = security
    if not c['ports']:
        del c['ports']
    return c


def limits(service_def):
    deploy_limits = ((service_def.get('deploy') or {}).get('resources') or {}).get('limits') or {}
    memory = quantity(service_def.get('mem_limit') or deploy_limits.get('memory'), '512Mi')
    cpus = service_def.get('cpus') or deploy_limits.get('cpus')
    return memory, (cpus if str(cpus or '0') not in ('0', '0.0', '') else None)


def image_of(target, name, service_def):
    key = SERVICES[name].get('image')
    if key:
        return f'{REGISTRY}/hoover-{key}:{image_tag(target.revision)}'
    ref = service_def.get('image')
    if not ref:
        raise RenderError(f'the Compose service {name} has no image and no image key in SERVICES.')
    first = ref.split('/')[0]
    return ref if '/' in ref and '.' in first else f'docker.io/{ref if "/" in ref else "library/" + ref}'


def image_tag(revision):
    """The image tag of a source commit. ../images/build-hoover.py tags each image with it."""
    return revision[:12]


def owner_init(target, store, image, claim_name, mount_path, deploy, mounts_config):
    """The init container that gives a store folder its owner, as deploy.py chown_command does for Compose."""
    row = next((r for r in deploy.VOLUMES if r.side == 'main' and CLAIMS.get(r.name) == claim_name), None)
    if row is None or (row.uid == 0 and row.gid == 0):
        return None
    if store in ('manticore', 'manticore-vectors'):
        script = ('if [ ! -e /d/auth.json ]; then cp /seed/auth.json.seed /d/auth.json; fi; '
                  'chmod 600 /d/auth.json; chown 999:999 /d /d/auth.json')
        extra = [{'name': 'manticore-seed', 'mountPath': '/seed', 'readOnly': True}]
        mounts_config.add('manticore-seed')
    else:
        script = f'chown {row.uid}:{row.gid} /d'
        extra = []
    return {'name': 'owner', 'image': image, 'command': ['sh', '-ec', script], 'securityContext': {'runAsUser': 0},
            'resources': {'requests': {'cpu': '10m', 'memory': '16Mi'}, 'limits': {'memory': '128Mi'}},
            'volumeMounts': [{'name': claim_name, 'mountPath': '/d'}, *extra]}


# ----------------------------------------------------------------------------------------------------------------------
# The translation
# ----------------------------------------------------------------------------------------------------------------------

def check_services(tree):
    """Stop on a Compose service of either side that SERVICES does not classify."""
    found = compose.compose_service_names(tree)
    unknown = {n: files for n, files in found.items() if n not in SERVICES}
    if unknown:
        listed = '; '.join(f'{n} in {", ".join(f)}' for n, f in sorted(unknown.items()))
        raise RenderError(f'the Compose files have services without a cluster form: {listed}. Add each one to SERVICES '
                          'in k3s/hoover/manifests.py and to the parity table in k3s/Compose_Parity.md.')
    return found


def translated(target, services, mounts, deploy):
    """The objects of the Compose services that the installation runs."""
    items, configs = [], set()
    public = target.site.with_role('public')[0].name
    common = {**store_env(target), 'HOOVER4_DATASET_MOUNTS': json.dumps(
        [{'name': m['name'], 'path': m['path'], 'writable': m['writable']} for m in mounts], separators=(',', ':')),
        'DATASETS_MOUNT_PATH': mounts[0]['path']}
    if target.hoover.chat_control_dir:
        common['HOOVER4_CHAT_CONTROL_DIR'] = '/control'
    python = ['/opt/pysetup/.venv/bin/python3', 'main.py']
    memory_table = {s.key.removeprefix('memory.hoover.'): target.values[s.key] for s in operator_settings.REGISTRY.values()
                    if s.key.startswith('memory.hoover.')}
    for name in SERVICES:
        role = SERVICES[name]['role']
        if name not in services or role in ('gpu', 'excluded'):
            continue
        if role in ('store', 'store-init', 'ui') and not target.local:
            # The zone layout has no operator user of its stores for the interfaces.
            continue
        if role == 'temporal-store' and not target.cassandra:
            continue
        if role == 'temporal' and not target.cassandra:
            continue
        svc = services[name]
        app = role in ('app', 'ui') or name == 'temporal'
        env = {k: v for k, v in svc.get('environment', {}).items()}
        if app:
            env.update(common if role == 'app' else {})
        pod_volumes, mounted, claims = volumes(target, name, svc, mounts if role == 'app' else [])
        configs |= {v['configMap']['name'] for v in pod_volumes if 'configMap' in v}
        memory, cpu = limits(svc)
        if name in MEASURED and not target.local:
            memory = memory_table[MEASURED[name]]
        img = image_of(target, name, svc)
        key = name.removeprefix('hoover4-')
        credentials = store_secrets(target, key, set(svc.get('environment', {})) | (set(STORE_CREDENTIALS[:6]) if role == 'app' else set()))
        node = home_selector(target) if target.local and (role in ('store', 'store-init', 'temporal-store') or
                                                          any('persistentVolumeClaim' in v for v in pod_volumes) or claims) else None
        if name == 'hoover4-website':
            env.update({'IP': '0.0.0.0', 'PORT': '8080', 'HOOVER4_SITE_URL': f'https://{target.host}',
                        'HOOVER4_ADMIN_GROUPS': target.values['website.admin_groups']})
            svc = {**svc, 'ports': ['8080']}
            web = container('hoover-website', svc, img, env, memory, mounted, command=['/app/server'],
                            extra_env=[*credentials, from_secret('HOOVER4_PROXY_SECRET', 'proxy-secret')])
            web['workingDir'] = '/app'
            web['readinessProbe'] = {'tcpSocket': {'port': 8080}, 'periodSeconds': 2, 'failureThreshold': 3}
            items += [workload(target, 'Deployment', 'hoover-website', pod_spec(target, [web], pod_volumes, node=node)),
                      service(target, 'hoover-website', [8080])]
            continue
        if name == 'hoover4-worker':
            grace = int(env.get('HOOVER4_WORKER_GRACEFUL_SHUTDOWN_SECONDS', '60')) + 30
            env['PATH'] = '/opt/pysetup/.venv/bin:/usr/local/bin:/usr/bin:/bin'
            migrate = container('migrate', svc, img, env, memory_table['migrate'], [m for m in mounted if m['name'] not in claims],
                                command=python + ['migrate'], extra_env=credentials)
            migrate.pop('readinessProbe', None)
            migrate['workingDir'] = '/app'
            sandbox = target.values['workers.parser_sandbox']
            tuner = target.values['workers.slot_tuner']
            pod_env = [value('HOOVER4_WORKERS', WORKERS), {'name': 'HOOVER4_HOST_QUEUE', 'valueFrom': {'fieldRef': {'fieldPath': 'metadata.name'}}}]
            if sandbox != 'off':
                pod_env.append(value('HOOVER4_PARSER_SANDBOX', sandbox))
            if tuner != 'fixed':
                pod_env += [value('HOOVER4_SLOT_TUNER', tuner), value('HOOVER4_TUNER_TARGET_MEMORY', target.values['workers.tuner_target_memory']),
                            value('HOOVER4_TUNER_TARGET_CPU', target.values['workers.tuner_target_cpu'])]
            workers = container('hoover-workers', svc, img, env, quantity(f"{target.budget['worker_memory_mib']}M", memory), mounted,
                                cpu=target.budget['worker_cpus'], command=python + ['worker'], extra_env=[*credentials, *pod_env])
            workers['workingDir'] = '/app'
            single_mounts = [m for m in mounted if m['name'] not in claims]
            single_volumes = list(pod_volumes) + [{'name': 'worker-temp-files', 'emptyDir': {}}]
            single_mounts.append({'name': 'worker-temp-files', 'mountPath': '/tmp/hoover4'})
            singles = container('hoover-singletons', svc, img, env, '3Gi', single_mounts, cpu=2, command=python + ['worker'],
                                extra_env=[*credentials, value('HOOVER4_WORKERS', SINGLETONS)])
            singles['workingDir'] = '/app'
            sandbox_env = [value('HOOVER4_PARSER_SANDBOX', sandbox)] if sandbox != 'off' else []
            singles['env'] += sandbox_env
            items += [workload(target, 'Deployment', 'hoover-singletons',
                               pod_spec(target, [singles], single_volumes, runtime='kata', grace=grace, init=[migrate], node=node)),
                      workload(target, 'StatefulSet' if target.local else 'Deployment', 'hoover-workers',
                               pod_spec(target, [workers], pod_volumes, runtime='kata', grace=grace, node=node),
                               replicas=target.budget['worker_pods'], labels={'hoover.dev/placement': 'any'}, spread=node is None,
                               claims=claims)]
            if target.local:
                # The headless Service gives the StatefulSet its pod names.
                items.append(service(target, 'hoover-workers', []))
                items[-1]['spec']['clusterIP'] = 'None'
            continue
        if name == 'hoover4-ops':
            grace = int(env.get('HOOVER4_WORKER_GRACEFUL_SHUTDOWN_SECONDS', '60')) + 30
            ops = container('hoover-operations', svc, img, env, memory, mounted, cpu=cpu, command=python + ['worker', 'operations'],
                            extra_env=credentials)
            ops['workingDir'] = '/app'
            items.append(workload(target, 'Deployment', 'hoover-operations',
                                  pod_spec(target, [ops], pod_volumes, runtime='kata', grace=grace, node=node)))
            continue
        if name == 'garage-init':
            job = container(name, svc, img, env, memory, mounted, extra_env=credentials)
            job.pop('readinessProbe', None)
            spec = pod_spec(target, [job], pod_volumes, node=node)
            spec['restartPolicy'] = 'OnFailure'
            items.append({'apiVersion': 'batch/v1', 'kind': 'Job', 'metadata': {'name': f'garage-init-{image_tag(target.revision)[:12]}', 'namespace': target.ns,
                                                                              'labels': {'app.kubernetes.io/name': 'garage-init', PART: 'garage-init'}},
                          'spec': {'backoffLimit': 6, 'ttlSecondsAfterFinished': 86400,
                                   'template': {'metadata': {'labels': {'app.kubernetes.io/name': 'garage-init'}}, 'spec': spec}}})
            continue
        labels = {'hoover.dev/egress': 'internet'} if name in INTERNET else None
        if role in ('store', 'temporal-store'):
            labels = {'hoover.dev/store': name}
        c = container(name, svc, img, env, memory, mounted, cpu=cpu, extra_env=credentials)
        init = []
        if role in ('store', 'temporal-store'):
            for m in pod_volumes:
                if 'persistentVolumeClaim' in m:
                    path = next(x['mountPath'] for x in mounted if x['name'] == m['name'])
                    found = owner_init(target, name, img, m['name'], path, deploy, configs)
                    if found:
                        init.append(found)
            if any(i['volumeMounts'][-1]['name'] == 'manticore-seed' for i in init):
                pod_volumes.append({'name': 'manticore-seed', 'configMap': {'name': 'manticore-seed'}})
        selector = node if role in ('store', 'temporal-store') or node else None
        if name in INTERNET:
            selector = {'kubernetes.io/hostname': public}
        spec = pod_spec(target, [c], pod_volumes, node=selector, init=init)
        kind = 'StatefulSet' if role in ('store', 'temporal-store') else 'Deployment'
        items.append(workload(target, kind, kube_name(name), spec, labels=labels,
                              annotations={'hoover.dev/config': config_hash(target, svc)} if name == 'temporal' else None))
        if ports(name, svc):
            items.append(service(target, kube_name(name), ports(name, svc)))
    return items, configs


def config_hash(target, svc):
    return hashlib.sha256(json.dumps(svc, sort_keys=True, default=str).encode()).hexdigest()[:12]


def config_maps(target, deploy, cfg, wanted):
    tree = Path(target.tree)
    docker = tree / 'main_services/ops/docker'
    tasks = tree / 'main_services/processing/tasks'
    data = {
        'tika-config': {'tika-config.json': deploy.render_tika_config(cfg)},
        'mirror': {'temporal_readiness.py': (tasks / 'temporal_readiness.py').read_text(),
                   'signal_calibration.json': (tasks / 'signal_calibration.json').read_text(),
                   'temporal_ready.rs': (tree / 'website/backend/src/temporal_ready.rs').read_text()},
        'clickhouse-config': {'config-override.xml': deploy.render_clickhouse_config(cfg),
                              'users-override.xml': (docker / 'clickhouse-users-override.xml').read_text()},
        'cassandra-entrypoint': {'entrypoint.sh': (docker / 'cassandra-entrypoint.sh').read_text()},
        'garage-config': {'garage.toml': (docker / 'garage/garage.toml').read_text()},
        'manticore-seed': {'auth.json.seed': (docker / 'manticore/auth.json.seed').read_text()},
        'temporal-dynamicconfig': {'docker.yaml': (docker / 'temporal-dynamicconfig/docker.yaml').read_text(),
                                   'generated.yaml': deploy.render_temporal_dynamic_config(
                                       cfg, (docker / 'temporal-dynamicconfig/docker.yaml').read_text())},
    }
    return [config_map(target, name, data[name]) for name in sorted(wanted)]


def temporal_retention(target, cfg, image):
    """The job that sets the retention of the default namespace, as deploy.py does after each Compose start."""
    retention = cfg.get('main_services', 'temporal_retention')
    script = ('until temporal operator namespace describe -n default --address temporal:7233 >/dev/null 2>&1; do sleep 5; done; '
              f'temporal operator namespace update -n default --retention {retention} --address temporal:7233')
    c = {'name': 'retention', 'image': image, 'command': ['sh', '-ec', script],
         'resources': {'requests': {'cpu': '10m', 'memory': '32Mi'}, 'limits': {'memory': '256Mi'}}}
    spec = pod_spec(target, [c])
    spec['restartPolicy'] = 'OnFailure'
    name = 'temporal-retention-' + hashlib.sha256(retention.encode()).hexdigest()[:8]
    return {'apiVersion': 'batch/v1', 'kind': 'Job', 'metadata': {'name': name, 'namespace': target.ns,
                                                                  'labels': {'app.kubernetes.io/name': 'temporal-retention', PART: 'temporal-retention'}},
            'spec': {'backoffLimit': 20, 'ttlSecondsAfterFinished': 86400,
                     'template': {'metadata': {'labels': {'app.kubernetes.io/name': 'temporal-retention'}}, 'spec': spec}}}


def temporal_pg(target, shards):
    """Temporal on the PostgreSQL of the zone, the backend of an existing remote zone."""
    prefix = target.zone.replace('-', '_')
    env = [value('DB', 'postgres12'), value('DB_PORT', '5432'), value('POSTGRES_SEEDS', f'postgresql.{target.zone}.svc.cluster.local'),
           value('POSTGRES_USER', f'{prefix}_temporal'), from_secret('POSTGRES_PWD', 'temporal-db-password'),
           value('DBNAME', f'{prefix}_temporal'), value('VISIBILITY_DBNAME', f'{prefix}_temporal_visibility'),
           # setup.py creates both databases with a role that cannot create databases. The shard count is fixed after the
           # first start.
           value('SKIP_DB_CREATE', 'true'), value('NUM_HISTORY_SHARDS', str(shards)),
           value('DEFAULT_NAMESPACE', 'default'), value('DEFAULT_NAMESPACE_RETENTION', target.values['main_services.temporal_retention']),
           value('BIND_ON_IP', '0.0.0.0'), value('TEMPORAL_BROADCAST_ADDRESS', '127.0.0.1')]
    c = {'name': 'temporal', 'image': TEMPORAL_PG, 'env': env, 'ports': [{'name': 'grpc', 'containerPort': 7233}, {'name': 'http', 'containerPort': 7243}],
         'resources': {'requests': {'cpu': '50m', 'memory': '128Mi'}, 'limits': {'memory': target.values['memory.hoover.temporal'], 'cpu': '2'}},
         'readinessProbe': {'tcpSocket': {'port': 7233}, 'periodSeconds': 2, 'failureThreshold': 3}}
    return [workload(target, 'Deployment', 'temporal', pod_spec(target, [c])), service(target, 'temporal', [7233, 7243])]


def proxy(target):
    """oauth2-proxy with the alpha configuration, which can add a header from a file."""
    issuer = f'https://id.{target.zone}.{target.site.suffix}/realms/opendesk'
    # A header claim can name only a session field. userIDClaim puts opendesk_username into the session field `email`,
    # so X-Forwarded-User reads that field. The session keeps no mail address, so the email header has no source: the
    # claim name below gives no value, and the entry only removes a value that the client sent.
    headers = [('X-Forwarded-User', {'claim': 'email'}), ('X-Forwarded-Preferred-Username', {'claim': 'preferred_username'}),
               ('X-Forwarded-Email', {'claim': 'mail_not_in_session'}), ('X-Forwarded-Groups', {'claim': 'groups'}),
               ('X-Hoover-Proxy', {'fromFile': '/secrets/proxy-secret'})]
    alpha = {
        'upstreamConfig': {'upstreams': [{'id': 'website', 'path': '/', 'uri': 'http://hoover-website:8080'}]},
        # preserveRequestValue false replaces a client value of the same header, so a browser cannot send its own identity.
        'injectRequestHeaders': [{'name': n, 'preserveRequestValue': False, 'values': [v]} for n, v in headers],
        'providers': [{'id': 'keycloak', 'provider': 'oidc', 'clientID': 'opendesk-hoover', 'clientSecretFile': '/secrets/client-secret',
                       'useSystemTrustStore': True, 'scope': 'openid',
                       'oidcConfig': {'issuerURL': issuer, 'emailClaim': 'email', 'groupsClaim': 'groups', 'userIDClaim': 'opendesk_username',
                                      'audienceClaims': ['aud', 'azp']}}],
        'server': {'BindAddress': '0.0.0.0:4180'},
    }
    args = ['--alpha-config=/config/alpha.yaml', '--email-domain=*', f'--redirect-url=https://{target.host}/oauth2/callback',
            '--cookie-secure=true', '--cookie-name=_hoover_proxy', '--reverse-proxy=true', '--skip-provider-button=true',
            f'--whitelist-domain=.{target.zone}.{target.site.suffix}', '--silence-ping-logging=true',
            # oauth2-proxy 7.12 has no OIDC back-channel logout. The proxy refreshes its tokens with Keycloak one minute
            # after the last refresh. Keycloak refuses the refresh after the user logged out, and the proxy then drops
            # its session.
            '--cookie-refresh=1m', '--cookie-expire=16h']
    c = {'name': 'oauth2-proxy', 'image': OAUTH2_PROXY, 'args': args,
         'env': [from_secret('OAUTH2_PROXY_COOKIE_SECRET', 'cookie-secret', 'oauth2-proxy')],
         'ports': [{'name': 'http', 'containerPort': 4180}],
         'resources': {'requests': {'cpu': '50m', 'memory': '32Mi'}, 'limits': {'memory': target.values['memory.hoover.oauth2-proxy'], 'cpu': '1'}},
         'readinessProbe': {'httpGet': {'path': '/ping', 'port': 4180}, 'periodSeconds': 2},
         'volumeMounts': [{'name': 'config', 'mountPath': '/config', 'readOnly': True},
                          {'name': 'secrets', 'mountPath': '/secrets', 'readOnly': True}]}
    vols = [{'name': 'config', 'configMap': {'name': 'oauth2-proxy'}}, {'name': 'secrets', 'secret': {'secretName': 'oauth2-proxy'}}]
    return [config_map(target, 'oauth2-proxy', {'alpha.yaml': json.dumps(alpha, indent=1)}),
            workload(target, 'Deployment', 'oauth2-proxy', pod_spec(target, [c], vols)), service(target, 'oauth2-proxy', [4180])]


def network(target):
    """The ingress and egress policies of the Hoover namespace.

    Egress is closed by default. Every pod reaches the cluster DNS and the pods of its namespace. In the zone layout
    every pod except the internet services reaches the stores and PostgreSQL in the zone namespace, and the browser
    server reaches the HTTP ports of ClickHouse and Garage. In the local layout the stores are pods of the namespace,
    and the internet services reach no store pod except the browser server, which reaches ClickHouse and Garage.
    oauth2-proxy reaches the public nodes on 443 for the OIDC issuer. The forwarder gpu reaches the GPU proxy. The
    internet services reach public addresses otherwise.
    """
    ns = target.ns

    def policy(name, spec):
        return {'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy', 'metadata': {'name': name, 'namespace': ns}, 'spec': spec}
    zone_ns = {'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': target.zone}}}
    dns = {'to': [{'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'kube-system'}},
                   'podSelector': {'matchLabels': {'k8s-app': 'kube-dns'}}}],
           'ports': [{'port': 53, 'protocol': 'UDP'}, {'port': 53, 'protocol': 'TCP'}]}
    frontend = [n.public_address or n.vpn_address for n in target.site.with_role('public') if n.public_address or n.vpn_address]
    items = [
        policy('website-from-proxy', {'podSelector': {'matchLabels': {'app.kubernetes.io/name': 'hoover-website'}}, 'policyTypes': ['Ingress'],
                                      'ingress': [{'from': [{'podSelector': {'matchLabels': {'app.kubernetes.io/name': 'oauth2-proxy'}}}],
                                                   'ports': [{'port': 8080}]}]}),
        # Workers and dependencies take connections only from the namespace. The proxy also takes them from the ingress.
        policy('namespace-only', {'podSelector': {'matchExpressions': [{'key': 'app.kubernetes.io/name', 'operator': 'NotIn',
                                                                        'values': ['hoover-website', 'oauth2-proxy']}]},
                                  'policyTypes': ['Ingress'], 'ingress': [{'from': [{'podSelector': {}}]}]}),
        policy('proxy-from-ingress', {'podSelector': {'matchLabels': {'app.kubernetes.io/name': 'oauth2-proxy'}}, 'policyTypes': ['Ingress'],
                                      'ingress': [{'from': [{'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'ingress'}}}],
                                                   'ports': [{'port': 4180}]}]}),
    ]
    if target.local:
        # The internet services reach no pod of the namespace except the services that they call.
        items.append(policy('egress-base', {'podSelector': {'matchExpressions': [{'key': 'hoover.dev/egress', 'operator': 'DoesNotExist'}]},
                                            'policyTypes': ['Egress'], 'egress': [dns, {'to': [{'podSelector': {}}]}]}))
        items.append(policy('egress-internet-local', {'podSelector': {'matchLabels': {'hoover.dev/egress': 'internet'}}, 'policyTypes': ['Egress'],
                                                      'egress': [dns, {'to': [{'podSelector': {'matchExpressions': [
                                                          {'key': 'hoover.dev/store', 'operator': 'DoesNotExist'}]}}]}]}))
        items.append(policy('egress-browser-stores', {'podSelector': {'matchLabels': {'app.kubernetes.io/name': 'hoover4-mcp-browser'}},
                                                      'policyTypes': ['Egress'],
                                                      'egress': [{'to': [{'podSelector': {'matchLabels': {'hoover.dev/store': 'clickhouse'}}}], 'ports': [{'port': 8123}]},
                                                                 {'to': [{'podSelector': {'matchLabels': {'hoover.dev/store': 'garage'}}}], 'ports': [{'port': 3900}]}]}))
    else:
        items += [
            policy('egress-base', {'podSelector': {}, 'policyTypes': ['Egress'], 'egress': [dns, {'to': [{'podSelector': {}}]}]}),
            policy('egress-stores', {'podSelector': {'matchExpressions': [{'key': 'hoover.dev/egress', 'operator': 'DoesNotExist'}]},
                                     'policyTypes': ['Egress'],
                                     'egress': [{'to': [{**zone_ns, 'podSelector': {'matchExpressions': [
                                         {'key': 'hoover.dev/store', 'operator': 'In', 'values': list(ZONE_STORES)}]}}]}]}),
            policy('egress-browser-stores', {'podSelector': {'matchLabels': {'app.kubernetes.io/name': 'hoover4-mcp-browser'}},
                                             'policyTypes': ['Egress'],
                                             'egress': [{'to': [{**zone_ns, 'podSelector': {'matchLabels': {'hoover.dev/store': 'clickhouse'}}}],
                                                         'ports': [{'port': 8123}]},
                                                        {'to': [{**zone_ns, 'podSelector': {'matchLabels': {'hoover.dev/store': 'garage'}}}],
                                                         'ports': [{'port': 3900}]}]}),
        ]
    items += [
        policy('egress-oidc', {'podSelector': {'matchLabels': {'app.kubernetes.io/name': 'oauth2-proxy'}}, 'policyTypes': ['Egress'],
                               'egress': [{'to': [{'ipBlock': {'cidr': f'{a}/32'}} for a in frontend], 'ports': [{'port': 443}]}]}),
        policy('egress-gpu', {'podSelector': {'matchLabels': {'app.kubernetes.io/name': 'gpu'}}, 'policyTypes': ['Egress'],
                              'egress': [{'to': [{'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': gpu.NS}}}],
                                          'ports': [{'port': p} for p in gpu.PORTS]}]}),
        policy('egress-internet', {'podSelector': {'matchLabels': {'hoover.dev/egress': 'internet'}}, 'policyTypes': ['Egress'],
                                   'egress': [{'to': [{'ipBlock': {'cidr': '0.0.0.0/0', 'except': PRIVATE_RANGES}}]}]}),
        {'apiVersion': 'networking.k8s.io/v1', 'kind': 'Ingress', 'metadata': {'name': 'hoover', 'namespace': ns},
         'spec': {'ingressClassName': 'haproxy', 'tls': [{'hosts': [target.host]}],
                  'rules': [{'host': target.host, 'http': {'paths': [{'path': '/', 'pathType': 'Prefix',
                                                                      'backend': {'service': {'name': 'oauth2-proxy', 'port': {'number': 4180}}}}]}}]}},
    ]
    return items


def zone_ini_text(target, mounts=None):
    mounts = mounts if mounts is not None else dataset_mounts(target)
    values = operator_settings.ini_values(target.values)
    # Garage declares the size of its data volume as its capacity.
    size = target.values['volume.garage-data']
    values[('storage', 'garage_capacity')] = re.sub(r'([KMGT])i$', r'\1', size)
    if target.source:
        # A migrated install keeps the history shard count of its Temporal stores.
        values[('main_services', 'temporal_history_shards')] = target.source.values['main_services']['temporal_history_shards']
    return zone_ini.render(values, mounts, bool(target.site.gpu_pool), admin_base_url=f'https://{target.host}/',
                           title=f'the Hoover installation {target.hoover.name}')


def objects(target):
    """Every object of the installation, in apply order."""
    check_services(target.tree)
    mounts = dataset_mounts(target)
    with tempfile.TemporaryDirectory() as folder:
        ini = Path(folder) / 'hoover4.ini'
        ini.write_text(zone_ini_text(target, mounts))
        try:
            deploy, cfg, env, services = compose.load(ini, target.tree)
        except Exception as error:  # deploy.DeployError of the loaded module
            if type(error).__name__ == 'DeployError':
                raise RenderError(f'the settings of {target.hoover.name} give an ini that deploy.py refuses: {error}') from None
            raise
    namespace = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': target.ns, 'labels': {
        'hoover.dev/zone': 'true', 'hoover.dev/home-node': target.hoover.home_node}}}
    claims = []
    if target.local:
        claims = [claim(target, c) for c in operator_settings.VOLUMES if c != 'worker-temp-files'
                  and (target.cassandra or not c.startswith('temporal-'))]
    else:
        claims = [claim(target, c) for c in sorted(ZONE_CLAIMS) if c != 'worker-temp-files']
    for m in mounts:
        if 'persistentVolumeClaim' in m['volume']:
            name = m['volume']['persistentVolumeClaim']['claimName']
            claims.append({'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': name, 'namespace': target.ns},
                           'spec': claim_spec(target, 'upload-tmp', target.values['volume.upload-tmp'])})
    stores = [] if target.local else [external(target, n) for n in ('clickhouse', 'manticore', 'manticore-vectors', 'garage')]
    items, configs = translated(target, services, mounts, deploy)
    shards = cfg.get('main_services', 'temporal_history_shards')
    extra = []
    if target.cassandra:
        temporal_image = next(c['image'] for i in items if i['metadata']['name'] == 'temporal' and i['kind'] == 'Deployment'
                              for c in i['spec']['template']['spec']['containers'])
        extra.append(temporal_retention(target, cfg, temporal_image))
    else:
        extra += temporal_pg(target, shards)
    return [namespace, *stores, *claims, *config_maps(target, deploy, cfg, configs | {'tika-config', 'mirror'}),
            *extra, *proxy(target), *gpu.forwarder(target.zone, target.ns), *items, *network(target)]


def render(target):
    """The List text of an installation. The same Target gives the same text."""
    return json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': objects(target)}, indent=1, sort_keys=True)


# The kinds that prune() checks. Secrets belong to setup.py and stay. Claims stay, because they hold data.
PRUNED = ('deployments.apps', 'statefulsets.apps', 'jobs.batch', 'services', 'configmaps',
          'networkpolicies.networking.k8s.io', 'ingresses.networking.k8s.io')


def prune(kubectl, ns, items):
    """Delete each object of the namespace that an earlier apply of this file created and the render no longer has."""
    wanted = {(i['kind'].lower(), i['metadata']['name']) for i in items if i['metadata'].get('namespace') == ns}
    for resource in PRUNED:
        found = json.loads(subprocess.run(kubectl + ['-n', ns, 'get', resource, '-o', 'json', '--show-managed-fields'],
                                          capture_output=True, text=True, check=True).stdout)
        for obj in found['items']:
            kind, name = obj['kind'].lower(), obj['metadata']['name']
            managers = {f.get('manager') for f in obj['metadata'].get('managedFields', [])}
            if 'hoover' in managers and (kind, name) not in wanted:
                subprocess.run(kubectl + ['-n', ns, 'delete', resource, name, '--wait=false'], check=True)


def nfs_addresses(kubectl, site):
    """The Service address of the NFS server of each data node, from the cluster."""
    out = {}
    for node in site.with_role('data'):
        r = subprocess.run(kubectl + ['-n', 'hoover-data', 'get', 'service', f'nfs-{node.name}', '-o', 'jsonpath={.spec.clusterIP}'],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            out[node.name] = r.stdout.strip()
    return out


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('installation')
    parser.add_argument('command', nargs='?', default='show', choices=('show', 'apply', 'diff'))
    parser.add_argument('--site', default=os.environ.get('HOOVER4_SITE', str(site_config.DEFAULT_SITE)))
    parser.add_argument('--revision', help='the source revision of the images. The default is the commit of the tree.')
    parser.add_argument('--settings-revision', type=int, help='the saved operator settings revision. The default is the newest.')
    args = parser.parse_args(argv)
    kubectl = ['kubectl', '--kubeconfig', k3s_settings.KUBECONFIG]
    site = site_config.read(args.site)
    hoover = find_hoover(site, args.installation)
    nfs = {} if hoover.source_ini else nfs_addresses(kubectl, site)
    target = target_from_site(args.site, args.installation, revision=args.revision, nfs=nfs,
                              settings_revision=args.settings_revision)
    rendered = render(target)
    if args.command == 'show':
        print(rendered)
        return
    cmd = ['apply', '--server-side', '--force-conflicts', '--field-manager=hoover', '-f', '-'] if args.command == 'apply' else ['diff', '-f', '-']
    r = subprocess.run(kubectl + cmd, input=rendered, text=True)
    if args.command == 'apply':
        if r.returncode:
            sys.exit(r.returncode)
        prune(kubectl, target.ns, json.loads(rendered)['items'])


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except site_config.SiteError as error:
        raise SystemExit(str(error))
