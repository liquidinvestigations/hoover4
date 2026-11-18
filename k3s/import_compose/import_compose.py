#!/usr/bin/env python3
"""Import a stopped Compose installation of Hoover into a new zone of the cluster, once per zone.

deploy-k3s import-compose runs this file in the operator image. The command creates the zone with the storage names
that its id gives (../config.py Hoover) and copies the Compose data into the volumes of its Hoover namespace. The
copy keeps the bytes. The renames step then gives the databases, tables and buckets the names of the zone.

Arguments:
  <zone>            a new zone id, for example zone-a. A zone that exists stops the plan step. An import that finished
                    stops every later run of the same zone.
  <folder>          the Compose volume folder ([storage] volumes_path of the Compose ini), relative to the data root of
                    the source node (data_root of the site file). A bind mount can put it there.
  --home NODE       the node of the imported store volumes and store images, with the role worker. The copy pod binds
                    the claims there, and the pods of the local layout that share the claims follow them
                    (../hoover/manifests.py). The zone has no home node, so the zone state does not keep this value.
  --ini FILE        the hoover4.ini of the Compose install, relative to the folder of the site file. Its explicit values
                    become operator settings of the Hoover installation of the zone, and it names the dataset mounts.
  --source-node N   the node that runs the Compose install. The default is the --home node. The import connects to it
                    with ssh and runs its root commands with sudo -n.
  --engine E        docker (rootful, the owners of the host stay) or podman (rootless, the owners map through the uid and
                    gid maps of the user namespace). The default is docker.
  --dataset N=DIR   the folder of the dataset mount N of the ini, relative to the data root of the source node. The copy
                    goes into the claim dataset-N of the zone. Each writable mount needs this option or
                    --without-dataset. A read-only mount without this option is left out.
  --without-dataset N   leaves out the writable dataset mount N, for example after a copy by hand.
The dataset rows of the Compose install name the container path of their mount. The renames step moves them below
/data/<mount name>, the mount path of the zone.
  --until STEP      stops after this step. --dry-run prints the plan and writes nothing.
  --users           creates a zone user for each owner of imported chats and boards, after the workers step.
  --status          prints the finished steps.

The steps run in this order. A finished step does not run again, so the command continues an interrupted import.
  plan      Reads the ini, checks the folders on the source node (probe.py), the owner maps of the source runtime, the
            content id of each store and Temporal image, the claim of each folder and the free capacity of the --home
            node. Saves the explicit ini values and the history shard count as operator settings of hoover:<zone>, and
            app.hoover = false for zone:<zone>, so that the zone step starts no Hoover service.
  freeze    Stops the Compose services that accept new work, then the workers with their Compose grace period.
  record    Records the Temporal namespaces, search attributes, workflow counts and open workflows with their histories,
            the row counts of each ClickHouse table, the Manticore tables and the Garage buckets with their aliases.
  stop      Stops Temporal, then the stores (Cassandra after nodetool drain), then every other Compose container.
  zone      zone.py apply creates the zone with stores = local and the Compose Temporal: openDesk, and the Hoover
            objects with zero replicas. The step removes the garage-init Jobs, so no bucket of the zone exists before
            the renames.
  images    Saves each store and Temporal image on the source node and imports it into the containerd of the --home node.
  copy      Copies each folder into its claim through a pod of the --home node (root_copy.py pack and verify): owners
            mapped, one hash per file. An interrupted folder is cleared and copied again.
  secrets   Writes the Secret hoover-runtime with the Compose store credentials and the shared secrets of the key files
            of the ini.
  stores    Starts the stores and Temporal without the application services, and compares the store contents with the
            record. A ClickHouse table with a TTL or a merging engine may hold fewer rows than the record.
  renames   Renames the ClickHouse databases, the Manticore tables and the Garage bucket aliases (renames.py), changes
            the bucket names in the s3 path columns and the container paths of the dataset rows, and compares the
            stores with the renamed record.
  temporal  Compares the target Temporal with the record. Every open workflow must have its run id and history.
  workers   Saves app.hoover = true and applies the whole render, so the workers and the website start.
  resume    Waits until each recorded open workflow has new history events, has closed, or waits for a timer or a child.
The records of a run are in operator/import/<zone>/ of the state folder. That folder stays on the workstation.
Each run holds the site operation lock (../oplock.py). The plan pins its inputs, and a later step with other inputs
stops.

Usage: import_compose.py <zone> <folder> --home NODE --ini FILE [options]
       import_compose.py <zone> --status | --users
"""
import argparse
import base64
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
K3S = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(K3S))
sys.path.insert(0, str(K3S / 'hoover'))
sys.path.insert(0, str(K3S / 'driver'))
import config as site_config  # noqa: E402
import renames  # noqa: E402
import source as compose_source  # noqa: E402

STEPS = ('plan', 'freeze', 'record', 'stop', 'zone', 'images', 'copy', 'secrets', 'stores', 'renames', 'temporal',
         'workers', 'resume')
# The Compose services that take new work. freeze stops them first.
INTAKE = ('hoover4-development-auth-backdoor', 'hoover4-website', 'hoover4-mcp-collections', 'hoover4-mcp-todo',
          'hoover4-mcp-browser', 'hoover4-mcp-metasearch', 'hoover4-mcp-whois', 'hoover4-internal-search-agent',
          'hoover4-full-research-agent')
WRITERS = ('hoover4-worker', 'hoover4-ops')
# The stop order after the writers: the interfaces and Temporal, then the stores.
STOP_ORDER = (('temporal-ui', 'hoover4_ch-ui_1', 'hoover4_clickhouse-monitoring_1'), ('temporal',),
              ('clickhouse', 'manticore', 'manticore-vectors', 'garage', 'zookeeper', 'redis'),
              ('temporal-cassandra', 'temporal-elasticsearch'))
# The store and Temporal containers whose exact image the target uses.
STORE_CONTAINERS = ('temporal-cassandra', 'temporal-elasticsearch', 'temporal', 'clickhouse', 'manticore', 'manticore-vectors',
                    'garage', 'zookeeper')
# The claim of the worker plan files of pod 0 (manifests.py volumeClaimTemplates of hoover-workers).
WORKER_CLAIM = 'worker-temp-files-hoover-workers-0'
# The image of the short pods that bind and fill the claims: the pinned image of the operator portal.
BIND_IMAGE = 'docker.io/library/python:3.14-alpine@sha256:7f2ec713f0436c59df2362d973b6a05af9e87ba78f0e94f5245c302984a7a1fd'
# The store layout of an imported zone: the Compose stores and the Compose Temporal in the Hoover namespace.
ZONE_VALUES = {'stores': 'local'}
HISTORY_SHARDS = 'main_services.temporal_history_shards'


class StepFailed(SystemExit):
    pass


def run(argv, input=None, check=True, timeout=None):
    r = subprocess.run([str(a) for a in argv], input=input, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise StepFailed(f'{" ".join(str(a) for a in argv[:6])} failed: {(r.stderr or r.stdout).strip()[-800:]}')
    return r.stdout


def kubeconfig():
    import settings as k3s_settings
    return k3s_settings.KUBECONFIG


def kubectl(*args, input=None, check=True):
    return run(['kubectl', '--kubeconfig', kubeconfig(), *args], input=input, check=check)


def operator_settings():
    import manifests
    return manifests.operator_settings


SSH_OPTIONS = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-o', 'StrictHostKeyChecking=accept-new']


def node_argv(node, argv):
    """A command on a node of the site over SSH. The operator image reaches the local node at localhost too."""
    return ['ssh', *SSH_OPTIONS, site_config.ssh_host(node), '--', ' '.join(shlex.quote(str(a)) for a in argv)]


class Source:
    """The container runtime and the node of the Compose install."""
    engine = 'docker'
    node = None

    @classmethod
    def argv(cls, argv):
        return node_argv(cls.node, argv)


def src(argv, input=None, check=True, timeout=None):
    """Run a command on the source node."""
    return run(Source.argv(argv), input=input, check=check, timeout=timeout)


def engine(*args):
    return [Source.engine, *args]


def owner_maps():
    """The uid and gid maps of the source runtime. A rootful Docker keeps the owners of the host."""
    if Source.engine == 'podman':
        return src(['podman', 'unshare', 'cat', '/proc/self/uid_map']), src(['podman', 'unshare', 'cat', '/proc/self/gid_map'])
    info = src(['docker', 'info', '--format', '{{json .SecurityOptions}}'], check=False)
    if 'rootless' in info:
        raise StepFailed('the source Docker runs rootless. Its owner maps are not supported. Use a rootful Docker or Podman.')
    identity = '0 0 4294967295\n'
    return identity, identity


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ----------------------------------------------------------------------------------------------------------------------
# The run and its inputs
# ----------------------------------------------------------------------------------------------------------------------

class Run:
    """The folder and the step records of the import of one zone."""

    def __init__(self, site, zone, site_path):
        self.site, self.zone, self.site_path = site, zone, str(site_path)
        self.folder = site.operator_state() / 'import' / zone
        self.revision = None
        # The inputs of a plan before it writes inputs.json.
        self.planned = None

    def path(self, name):
        return self.folder / name

    def read(self, name, default=None):
        path = self.path(name)
        return json.loads(path.read_text()) if path.exists() else default

    def write(self, name, value):
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.path(name)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(value, indent=1, sort_keys=True) + '\n')
        os.replace(tmp, path)

    def done(self, step):
        return step in self.read('steps.json', {})

    def finish(self, step, summary):
        steps = self.read('steps.json', {})
        steps[step] = {'time': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'summary': summary}
        self.write('steps.json', steps)

    @property
    def inputs(self):
        return self.planned or self.read('inputs.json') or {}

    @property
    def hoover(self):
        inputs = self.inputs
        return site_config.Hoover(zone=self.zone, **ZONE_VALUES)

    @property
    def node(self):
        """The node of the imported store volumes and images (--home)."""
        return self.inputs['home']


def refusal(r, zones):
    """The message that stops an import of a zone, or None. zones holds the zone ids of the zone state."""
    steps = r.read('steps.json', {})
    if 'resume' in steps:
        return (f'the zone {r.zone} holds the import of {r.inputs.get("folder")} since {steps["resume"]["time"]}. '
                f'An import runs once per zone. A new import needs a new zone id.')
    if r.zone in zones and 'zone' not in steps:
        return (f'the zone {r.zone} exists. The import creates a new zone. Give a new zone id, or delete the zone in the '
                'operator portal first.')
    if 'zone' in steps and r.zone not in zones:
        return (f'the zone {r.zone} was deleted after the zone step of its import. Remove the import records in '
                f'{r.folder} to start again.')
    return None


def check_arguments(r, args):
    """Refuse arguments that differ from the pinned inputs of the plan. Return the inputs."""
    inputs = r.inputs
    given = {'folder': args.folder and compose_source.relative_folder(args.folder), 'home': args.home,
             'ini': args.ini and str(Path(args.ini)), 'source_node': args.source_node, 'engine': args.engine_given}
    problems = [f'{key} is {value}, and the plan has {inputs.get(key)}' for key, value in given.items()
                if value and inputs.get(key) != value]
    if problems:
        raise StepFailed(f'the import of {r.zone} started with other inputs: ' + '; '.join(problems) + '.')
    return inputs


def check_inputs(r, revision):
    """Refuse a step whose site file, ini, commit or source differ from inputs.json."""
    inputs = r.inputs
    if not inputs:
        raise StepFailed('the import has no inputs.json. Run the plan step first.')
    problems = []
    if digest(r.site_path) != inputs['site_fingerprint']:
        problems.append('the site file changed')
    if digest(ini_path(r, inputs['ini'])) != inputs['ini_fingerprint']:
        problems.append('the Compose ini changed')
    if revision != inputs['revision']:
        problems.append(f'the revision {revision} is not the pinned {inputs["revision"]}')
    if (Source.engine, Source.node.name) != (inputs['engine'], inputs['source_node']):
        problems.append(f'the source is {Source.engine} on {Source.node.name}, not {inputs["engine"]} on '
                        f'{inputs["source_node"]}')
    if problems:
        raise StepFailed('the inputs of the import changed: ' + '; '.join(problems) + '.')
    return inputs


def ini_path(r, relative):
    """The ini of the Compose install, relative to the folder of the site file. The folder stays below that folder."""
    relative = compose_source.relative_folder(relative, 'the ini')
    base = Path(r.site_path).resolve().parent
    path = (base / relative).resolve()
    if base not in path.parents:
        raise StepFailed(f'the ini {relative} leaves the folder of the site file through a symbolic link.')
    return path


def read_source(r):
    try:
        return compose_source.read_ini(ini_path(r, r.inputs['ini']))
    except compose_source.SourceError as error:
        raise StepFailed(str(error)) from None


# ----------------------------------------------------------------------------------------------------------------------
# Plan
# ----------------------------------------------------------------------------------------------------------------------

def folder_claims(source, probed, datasets):
    """{source path: claim} of every copied folder. probed is the answer of probe.py, datasets the writable mounts."""
    import manifests
    out = {}
    for name, row in sorted(probed['volumes'].items()):
        if name in compose_source.SKIPPED:
            continue
        claim = manifests.CLAIMS.get(name)
        if claim == 'worker-temp-files':
            claim = WORKER_CLAIM
        if claim:
            out[row['path']] = claim
    for name in datasets:
        out[probed['datasets'][name]['path']] = f"dataset-{name.replace('_', '-')}"
    return out


def dataset_choices(source, given, without):
    """{name: folder} of the dataset mounts to copy, and the problems of the dataset options.

    Each writable mount needs --dataset or --without-dataset, because its folder holds the uploads. A read-only mount
    is copied only with --dataset. Without it the plan lists it as left out.
    """
    mounts = {m['name']: m for m in source.dataset_mounts}
    writable = {n for n, m in mounts.items() if m['writable']}
    problems = []
    for name in sorted(set(given) | set(without)):
        if name not in mounts:
            problems.append(f'the ini has no dataset mount {name}.')
    for name in sorted(writable - set(given) - set(without)):
        problems.append(f'the writable dataset mount {name} ({mounts[name]["host_path"]}) needs --dataset {name}=<folder '
                        f'below the data root>, or --without-dataset {name}.')
    for name in sorted(set(given) & set(without)):
        problems.append(f'{name} has both --dataset and --without-dataset.')
    return {k: v for k, v in given.items() if k in mounts and k not in without}, problems


def render_target(r, revision, settings_revision=None):
    """The Target of the Hoover installation of the zone, with replicas, also before the zone exists."""
    import manifests
    hoover = r.hoover
    state = operator_settings().State(r.site.operator_state())
    overrides = state.overrides(settings_revision) if (r.site.operator_state() / 'desired.json').exists() else {}
    values = operator_settings().installation_values(hoover.name, overrides, pooled=hoover.stores == 'site')
    return manifests.Target(site=r.site, hoover=hoover, values=values, revision=revision, enabled=True,
                            local_ca=site_config.local_ca(r.site))


def target_items(r, revision):
    import manifests
    return json.loads(manifests.render(render_target(r, revision, r.inputs.get('settings_revision'))))['items']


def probe(r, inputs, source, datasets):
    request = {'root': r.site.nodes[inputs['source_node']].data_root, 'folder': inputs['folder'],
               'volumes': source.volumes, 'required': list(compose_source.REQUIRED), 'datasets': datasets}
    out = src(['sudo', '-n', 'python3', '-', json.dumps(request)], input=(HERE / 'probe.py').read_text(), timeout=3600)
    return json.loads(out.strip().splitlines()[-1])


def home_capacity(r, node_name):
    """The largest free TopoLVM capacity of the --home node."""
    annotations = json.loads(kubectl('get', 'node', node_name, '-o', 'jsonpath={.metadata.annotations}') or '{}')
    values = [int(v) for k, v in annotations.items() if k.startswith('capacity.topolvm.io/') and v.isdigit()]
    if not values:
        raise StepFailed(f'the node {node_name} reports no TopoLVM capacity.')
    return max(values)


def parse_size(text):
    units = {'Ki': 2**10, 'Mi': 2**20, 'Gi': 2**30, 'Ti': 2**40}
    for suffix, factor in units.items():
        if str(text).endswith(suffix):
            return int(float(str(text)[:-2]) * factor)
    return int(text)


def image_ids(containers=STORE_CONTAINERS):
    out = {}
    for name in containers:
        found = json.loads(src(engine('inspect', name)))[0]
        out[name] = {'reference': found['Config']['Image'], 'id': found['Image'].removeprefix('sha256:')}
    return out


def plan(r, args, zones, dry_run=False):
    message = refusal(r, zones)
    if message:
        raise StepFailed(message)
    if not (args.folder and args.home and args.ini):
        raise StepFailed('the plan step needs <folder>, --home and --ini.')
    for name, label in ((args.home, '--home'), (args.source_node or args.home, '--source-node')):
        if name not in r.site.nodes:
            raise StepFailed(f'{label} {name} is not a node of the site. The nodes are: {", ".join(r.site.nodes)}.')
    problems = site_config.zone_problems(r.zone, dict(ZONE_VALUES), r.site)
    if not r.site.nodes[args.home].has('worker'):
        problems.append(f'--home {args.home} does not have the role worker.')
    if problems:
        raise StepFailed('; '.join(problems))
    inputs = {'folder': compose_source.relative_folder(args.folder), 'home': args.home, 'ini': str(Path(args.ini)),
              'source_node': Source.node.name, 'engine': Source.engine}
    r.planned = inputs
    ini = ini_path(r, inputs['ini'])
    try:
        source = compose_source.read_ini(ini)
    except compose_source.SourceError as error:
        raise StepFailed(str(error)) from None
    datasets, problems = dataset_choices(source, dict(args.dataset), set(args.without_dataset))
    datasets = {k: compose_source.relative_folder(v, f'the dataset folder of {k}') for k, v in datasets.items()}
    if problems:
        raise StepFailed('the dataset options have problems:\n    ' + '\n    '.join(problems))
    probed = probe(r, inputs, source, datasets)
    problems = list(probed['problems'])
    if problems:
        raise StepFailed('the source folders have problems:\n    ' + '\n    '.join(problems))
    claims = folder_claims(source, probed, datasets)
    folders = {}
    for row in list(probed['volumes'].values()) + list(probed['datasets'].values()):
        if row['path'] in claims:
            folders[row['path']] = {'claim': claims[row['path']], 'bytes': row['bytes'], 'owner': row['owner']}
    uid_map, gid_map = owner_maps()
    free = home_capacity(r, args.home)
    target = render_target(r, '0' * 40)
    sizes = {c: target.values.get(f'volume.{c}', target.values['volume.upload-tmp']) for c in set(claims.values())}
    sizes[WORKER_CLAIM] = target.values['volume.worker-temp-files']
    needed = sum(parse_size(s) for s in sizes.values())
    import manifests
    rendered_claims = [i for i in json.loads(manifests.render(target))['items'] if i['kind'] == 'PersistentVolumeClaim']
    rendered = {i['metadata']['name'] for i in rendered_claims}
    # A claim takes the first preferred tier of the site, and the copy pod binds it on the --home node.
    for item in rendered_claims:
        tier_name = item['spec']['storageClassName'].rsplit('-', 1)[0]
        if item['metadata']['name'] in set(claims.values()) and tier_name not in r.site.nodes[args.home].tiers:
            problems.append(f"the claim {item['metadata']['name']} uses the tier {tier_name}, which the node {args.home} "
                            'does not have. Give a --home node with that tier.')
    for claim in sorted(set(claims.values()) - rendered - {WORKER_CLAIM}):
        # A site with data nodes keeps the dataset folders on NFS (../platform/hoover-data), not in claims.
        problems.append(f'the zone has no claim {claim}. Copy that folder into the data folder of the zone by hand, and '
                        'give --without-dataset for it.')
    for path, row in folders.items():
        # A claim needs the source bytes and room for the startup changes of its store.
        if row['bytes'] * 1.5 > parse_size(sizes[row['claim']]):
            problems.append(f"{path} holds {row['bytes']} bytes, and the claim {row['claim']} has {sizes[row['claim']]}. "
                            f"Save a larger volume.{row['claim']} in the operator settings of hoover:{r.zone}.")
    if needed > free:
        problems.append(f'the claims need {needed} bytes, and the node {args.home} has {free} free.')
    result = {'zone': r.zone, 'namespace': r.hoover.namespace, 'identity': r.hoover.identity(),
              'dropped_settings': source.dropped, 'not_imported': source.not_imported, 'folders': folders,
              'skipped': {k: v for k, v in compose_source.SKIPPED.items() if k in probed['volumes']},
              'dataset_mounts': source.dataset_mounts,
              'datasets_left_out': sorted(m['name'] for m in source.dataset_mounts if m['name'] not in datasets),
              'uid_map': uid_map, 'gid_map': gid_map, 'images': image_ids(), 'claim_sizes': sizes, 'free_bytes': free,
              'needed_bytes': needed, 'history_shards': compose_source.effective(source, 'main_services',
                                                                                  'temporal_history_shards'),
              'problems': problems}
    if dry_run:
        print(json.dumps(result, indent=1))
        return result
    if problems:
        r.write('plan-refused.json', result)
        raise StepFailed('the plan has problems:\n    ' + '\n    '.join(problems))
    result['settings_revision'] = seed_settings(r, source, result['history_shards'])
    r.write('plan.json', result)
    r.planned = None
    r.write('inputs.json', {**inputs, 'revision': r.revision, 'settings_revision': result['settings_revision'],
                            'site_fingerprint': digest(r.site_path), 'ini_fingerprint': digest(ini),
                            'images': result['images'], 'identity': result['identity']})
    return {'folders': len(folders), 'bytes': sum(f['bytes'] for f in folders.values()), 'free': free,
            'settings_revision': result['settings_revision']}


def seed_settings(r, source, shards):
    """Save the explicit ini values as settings of hoover:<zone> once, the history shard count of the Compose Temporal,
    and app.hoover = false for zone:<zone>. Return the revision that the render pins."""
    module = operator_settings()
    state = module.State(r.site.operator_state())
    scope = f'hoover:{r.zone}'
    state.seed(scope, source, actor='import', new_scope=True)
    changes = {f'zone:{r.zone}': {'app.hoover': 'false'}}
    if state.effective(scope)[HISTORY_SHARDS] != shards:
        # Temporal keeps the shard count of its store. Without the same count it does not start.
        changes[scope] = {HISTORY_SHARDS: shards}
    while True:
        try:
            return state.save(state.revision(), changes, actor='import', note=f'import of {r.zone}',
                              new_scopes=tuple(changes))
        except module.StaleRevision:
            continue


# ----------------------------------------------------------------------------------------------------------------------
# Source shutdown and record
# ----------------------------------------------------------------------------------------------------------------------

def running(name):
    r = subprocess.run(Source.argv(engine('inspect', '-f', '{{.State.Running}}', name)), capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == 'true'


def stop(names, timeout):
    stopped = []
    for name in names:
        if running(name):
            src(engine('stop', '-t', str(timeout), name), timeout=timeout + 120)
            stopped.append(name)
    return stopped


def freeze(r):
    # The website and the sign-in proxy take uploads and chat turns, so they stop first.
    intake = stop(INTAKE, 30)
    # The workers drain their activities in the Compose grace period. Temporal keeps every workflow.
    writers = stop(WRITERS, 90)
    return {'intake': intake, 'writers': writers}


def temporal(*args):
    return src(engine('exec', 'temporal', 'temporal', *args, '--address', 'temporal:7233'), timeout=600)


def temporal_record(cli):
    """The Temporal state through a CLI function: namespaces, search attributes, counts, open workflows."""
    namespaces = json.loads(cli('operator', 'namespace', 'list', '-o', 'json') or '[]')
    names = sorted(n['namespaceInfo']['name'] for n in namespaces)
    out = {'namespaces': {}, 'search_attributes': {}, 'counts': {}, 'open': {}}
    for ns in names:
        info = next(n for n in namespaces if n['namespaceInfo']['name'] == ns)
        out['namespaces'][ns] = {'id': info['namespaceInfo'].get('id'), 'retention': info.get('config', {}).get('workflowExecutionRetentionTtl')}
        attributes = json.loads(cli('operator', 'search-attribute', 'list', '-n', ns, '-o', 'json') or '{}')
        out['search_attributes'][ns] = sorted((attributes.get('customAttributes') or {}).items())
        counts = {}
        for status in ('Running', 'Completed', 'Failed', 'Canceled', 'Terminated', 'ContinuedAsNew', 'TimedOut'):
            text = cli('workflow', 'count', '-n', ns, '--query', f'ExecutionStatus="{status}"', '-o', 'json')
            counts[status] = int(json.loads(text).get('count', 0))
        counts['total'] = int(json.loads(cli('workflow', 'count', '-n', ns, '-o', 'json')).get('count', 0))
        out['counts'][ns] = counts
        listed = json.loads(cli('workflow', 'list', '-n', ns, '--query', 'ExecutionStatus="Running"', '-o', 'json', '--limit', '1000') or '[]')
        for w in listed:
            wid, rid = w['execution']['workflowId'], w['execution']['runId']
            history = json.loads(cli('workflow', 'show', '-n', ns, '-w', wid, '-r', rid, '-o', 'json'))
            events = history.get('events', history if isinstance(history, list) else [])
            out['open'][f'{ns}/{wid}'] = {'run_id': rid, 'type': w.get('type', {}).get('name'), 'events': len(events),
                                          'last_event_id': int(events[-1]['eventId']) if events else 0}
    return out


def clickhouse_counts(query):
    """{database.table: row count} of ClickHouse. The answer is one JSON document whose row count must match its rows, so
    an answer that a remote command cut stops the step."""
    text = query("SELECT database, name, total_rows FROM system.tables WHERE database NOT IN ('system', 'INFORMATION_SCHEMA', "
                 "'information_schema') AND engine NOT IN ('View', 'MaterializedView') ORDER BY database, name FORMAT JSON")
    try:
        answer = json.loads(text)
        rows = answer['data']
        complete = answer['rows'] == len(rows)
    except (ValueError, KeyError, TypeError):
        complete = False
    if not complete:
        raise StepFailed(f'ClickHouse gave an incomplete answer to the table list: {text.strip()[-200:]!r}')
    return {f"{row['database']}.{row['name']}": int(row['total_rows'] or 0) for row in rows}


def source_clickhouse(sql):
    return src(engine('exec', '-i', 'clickhouse', 'clickhouse-client', '--user', 'hoover4', '--password', 'hoover4'), input=sql)


def manticore_listing(text, statement):
    """The rows of the XML answer of the mysql client to one statement, as {column: value}.

    An answer that a remote command cut, or an empty answer, does not parse, so it stops the step and is never read as a
    list without the rest of its rows (stores/shared.py manticore_list() reads the shared daemons the same way)."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(text.strip())
    except ET.ParseError:
        raise StepFailed(f'Manticore gave an incomplete answer to {statement}: {text.strip()[-200:]!r}') from None
    if root.tag != 'resultset' or root.get('statement', '').strip().rstrip(';').strip() != statement:
        raise StepFailed(f'Manticore answered another statement than {statement}: {text.strip()[:200]!r}')
    return [{field.get('name'): field.text or '' for field in row.findall('field')} for row in root.findall('row')]


def manticore_tables(listing):
    """{table: row count} of a Manticore daemon. ``listing(statement)`` returns the complete rows of one statement."""
    out = {}
    for row in listing('SHOW TABLES'):
        name = row['Table']
        counts = listing(f'SELECT COUNT(*) AS n FROM {name}')
        if len(counts) != 1 or not counts[0].get('n', '').isdigit():
            raise StepFailed(f'Manticore gave no row count for the table {name}: {counts!r}')
        out[name] = int(counts[0]['n'])
    return out


def source_manticore_listing(container):
    def listing(statement):
        return manticore_listing(src(engine('exec', container, 'mysql', '-h0', '-P9306', '-umanticore', '-pmanticore',
                                            '--xml', '-e', statement)), statement)
    return listing


def garage_buckets(call):
    """The ListBuckets answer of the Garage admin endpoint, through `garage json-api` of a Garage container."""
    return json.loads(call('ListBuckets') or '[]')


def source_garage(endpoint, payload=None):
    return src(engine('exec', 'garage', '/garage', 'json-api', endpoint, *([json.dumps(payload)] if payload else [])))


def record(r):
    # The record of Temporal comes first, because the stores can be read after Temporal stops.
    state = temporal_record(temporal)
    histories = r.path('histories')
    histories.mkdir(exist_ok=True)
    for key, w in state['open'].items():
        ns, wid = key.split('/', 1)
        (histories / f'{ns}--{wid}.json').write_text(temporal('workflow', 'show', '-n', ns, '-w', wid, '-r', w['run_id'], '-o', 'json'))
    state['clickhouse'] = clickhouse_counts(source_clickhouse)
    state['manticore'] = manticore_tables(source_manticore_listing('manticore'))
    state['manticore_vectors'] = manticore_tables(source_manticore_listing('manticore-vectors'))
    state['garage_buckets'] = garage_buckets(source_garage)
    r.write('record.json', state)
    return {'namespaces': len(state['namespaces']), 'open': len(state['open']), 'tables': len(state['clickhouse']),
            'buckets': len(state['garage_buckets']), 'counts': state['counts']}


def stop_source(r):
    stopped = []
    for group in STOP_ORDER:
        if 'temporal-cassandra' in group and running('temporal-cassandra'):
            # drain writes the commit log into the SSTables, so the copy holds no unflushed write.
            src(engine('exec', 'temporal-cassandra', 'nodetool', 'drain'), timeout=600)
        stopped += stop(group, 120)
    # Every other container of the Compose project stops too, so no source writer remains.
    names = src(engine('ps', '--format', '{{.Names}}', '--filter', 'label=com.docker.compose.project=hoover4')).split()
    names += [n for n in src(engine('ps', '--format', '{{.Names}}')).split() if n.startswith('hoover4')]
    stopped += stop(sorted(set(names)), 60)
    left = [n for n in STORE_CONTAINERS + WRITERS + INTAKE if running(n)]
    if left:
        raise StepFailed(f'these source containers still run: {", ".join(left)}')
    return {'stopped': stopped}


# ----------------------------------------------------------------------------------------------------------------------
# Zone, images, copy and secrets
# ----------------------------------------------------------------------------------------------------------------------

def remove_garage_init(ns):
    kubectl('-n', ns, 'delete', 'job', '-l', 'app.kubernetes.io/name=garage-init', '--ignore-not-found', '--wait=true')


def create_zone(r):
    inputs = r.inputs
    argv = [sys.executable, K3S / 'zones' / 'zone.py', 'apply', r.zone,
            '--stores', ZONE_VALUES['stores']]
    result = subprocess.run([str(a) for a in argv])
    if result.returncode:
        raise StepFailed(f'zone.py apply {r.zone} failed with exit code {result.returncode}. Run the import again to '
                         'continue at the zone step.')
    # The garage-init Job of the render creates the system bucket of the zone. The renames step gives that name to the
    # copied Compose bucket, so no Job may create it first. The workers step applies the Job again.
    remove_garage_init(r.hoover.namespace)
    return {'zone': r.zone, 'home': inputs['home'], **ZONE_VALUES}


def home_root(r, script, timeout=3600):
    """Run a root shell script on the --home node with sudo -n. The operator user needs sudo without a password there."""
    node = r.site.nodes[r.node]
    return run(node_argv(node, ['sudo', '-n', 'sh', '-c', script]), timeout=timeout)


def cluster_image_id(r, reference):
    out = home_root(r, f'k3s crictl inspecti -o json {shlex.quote(reference)} 2>/dev/null; true', timeout=300)
    try:
        return json.loads(out)['status']['id'].removeprefix('sha256:')
    except (ValueError, KeyError):
        return ''


def import_image(r, image_id, full):
    """Save a source image and import it into the containerd of the --home node under the reference of the render."""
    node = r.site.nodes[r.node]
    path = f'/tmp/hoover4-image-{image_id[:12]}.tar'
    save = subprocess.Popen(Source.argv(engine('save', image_id)), stdout=subprocess.PIPE)
    receive = subprocess.run(node_argv(node, ['sh', '-c', f'umask 077 && cat > {path}']), stdin=save.stdout,
                             capture_output=True)
    save.stdout.close()
    if save.wait() or receive.returncode:
        raise StepFailed(f'the transfer of {full} to {node.name} failed.')
    # The archive names the image by its id. ctr tags it with the reference of the render.
    home_root(r, f'k3s ctr -n k8s.io images import --no-unpack=false --index-name {shlex.quote(full)} {path}; '
                 f'status=$?; rm -f {path}; exit $status')


def full_reference(reference):
    """The image reference as the render writes it (manifests.image_of)."""
    first = reference.split('/')[0]
    return reference if '/' in reference and '.' in first else f'docker.io/{reference if "/" in reference else "library/" + reference}'


def images(r):
    wanted = r.read('plan.json')['images']
    result = {}
    for name, image in wanted.items():
        full = full_reference(image['reference'])
        if cluster_image_id(r, full) != image['id'] and '@' not in full:
            import_image(r, image['id'], full)
        found = cluster_image_id(r, full)
        if found != image['id']:
            raise StepFailed(f'the cluster image {full} has the id {found}, not the source id {image["id"]}.')
        result[name] = {'reference': full, 'id': found}
    r.write('images.json', result)
    return {'images': len(result)}


def claim_objects(r, revision):
    items = target_items(r, revision)
    wanted = {row['claim'] for row in r.read('plan.json')['folders'].values()}
    out = [i for i in items if i['kind'] in ('PersistentVolume', 'PersistentVolumeClaim')
           and (i['kind'] == 'PersistentVolume' or i['metadata']['name'] in wanted)]
    missing = wanted - {i['metadata']['name'] for i in out if i['kind'] == 'PersistentVolumeClaim'} - {WORKER_CLAIM}
    if missing:
        raise StepFailed(f'the render of the zone has no claim {", ".join(sorted(missing))}, which the plan found.')
    if WORKER_CLAIM in wanted:
        workers = next(i for i in items if i['kind'] == 'StatefulSet' and i['metadata']['name'] == 'hoover-workers')
        template = next(t for t in workers['spec']['volumeClaimTemplates'] if t['metadata']['name'] == 'worker-temp-files')
        out.append({'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
                    'metadata': {'name': WORKER_CLAIM, 'namespace': r.hoover.namespace,
                                 'labels': {'app.kubernetes.io/name': 'hoover-workers'}}, 'spec': template['spec']})
    return out, wanted


def claim_identity(ns, claim):
    """The UID and the volume of a bound claim."""
    found = json.loads(kubectl('-n', ns, 'get', 'pvc', claim, '-o', 'json'))
    return {'uid': found['metadata']['uid'], 'volume': found['spec'].get('volumeName', '')}


def copy_pod(r, claim):
    """A short root pod on the --home node that mounts one target claim at /target. It binds the claim there."""
    return {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'import-copy', 'namespace': r.hoover.namespace},
            'spec': {'restartPolicy': 'Never', 'automountServiceAccountToken': False, 'enableServiceLinks': False,
                     'nodeSelector': {'kubernetes.io/hostname': r.node},
                     'containers': [{'name': 'copy', 'image': BIND_IMAGE, 'command': ['sleep', '86400'],
                                     'securityContext': {'runAsUser': 0},
                                     'resources': {'limits': {'memory': '512Mi'}},
                                     'volumeMounts': [{'name': 'target', 'mountPath': '/target'}]}],
                     'volumes': [{'name': 'target', 'persistentVolumeClaim': {'claimName': claim}}]}}


EXTRACT = ("import sys, tarfile; tarfile.open(fileobj=sys.stdin.buffer, mode='r|')"
           ".extractall('/target', numeric_owner=True, filter='fully_trusted')")


def copy(r, revision):
    """Copy each folder into its claim through a pod of the --home node. A copied claim is not copied again."""
    plan_data = r.read('plan.json')
    if any(running(n) for n in STORE_CONTAINERS + WRITERS):
        raise StepFailed('a source store or writer runs. Run the stop step first.')
    objects, _ = claim_objects(r, revision)
    kubectl('apply', '--server-side', '--force-conflicts', '--field-manager=hoover', '-f', '-',
            input=json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': objects}))
    ns = r.hoover.namespace
    script = (HERE / 'root_copy.py').read_bytes()
    progress = r.read('copy.json', {})
    for source, row in sorted(plan_data['folders'].items()):
        claim = row['claim']
        recorded = progress.get(claim, {})
        if recorded.get('verified'):
            identity = claim_identity(ns, claim)
            if recorded.get('identity') and recorded['identity'] != identity:
                raise StepFailed(f'the claim {claim} has the identity {identity}, not the recorded {recorded["identity"]}. '
                                 'It is another volume. Inspect it before you continue.')
            continue
        kubectl('-n', ns, 'delete', 'pod', 'import-copy', '--ignore-not-found', '--wait=true')
        kubectl('apply', '-f', '-', input=json.dumps(copy_pod(r, claim)))
        kubectl('-n', ns, 'wait', '--for=condition=Ready', 'pod/import-copy', '--timeout=600s')
        # The pod binds the claim, so the claim has its volume now.
        identity = claim_identity(ns, claim)
        if recorded.get('identity') and recorded['identity'] != identity:
            raise StepFailed(f'the claim {claim} has the identity {identity}, not the recorded {recorded["identity"]}. '
                             'It is another volume. Inspect it before you continue.')
        exec_pod = ['kubectl', '--kubeconfig', kubeconfig(), '-n', ns, 'exec', '-i', 'import-copy', '--']
        try:
            entries = run(exec_pod + ['sh', '-c', 'ls -A /target | grep -vx lost+found | head -1']).strip()
            if entries and not recorded.get('started'):
                raise StepFailed(f'the claim {claim} is not empty and no copy of this import started it. Inspect it.')
            if entries:
                # An interrupted copy starts again from an empty volume.
                run(exec_pod + ['python3', '-', 'clear', '/target'], input=script.decode())
            progress[claim] = {'started': True, 'source': source, 'identity': identity}
            r.write('copy.json', progress)
            started = time.monotonic()
            packer = subprocess.Popen(Source.argv(['sudo', '-n', 'python3', '-', 'pack', source, plan_data['uid_map'],
                                                   plan_data['gid_map']]),
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            packer.stdin.write(script)
            packer.stdin.close()
            extract = subprocess.run(exec_pod + ['python3', '-c', EXTRACT], stdin=packer.stdout, capture_output=True)
            packer.stdout.close()
            if packer.wait() or extract.returncode:
                raise StepFailed(f'the stream of {source} into {claim} failed: '
                                 f'{extract.stderr.decode(errors="replace")[-500:]}')
            manifest = r.path(f'hashes-{claim}.jsonl')
            manifest.write_text(run(exec_pod + ['sh', '-c', 'cat /target/.hoover4-copy-manifest.jsonl && '
                                                            'mv /target/.hoover4-copy-manifest.jsonl /tmp/m.jsonl']))
            out = run(exec_pod + ['python3', '-', 'verify', '/target', '/tmp/m.jsonl'], input=script.decode(), check=False)
            verified = json.loads(out.strip().splitlines()[-1])
            if verified['differences']:
                raise StepFailed(f'the copy of {source} differs from its manifest: {verified["first"]}')
            progress[claim].update(verified=True, files=verified['files'], bytes=verified['bytes'],
                                   seconds=round(time.monotonic() - started, 1))
            r.write('copy.json', progress)
        finally:
            kubectl('-n', ns, 'delete', 'pod', 'import-copy', '--ignore-not-found', '--wait=false', check=False)
    return {c: {k: v for k, v in p.items() if k in ('files', 'bytes', 'seconds')} for c, p in progress.items()}


def secrets(r):
    ns = r.hoover.namespace
    source = read_source(r)
    current = kubectl('-n', ns, 'get', 'secret', 'hoover-runtime', '-o', 'json', check=False)
    data = {k: base64.b64decode(v).decode() for k, v in (json.loads(current).get('data', {}) if current else {}).items()}
    import secrets as random
    import gpu
    # The store credentials of Compose (../hoover/setup.py COMPOSE_STORE_VALUES), which the copied stores hold.
    wanted = {'clickhouse-user': 'hoover4', 'clickhouse-password': 'hoover4', 'manticore-user': 'manticore',
              'manticore-password': 'manticore', 's3-access-key': 'hoover4-blobs-rw',
              's3-secret-key': 'hoover4-garage-blob-secret-key-0',
              'garage-rpc-secret': 'cbc5a1dbd1c832a3bdcb0abff4e5ffc950035febf867de39e9b079cec8863e1d',
              'garage-admin-token': 'hoover4-garage-admin-token', 'gpu-token': gpu.token(r.zone)}
    taken = []
    # The shared secrets of the key files of the ini keep the access that the Compose services had. The files are on
    # the source node.
    for item, key in (('mcp-shared-secret', 'mcp_shared_secret_file'), ('browser-fetch-token', 'browser_fetch_token_file'),
                      ('factcheck-api-key', 'factcheck_api_key_file')):
        path = source.values.get('main_services', {}).get(key, '')
        if path:
            value = src(['sudo', '-n', 'cat', path], check=False).strip()
            if value:
                wanted[item] = value
                taken.append(item)
    for item in ('proxy-secret', 'mcp-shared-secret', 'browser-fetch-token'):
        wanted.setdefault(item, data.get(item) or random.token_hex(32))
    data.update(wanted)
    kubectl('apply', '-f', '-', input=json.dumps({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'hoover-runtime', 'namespace': ns},
                                                   'type': 'Opaque', 'stringData': data}))
    return {'secrets': ['hoover-runtime'], 'from_source_files': taken}


# ----------------------------------------------------------------------------------------------------------------------
# Target start, renames and checks
# ----------------------------------------------------------------------------------------------------------------------

STORE_PARTS = {'clickhouse', 'manticore', 'manticore-vectors', 'garage', 'zookeeper', 'temporal-cassandra',
               'temporal-elasticsearch', 'temporal', 'temporal-ui', 'clickhouse-monitoring', 'ch-ui'}


def apply_items(items):
    kubectl('apply', '--server-side', '--force-conflicts', '--field-manager=hoover', '-f', '-',
            input=json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': items}))


def wait_ready(ns, kind, name, timeout=1200):
    kubectl('-n', ns, 'rollout', 'status', f'{kind}/{name}', f'--timeout={timeout}s')


def target_clickhouse(ns, settings=()):
    """The query function of the ClickHouse of the target. The standard input stays open until the client ends
    (../podexec.py), because the output of the Kata store pod stops after 32 KiB once kubectl closes it."""
    def query(sql):
        import podexec
        argv = ['kubectl', '--kubeconfig', kubeconfig(), '-n', ns, 'exec', '-i', 'clickhouse-0']
        r = podexec.call(argv, ['clickhouse-client', '--user', 'hoover4', '--password', 'hoover4', *settings], sql)
        if r.returncode:
            raise StepFailed(f'the ClickHouse of {ns} refused the query: {(r.stderr or r.stdout).strip()[-800:]}')
        return r.stdout
    return query


def target_manticore(ns, pod):
    def query(sql):
        return kubectl('-n', ns, 'exec', pod, '--', 'mysql', '-h0', '-P9306', '-umanticore', '-pmanticore', '--batch', '-e', sql, check=False)
    return query


def target_manticore_listing(ns, pod):
    def listing(statement):
        return manticore_listing(kubectl('-n', ns, 'exec', pod, '--', 'mysql', '-h0', '-P9306', '-umanticore', '-pmanticore',
                                         '--xml', '-e', statement), statement)
    return listing


def target_garage(ns):
    def call(endpoint, payload=None):
        return kubectl('-n', ns, 'exec', 'garage-0', '--', '/garage', 'json-api', endpoint,
                       *([json.dumps(payload)] if payload else []))
    return call


def store_subset(items):
    """The objects of the stores and Temporal: no application service and no garage-init Job (see create_zone())."""
    return [i for i in items if i['kind'] in ('Namespace', 'ConfigMap', 'PersistentVolume', 'PersistentVolumeClaim',
                                              'NetworkPolicy')
            or (i['kind'] != 'Job' and i['metadata'].get('labels', {}).get(manifests_part()) in STORE_PARTS)
            or (i['kind'] == 'Service' and i['metadata']['name'] in STORE_PARTS)
            or (i['kind'] == 'Job' and i['metadata']['name'].startswith('temporal-retention'))]


def manifests_part():
    import manifests
    return manifests.PART


def found_stores(ns):
    return {'clickhouse': clickhouse_counts(target_clickhouse(ns)),
            'manticore': manticore_tables(target_manticore_listing(ns, 'manticore-0')),
            'manticore_vectors': manticore_tables(target_manticore_listing(ns, 'manticore-vectors-0')),
            'garage_buckets': renames.bucket_aliases(garage_buckets(target_garage(ns)))}


def compare_stores(ns, expected, found):
    """The differences between the expected and the found store contents, and the tables with fewer rows."""
    differences, fewer = {}, {}
    # A table with a TTL clause drops its expired rows when ClickHouse starts, so it may hold fewer rows than the record.
    # A merge of a Replacing, Collapsing, Summing or Aggregating table removes the rows that it combines, and ClickHouse
    # merges parts after it starts. Such a table can hold fewer rows than the record, never more.
    query = target_clickhouse(ns)
    ttl = set(query("SELECT concat(database, '.', name) FROM system.tables WHERE create_table_query LIKE '% TTL %' "
                    "FORMAT TSV").split())
    merging = set(query("SELECT concat(database, '.', name) FROM system.tables WHERE engine REGEXP "
                        "'^(Replicated)?(Replacing|Collapsing|VersionedCollapsing|Summing|Aggregating)MergeTree' "
                        "FORMAT TSV").split())
    for key in ('clickhouse', 'manticore', 'manticore_vectors'):
        for table, count in expected[key].items():
            if found[key].get(table) != count:
                if key == 'clickhouse' and (table in ttl or table in merging) and (found[key].get(table) or 0) <= count:
                    fewer[table] = {'source': count, 'target': found[key].get(table), 'reason': 'TTL' if table in ttl else 'merge'}
                    continue
                differences[f'{key}:{table}'] = {'source': count, 'target': found[key].get(table)}
    if found['garage_buckets'] != expected['garage_buckets']:
        differences['garage_buckets'] = {'source': expected['garage_buckets'], 'target': found['garage_buckets']}
    return differences, fewer


def stores(r, revision):
    ns = r.hoover.namespace
    remove_garage_init(ns)
    apply_items(store_subset(target_items(r, revision)))
    for name in ('clickhouse', 'manticore', 'manticore-vectors', 'garage', 'zookeeper', 'temporal-cassandra', 'temporal-elasticsearch'):
        wait_ready(ns, 'statefulset', name)
    record_data = r.read('record.json')
    expected = {k: record_data[k] for k in ('clickhouse', 'manticore', 'manticore_vectors')}
    expected['garage_buckets'] = renames.bucket_aliases(record_data['garage_buckets'])
    found = found_stores(ns)
    differences, fewer = compare_stores(ns, expected, found)
    r.write('stores.json', {'found': found, 'differences': differences, 'fewer_rows': fewer})
    if differences:
        raise StepFailed(f'the target stores differ from the record: {json.dumps(differences)[:1500]}')
    wait_ready(ns, 'deployment', 'temporal')
    return {'tables': len(found['clickhouse']), 'manticore': len(found['manticore']), 'buckets': len(found['garage_buckets']),
            'fewer_rows': fewer}


def rename_plan(r):
    """The renames of the record (renames.py). The step writes it into renames.json before the first change."""
    record_data = r.read('record.json')
    plan_data = r.read('plan.json')
    hoover = r.hoover
    databases = renames.database_renames({k.split('.', 1)[0] for k in record_data['clickhouse']}, hoover)
    tables = renames.table_renames(record_data['manticore'], hoover)
    vectors = renames.table_renames(record_data['manticore_vectors'], hoover)
    buckets = renames.bucket_renames(record_data['garage_buckets'], hoover)
    paths = renames.dataset_paths(plan_data['dataset_mounts'])
    return {'databases': databases, 'manticore': tables, 'manticore_vectors': vectors, 'buckets': buckets,
            'dataset_paths': paths}


def rename_databases(query, databases):
    present = set(query('SELECT name FROM system.databases FORMAT TSV').split())
    for old, new in databases:
        if old in present and new in present:
            raise StepFailed(f'the databases {old} and {new} both exist. Inspect them before you continue.')
        if old in present:
            query(f'RENAME DATABASE {renames.ident(old)} TO {renames.ident(new)}')
        elif new not in present:
            raise StepFailed(f'the database {old} of the record does not exist, and {new} neither.')


def rename_tables(query, listing, tables, label):
    present = {row['Table'] for row in listing('SHOW TABLES')}
    for old, new in tables:
        if old in present and new in present:
            raise StepFailed(f'the {label} tables {old} and {new} both exist. Inspect them before you continue.')
        if old in present:
            out = query(f'ALTER TABLE {old} RENAME {new}')
            if 'ERROR' in out.upper():
                raise StepFailed(f'the rename of the {label} table {old} failed: {out.strip()[-300:]}')
        elif new not in present:
            raise StepFailed(f'the {label} table {old} of the record does not exist, and {new} neither.')


def rename_buckets(call, changes):
    current = renames.bucket_aliases(garage_buckets(call))
    for change in changes:
        suffix = f'@{change["accessKeyId"]}' if change['accessKeyId'] else ''
        aliases = current.get(change['bucketId'], [])
        if change['new'] + suffix not in aliases:
            call('AddBucketAlias', renames.alias_request(change, 'new'))
        if change['old'] + suffix in aliases:
            call('RemoveBucketAlias', renames.alias_request(change, 'old'))


def rename_stores(r):
    ns = r.hoover.namespace
    planned = r.read('renames.json') or rename_plan(r)
    r.write('renames.json', planned)
    rename_databases(target_clickhouse(ns), planned['databases'])
    rename_tables(target_manticore(ns, 'manticore-0'), target_manticore_listing(ns, 'manticore-0'), planned['manticore'],
                  'Manticore')
    rename_tables(target_manticore(ns, 'manticore-vectors-0'), target_manticore_listing(ns, 'manticore-vectors-0'),
                  planned['manticore_vectors'], 'Manticore vectors')
    rename_buckets(target_garage(ns), planned['buckets'])
    # The UPDATE statements wait for their mutations (mutations_sync = 2), so the check below reads the new values.
    query = target_clickhouse(ns, ('--mutations_sync', '2'))
    new_databases = [new for _, new in planned['databases']]
    columns = []
    if new_databases:
        listed = ', '.join(renames.quote(d) for d in new_databases)
        text = query(f"SELECT database, table, name, is_in_sorting_key FROM system.columns WHERE database IN ({listed}) "
                     f"AND endsWith(name, {renames.quote(renames.S3_COLUMN_SUFFIX)}) AND type = 'String' FORMAT JSONEachRow")
        columns = [(c['database'], c['table'], c['name'], bool(c['is_in_sorting_key']))
                   for c in map(json.loads, text.splitlines()) if c]
    statements = renames.s3_path_updates(columns, renames.bucket_map(planned['buckets']))
    processing = f'{r.hoover.clickhouse_database_prefix}_Processing'
    update = renames.dataset_path_update(processing, planned['dataset_paths'])
    if update and processing in new_databases:
        statements.append(update)
    for statement in statements:
        query(statement)
    record_data = r.read('record.json')
    expected = {'clickhouse': renames.renamed_counts(r.read('stores.json')['found']['clickhouse'], planned['databases']),
                'manticore': renames.renamed_tables(record_data['manticore'], planned['manticore']),
                'manticore_vectors': renames.renamed_tables(record_data['manticore_vectors'], planned['manticore_vectors']),
                'garage_buckets': renames.renamed_aliases(record_data['garage_buckets'], planned['buckets'])}
    found = found_stores(ns)
    differences, fewer = compare_stores(ns, expected, found)
    r.write('renames-check.json', {'found': found, 'differences': differences, 'fewer_rows': fewer, 'statements': statements})
    if differences:
        raise StepFailed(f'the stores differ from the renamed record: {json.dumps(differences)[:1500]}')
    return {'databases': len(planned['databases']), 'tables': len(planned['manticore']) + len(planned['manticore_vectors']),
            'bucket_aliases': len(planned['buckets']), 'updates': len(statements)}


def target_temporal(ns):
    def cli(*args):
        return kubectl('-n', ns, 'exec', 'deploy/temporal', '--', 'temporal', *args, '--address', 'temporal:7233')
    return cli


def temporal_check(r):
    ns = r.hoover.namespace
    source = r.read('record.json')
    deadline = time.monotonic() + 600
    while True:
        try:
            found = temporal_record(target_temporal(ns))
            break
        except StepFailed:
            if time.monotonic() > deadline:
                raise
            time.sleep(10)
    differences = {}
    for key in ('namespaces', 'search_attributes', 'counts'):
        if json.loads(json.dumps(found[key])) != json.loads(json.dumps(source[key])):
            differences[key] = {'source': source[key], 'target': found[key]}
    for wid, w in source['open'].items():
        t = found['open'].get(wid)
        if not t or t['run_id'] != w['run_id'] or t['events'] < w['events']:
            differences[f'open:{wid}'] = {'source': w, 'target': t}
    r.write('temporal.json', {'found': found, 'differences': differences})
    if differences:
        raise StepFailed(f'the target Temporal differs from the record: {json.dumps(differences)[:1500]}')
    return {'namespaces': len(found['namespaces']), 'open': len(found['open']), 'counts': found['counts']}


def workers(r, revision):
    module = operator_settings()
    state = module.State(r.site.operator_state())
    while True:
        try:
            settings_revision = state.save(state.revision(), {f'zone:{r.zone}': {'app.hoover': None}}, actor='import',
                                           note=f'import of {r.zone}')
            break
        except module.StaleRevision:
            continue
    import manifests
    items = json.loads(manifests.render(render_target(r, revision, settings_revision)))['items']
    apply_items(items)
    ns = r.hoover.namespace
    for kind, name in (('statefulset', 'hoover-workers'), ('deployment', 'hoover-singletons'), ('deployment', 'hoover-operations'),
                       ('deployment', 'hoover-website')):
        wait_ready(ns, kind, name, 1800)
    # The installation now runs this settings revision, so its scopes stop showing those values as pending.
    state.record_scopes([f'hoover:{r.zone}', f'zone:{r.zone}'], settings_revision, f'import:{r.zone}', revision)
    return {'objects': len(items), 'settings_revision': settings_revision}


def next_wakeup(r, key):
    """The time of the next event that the workflow waits for, from its recorded history: the end of its last timer, or
    the first run of a cron workflow. None when the workflow waits for no time."""
    ns, wid = key.split('/', 1)
    path = r.path('histories') / f'{ns}--{wid}.json'
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    events = data.get('events', data if isinstance(data, list) else [])
    if not events:
        return None
    last = events[-1]

    def seconds(text):
        return float(str(text).rstrip('s') or 0)

    def stamp(text):
        from datetime import datetime
        return datetime.fromisoformat(text.replace('Z', '+00:00')).timestamp()
    attributes = next((v for k, v in last.items() if k.endswith('Attributes')), {})
    if last['eventType'] == 'EVENT_TYPE_TIMER_STARTED':
        return stamp(last['eventTime']) + seconds(attributes.get('startToFireTimeout', 0))
    if last['eventType'] == 'EVENT_TYPE_WORKFLOW_EXECUTION_STARTED' and attributes.get('firstWorkflowTaskBackoff'):
        return stamp(last['eventTime']) + seconds(attributes['firstWorkflowTaskBackoff'])
    return None


def resume(r, timeout):
    ns = r.hoover.namespace
    source = r.read('record.json')
    cli = target_temporal(ns)
    deadline = time.monotonic() + timeout
    progress = {}
    while True:
        for key, w in source['open'].items():
            n, wid = key.split('/', 1)
            described = json.loads(cli('workflow', 'describe', '-n', n, '-w', wid, '-r', w['run_id'], '-o', 'json'))
            info = described.get('workflowExecutionInfo', {})
            progress[key] = {'status': info.get('status'), 'history_length': int(info.get('historyLength', 0)),
                             'recorded_length': w['events'], 'type': w['type']}
            if progress[key]['history_length'] <= w['events'] and info.get('status') == 'WORKFLOW_EXECUTION_STATUS_RUNNING':
                due_at = next_wakeup(r, key)
                if due_at and due_at > time.time():
                    progress[key]['waits_until'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(due_at))
                # A parent gets its next event when a child closes. Each child is a recorded workflow of its own.
                children = described.get('pendingChildren') or []
                if children:
                    progress[key]['waits_for_children'] = len(children)
                # Temporal writes the start of an activity into the history when it ends, so a started activity of a
                # target worker is progress without a new event.
                started = [a['activityType']['name'] for a in described.get('pendingActivities') or []
                           if a.get('state') == 'PENDING_ACTIVITY_STATE_STARTED']
                if started:
                    progress[key]['started_activities'] = started

        def passed(p):
            return (p['history_length'] > p['recorded_length'] or p['status'] != 'WORKFLOW_EXECUTION_STATUS_RUNNING'
                    or p.get('waits_until') or p.get('waits_for_children') or p.get('started_activities'))
        moved = all(passed(p) for p in progress.values())
        if moved or time.monotonic() > deadline:
            break
        time.sleep(20)
    r.write('resume.json', progress)
    if not moved:
        waiting = [k for k, p in progress.items() if not passed(p)]
        raise StepFailed(f'these open workflows have no new events after {timeout} s: {waiting}')
    return {'workflows': len(progress), 'closed': sum(p['status'] != 'WORKFLOW_EXECUTION_STATUS_RUNNING' for p in progress.values())}


def owners(r):
    """The usernames that own imported chats and boards, and the admin flag of each in the Compose install."""
    db = f'{r.hoover.clickhouse_database_prefix}_Processing'
    text = target_clickhouse(r.hoover.namespace)(
        f"SELECT DISTINCT owner AS name FROM {db}.boards FINAL UNION DISTINCT SELECT DISTINCT username AS name FROM {db}.chat_sessions FINAL "
        f"FORMAT TSV")
    names = sorted(n for n in text.split() if n)
    groups = target_clickhouse(r.hoover.namespace)(
        f"SELECT username, groupname FROM {db}.user_group_membership FINAL WHERE origin = 'header' AND is_deleted = 0 FORMAT TSV")
    admin = {line.split('\t')[0] for line in groups.splitlines() if line.split('\t')[-1] in ('admin', 'superuser')}
    return {n: n in admin for n in names}


def users(r):
    """Create an openDesk user of the zone for each owner of imported chats and boards that the zone lacks.

    The Compose install signed every request in as one header identity, so the owners have no zone account. The user
    gets the same username, so the website finds the owner of the data. An owner that was an administrator in Compose
    joins Domain Admins, the administrator group of the cluster render (website.admin_groups). The passwords are in
    <state folder>/zones/<zone>/imported-users.json. The step prints no password.
    """
    import settings as k3s_settings
    sys.path.insert(0, str(K3S / 'zones'))
    k3s_settings.use_kubeconfig()
    import udm
    import secrets as random
    import string
    import urllib.parse
    call = udm.client(r.zone)
    base = 'dc=swp-ldap,dc=internal'
    path = k3s_settings.PRIVATE / 'zones' / r.zone / 'imported-users.json'
    stored = json.loads(path.read_text()) if path.exists() else {}
    flags = {f'opendesk{a}Enabled': True for a in ('Fileshare', 'Projectmanagement', 'Knowledgemanagement', 'Livecollaboration',
                                                   'Notes', 'Videoconference')}
    result = {}
    for name, admin in owners(r).items():
        found = udm.user(call, name)
        groups = [f'cn=Domain Users,cn=groups,{base}'] + ([f'cn=Domain Admins,cn=groups,{base}'] if admin else [])
        if found is None:
            alphabet = string.ascii_letters + string.digits
            while True:
                value = ''.join(random.choice(alphabet) for _ in range(20))
                if any(c.isdigit() for c in value) and any(c.isupper() for c in value) and any(c.islower() for c in value):
                    break
            call('POST', 'users/user/', {'position': f'cn=users,{base}', 'properties': {
                'username': name, 'firstname': name, 'lastname': 'Imported', 'password': value, 'groups': groups,
                'mailPrimaryAddress': f'{name}@{site_config.zone_domain(r.zone, r.site.domain)}', **flags}})
            stored[name] = value
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(stored, indent=1) + '\n')
            path.chmod(0o600)
            result[name] = 'created' + (', Domain Admins' if admin else '')
        else:
            dn = urllib.parse.quote(found['dn'], safe='')
            missing = [g for g in groups if g not in (found['properties'].get('groups') or [])]
            if missing:
                _, headers, _ = call('GET', f'users/user/{dn}')
                call('PATCH', f'users/user/{dn}', {'properties': {'groups': sorted(set((found['properties'].get('groups') or []) + groups))}},
                     {'If-Match': headers.get('Etag', '*')})
            result[name] = 'exists' + (', joined ' + ', '.join(m.split(',')[0][3:] for m in missing) if missing else '')
    return result


def dataset_option(text):
    name, sep, folder = str(text).partition('=')
    if not sep or not name or not folder:
        raise argparse.ArgumentTypeError(f'{text} is not NAME=FOLDER')
    return name, folder


def parse(argv):
    parser = argparse.ArgumentParser(prog='deploy-k3s import-compose', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('zone')
    parser.add_argument('folder', nargs='?')
    parser.add_argument('--home')
    parser.add_argument('--ini')
    parser.add_argument('--source-node')
    parser.add_argument('--engine', choices=('docker', 'podman'))
    parser.add_argument('--dataset', type=dataset_option, action='append', default=[])
    parser.add_argument('--without-dataset', action='append', default=[])
    parser.add_argument('--until', choices=STEPS)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--timeout', type=int, default=1800, help='the seconds that the resume step waits')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--users', action='store_true')
    parser.add_argument('--site', default=os.environ.get('HOOVER4_SITE'))
    args = parser.parse_args(argv)
    if not args.site:
        parser.error('give the site file with --site FILE, or set HOOVER4_SITE.')
    if not site_config.ZONE.fullmatch(args.zone):
        parser.error(f'{args.zone} is not a zone id: zone- and 1 to 12 characters from a-z and 0-9.')
    args.engine_given = args.engine
    return args


def main(argv):
    args = parse(argv)
    os.environ['HOOVER4_SITE'] = str(Path(args.site).resolve())
    import clusterstate
    import oplock
    import settings as k3s_settings
    import manifests
    site = site_config.read(args.site)
    r = Run(site, args.zone, Path(args.site).resolve())
    if args.status:
        print(json.dumps({'zone': args.zone, 'inputs': r.inputs, 'steps': r.read('steps.json', {})}, indent=1))
        return
    inputs = check_arguments(r, args) if r.inputs else {}
    source_node = inputs.get('source_node') or args.source_node or args.home
    if source_node not in site.nodes:
        raise StepFailed(f'the source node {source_node} is not a node of the site. Give --home or --source-node.')
    Source.engine = inputs.get('engine') or args.engine or 'docker'
    Source.node = site.nodes[source_node]
    r.revision = inputs.get('revision') or manifests.resolve_revision()
    k3s_settings.use_kubeconfig()
    lock = oplock.site_lock(site.operator_state())
    try:
        lock.acquire('import', f'import-{args.zone}')
    except oplock.Busy as error:
        raise StepFailed(str(error)) from None
    try:
        if isinstance(lock, oplock.LeaseLock):
            # zone.py and this command write the zone state and the operator settings into the cluster copy.
            os.environ[clusterstate.ENV] = '1'
            clusterstate.pull(site.state_folder())
        try:
            run_steps(r, args, manifests.resolve_revision())
        finally:
            clusterstate.checkpoint(site.state_folder())
    finally:
        lock.release()


def run_steps(r, args, revision):
    zones = set(site_config.hoovers(r.site))
    if args.users:
        if not r.done('workers'):
            raise StepFailed('the users step runs after the workers step.')
        result = users(r)
        r.write('users.json', result)
        print(json.dumps({'step': 'users', 'result': result}))
        return
    if args.dry_run:
        if r.done('plan'):
            raise StepFailed('the plan step has finished. --dry-run belongs to a new import.')
        plan(r, args, zones, dry_run=True)
        return
    message = refusal(r, zones)
    if message:
        raise StepFailed(message)
    functions = {'plan': lambda: plan(r, args, zones), 'freeze': lambda: freeze(r), 'record': lambda: record(r),
                 'stop': lambda: stop_source(r), 'zone': lambda: create_zone(r), 'images': lambda: images(r),
                 'copy': lambda: copy(r, revision), 'secrets': lambda: secrets(r), 'stores': lambda: stores(r, revision),
                 'renames': lambda: rename_stores(r), 'temporal': lambda: temporal_check(r),
                 'workers': lambda: workers(r, revision), 'resume': lambda: resume(r, args.timeout)}
    import clusterstate
    for step in STEPS:
        if not r.done(step):
            if step != 'plan':
                check_inputs(r, revision)
            started = time.monotonic()
            summary = {**(functions[step]() or {}), 'seconds': round(time.monotonic() - started, 1)}
            r.finish(step, summary)
            print(json.dumps({'step': step, 'state': 'done', 'summary': summary}), flush=True)
            clusterstate.checkpoint(r.site.state_folder())
        if step == args.until:
            break


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except (site_config.SiteError, compose_source.SourceError, renames.RenameError) as error:
        raise SystemExit(str(error))
