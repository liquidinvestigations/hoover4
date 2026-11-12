#!/usr/bin/env python3
"""Move a stopped Compose installation of Hoover into a Hoover installation of the cluster, offline.

The target is a [hoover.<name>] section of the site file with source_ini, the hoover4.ini of the Compose install.
Each step writes its result into <operator state>/migration/<run>/ and prints a JSON summary. A step that finished is
not run again. The steps follow the offline sequence of the design: the source stays unchanged and stopped from the
copy on, and no target service starts before the hashes of its copy are verified.

  plan      Reads the source ini with the compatibility reader (removed settings such as Serena are reported and left
            out), the folder sizes, the owner of each folder, the uid and gid maps of the rootless Podman runtime, the
            content id of each store and Temporal image, and the claim of the target for each folder. It checks the
            free space of the volume group. With --dry-run it prints the plan and writes nothing.
  freeze    Stops the services that accept new work (the website and its sign-in proxy, the MCP and agent servers),
            then the workers and the operations worker with their Compose grace period. Temporal and the stores run on.
  record    Records the Temporal namespaces, search attributes, workflow counts by status, every open workflow with
            its run id and history length, the history of each open workflow, the row counts of each table of the
            Hoover databases, the Manticore tables and the Garage buckets.
  stop      Stops Temporal, then the stores (Cassandra after nodetool drain), then every other source container.
  images    Saves each store and Temporal image from Podman and imports it into the containerd of k3s, and checks that
            the content id in the cluster is the source id.
  copy      Creates the target claims, binds them with a short pod, and copies each source folder into its volume with
            root_copy.py: owners mapped, one hash for each file. It then verifies each target against its manifest.
            An interrupted folder is cleared and copied again. A copied folder is not copied again.
  secrets   Writes the Secret hoover-runtime with the Compose store credentials and the shared secrets of the source key
            files, and keeps the other present values.
  stores    Applies the namespace objects, the stores, Temporal and the interfaces of the render, without the
            application services, and compares the store contents with the record. A ClickHouse table with a TTL or a
            merging engine may hold fewer rows than the record, because ClickHouse removes rows at start and in merges.
  temporal  Compares the namespaces, search attributes, counts and open workflows of the target Temporal with the
            record. Every open workflow must have its run id and at least its recorded history length.
  workers   Applies the whole render, so the workers, the website and the other services start.
  resume    Waits until each recorded open workflow has new history events or has closed. A workflow whose recorded last
            event is a timer or a cron start that ends after now passes as waiting, with the time that it waits for. A
            parent with open child workflows passes as waiting for them.
  users     Creates a zone user for each owner of migrated chats and boards (users()). It is not part of the sequence.
Source and destination. The source containers and folders belong to the source host: this host, or the host of
--source-host over SSH. --engine names their runtime: docker (rootful, so a file owner of the host is the owner inside
the container) or podman (rootless, so the owners map through the uid and gid maps of the user namespace). The
destination is the home node of the installation. When the home node is the local node of the site, the copy mounts
each target volume on this host (root_copy.py copy). Otherwise the copy streams a tar with the mapped owners
(root_copy.py pack) from the source host into a short pod on the home node that mounts the claim, and verifies the
claim inside that pod against the manifest. The record of each claim keeps its UID and volume, and a resume refuses a
claim with another identity. A remote destination imports the store images through the root route of the home node.
Run inputs. plan writes inputs.json before the freeze: the commit of the render, the saved settings revision after the
seed, the SHA-256 of the site file, the engine, the source host, the image ids and the storage identity. Every later
step compares the site file and the commit with inputs.json, and every render uses the pinned settings revision. A
changed input stops the step. The workers step records the settings revision of the installation as applied after its
workloads are ready.
Each mutating step holds the site operation lock (../oplock.py).
Usage: migrate.py <step> <installation> [--run NAME] [--site FILE] [--revision REV] [--engine docker|podman]
                  [--source-host HOST] [--dry-run]
       migrate.py status <installation> [--run NAME]
"""
import argparse
import base64
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
K3S = HERE.parent
sys.path.insert(0, str(K3S))
sys.path.insert(0, str(K3S / 'hoover'))
import config as site_config  # noqa: E402
import settings as k3s_settings  # noqa: E402
import manifests  # noqa: E402
import oplock  # noqa: E402
sys.path.insert(0, str(K3S / 'driver'))
import hostroute  # noqa: E402

STEPS = ('plan', 'freeze', 'record', 'stop', 'images', 'copy', 'secrets', 'stores', 'temporal', 'workers', 'resume')
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
# Folders of volumes_path that the target does not copy, and why.
SKIPPED = {'hoover4-website-target': 'the build folder of the development website. The release image holds the server.',
           'easyocr_models_cache': 'a model cache. The worker downloads the models again.'}
# The claim of the worker plan files of pod 0 (manifests.py volumeClaimTemplates of hoover-workers).
WORKER_CLAIM = 'worker-temp-files-hoover-workers-0'
MOUNTS = Path('/run/hoover4-migration')
# The image of the short pod that binds the claims: the pinned image of the operator portal, which every site has.
BIND_IMAGE = 'docker.io/library/python:3.14-alpine@sha256:7f2ec713f0436c59df2362d973b6a05af9e87ba78f0e94f5245c302984a7a1fd'


class StepFailed(SystemExit):
    pass


def run(argv, input=None, check=True, timeout=None):
    r = subprocess.run([str(a) for a in argv], input=input, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise StepFailed(f'{" ".join(str(a) for a in argv[:6])} failed: {(r.stderr or r.stdout).strip()[-800:]}')
    return r.stdout


def kubectl(*args, input=None, check=True):
    return run(['kubectl', '--kubeconfig', k3s_settings.KUBECONFIG, *args], input=input, check=check)


def sudo(*args, input=None, check=True):
    return run(['sudo', '-n', *args], input=input, check=check)


class Source:
    """The container runtime and the host of the source install. A command runs there, locally or over SSH."""
    engine = 'docker'
    host = ''

    @classmethod
    def argv(cls, argv):
        argv = [str(a) for a in argv]
        if not cls.host:
            return argv
        return ['ssh', *hostroute.SSH_OPTIONS, cls.host, '--', ' '.join(shlex.quote(a) for a in argv)]


def src(argv, input=None, check=True, timeout=None):
    """Run a command on the source host."""
    return run(Source.argv(argv), input=input, check=check, timeout=timeout)


def src_sudo(*args, input=None, check=True):
    return src(['sudo', '-n', *args], input=input, check=check)


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


def site_fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Run:
    """The folder and the step records of one migration run."""

    def __init__(self, site, hoover, name, site_path):
        self.site, self.hoover, self.site_path = site, hoover, str(site_path)
        self.folder = site.operator_state() / 'migration' / f'{hoover.name}-{name}'
        self.folder.mkdir(parents=True, exist_ok=True)

    def path(self, name):
        return self.folder / name

    def read(self, name, default=None):
        path = self.path(name)
        return json.loads(path.read_text()) if path.exists() else default

    def write(self, name, value):
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


# ----------------------------------------------------------------------------------------------------------------------
# Plan
# ----------------------------------------------------------------------------------------------------------------------

def du(path):
    out = src_sudo('du', '-sb', path)
    return int(out.split()[0])


def owner(path):
    return [int(x) for x in src_sudo('stat', '-c', '%u %g', path).split()]


def image_ids(containers=STORE_CONTAINERS):
    out = {}
    for name in containers:
        found = json.loads(src(engine('inspect', name)))[0]
        out[name] = {'reference': found['Config']['Image'], 'id': found['Image'].removeprefix('sha256:')}
    return out


def folder_claims(source):
    """{source folder: claim} of every copied folder of the source."""
    out = {}
    for folder, path in sorted(source.volumes.items()):
        if folder in SKIPPED:
            continue
        claim = manifests.CLAIMS.get(folder)
        if claim == 'worker-temp-files':
            claim = WORKER_CLAIM
        if claim:
            out[path] = claim
    if source.ops_backup_dir != source.volumes['ops_backups']:
        out.pop(source.volumes['ops_backups'], None)
        out[source.ops_backup_dir] = 'ops-backups'
    for mount in source.dataset_mounts:
        if mount['writable']:
            out[mount['host_path']] = f"dataset-{mount['name'].replace('_', '-')}"
    return out


def plan(r, dry_run=False):
    hoover = r.hoover
    if not hoover.source_ini:
        raise StepFailed(f'[hoover.{hoover.name}] has no source_ini. A migration needs the hoover4.ini of the Compose install.')
    source = site_config.read_source_ini(hoover.source_ini)
    claims = folder_claims(source)
    folders = {}
    for path, claim in claims.items():
        folders[path] = {'claim': claim, 'bytes': du(path), 'owner': owner(path)}
    uid_map, gid_map = owner_maps()
    vg = r.site.nodes[hoover.home_node].lvm_volume_group
    free = volume_group_free(r.site, hoover.home_node, vg)
    target = manifests.target_from_site(r.site_path, hoover.name, revision='0' * 40)
    sizes = {c: target.values.get(f'volume.{c}', target.values['volume.upload-tmp']) for c in set(claims.values())}
    sizes[WORKER_CLAIM] = target.values['volume.worker-temp-files']
    needed = sum(parse_size(s) for s in sizes.values())
    problems = []
    for path, row in folders.items():
        # A claim needs the source bytes and room for the startup changes of its store.
        if row['bytes'] * 1.5 > parse_size(sizes[row['claim']]):
            problems.append(f"{path} holds {row['bytes']} bytes, and the claim {row['claim']} has {sizes[row['claim']]}. "
                            f"Save a larger volume.{row['claim']} in the operator settings.")
    if needed > free:
        problems.append(f'the claims need {needed} bytes, and the volume group {vg} has {free} free.')
    result = {'installation': hoover.name, 'namespace': hoover.namespace, 'source_ini': hoover.source_ini,
              'dropped_settings': source.dropped, 'volumes_path': source.volumes_path, 'folders': folders,
              'skipped': {source.volumes[k]: v for k, v in SKIPPED.items() if k in source.volumes},
              'read_only_mounts': [m for m in source.dataset_mounts if not m['writable']],
              'chat_control_dir': source.chat_control_dir, 'uid_map': uid_map, 'gid_map': gid_map,
              'images': image_ids(), 'claim_sizes': sizes, 'volume_group': vg, 'free_bytes': free, 'needed_bytes': needed,
              'identity': hoover.identity(), 'history_shards': source.values['main_services'].get('temporal_history_shards'),
              'problems': problems}
    if dry_run:
        print(json.dumps(result, indent=1))
        return result
    if problems:
        r.write('plan-refused.json', result)
        raise StepFailed('the plan has problems:\n    ' + '\n    '.join(problems))
    # The explicit values of the source ini become saved operator settings of the installation once (OQ10). A value
    # that an operator saved stays.
    state = manifests.operator_settings.State(r.site.operator_state())
    result['settings_revision'] = state.seed(f'hoover:{hoover.name}', source, actor='migration')
    r.write('plan.json', result)
    r.write('inputs.json', pinned_inputs(r, r.revision, result))
    return {'folders': len(folders), 'bytes': sum(f['bytes'] for f in folders.values()), 'free': free,
            'settings_revision': result['settings_revision']}


def volume_group_free(site, node_name, vg):
    """The free bytes of the volume group of the home node: vgs on the local node, else the TopoLVM node capacity."""
    if site.nodes[node_name].local:
        return int(float(sudo('vgs', '--noheadings', '--units', 'b', '--nosuffix', '-o', 'vg_free', vg).strip()))
    annotations = json.loads(kubectl('get', 'node', node_name, '-o', 'jsonpath={.metadata.annotations}') or '{}')
    values = [int(v) for k, v in annotations.items() if k.startswith('capacity.topolvm.io/') and v.isdigit()]
    if not values:
        raise StepFailed(f'the node {node_name} reports no TopoLVM capacity.')
    return max(values)


def pinned_inputs(r, revision, result):
    """The inputs of the run, written once by plan."""
    state = manifests.operator_settings.State(r.site.operator_state())
    return {'revision': revision, 'settings_revision': state.revision(), 'site_fingerprint': site_fingerprint(r.site_path),
            'engine': Source.engine, 'source_host': Source.host, 'images': result['images'],
            'identity': result['identity'], 'home_node': r.hoover.home_node}


def check_inputs(r, revision):
    """Refuse a step whose site file, commit, engine or source host differ from inputs.json."""
    inputs = r.read('inputs.json')
    if inputs is None:
        raise StepFailed('the run has no inputs.json. Run the plan step first.')
    problems = []
    if site_fingerprint(r.site_path) != inputs['site_fingerprint']:
        problems.append('the site file changed')
    if revision and revision != inputs['revision']:
        problems.append(f'the revision {revision} is not the pinned {inputs["revision"]}')
    if (Source.engine, Source.host) != (inputs['engine'], inputs['source_host']):
        problems.append(f'the source is {Source.engine} on {Source.host or "this host"}, not {inputs["engine"]} on '
                        f'{inputs["source_host"] or "this host"}')
    if r.hoover.home_node != inputs['home_node'] or r.hoover.identity() != inputs['identity']:
        problems.append('the home node or the storage identity of the installation changed')
    if problems:
        raise StepFailed('the inputs of the run changed: ' + '; '.join(problems) + '. Start a new run with --run.')
    return inputs


def parse_size(text):
    units = {'Ki': 2**10, 'Mi': 2**20, 'Gi': 2**30, 'Ti': 2**40}
    for suffix, factor in units.items():
        if str(text).endswith(suffix):
            return int(float(str(text)[:-2]) * factor)
    return int(text)


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
    text = query("SELECT database, name, total_rows FROM system.tables WHERE database NOT IN ('system', 'INFORMATION_SCHEMA', "
                 "'information_schema') AND engine NOT IN ('View', 'MaterializedView') ORDER BY database, name FORMAT JSONEachRow")
    return {f"{row['database']}.{row['name']}": int(row['total_rows'] or 0) for row in map(json.loads, text.splitlines()) if row}


def source_clickhouse(sql):
    return src(engine('exec', '-i', 'clickhouse', 'clickhouse-client', '--user', 'hoover4', '--password', 'hoover4'), input=sql)


def cells(text):
    """The rows of a mysql client answer of Manticore, which prints a table with borders or tab-separated lines."""
    rows = []
    for line in text.splitlines():
        if line.startswith('+') or not line.strip() or line.startswith('mysql:'):
            continue
        parts = [c.strip() for c in (line.strip('|').split('|') if line.startswith('|') else line.split('\t'))]
        rows.append(parts)
    return rows


def manticore_tables(query):
    out = {}
    for row in cells(query('SHOW TABLES')):
        name = row[0]
        if name in ('Table', 'Index', ''):
            continue
        count = [r[0] for r in cells(query(f'SELECT COUNT(*) FROM {name}')) if r and r[0].isdigit()]
        out[name] = int(count[0]) if count else None
    return out


def source_manticore(container):
    def query(sql):
        return src(engine('exec', container, 'mysql', '-h0', '-P9306', '-umanticore', '-pmanticore', '--batch', '-e', sql), check=False)
    return query


def record(r):
    # The record of Temporal comes first, because the stores can be read after Temporal stops.
    state = temporal_record(temporal)
    histories = r.path('histories')
    histories.mkdir(exist_ok=True)
    for key, w in state['open'].items():
        ns, wid = key.split('/', 1)
        (histories / f'{ns}--{wid}.json').write_text(temporal('workflow', 'show', '-n', ns, '-w', wid, '-r', w['run_id'], '-o', 'json'))
    state['clickhouse'] = clickhouse_counts(source_clickhouse)
    state['manticore'] = manticore_tables(source_manticore('manticore'))
    state['manticore_vectors'] = manticore_tables(source_manticore('manticore-vectors'))
    state['garage_buckets'] = sorted(line.split()[0] for line in
                                     src(engine('exec', 'garage', '/garage', 'bucket', 'list')).splitlines()[1:] if line.strip())
    r.write('record.json', state)
    return {'namespaces': len(state['namespaces']), 'open': len(state['open']), 'tables': len(state['clickhouse']),
            'counts': state['counts']}


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
# Images, copy and secrets
# ----------------------------------------------------------------------------------------------------------------------

def home_is_local(r):
    return r.site.nodes[r.hoover.home_node].local


def home_root(r):
    """The root route of the home node through the cluster (../driver/hostroute.py)."""
    return hostroute.ClusterRoot(k3s_settings.KUBECONFIG, hostroute.Shell(r.site.nodes[r.hoover.home_node]))


def cluster_image_id(reference, r=None):
    if r is None or home_is_local(r):
        out = sudo('k3s', 'crictl', 'inspecti', '-o', 'json', reference, check=False)
    else:
        shell = hostroute.Shell(r.site.nodes[r.hoover.home_node])
        name = hashlib.sha256(reference.encode()).hexdigest()[:10]
        unit = f'hoover4-inspect-{name}-{int(time.time())}'
        path = f'/tmp/hoover4-inspect-{name}.json'
        home_root(r).start(unit, (), ['/bin/sh', '-c', f'k3s crictl inspecti -o json {shlex.quote(reference)} > {path} '
                                                       f'2>/dev/null; chmod 0644 {path}; true'])
        home_root(r).wait(unit)
        out = shell.run(f'cat {path}; rm -f {path}')[1]
    try:
        return json.loads(out)['status']['id'].removeprefix('sha256:')
    except (ValueError, KeyError):
        return ''


def import_image(r, image_id, full, folder):
    """Save a source image and import it into the containerd of the home node under the reference of the render."""
    if home_is_local(r):
        archive = Path(folder) / 'image.tar'
        with open(archive, 'wb') as out:
            subprocess.run(Source.argv(engine('save', image_id)), stdout=out, check=True, timeout=3600)
        # The archive names the image by its id. ctr tags it with the reference of the render.
        sudo('k3s', 'ctr', '-n', 'k8s.io', 'images', 'import', '--no-unpack=false', '--index-name', full, str(archive))
        archive.unlink()
        return
    shell = hostroute.Shell(r.site.nodes[r.hoover.home_node])
    path = f'/tmp/hoover4-image-{image_id[:12]}.tar'
    save = subprocess.Popen(Source.argv(engine('save', image_id)), stdout=subprocess.PIPE)
    receive = subprocess.run(shell.command(f'umask 077 && cat > {path}'), stdin=save.stdout, capture_output=True)
    save.stdout.close()
    if save.wait() or receive.returncode:
        raise StepFailed(f'the transfer of {full} to {r.hoover.home_node} failed.')
    unit = f'hoover4-import-{image_id[:12]}-{int(time.time())}'
    home_root(r).start(unit, (), ['/bin/sh', '-c', f'k3s ctr -n k8s.io images import --no-unpack=false --index-name '
                                                   f'{shlex.quote(full)} {path}; status=$?; rm -f {path}; exit $status'])
    home_root(r).wait(unit, timeout=3600)


def full_reference(reference):
    """The image reference as the render writes it (manifests.image_of)."""
    first = reference.split('/')[0]
    return reference if '/' in reference and '.' in first else f'docker.io/{reference if "/" in reference else "library/" + reference}'


def images(r):
    wanted = r.read('plan.json')['images']
    result = {}
    with tempfile.TemporaryDirectory(dir=str(r.folder)) as folder:
        for name, image in wanted.items():
            reference = image['reference']
            full = full_reference(reference)
            if cluster_image_id(full, r) != image['id'] and '@' not in full:
                import_image(r, image['id'], full, folder)
            found = cluster_image_id(full, r)
            if found != image['id']:
                raise StepFailed(f'the cluster image {full} has the id {found}, not the source id {image["id"]}.')
            result[name] = {'reference': full, 'id': found}
    r.write('images.json', result)
    return {'images': len(result)}


def target(r, revision):
    inputs = r.read('inputs.json') or {}
    return manifests.target_from_site(r.site_path, r.hoover.name, revision=revision,
                                      settings_revision=inputs.get('settings_revision'))


def target_items(r, revision):
    return json.loads(manifests.render(target(r, revision)))['items']


def claim_objects(r, revision):
    items = target_items(r, revision)
    wanted = set(r.read('plan.json')['folders'][p]['claim'] for p in r.read('plan.json')['folders'])
    out = [i for i in items if i['kind'] == 'Namespace']
    out += [i for i in items if i['kind'] in ('PersistentVolume', 'PersistentVolumeClaim')]
    if WORKER_CLAIM in wanted:
        workers = next(i for i in items if i['kind'] == 'StatefulSet' and i['metadata']['name'] == 'hoover-workers')
        template = next(t for t in workers['spec']['volumeClaimTemplates'] if t['metadata']['name'] == 'worker-temp-files')
        out.append({'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
                    'metadata': {'name': WORKER_CLAIM, 'namespace': r.hoover.namespace,
                                 'labels': {'app.kubernetes.io/name': 'hoover-workers'}}, 'spec': template['spec']})
    return out, wanted


def bind_claims(r, claims):
    """A pod that mounts each claim makes TopoLVM create its volume. The pod ends before the copy."""
    ns = r.hoover.namespace
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'migration-bind', 'namespace': ns},
           'spec': {'restartPolicy': 'Never', 'automountServiceAccountToken': False,
                    'nodeSelector': {'kubernetes.io/hostname': r.hoover.home_node},
                    'containers': [{'name': 'bind', 'image': BIND_IMAGE, 'command': ['true'], 'resources': {'limits': {'memory': '32Mi'}},
                                    'volumeMounts': [{'name': c, 'mountPath': f'/v/{c}'} for c in sorted(claims)]}],
                    'volumes': [{'name': c, 'persistentVolumeClaim': {'claimName': c}} for c in sorted(claims)]}}
    kubectl('-n', ns, 'delete', 'pod', 'migration-bind', '--ignore-not-found', '--wait=true')
    kubectl('apply', '-f', '-', input=json.dumps(pod))
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        phase = kubectl('-n', ns, 'get', 'pod', 'migration-bind', '-o', 'jsonpath={.status.phase}', check=False).strip()
        if phase in ('Succeeded', 'Failed'):
            break
        time.sleep(3)
    kubectl('-n', ns, 'delete', 'pod', 'migration-bind', '--wait=true')
    out = {}
    for c in claims:
        volume = kubectl('-n', ns, 'get', 'pvc', c, '-o', 'jsonpath={.spec.volumeName}').strip()
        if not volume:
            raise StepFailed(f'the claim {c} has no volume after the bind pod.')
        handle = kubectl('get', 'pv', volume, '-o', 'jsonpath={.spec.csi.volumeHandle}').strip()
        # The device path exists on the home node only. copy() uses it when the home node is this host.
        out[c] = f'/dev/{r.site.nodes[r.hoover.home_node].lvm_volume_group}/{handle}'
    return out


def ensure_unused(device):
    mounted = run(['findmnt', '-n', '-o', 'TARGET', '--source', device], check=False).strip()
    if mounted and not mounted.startswith(str(MOUNTS)):
        raise StepFailed(f'{device} is mounted at {mounted}. Stop the pod that uses it before the copy.')


def claim_identity(ns, claim):
    """The UID and the volume of a bound claim."""
    found = json.loads(kubectl('-n', ns, 'get', 'pvc', claim, '-o', 'json'))
    return {'uid': found['metadata']['uid'], 'volume': found['spec'].get('volumeName', '')}


def copy_pod(r, claim):
    """A short root pod on the home node that mounts one target claim at /target."""
    return {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'migration-copy', 'namespace': r.hoover.namespace},
            'spec': {'restartPolicy': 'Never', 'automountServiceAccountToken': False, 'enableServiceLinks': False,
                     'nodeSelector': {'kubernetes.io/hostname': r.hoover.home_node},
                     'containers': [{'name': 'copy', 'image': BIND_IMAGE, 'command': ['sleep', '86400'],
                                     'securityContext': {'runAsUser': 0},
                                     'resources': {'limits': {'memory': '512Mi'}},
                                     'volumeMounts': [{'name': 'target', 'mountPath': '/target'}]}],
                     'volumes': [{'name': 'target', 'persistentVolumeClaim': {'claimName': claim}}]}}


EXTRACT = ("import sys, tarfile; tarfile.open(fileobj=sys.stdin.buffer, mode='r|')"
           ".extractall('/target', numeric_owner=True, filter='fully_trusted')")


def stream_copy(r, plan_data, claims):
    """Copy each folder into its claim through a pod of the home node. A copied claim is not copied again."""
    ns = r.hoover.namespace
    script = (HERE / 'root_copy.py').read_bytes()
    progress = r.read('copy.json', {})
    for source, row in sorted(plan_data['folders'].items()):
        claim = row['claim']
        identity = claim_identity(ns, claim)
        recorded = progress.get(claim, {})
        if recorded.get('identity') and recorded['identity'] != identity:
            raise StepFailed(f'the claim {claim} has the identity {identity}, not the recorded {recorded["identity"]}. '
                             'It is another volume. Inspect it before a new run.')
        if recorded.get('verified'):
            continue
        kubectl('-n', ns, 'delete', 'pod', 'migration-copy', '--ignore-not-found', '--wait=true')
        kubectl('apply', '-f', '-', input=json.dumps(copy_pod(r, claim)))
        kubectl('-n', ns, 'wait', '--for=condition=Ready', 'pod/migration-copy', '--timeout=600s')
        exec_pod = ['kubectl', '--kubeconfig', k3s_settings.KUBECONFIG, '-n', ns, 'exec', '-i', 'migration-copy', '--']
        try:
            entries = run(exec_pod[:-1] + ['--', 'sh', '-c', 'ls -A /target | grep -vx lost+found | head -1']).strip()
            if entries and not recorded.get('started'):
                raise StepFailed(f'the claim {claim} is not empty and no copy of this run started it. Inspect it.')
            if entries:
                # An interrupted copy starts again from an empty volume.
                run(exec_pod + ['python3', '-', 'clear', '/target'], input=script.decode())
            progress[claim] = {'started': True, 'source': source, 'identity': identity, 'mode': 'stream'}
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
            kubectl('-n', ns, 'delete', 'pod', 'migration-copy', '--ignore-not-found', '--wait=false', check=False)
    return {c: {k: v for k, v in p.items() if k in ('files', 'bytes', 'seconds')} for c, p in progress.items()}


def copy(r, revision):
    plan_data = r.read('plan.json')
    if any(running(n) for n in STORE_CONTAINERS + WRITERS):
        raise StepFailed('a source store or writer runs. Run the stop step first.')
    objects, claims = claim_objects(r, revision)
    kubectl('apply', '--server-side', '--force-conflicts', '--field-manager=hoover', '-f', '-',
            input=json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': objects}))
    if not home_is_local(r):
        bind_claims(r, claims)
        return stream_copy(r, plan_data, claims)
    devices = bind_claims(r, claims)
    maps = r.path('maps')
    maps.mkdir(exist_ok=True)
    (maps / 'uid_map').write_text(plan_data['uid_map'])
    (maps / 'gid_map').write_text(plan_data['gid_map'])
    progress = r.read('copy.json', {})
    script = HERE / 'root_copy.py'
    for source, row in sorted(plan_data['folders'].items()):
        claim = row['claim']
        if progress.get(claim, {}).get('verified'):
            continue
        device = devices[claim]
        ensure_unused(device)
        mount = MOUNTS / claim
        sudo('mkdir', '-p', str(mount))
        if not run(['findmnt', '-n', str(mount)], check=False).strip():
            sudo('mount', device, str(mount))
        try:
            manifest = r.path(f'hashes-{claim}.jsonl')
            if progress.get(claim, {}).get('started'):
                # An interrupted copy starts again from an empty volume.
                sudo(sys.executable, str(script), 'clear', str(mount))
            progress[claim] = {'started': True, 'source': source, 'device': device,
                               'identity': claim_identity(r.hoover.namespace, claim)}
            r.write('copy.json', progress)
            started = time.monotonic()
            tmp_manifest = Path('/tmp') / f'hoover4-migration-{claim}.jsonl'
            sudo(sys.executable, str(script), 'copy', source, str(mount), str(maps / 'uid_map'), str(maps / 'gid_map'), str(tmp_manifest))
            shutil.copyfile(tmp_manifest, manifest) if os.access(tmp_manifest, os.R_OK) else \
                manifest.write_text(sudo('cat', str(tmp_manifest)))
            sudo('rm', '-f', str(tmp_manifest))
            verified = json.loads(sudo(sys.executable, str(script), 'verify', str(mount), str(manifest), check=False).strip().splitlines()[-1])
            if verified['differences']:
                raise StepFailed(f'the copy of {source} differs from its manifest: {verified["first"]}')
            progress[claim].update(verified=True, files=verified['files'], bytes=verified['bytes'],
                                   seconds=round(time.monotonic() - started, 1))
            r.write('copy.json', progress)
        finally:
            sudo('umount', str(mount), check=False)
    return {c: {k: v for k, v in p.items() if k in ('files', 'bytes', 'seconds')} for c, p in progress.items()}


def secrets(r):
    ns = r.hoover.namespace
    source = site_config.read_source_ini(r.hoover.source_ini, check_paths=False)
    current = kubectl('-n', ns, 'get', 'secret', 'hoover-runtime', '-o', 'json', check=False)
    data = {k: base64.b64decode(v).decode() for k, v in (json.loads(current).get('data', {}) if current else {}).items()}
    import secrets as random
    sys.path.insert(0, str(K3S / 'hoover'))
    import gpu
    wanted = {'clickhouse-user': 'hoover4', 'clickhouse-password': 'hoover4', 'manticore-user': 'manticore',
              'manticore-password': 'manticore', 's3-access-key': 'hoover4-blobs-rw', 's3-secret-key': 'hoover4-garage-blob-secret-key-0',
              'garage-rpc-secret': 'cbc5a1dbd1c832a3bdcb0abff4e5ffc950035febf867de39e9b079cec8863e1d',
              'garage-admin-token': 'hoover4-garage-admin-token', 'gpu-token': gpu.token(r.hoover.zone), 'factcheck-api-key': ''}
    taken = []
    # The shared secrets of the source key files keep the access that the Compose services had.
    for item, key in (('mcp-shared-secret', 'mcp_shared_secret_file'), ('browser-fetch-token', 'browser_fetch_token_file'),
                      ('factcheck-api-key', 'factcheck_api_key_file')):
        path = source.values.get('main_services', {}).get(key, '')
        if path and os.path.exists(path):
            wanted[item] = Path(path).read_text().strip()
            taken.append(item)
    for item in ('proxy-secret', 'mcp-shared-secret', 'browser-fetch-token'):
        wanted.setdefault(item, data.get(item) or random.token_hex(32))
    data.update(wanted)
    kubectl('apply', '-f', '-', input=json.dumps({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'hoover-runtime', 'namespace': ns},
                                                   'type': 'Opaque', 'stringData': data}))
    proxy = kubectl('-n', ns, 'get', 'secret', 'oauth2-proxy', '-o', 'json', check=False)
    proxy_data = {k: base64.b64decode(v).decode() for k, v in (json.loads(proxy).get('data', {}) if proxy else {}).items()}
    proxy_data['proxy-secret'] = data['proxy-secret']
    proxy_data.setdefault('cookie-secret', random.token_hex(16))
    zones = k3s_settings.PRIVATE / 'zones/secrets.json'
    known = json.loads(zones.read_text()).get(r.hoover.zone, {}) if zones.exists() else {}
    proxy_data['client-secret'] = known.get('hoover_oidc_secret') or proxy_data.get('client-secret') or random.token_hex(16)
    kubectl('apply', '-f', '-', input=json.dumps({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'oauth2-proxy', 'namespace': ns},
                                                   'type': 'Opaque', 'stringData': proxy_data}))
    return {'secrets': ['hoover-runtime', 'oauth2-proxy'], 'from_source_files': taken}


# ----------------------------------------------------------------------------------------------------------------------
# Target start and checks
# ----------------------------------------------------------------------------------------------------------------------

STORE_PARTS = {'clickhouse', 'manticore', 'manticore-vectors', 'garage', 'zookeeper', 'temporal-cassandra',
               'temporal-elasticsearch', 'temporal', 'temporal-ui', 'clickhouse-monitoring', 'ch-ui'}


def apply_items(items):
    kubectl('apply', '--server-side', '--force-conflicts', '--field-manager=hoover', '-f', '-',
            input=json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': items}))


def wait_ready(ns, kind, name, timeout=1200):
    kubectl('-n', ns, 'rollout', 'status', f'{kind}/{name}', f'--timeout={timeout}s')


def target_clickhouse(ns):
    def query(sql):
        return kubectl('-n', ns, 'exec', '-i', 'clickhouse-0', '--', 'clickhouse-client', '--user', 'hoover4', '--password', 'hoover4',
                       input=sql)
    return query


def target_manticore(ns, pod):
    def query(sql):
        return kubectl('-n', ns, 'exec', pod, '--', 'mysql', '-h0', '-P9306', '-umanticore', '-pmanticore', '--batch', '-e', sql, check=False)
    return query


def stores(r, revision):
    if not r.done('copy'):
        raise StepFailed('the copy step has not finished. No target store starts before its copy is verified.')
    items = target_items(r, revision)
    ns = r.hoover.namespace
    subset = [i for i in items if i['kind'] in ('Namespace', 'ConfigMap', 'PersistentVolume', 'PersistentVolumeClaim',
                                                'NetworkPolicy')
              or (i['metadata'].get('labels', {}).get(manifests.PART) in STORE_PARTS)
              or (i['kind'] == 'Service' and i['metadata']['name'] in STORE_PARTS)
              or (i['kind'] == 'Job' and i['metadata']['name'].startswith(('garage-init', 'temporal-retention')))]
    apply_items(subset)
    for name in ('clickhouse', 'manticore', 'manticore-vectors', 'garage', 'zookeeper', 'temporal-cassandra', 'temporal-elasticsearch'):
        wait_ready(ns, 'statefulset', name)
    record_data = r.read('record.json')
    found = {'clickhouse': clickhouse_counts(target_clickhouse(ns)),
             'manticore': manticore_tables(target_manticore(ns, 'manticore-0')),
             'manticore_vectors': manticore_tables(target_manticore(ns, 'manticore-vectors-0'))}
    buckets = kubectl('-n', ns, 'exec', 'garage-0', '--', '/garage', 'bucket', 'list')
    found['garage_buckets'] = sorted(line.split()[0] for line in buckets.splitlines()[1:] if line.strip())
    differences, expired = {}, {}
    # A table with a TTL clause drops its expired rows when ClickHouse starts, so it may hold fewer rows than the record.
    # The file hashes of the copy show that the copied parts are equal.
    ttl = set(target_clickhouse(ns)("SELECT concat(database, '.', name) FROM system.tables WHERE create_table_query LIKE '% TTL %' "
                                    "FORMAT TSV").split())
    # A merge of a Replacing, Collapsing, Summing or Aggregating table removes the rows that it combines, and ClickHouse
    # merges parts after it starts. Such a table can hold fewer rows than the record, never more.
    merging = set(target_clickhouse(ns)("SELECT concat(database, '.', name) FROM system.tables WHERE engine REGEXP "
                                        "'^(Replicated)?(Replacing|Collapsing|VersionedCollapsing|Summing|Aggregating)MergeTree' "
                                        "FORMAT TSV").split())
    for key in ('clickhouse', 'manticore', 'manticore_vectors'):
        for table, count in record_data[key].items():
            if found[key].get(table) != count:
                if key == 'clickhouse' and (table in ttl or table in merging) and (found[key].get(table) or 0) <= count:
                    expired[table] = {'source': count, 'target': found[key].get(table),
                                      'reason': 'TTL' if table in ttl else 'merge'}
                    continue
                differences[f'{key}:{table}'] = {'source': count, 'target': found[key].get(table)}
    if found['garage_buckets'] != record_data['garage_buckets']:
        differences['garage_buckets'] = {'source': record_data['garage_buckets'], 'target': found['garage_buckets']}
    r.write('stores.json', {'found': found, 'differences': differences, 'fewer_rows': expired})
    if differences:
        raise StepFailed(f'the target stores differ from the record: {json.dumps(differences)[:1500]}')
    wait_ready(ns, 'deployment', 'temporal')
    return {'tables': len(found['clickhouse']), 'manticore': len(found['manticore']), 'buckets': len(found['garage_buckets']),
            'fewer_rows': expired}


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
    if not r.done('temporal'):
        raise StepFailed('the temporal step has not passed. The workers start only after the Temporal checks.')
    items = target_items(r, revision)
    apply_items(items)
    ns = r.hoover.namespace
    for kind, name in (('statefulset', 'hoover-workers'), ('deployment', 'hoover-singletons'), ('deployment', 'hoover-operations'),
                       ('deployment', 'hoover-website')):
        wait_ready(ns, kind, name, 1800)
    # The installation now runs the pinned settings revision, so its scope stops showing those values as pending.
    inputs = r.read('inputs.json') or {}
    if inputs.get('settings_revision') is not None:
        state = manifests.operator_settings.State(r.site.operator_state())
        state.record_scopes([f'hoover:{r.hoover.name}'], inputs['settings_revision'], f'migration:{r.folder.name}', revision)
    return {'objects': len(items), 'settings_revision': inputs.get('settings_revision')}


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
    """The usernames that own migrated chats and boards, and the admin flag of each in the Compose install."""
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
    """Create an openDesk user of the zone for each owner of migrated chats and boards that the zone lacks.

    The Compose install signed every request in as one header identity, so the owners have no zone account. The user
    gets the same username, so the website finds the owner of the data. An owner that was an administrator in Compose
    joins Domain Admins, the administrator group of the cluster render (website.admin_groups). The passwords are in
    k3s/private/zones/<zone>/migrated-users.json. The step prints no password.
    """
    sys.path.insert(0, str(K3S / 'zones'))
    k3s_settings.use_kubeconfig()
    import udm
    import secrets as random
    import string
    import urllib.parse
    call = udm.client(r.hoover.zone)
    base = 'dc=swp-ldap,dc=internal'
    path = k3s_settings.PRIVATE / 'zones' / r.hoover.zone / 'migrated-users.json'
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
                'username': name, 'firstname': name, 'lastname': 'Migrated', 'password': value, 'groups': groups,
                'mailPrimaryAddress': f'{name}@{r.hoover.zone}.{r.site.suffix}', **flags}})
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


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('step', choices=STEPS + ('status', 'users'))
    parser.add_argument('installation')
    parser.add_argument('--run', default='1')
    parser.add_argument('--site', default=str(k3s_settings.SITE_FILE))
    parser.add_argument('--revision')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--timeout', type=int, default=1800)
    parser.add_argument('--engine', choices=('docker', 'podman'), default='docker',
                        help='the runtime of the source containers. The default is docker.')
    parser.add_argument('--source-host', default='', help='the SSH host of the source install. The default is this host.')
    args = parser.parse_args(argv)
    Source.engine, Source.host = args.engine, args.source_host
    site = site_config.read(args.site)
    hoover = manifests.find_hoover(site, args.installation)
    r = Run(site, hoover, args.run, args.site)
    if args.step == 'status':
        print(json.dumps(r.read('steps.json', {}), indent=1))
        return
    if args.step == 'users':
        if not r.done('workers'):
            raise StepFailed('the users step runs after the workers step.')
        result = users(r)
        r.write('users.json', result)
        print(json.dumps({'step': 'users', 'result': result}))
        return
    if args.step == 'plan' and args.dry_run:
        plan(r, dry_run=True)
        return
    if r.done(args.step):
        print(json.dumps({'step': args.step, 'state': 'done', **r.read('steps.json')[args.step]}))
        return
    index = STEPS.index(args.step)
    missing = [s for s in STEPS[:index] if not r.done(s)]
    if missing:
        raise StepFailed(f'the step {args.step} needs the steps {", ".join(missing)} first.')
    # The images of the cluster carry the revision of the applied deployment (deploy-k3s), which the render must name.
    applied = site.operator_state() / 'deploy' / 'applied.json'
    applied_revision = json.loads(applied.read_text()).get('revision') if applied.exists() else None
    pinned = (r.read('inputs.json') or {}).get('revision')
    revision = args.revision or pinned or applied_revision or manifests.resolve_revision()
    r.revision = revision
    if args.step != 'plan':
        check_inputs(r, revision)
    lock = oplock.SiteLock(site.operator_state())
    try:
        lock.acquire('migration', f'migration-{r.folder.name}-{args.step}')
    except oplock.Busy as error:
        raise StepFailed(str(error))
    functions = {'plan': lambda: plan(r), 'freeze': lambda: freeze(r), 'record': lambda: record(r), 'stop': lambda: stop_source(r),
                 'images': lambda: images(r), 'copy': lambda: copy(r, revision), 'secrets': lambda: secrets(r),
                 'stores': lambda: stores(r, revision), 'temporal': lambda: temporal_check(r),
                 'workers': lambda: workers(r, revision), 'resume': lambda: resume(r, args.timeout)}
    started = time.monotonic()
    try:
        summary = functions[args.step]()
    finally:
        lock.release()
    summary = {**(summary or {}), 'seconds': round(time.monotonic() - started, 1)}
    r.finish(args.step, summary)
    print(json.dumps({'step': args.step, 'state': 'done', 'summary': summary}))


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except site_config.SiteError as error:
        raise SystemExit(str(error))
