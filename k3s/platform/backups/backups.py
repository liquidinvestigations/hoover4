#!/usr/bin/env python3
"""Run the optional backups of a site and restore a copy into an isolated target.

The site file [backup] names the node and the folder of the destination. The operator settings `backup.*` of the
applied revision turn each job on and set its retained copies. Without [backup] or with every job off, nothing runs.
schedule.py holds the rules. This file reads the receipts and the sizes, runs one job at a time and keeps the state in
<operator state>/backups/state.json, which it writes atomically.

Arguments are names: a zone, a collection, a job and a generation (the name of a copy). No command takes a host path.
The site file [backup] names the node and the mount folder of the destination. The copies of a zone are in
<mount>/zones/<zone>/<generation>/, the collection exports of a zone in <mount>/zones/<zone>/collections/<collection>/
<generation>/, and the platform copies in <mount>/platform/<generation>/. The level zones/ keeps a zone named
platform apart from the platform copies.

Jobs:
- zone:<zone>: the complete zone, which is its openDesk namespace and its complete Hoover installation. The copy holds
  a SQL dump of each database server of the zone namespace, a tar file of each other claim, and the Secrets and
  ConfigMaps of the namespace. The folder hoover/<installation>/ holds the same parts of the Hoover namespace: its
  claims, Secrets and ConfigMaps. The tar files keep the owners and modes. A file system claim is read through a short
  pod in its namespace. The pod does not ask for a read-only mount of the claim, because the kernel refuses a second
  mount of a mounted ext4 device with other options. Its container mount is read-only. A Block claim holds the file
  system of a Kata store, which only the guest of the store pod mounts, so the copy reads it through the store
  container with the busybox of ../../hoover/stores/podspec.py. A claim that a pod owns (a generic ephemeral volume)
  holds temporary files and is not copied. The earlier job key opendesk:<zone> reads as zone:<zone>.
- hoover:<zone>:<collection>: the collection export of the operations worker (main.py export-collection), streamed out
  of the claim ops-backups. The export directory in the claim is removed after the copy, so no second archive stays.
- platform: an etcd snapshot of the control-plane server with its token and k3s configuration (root-install-k3s.py
  --snapshot through the root route of that node, ../../driver/hostroute.py), the operator state and the private files
  of the site (credentials included), and recovery.json. recovery.json has format_version 2, the datastore etcd, the
  execution host, the control plane, the destination node, the k3s version, the applied source and settings
  revisions, the pinned tool versions and the application copies that a complete recovery needs. An etcd snapshot holds
  no claim data, so the application copies are part of the recovery set. read_recovery() also reads a copy of the
  earlier format, with the SQLite file k3s-state.db, for the conversion of an earlier installation. No new copy uses
  SQLite.
The copy of a job is made in <operator state>/backups/staging/ on this host. It gets copy-manifest.json with the size and
SHA-256 of every file. It then goes over the user shell of the [backup] node into <folder>/<generation>.partial,
is read again there against the manifest, and is renamed. Only then does retention remove older copies. A failed transfer
or check leaves the older copies. The capacity check, the marker check, the check of the copy and retention run on the
[backup] node.
The zone job closes intake first: it scales the applications of the zone and of its Hoover installation to zero and
suspends their CronJobs, and records the earlier replicas and suspensions in the state file. The stores keep running,
because the dumps and the Block copies need them. After the copy the job restores the recorded values. A runner that
finds a recorded closure without a running job restores it.
The zone and platform jobs hold the site operation lock (../../oplock.py), so no deployment, Apply or migration
changes the site during the copy.
restore-zone restores a complete zone copy into an installed zone: the Secrets, the claims and the database dumps of
the zone namespace and of its Hoover installation, with the applications and the other stores stopped. --from names
the zone of the copy when it differs. On a failure the zone stays closed, and the state file names the step.
A runner restart finds a job that runs (its process id and its export operation in the state) and waits for it.
Receipts of a collection come from the table operations of the installation: the first finished add_dataset of each of
its datasets, when none of its dataset operations still runs, is the ingestion receipt. A finished update_collection,
after which every included update_dataset finished without an error, is a complete reprocessing receipt.
Usage: backups.py tick                      start the next due job, as the operator runner does every minute
       backups.py status                    print the state, the next slots and the blocked jobs
       backups.py run <job> <generation>    run one job now, in the foreground
       backups.py enable                    write the marker of the destination folder
       backups.py copies                    list the copies of the destination
       backups.py verify <job> <generation>                        read a copy again against its manifest, on its node
       backups.py restore-zone <zone> <generation> [--from <zone>]  restore a complete zone copy into a zone
       backups.py restore-hoover <zone> <collection> <generation> [--from <zone>]
                                                                    import a collection copy into the zone's Hoover
       backups.py recovery <generation>                             print the recovery set of a platform copy
       backups.py restore-platform <generation>                     print the root steps that restore a platform copy
"""
import base64
import hashlib
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
K3S = HERE.parents[1]
sys.path.insert(0, str(K3S))
sys.path.insert(0, str(K3S / 'hoover'))
sys.path.insert(0, str(K3S / 'hoover' / 'stores'))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(K3S / 'driver'))
import config as site_config  # noqa: E402
import hostroute  # noqa: E402
import oplock  # noqa: E402
import podspec  # noqa: E402
import settings as k3s_settings  # noqa: E402
import schedule  # noqa: E402

# The manifest of a copy. A collection export holds its own manifest.json, which the import reads, so this file has
# another name.
MANIFEST = 'copy-manifest.json'
HELPER_IMAGE = 'docker.io/library/python:3.14-alpine@sha256:7f2ec713f0436c59df2362d973b6a05af9e87ba78f0e94f5245c302984a7a1fd'
PYTHON = ['/opt/pysetup/.venv/bin/python3', 'main.py']
# The check of a collection export before the copy: the JSON metadata of each Manticore table must parse. An export
# once held a truncated .meta file, which the import refuses. It runs in the operations pod, whose Python has
# zstandard. Argument: the export folder. Output: a JSON list of the files that do not parse.
META_CHECK = """
import glob, json, sys, tarfile, zstandard
bad = []
for archive in sorted(glob.glob(sys.argv[1] + '/manticore/*.tar.zst')):
    with open(archive, 'rb') as raw, zstandard.ZstdDecompressor().stream_reader(raw) as stream:
        with tarfile.open(fileobj=stream, mode='r|') as tar:
            for member in tar:
                if member.isfile() and member.name.endswith('.meta'):
                    try:
                        json.loads(tar.extractfile(member).read())
                    except ValueError:
                        bad.append(archive.rsplit('/', 1)[1] + ':' + member.name)
print(json.dumps(bad))
"""


NAME = __import__('re').compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}')


def name_arg(value, what='name'):
    """value when it is a name: letters, digits, '.', '_' and '-', no '/', and not '.' or '..' at the start."""
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise SystemExit(f'the {what} {value!r} is not a name. A name has letters, digits, ".", "_" and "-", and no "/".')
    return value


def job_folder(key):
    """The folder of a job below the backup mount: platform, zones/<zone> or zones/<zone>/collections/<collection>."""
    kind, _, rest = key.partition(':')
    if key == 'platform':
        return 'platform'
    if kind in ('zone', 'opendesk'):
        return f'zones/{name_arg(rest, "zone")}'
    if kind == 'hoover':
        zone, _, collection = rest.partition(':')
        return f'zones/{name_arg(zone, "zone")}/collections/{name_arg(collection, "collection")}'
    raise SystemExit(f'{key!r} is not a job. A job is platform, zone:<zone> or hoover:<zone>:<collection>.')


def kubectl(*args, input=None, check=True, stdout=None):
    r = subprocess.run(['kubectl', '--kubeconfig', k3s_settings.KUBECONFIG, *args], input=input, text=stdout is None,
                       stdout=stdout or subprocess.PIPE, stderr=subprocess.PIPE)
    if check and r.returncode:
        raise SystemExit(f'kubectl {" ".join(args[:5])} failed: {(r.stderr or b"").strip()[-500:] if isinstance(r.stderr, str) else r.stderr[-500:]}')
    return r.stdout


def operator_module():
    import manifests
    return manifests.operator_settings


def site():
    return site_config.read(k3s_settings.SITE_FILE)


def state_path(s):
    return s.operator_state() / 'backups' / 'state.json'


def load_state(s):
    """The state file. The job records of the earlier key opendesk:<zone> read as zone:<zone>."""
    path = state_path(s)
    data = json.loads(path.read_text()) if path.exists() else {'jobs': {}, 'blocked': [], 'paused': ''}
    for key in [k for k in data['jobs'] if k.startswith('opendesk:')]:
        data['jobs'].setdefault('zone:' + key.split(':', 1)[1], data['jobs'].pop(key))
    return data


def save_state(s, data):
    path = state_path(s)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + '\n')
    with open(tmp) as f:
        os.fsync(f.fileno())
    os.replace(tmp, path)


def applied_values(s, scope):
    """The effective values of a scope at its applied revision."""
    module = operator_module()
    if not (s.operator_state() / 'desired.json').exists():
        return module.effective(scope, {})
    state = module.State(s.operator_state())
    return module.effective(scope, state.overrides(state.applied_revision(scope)).get(scope, {}))


def clickhouse_command(hoover):
    """(namespace, pod, container, shell command) of the ClickHouse client of an installation.

    The local store layout runs ClickHouse in the Hoover namespace with the Compose credentials of its environment. The
    zone layout runs it in the zone namespace, and the client uses the zone user, whose password the store container
    holds in CH_ZONE_PASSWORD. No password appears in a command argument of this host.
    """
    if hoover.stores == 'zone':
        user = hoover.zone.replace('-', '_')
        return (hoover.zone, 'clickhouse-0', 'clickhouse',
                f'exec clickhouse-client --user {user} --password "$CH_ZONE_PASSWORD" --format JSONEachRow')
    return (hoover.namespace, 'clickhouse-0', None,
            'exec clickhouse-client --user "${CLICKHOUSE_USER:-hoover4}" --password "${CLICKHOUSE_PASSWORD:-hoover4}" '
            '--format JSONEachRow')


def clickhouse(hoover, sql):
    ns, pod, container, command = clickhouse_command(hoover)
    return kubectl('-n', ns, 'exec', '-i', pod, *(['-c', container] if container else []), '--', 'sh', '-c', command,
                   input=sql)


def receipts(hoover, collection):
    """The ingestion and complete reprocessing receipts of one collection, from the operations table."""
    db = f'{hoover.clickhouse_database_prefix}_Processing'
    rows = [json.loads(line) for line in clickhouse(hoover, (
        f"SELECT op_id, kind, collection_dataset, state, toUnixTimestamp(started_at) AS started, toUnixTimestamp(finished_at) AS finished "
        f"FROM {db}.operations FINAL WHERE collectionname = '{collection}' "
        f"AND kind IN ('add_dataset', 'delete_dataset', 'update_collection', 'update_dataset', 'rescan_dataset', 'execute_plans') "
        f"ORDER BY started_at")).splitlines() if line.strip()]
    return receipts_from_operations(rows)


def receipts_from_operations(rows):
    out = []
    datasets = {}
    for row in rows:
        if row['kind'] == 'add_dataset':
            datasets.setdefault(row['collection_dataset'], []).append(row)
        if row['kind'] == 'delete_dataset' and row['state'] == 'finished':
            datasets.pop(row['collection_dataset'], None)
    active = [r for r in rows if r['state'] in ('pending', 'running') and r['kind'] != 'update_collection']
    firsts = [next((r for r in ops if r['state'] == 'finished'), None) for ops in datasets.values()]
    if datasets and all(firsts) and not active:
        settled = max(r['finished'] for r in firsts)
        out.append({'kind': 'ingest', 'generation': 'ingest-' + hashlib.sha256(','.join(sorted(r['op_id'] for r in firsts)).encode()).hexdigest()[:12],
                    'settled': settled})
    for run in (r for r in rows if r['kind'] == 'update_collection' and r['state'] == 'finished'):
        included = [r for r in rows if r['kind'] == 'update_dataset' and r['started'] >= run['started']
                    and r['collection_dataset'] in datasets and r['started'] <= run['finished']]
        covered = {r['collection_dataset'] for r in included if r['state'] == 'finished'}
        if datasets and covered == set(datasets) and all(r['state'] == 'finished' for r in included):
            out.append({'kind': 'reprocess', 'generation': 'reprocess-' + run['op_id'][-12:],
                        'settled': max([run['finished']] + [r['finished'] for r in included])})
    return out


def collections(hoover):
    db = f'{hoover.clickhouse_database_prefix}_Processing'
    return [json.loads(line)['collectionname'] for line in clickhouse(
        hoover, f'SELECT DISTINCT collectionname FROM {db}.collections FINAL').splitlines() if line.strip()]


def jobs(s, data):
    out = []
    cluster = applied_values(s, 'cluster')
    if cluster['backup.platform.enabled'] == 'true':
        out.append(schedule.Job('platform', int(cluster['backup.platform.copies']), duration=600))
    for hoover in s.hoovers.values():
        zone = applied_values(s, f'zone:{hoover.zone}')
        if zone.get('backup.opendesk.enabled') == 'true':
            out.append(schedule.Job(f'zone:{hoover.zone}', int(zone['backup.opendesk.copies'])))
        if zone.get('backup.hoover.enabled') == 'true':
            for collection in collections(hoover):
                key = f'hoover:{hoover.zone}:{collection}'
                last = schedule.last_copy(data['jobs'].get(key, {}))
                out.append(schedule.Job(key, int(zone['backup.hoover.copies']), receipts(hoover, collection),
                                        estimated_bytes=(last or {}).get('bytes', 0)))
    return out


class Destination:
    """The destination folder on the [backup] node. Every check, write and removal runs on that node."""

    def __init__(self, s):
        self.node = s.nodes[s.backup['node']]
        self.path = s.backup['path']
        self.shell = hostroute.Shell(self.node)

    def run(self, script, timeout=600, input=None):
        return self.shell.run(script, timeout=timeout, input=input)

    def problem(self):
        q = shlex.quote(self.path)
        code, out = self.run(f'if [ ! -d {q} ]; then echo missing; elif [ ! -e {q}/{schedule.MARKER} ]; then echo marker; '
                             'else echo ok; fi', timeout=60)
        if code:
            return f'the backup node {self.node.name} does not answer: {out[-200:]}'
        state = out.strip().splitlines()[-1] if out.strip() else ''
        if state == 'missing':
            return f'the backup destination {self.path} on {self.node.name} does not exist.'
        if state == 'marker':
            return (f'the backup destination {self.path} on {self.node.name} has no {schedule.MARKER}. A mount may be '
                    'missing. The jobs pause until the destination is mounted again.')
        return ''

    def free_bytes(self):
        code, out = self.run(f'df -P -B1 {shlex.quote(self.path)} | tail -n 1', timeout=60)
        if code:
            raise SystemExit(f'the free space of {self.path} on {self.node.name} is unreadable: {out[-200:]}')
        return int(out.split()[3])

    def folder(self, key, generation):
        return f'{self.path}/{job_folder(key)}/{name_arg(generation, "generation")}'

    def copies(self):
        """{job folder: [generations]} of the destination, from its folders."""
        q = shlex.quote(self.path)
        code, out = self.run(f'cd {q} && find platform zones -mindepth 2 -maxdepth 5 -name {MANIFEST} 2>/dev/null', timeout=120)
        found = {}
        for line in out.splitlines():
            folder, _, generation = line.strip().rsplit('/', 1)[0].rpartition('/')
            if folder and not generation.endswith('.partial'):
                found.setdefault(folder, []).append(generation)
        return {k: sorted(v) for k, v in sorted(found.items())}

    def check(self, key, generation):
        """Read a copy on the node again against its manifest."""
        path = self.folder(key, generation)
        code, out = self.run(f'python3 -c {shlex.quote(REMOTE_VERIFY)} {shlex.quote(path)}', timeout=24 * 3600)
        try:
            return json.loads(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise SystemExit(f'the check of {path} on {self.node.name} failed: {out[-200:]}')

    def publish(self, local, key, generation):
        """Copy a verified local copy to the node, check it there against its manifest, then rename it."""
        final = self.folder(key, generation)
        partial = final + '.partial'
        code, out = self.run(f'rm -rf {shlex.quote(partial)}')
        if code:
            raise SystemExit(f'the old partial copy {partial} on {self.node.name} cannot be removed: {out[-200:]}')
        try:
            self.shell.send_tree(local, partial, timeout=24 * 3600)
        except hostroute.RouteError as error:
            raise SystemExit(f'the transfer to {self.node.name} failed: {error}')
        code, out = self.run(f'python3 -c {shlex.quote(REMOTE_VERIFY)} {shlex.quote(partial)}', timeout=24 * 3600)
        try:
            checked = json.loads(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            checked = {'differences': [f'the check on {self.node.name} failed: {out[-200:]}']}
        if code or checked['differences']:
            self.run(f'rm -rf {shlex.quote(partial)}')
            raise SystemExit(f'the copy {partial} on {self.node.name} differs from its manifest: {checked["differences"][:5]}')
        code, out = self.run(f'rm -rf {shlex.quote(final)} && mv {shlex.quote(partial)} {shlex.quote(final)}')
        if code:
            raise SystemExit(f'the copy {partial} on {self.node.name} cannot be renamed: {out[-200:]}')
        return final, checked

    def remove(self, path):
        if not path.startswith(self.path.rstrip('/') + '/'):
            raise SystemExit(f'{path} is outside the backup destination {self.path}.')
        self.run(f'rm -rf {shlex.quote(path)}')

    def fetch(self, key, generation, target):
        """Copy a copy of the node into a local staging folder, for a restore."""
        path = self.folder(key, generation)
        target = Path(target)
        target.mkdir(parents=True, exist_ok=True)
        reader = subprocess.Popen(self.shell.command(f'tar -C {shlex.quote(path)} -cf - .'), stdout=subprocess.PIPE)
        subprocess.run(['tar', '-C', str(target), '-xf', '-'], stdin=reader.stdout, check=True)
        reader.stdout.close()
        if reader.wait():
            raise SystemExit(f'the copy {path} on {self.node.name} cannot be read.')
        return target


# The check of a copy on the destination node: the size and SHA-256 of every file against copy-manifest.json. It runs
# with the python3 of the node, so it needs no file of this repository there.
REMOTE_VERIFY = r"""
import hashlib, json, os, sys
folder = sys.argv[1]
wanted = json.load(open(os.path.join(folder, 'copy-manifest.json')))
found = {}
for root, _, files in os.walk(folder):
    for name in files:
        path = os.path.join(root, name)
        rel = os.path.relpath(path, folder)
        if rel == 'copy-manifest.json':
            continue
        digest = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(4 << 20), b''):
                digest.update(chunk)
        found[rel] = {'path': rel, 'bytes': os.path.getsize(path), 'sha256': digest.hexdigest()}
differences = [r['path'] for r in wanted['files'] if found.get(r['path']) != r]
differences += sorted(set(found) - {r['path'] for r in wanted['files']})
print(json.dumps({'files': len(wanted['files']), 'bytes': sum(r['bytes'] for r in wanted['files']),
                  'differences': differences}))
"""


def destination(s):
    """(Destination, problem). The Destination is None when the site has no [backup] section."""
    if not s.backup:
        return None, 'the site file has no [backup] section.'
    target = Destination(s)
    return target, target.problem()


def staging(s):
    return s.operator_state() / 'backups' / 'staging'


def free_bytes(target):
    return target.free_bytes()


def running(record):
    pid = (record.get('running') or {}).get('pid')
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def tick(now=None):
    s = site()
    now = now or int(time.time())
    data = load_state(s)
    target, problem = destination(s)
    if target is None:
        return {'state': 'off', 'reason': problem}
    data['paused'] = problem
    if problem:
        save_state(s, data)
        return {'state': 'paused', 'reason': problem}
    if any(running(r) for r in data['jobs'].values()):
        return {'state': 'running', 'job': next(k for k, r in data['jobs'].items() if running(r))}
    # A job that ended without restoring its closed zone, for example after a kill, has its closure restored now.
    for key, record in data['jobs'].items():
        if record.get('closed') and not running(record):
            reopen(record['closed'])
            data = load_state(s)
            data['jobs'][key].pop('closed', None)
            save_state(s, data)
    holder = oplock.SiteLock(s.operator_state()).busy()
    if holder:
        return {'state': 'waiting', 'reason': f'the site operation {holder.get("kind")} {holder.get("id")} runs'}
    selected = jobs(s, data)
    for job in selected:
        record = data['jobs'].setdefault(job.key, {'copies': []})
        if job.weekly and not record.get('slot'):
            last = schedule.last_copy(record)
            record['slot'] = schedule.slot_after(job.key, last['finished'] if last else now)
    start, blocked, slots = schedule.plan(selected, data['jobs'], now, free_bytes(target))
    data['blocked'] = blocked
    for key, slot in slots.items():
        data['jobs'][key]['slot'] = slot
    if start:
        job, generation = start[0]
        log = s.operator_state() / 'backups' / 'logs' / f'{job.key.replace(":", "_")}-{now}.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        process = subprocess.Popen([sys.executable, __file__, 'run', job.key, generation], stdout=open(log, 'w'),
                                   stderr=subprocess.STDOUT, start_new_session=True)
        data['jobs'][job.key]['running'] = {'pid': process.pid, 'generation': generation, 'started': now, 'log': str(log)}
    save_state(s, data)
    return {'state': 'started' if start else 'idle', 'job': start[0][0].key if start else None, 'blocked': len(blocked)}


def path_is_manifest(folder, root, name):
    return name == MANIFEST and Path(root) == Path(folder)


def manifest(folder):
    rows = []
    for root, _, files in os.walk(folder):
        for name in sorted(files):
            if path_is_manifest(folder, root, name):
                continue
            path = Path(root) / name
            digest = hashlib.sha256()
            with open(path, 'rb') as f:
                while chunk := f.read(4 << 20):
                    digest.update(chunk)
            rows.append({'path': str(path.relative_to(folder)), 'bytes': path.stat().st_size, 'sha256': digest.hexdigest()})
    return rows


def verify(folder):
    wanted = json.loads((Path(folder) / MANIFEST).read_text())
    found = {r['path']: r for r in manifest(folder)}
    differences = [r['path'] for r in wanted['files'] if found.get(r['path']) != r]
    return {'files': len(wanted['files']), 'bytes': sum(r['bytes'] for r in wanted['files']), 'differences': differences}


def tar_command(ns, pod, container, folder, tar=('tar',)):
    return ['kubectl', '--kubeconfig', k3s_settings.KUBECONFIG, '-n', ns, 'exec', pod,
            *(['-c', container] if container else []), '--', *tar, '-C', folder, '-cf', '-', '.']


def stream_out(ns, pod, container, folder, target):
    """Copy a folder of a pod into a host folder with tar over kubectl exec."""
    target.mkdir(parents=True, exist_ok=True)
    reader = subprocess.Popen(tar_command(ns, pod, container, folder), stdout=subprocess.PIPE)
    subprocess.run(['tar', '-C', str(target), '-xf', '-', '--no-same-owner'], stdin=reader.stdout, check=True)
    if reader.wait():
        raise SystemExit(f'the copy of {pod}:{folder} failed.')


def tar_complete(path):
    """True when the tar file at path reads to its end-of-archive marker."""
    import tarfile
    try:
        with tarfile.open(path) as archive:
            for _ in archive:
                pass
        return True
    except (tarfile.TarError, EOFError, OSError):
        return False


def tar_out(ns, pod, container, folder, target, tar=('tar',)):
    """Write a folder of a pod into one host tar file, with its owners and modes.

    kubectl exec can end with status 0 after a stream reset, so the file is read to its end. An incomplete file is
    written again, up to three times.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        with open(target, 'wb') as out:
            code = subprocess.run(tar_command(ns, pod, container, folder, tar), stdout=out).returncode
        if code == 0 and tar_complete(target):
            return
    raise SystemExit(f'the copy of {pod}:{folder} failed or stayed incomplete after three attempts.')


def block_source(claim, pods):
    """(pod, container, folder) of the Kata store that mounts a Block claim, or None."""
    for pod in pods:
        if pod['status'].get('phase') != 'Running':
            continue
        volumes = [v['name'] for v in pod['spec'].get('volumes', []) if (v.get('persistentVolumeClaim') or {}).get('claimName') == claim]
        for c in pod['spec']['containers']:
            env = {e['name']: e.get('value', '') for e in c.get('env', [])}
            mounts = dict(pair.split(':', 1) for pair in env.get('BLOCK_MOUNTS', '').split())
            for device in c.get('volumeDevices', []):
                if device['name'] in volumes and device['devicePath'] in mounts:
                    return pod['metadata']['name'], c['name'], mounts[device['devicePath']]
    return None


def operations_pod(ns):
    return kubectl('-n', ns, 'get', 'pod', '-l', 'app.kubernetes.io/name=hoover-operations', '-o', 'jsonpath={.items[0].metadata.name}').strip()


def run_hoover(s, zone, collection, generation, partial):
    hoover = next(h for h in s.hoovers.values() if h.zone == zone)
    ns = hoover.namespace
    pod = operations_pod(ns)
    name = f'backup-{collection}-{generation}'
    kubectl('-n', ns, 'exec', pod, '--', 'sh', '-c', f'cd /app && {" ".join(PYTHON)} export-collection {collection} --destination {name} --wait')
    problems = json.loads(kubectl('-n', ns, 'exec', pod, '--', PYTHON[0], '-c', META_CHECK, f'/backups/{name}').strip() or '[]')
    if problems:
        kubectl('-n', ns, 'exec', pod, '--', 'rm', '-rf', f'/backups/{name}')
        raise SystemExit(f'the export of {collection} holds Manticore metadata that the import cannot read: {problems}. '
                         f'The copy is not kept. Run the job again.')
    stream_out(ns, pod, None, f'/backups/{name}', partial)
    kubectl('-n', ns, 'exec', pod, '--', 'rm', '-rf', f'/backups/{name}')


def helper_pod(ns, claim, node):
    name = f'backup-read-{hashlib.sha256(claim.encode()).hexdigest()[:8]}'
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': ns, 'labels': {'app.kubernetes.io/name': 'backup-reader'}},
           'spec': {'restartPolicy': 'Never', 'automountServiceAccountToken': False, 'enableServiceLinks': False,
                    **({'nodeSelector': {'kubernetes.io/hostname': node}} if node else {}),
                    'containers': [{'name': 'read', 'image': HELPER_IMAGE, 'command': ['sleep', '3600'],
                                    'resources': {'limits': {'memory': '256Mi'}},
                                    'volumeMounts': [{'name': 'data', 'mountPath': '/data', 'readOnly': True}]}],
                    'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': claim}}]}}
    kubectl('apply', '-f', '-', input=json.dumps(pod))
    kubectl('-n', ns, 'wait', '--for=condition=Ready', f'pod/{name}', '--timeout=300s')
    return name


DATABASES = ('postgresql', 'mariadb')


def tier_of(namespace, name):
    sys.path.insert(0, str(K3S / 'driver'))
    import deploy
    return deploy.tier(namespace, name)


def close_zone(s, zone):
    """Close the intake and the writers of a zone and its Hoover installation. Return the record of the earlier values.

    The applications, gates and workers scale to zero and the CronJobs are suspended. The stores keep running.
    """
    namespaces = [zone] + [h.namespace for h in s.hoovers.values() if h.zone == zone]
    record = {'namespaces': namespaces, 'workloads': {}, 'cronjobs': {}}
    for ns in namespaces:
        items = json.loads(kubectl('-n', ns, 'get', 'deployments,statefulsets,cronjobs', '-o', 'json'))['items']
        for item in items:
            kind, name = item['kind'].lower(), item['metadata']['name']
            if kind == 'cronjob':
                record['cronjobs'][f'{ns}/{name}'] = bool(item['spec'].get('suspend', False))
            elif tier_of(ns, name) in ('applications', 'ingress', 'temporal'):
                record['workloads'][f'{ns}/{kind}/{name}'] = item['spec'].get('replicas', 1)
    return record


def apply_closure(record):
    for key in record['cronjobs']:
        ns, name = key.split('/')
        kubectl('-n', ns, 'patch', 'cronjob', name, '--type', 'merge', '-p', '{"spec":{"suspend":true}}')
    for key, replicas in record['workloads'].items():
        ns, kind, name = key.split('/')
        if replicas:
            kubectl('-n', ns, 'scale', kind, name, '--replicas=0')
    # A scale request is not a stopped pod. The copy starts when no pod of a closed workload runs.
    deadline = time.monotonic() + 900
    for key, replicas in record['workloads'].items():
        ns, kind, name = key.split('/')
        while replicas and time.monotonic() < deadline:
            if kubectl('-n', ns, 'get', kind, name, '-o', 'jsonpath={.status.replicas}', check=False).strip() in ('', '0'):
                break
            time.sleep(3)
        else:
            if replicas:
                raise SystemExit(f'{key} still has pods after 900 s. The zone stays closed. Reopen it with backups.py tick.')


def reopen(record):
    """Restore the recorded replicas and CronJob suspensions."""
    for key, replicas in record['workloads'].items():
        ns, kind, name = key.split('/')
        kubectl('-n', ns, 'scale', kind, name, f'--replicas={replicas}', check=False)
    for key, suspended in record['cronjobs'].items():
        ns, name = key.split('/')
        kubectl('-n', ns, 'patch', 'cronjob', name, '--type', 'merge',
                '-p', json.dumps({'spec': {'suspend': suspended}}), check=False)


def run_zone(s, zone, partial, key=None):
    """Copy a complete zone: its namespace into partial, and each Hoover installation into partial/hoover/<name>/."""
    partial.mkdir(parents=True, exist_ok=True)
    closed = close_zone(s, zone)
    if key:
        data = load_state(s)
        data['jobs'].setdefault(key, {'copies': []})['closed'] = closed
        save_state(s, data)
    apply_closure(closed)
    copy_namespace(zone, partial)
    for hoover in (h for h in s.hoovers.values() if h.zone == zone):
        copy_namespace(hoover.namespace, partial / 'hoover' / hoover.name)
    reopen(closed)
    if key:
        data = load_state(s)
        data['jobs'][key].pop('closed', None)
        save_state(s, data)
    (partial / 'closure.json').write_text(json.dumps(closed, indent=1))


def copy_namespace(ns, partial):
    """Copy the database dumps, the claims, the Secrets and the ConfigMaps of one namespace into partial."""
    partial.mkdir(parents=True, exist_ok=True)
    pods = json.loads(kubectl('-n', ns, 'get', 'pods', '-o', 'json'))['items']
    names = {p['metadata']['name'] for p in pods}
    if 'postgresql-0' in names:
        # --clean lets restore-zone replace the databases of a zone that the installer created.
        with open(partial / 'postgresql.sql', 'wb') as out:
            kubectl('-n', ns, 'exec', 'postgresql-0', '-c', 'postgresql', '--', 'pg_dumpall', '-U', 'postgres', '--clean',
                    '--if-exists', stdout=out)
    if 'mariadb-0' in names:
        with open(partial / 'mariadb.sql', 'wb') as out:
            kubectl('-n', ns, 'exec', 'mariadb-0', '--', 'sh', '-c',
                    'mariadb-dump --all-databases --single-transaction -uroot -p"$MARIADB_ROOT_PASSWORD"', stdout=out)
    claims = json.loads(kubectl('-n', ns, 'get', 'pvc', '-o', 'json'))['items']
    rows = []
    for item in claims:
        claim = item['metadata']['name']
        if any(d in claim for d in DATABASES) or any(o['kind'] == 'Pod' for o in item['metadata'].get('ownerReferences', [])):
            continue
        mode = item['spec'].get('volumeMode') or 'Filesystem'
        target = partial / 'claims' / f'{claim}.tar'
        if mode == 'Block':
            source = block_source(claim, pods)
            if source is None:
                raise SystemExit(f'no running store pod mounts the Block claim {ns}/{claim}. Start the zone and run the job again.')
            tar_out(ns, *source, target, tar=('/tools/busybox', 'tar'))
        else:
            node = (item['metadata'].get('annotations') or {}).get('volume.kubernetes.io/selected-node')
            pod = helper_pod(ns, claim, node)
            try:
                tar_out(ns, pod, None, '/data', target)
            finally:
                kubectl('-n', ns, 'delete', 'pod', pod, '--wait=false')
        rows.append({'claim': claim, 'size': item['spec']['resources']['requests']['storage'],
                     'storage_class': item['spec'].get('storageClassName'), 'volume_mode': mode})
    (partial / 'claims.json').write_text(json.dumps(rows, indent=1))
    (partial / 'objects.json').write_text(kubectl('-n', ns, 'get', 'secrets,configmaps', '-o', 'json'))
    os.chmod(partial / 'objects.json', 0o600)


RECOVERY_FORMAT = 'hoover4-platform-recovery'
# The private folders that hold no recovery input: builds, downloads, tool binaries and the staged k3s files of each
# architecture. staging/tokens holds the site tokens and is part of the copy.
PRIVATE_EXCLUDED = ['build', 'bin', 'browser-venv', 'checks', 'downloads', 'operator/backups', 'operator/deploy/logs',
                    'staging/amd64', 'staging/arm64', 'deploy/remote']


def snapshot_root(s, name):
    """Run root-install-k3s.py --snapshot <name> on the control plane through its root route.

    The script writes ~<operator>/k3s-install/snapshots/<name>/ there. Its site is the bundle `backup`, which this
    function writes over the user shell. The root command gets names only.
    """
    node = s.nodes[s.control_plane]
    shell = hostroute.Shell(node)
    user = s.operator_user or os.environ.get('USER', '')
    hosts = json.dumps(site_config.legacy_hosts(s))
    code, out = shell.run('umask 077 && mkdir -p ~/k3s-install/backup && cat > ~/k3s-install/backup/hosts.json', input=hosts)
    if code:
        raise SystemExit(f'the site of the snapshot cannot be written on {node.name}: {out[-300:]}')
    script = K3S / 'hosts' / 'root-install-k3s.py'
    argv = [f'{hostroute.LIBEXEC}/root-install-k3s.py', '--bundle', 'backup', '--node', node.name, '--operator', user,
            '--snapshot', name_arg(name, 'snapshot')]
    code, out = shell.run('sudo -n true', timeout=30)
    if code == 0 or shell.run(f'sudo -n -l {hostroute.LIBEXEC}/root-install-k3s.py', timeout=30)[0] == 0:
        code, out = shell.run('sudo -n ' + ' '.join(shlex.quote(a) for a in argv), timeout=3600)
        if code:
            raise SystemExit(f'the etcd snapshot on {node.name} failed: {out[-300:]}')
        return 'sudo'
    # The cluster route installs the script of this tree and runs it as a unit of the host.
    root = hostroute.ClusterRoot(k3s_settings.KUBECONFIG, shell)
    unit = f'hoover4-snapshot-{int(time.time())}'
    files = [(f'{hostroute.LIBEXEC}/root-install-k3s.py', script.read_bytes())]
    root.start(unit, files, argv)
    try:
        root.wait(unit, timeout=3600)
    except hostroute.RouteError as error:
        raise SystemExit(f'the etcd snapshot on {node.name} failed: {error}')
    return 'cluster'


def application_copies(data):
    """The newest verified copy of each application job, which a complete recovery restores after the cluster."""
    out = {}
    for key, record in data['jobs'].items():
        if key == 'platform':
            continue
        last = schedule.last_copy(record)
        if last:
            out[key] = {'generation': last['generation'], 'path': last['path'], 'host': last.get('host', '')}
    return out


def run_platform(s, partial):
    """An etcd snapshot of the control plane with its token, the private files and recovery.json."""
    partial.mkdir(parents=True, exist_ok=True)
    node = s.nodes[s.control_plane]
    shell = hostroute.Shell(node)
    name = f'platform-{int(time.time())}'
    remote = f'k3s-install/snapshots/{name}'
    route = snapshot_root(s, name)
    try:
        etcd = partial / 'etcd'
        etcd.mkdir()
        reader = subprocess.Popen(shell.command(f'tar -C ~/{remote} -cf - .'), stdout=subprocess.PIPE)
        subprocess.run(['tar', '-C', str(etcd), '-xf', '-'], stdin=reader.stdout, check=True)
        reader.stdout.close()
        if reader.wait():
            raise SystemExit(f'the snapshot folder {remote} on {node.name} cannot be read.')
    finally:
        shell.run(f'rm -rf ~/{remote}')
    os.chmod(etcd, 0o700)
    host = json.loads((etcd / 'host.json').read_text())
    for name, digest in host['sha256'].items():
        actual = hashlib.sha256((etcd / name).read_bytes()).hexdigest()
        if actual != digest:
            raise SystemExit(f'the snapshot file {name} changed in the transfer.')
    private = k3s_settings.PRIVATE
    subprocess.run(['tar', '-C', str(private), '-cf', str(partial / 'private.tar'),
                    *[f'--exclude=./{e}' for e in PRIVATE_EXCLUDED], '.'], check=True)
    os.chmod(partial / 'private.tar', 0o600)
    state = s.operator_state()
    applied = json.loads((state / 'deploy' / 'applied.json').read_text()) if (state / 'deploy' / 'applied.json').exists() else {}
    settings_applied = json.loads((state / 'applied.json').read_text()) if (state / 'applied.json').exists() else {}
    recovery = {
        'format': RECOVERY_FORMAT, 'format_version': 2, 'datastore': 'etcd', 'route': route,
        'execution_host': socket.gethostname(), 'control_plane': node.name, 'destination_node': s.backup.get('node'),
        'k3s_version': host['k3s_version'], 'snapshot': f'etcd/{host["snapshot"]}', 'token': 'etcd/token',
        'k3s_config': 'etcd/config.yaml', 'private': 'private.tar', 'site': s.name,
        'source_revision': applied.get('revision', ''), 'settings_revision': settings_applied.get('revision', 0),
        'settings_scopes': settings_applied.get('scopes', {}),
        'artifacts': json.loads((K3S / 'driver' / 'artifacts.json').read_text()),
        'application_copies': application_copies(load_state(s)),
    }
    (partial / 'recovery.json').write_text(json.dumps(recovery, indent=1, sort_keys=True))


def read_recovery(folder):
    """The recovery set of a platform copy. A copy of the earlier format holds the SQLite file k3s-state.db."""
    folder = Path(folder)
    path = folder / 'recovery.json'
    if path.exists():
        data = json.loads(path.read_text())
        if data.get('format') != RECOVERY_FORMAT or data.get('format_version') != 2:
            raise SystemExit(f'{path} has the format {data.get("format")} {data.get("format_version")}, which this '
                             'version does not read.')
        return data
    if (folder / 'k3s-state.db').exists():
        return {'format': RECOVERY_FORMAT, 'format_version': 1, 'datastore': 'sqlite', 'snapshot': 'k3s-state.db',
                'token': None, 'private': 'private.tar', 'application_copies': {},
                'note': 'A copy of the earlier format. It restores an earlier SQLite server, whose token is in '
                        'private.tar only when the operator kept it there. Convert the restored server to etcd.'}
    raise SystemExit(f'{folder} holds no platform recovery set.')


def restore_platform_steps(generation):
    """The steps that restore a platform copy on the stopped server of an isolated cluster. Each command uses names."""
    return platform_steps(fetched(site(), 'platform', generation), generation)


def platform_steps(folder, generation):
    """The restore steps of a fetched platform copy."""
    data = read_recovery(folder)
    if data['datastore'] != 'etcd':
        return [f'This copy holds the SQLite datastore {data["snapshot"]}. Stop k3s on the server, copy it to '
                '/var/lib/rancher/k3s/server/db/state.db with the token of the earlier server, start k3s, then run '
                'root-install-k3s.py with --convert-sqlite to convert it to etcd.']
    name = f'restore-{name_arg(generation, "generation")}'
    return [f'Copy the folder etcd/ of the copy into ~/k3s-install/snapshots/{name}/ of the operator user on the server. '
            f'This host holds it in {folder / "etcd"}.',
            f'Write hosts.json of the isolated site into ~/k3s-install/backup/ on the server.',
            f'sudo /usr/local/libexec/hoover4/root-install-k3s.py --bundle backup --node <server> '
            f'--restore-snapshot {name}',
            f'Unpack {data["private"]} of the copy into the private folder of the checkout.',
            'Restore the application copies that recovery.json names: backups.py restore-zone for each zone copy '
            'and backups.py restore-hoover for each collection copy, then sign in to each zone.']


def restore_staging(s, key, generation):
    """The local folder of a fetched copy: <operator state>/backups/restore/<job folder>/<generation>."""
    return s.operator_state() / 'backups' / 'restore' / job_folder(key) / name_arg(generation, 'generation')


def run_job(key, generation):
    s = site()
    target, problem = destination(s)
    if problem:
        raise SystemExit(problem)
    data = load_state(s)
    data['jobs'].setdefault(key, {'copies': []})
    partial = staging(s) / key.replace(':', '_') / f'{generation}.partial'
    shutil.rmtree(partial, ignore_errors=True)
    partial.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    kind, _, rest = key.partition(':')
    lock = oplock.SiteLock(s.operator_state())
    try:
        if kind in ('zone', 'opendesk', 'platform'):
            # The copy is the consistency boundary of the zone or the cluster, so no other operation changes the site.
            lock.acquire('backup', f'backup-{key}-{generation}')
        if kind == 'hoover':
            zone, collection = rest.split(':')
            run_hoover(s, zone, collection, generation, partial)
        elif kind in ('zone', 'opendesk'):
            run_zone(s, rest, partial, key)
        else:
            run_platform(s, partial)
        lock.release()
        rows = manifest(partial)
        (partial / MANIFEST).write_text(json.dumps({'job': key, 'generation': generation, 'files': rows}, indent=1))
        checked = verify(partial)
        if checked['differences']:
            raise SystemExit(f'the copy {partial} differs from its manifest: {checked["differences"][:5]}')
        final, remote_check = target.publish(partial, key, generation)
        copy = {'generation': generation, 'path': final, 'host': target.node.name,
                'execution_host': socket.gethostname(), 'finished': int(time.time()), 'bytes': remote_check['bytes'],
                'seconds': round(time.time() - started), 'verified': True}
    except BaseException as error:
        lock.release()
        data = load_state(s)
        data['jobs'].setdefault(key, {'copies': []})['last_error'] = str(error)[:500]
        data['jobs'][key].pop('running', None)
        save_state(s, data)
        shutil.rmtree(partial, ignore_errors=True)
        raise
    shutil.rmtree(partial, ignore_errors=True)
    data = load_state(s)
    record = data['jobs'].setdefault(key, {'copies': []})
    record['copies'].append(copy)
    record.pop('running', None)
    record.pop('slot', None)
    record.pop('last_error', None)
    copies = {'hoover': 'backup.hoover.copies', 'zone': 'backup.opendesk.copies', 'opendesk': 'backup.opendesk.copies',
              'platform': 'backup.platform.copies'}[kind]
    scope = 'cluster' if key == 'platform' else f'zone:{key.split(":")[1]}'
    # Retention runs on the destination node, and only after the new copy was verified there.
    for old in schedule.retention(record, int(applied_values(s, scope)[copies])):
        target.remove(old['path'])
        record['copies'].remove(old)
    save_state(s, data)
    print(json.dumps({'job': key, **copy}))


def fetched(s, key, generation):
    """Fetch a copy of the destination into the restore staging folder and verify it there. Return the folder."""
    target, problem = destination(s)
    if problem:
        raise SystemExit(problem)
    if target.node.local:
        # The destination is a folder of this host, so the restore reads it in place.
        folder = Path(target.folder(key, generation))
        if not (folder / MANIFEST).exists():
            raise SystemExit(f'the copy {folder} does not exist.')
        if verify(folder)['differences']:
            raise SystemExit(f'the copy {folder} differs from its manifest.')
        return folder
    folder = restore_staging(s, key, generation)
    if not (folder.exists() and not verify(folder)['differences']):
        shutil.rmtree(folder, ignore_errors=True)
        target.fetch(key, generation, folder)
    return folder


def restore_hoover(zone, collection, generation, source_zone=None):
    """Import a collection copy into the Hoover installation of a zone that has no collection of that name."""
    s = site()
    hoover = next((h for h in s.hoovers.values() if h.zone == name_arg(zone, 'zone')), None)
    if hoover is None:
        raise SystemExit(f'the site file has no Hoover installation in {zone}.')
    folder = fetched(s, f'hoover:{source_zone or zone}:{name_arg(collection, "collection")}', generation)
    meta = json.loads((Path(folder) / MANIFEST).read_text())
    checked = verify(folder)
    if checked['differences']:
        raise SystemExit(f'the copy {folder} differs from its manifest.')
    ns = hoover.namespace
    pod = operations_pod(ns)
    name = f'restore-{collection}-{meta["generation"]}'
    tar = subprocess.Popen(['tar', '-C', str(folder), '-cf', '-', f'--exclude=./{MANIFEST}', '.'], stdout=subprocess.PIPE)
    subprocess.run(['kubectl', '--kubeconfig', k3s_settings.KUBECONFIG, '-n', ns, 'exec', '-i', pod, '--', 'sh', '-c',
                    # The host copy has the owner of the host user. ClickHouse and Manticore read the files of the
                    # import with their own users, so the files must be readable for them.
                    f'mkdir -p /backups/{name} && tar -C /backups/{name} -xf - --no-same-owner && chmod -R a+rX /backups/{name}'],
                   stdin=tar.stdout, check=True)
    tar.wait()
    kubectl('-n', ns, 'exec', pod, '--', 'sh', '-c',
            f'cd /app && {" ".join(PYTHON)} create-collection {collection} >/dev/null 2>&1; {" ".join(PYTHON)} import-collection {collection} --source {name} --confirm {collection} --wait')
    print(json.dumps({'restored': collection, 'installation': hoover.name, 'files': checked['files'], 'bytes': checked['bytes']}))


def restore_pod(namespace, row):
    """The pod that writes one claim. A Block claim gets the Kata wrapper of the stores, which makes and mounts its file
    system at /data."""
    spec = {'restartPolicy': 'Never', 'automountServiceAccountToken': False, 'enableServiceLinks': False,
            # A Kata guest does not start a container without limits.
            'containers': [{'name': 'write', 'image': HELPER_IMAGE, 'command': ['sleep', '3600'],
                            'resources': {'limits': {'cpu': '1', 'memory': '256Mi'}},
                            'volumeMounts': [{'name': 'data', 'mountPath': '/data'}]}],
            'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': row['claim']}}]}
    if row.get('volume_mode') == 'Block':
        spec['containers'][0]['volumeMounts'] = []
        spec = podspec.blockmount(spec, 'write', ['sleep', '3600'], [('data', row['claim'], '/data')])
        spec['runtimeClassName'] = 'kata'
    return {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'restore-write', 'namespace': namespace}, 'spec': spec}


def zone_parts(s, folder, zone):
    """[(folder part, namespace)] of a zone copy: the zone namespace, then each Hoover installation of the zone.

    A copy part hoover/<name>/ restores into the installation <name> of the zone. A copy with one installation restores
    into the one installation of the target zone, also under another name.
    """
    parts = [(folder, zone)]
    targets = [h for h in s.hoovers.values() if h.zone == zone]
    sources = sorted(p for p in (folder / 'hoover').iterdir() if p.is_dir()) if (folder / 'hoover').is_dir() else []
    for part in sources:
        match = next((h for h in targets if h.name == part.name), None)
        if match is None and len(sources) == 1 and len(targets) == 1:
            match = targets[0]
        if match is None:
            raise SystemExit(f'the copy part hoover/{part.name} has no Hoover installation of that name in {zone}.')
        parts.append((part, match.namespace))
    return parts


def restore_zone(zone, generation, source_zone=None):
    """Restore a complete zone copy into an installed zone.

    The zone must exist, for example after zone.py apply. The steps: fetch and verify the copy, close the zone and its
    Hoover installation and stop their stores except the zone databases, apply the Secrets of each part, replace the
    content of each claim, import the database dumps, restart the databases, and open the zone with the replicas of the
    copy. Each step is recorded in <operator state>/backups/restore-<zone>.json. A failure leaves the zone closed.
    """
    s = site()
    name_arg(zone, 'zone')
    key = f'zone:{source_zone or zone}'
    if kubectl('get', 'namespace', zone, '--ignore-not-found', '-o', 'name').strip() == '':
        raise SystemExit(f'the zone namespace {zone} does not exist. Install the zone first.')
    copy = f'{job_folder(key)}/{name_arg(generation, "generation")}'
    record_path = s.operator_state() / 'backups' / f'restore-{zone}.json'
    progress = json.loads(record_path.read_text()) if record_path.exists() else {'copy': copy, 'steps': []}
    if progress['copy'] != copy:
        raise SystemExit(f'{record_path} belongs to the restore of {progress["copy"]}. Remove it after its check.')
    # fetched() checks the copy against its manifest.
    folder = fetched(s, key, generation)
    if (folder / 'postgresql.sql').exists() and b'DROP DATABASE' not in (folder / 'postgresql.sql').read_bytes()[:1 << 20]:
        raise SystemExit('the PostgreSQL dump of this copy has no DROP statements, because an earlier version made it. '
                         'Restore it into a new database server by hand.')
    parts = zone_parts(s, folder, zone)

    def step(name, function):
        if name in progress['steps']:
            return
        function()
        progress['steps'].append(name)
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(json.dumps(progress, indent=1))

    lock = oplock.SiteLock(s.operator_state())
    lock.acquire('restore', f'restore-{zone}')
    try:
        source = json.loads((folder / 'closure.json').read_text()) if (folder / 'closure.json').exists() else None
        if 'closed' not in progress:
            closed = close_zone(s, zone)
            # The stores stop too, except the zone databases, which import the dumps.
            for _, ns in parts:
                for item in json.loads(kubectl('-n', ns, 'get', 'statefulsets', '-o', 'json'))['items']:
                    name = item['metadata']['name']
                    if tier_of(ns, name) == 'stores' and not (ns == zone and any(d in name for d in DATABASES)):
                        closed['workloads'][f'{ns}/statefulset/{name}'] = item['spec'].get('replicas', 1)
            progress['closed'] = closed
            record_path.parent.mkdir(parents=True, exist_ok=True)
            record_path.write_text(json.dumps(progress, indent=1))
        step('close', lambda: apply_closure(progress['closed']))
        for part, ns in parts:
            label = '' if ns == zone else f':{ns}'
            step('secrets' + label, lambda part=part, ns=ns: restore_secrets(part, ns))
            restore_claims(part, ns, step)
        step('databases', lambda: restore_databases(folder, zone))
        # The replicas of the source zone apply when the copy names them. Otherwise the zone keeps its own.
        opened = dict(progress['closed'])
        if source:
            renamed = {source['namespaces'][0]: zone}
            renamed.update({f'hoover-{source["namespaces"][0]}': f'hoover-{zone}'})
            opened['workloads'] = {}
            for k, v in source['workloads'].items():
                ns, rest = k.split('/', 1)
                if ns in renamed:
                    opened['workloads'][f'{renamed[ns]}/{rest}'] = v
            opened['workloads'].update({k: v for k, v in progress['closed']['workloads'].items() if k not in opened['workloads']})
        step('open', lambda: reopen(opened))
    finally:
        lock.release()
    print(json.dumps({'zone': zone, 'restored': copy, 'steps': progress['steps']}))


def restore_secrets(folder, zone):
    """Apply the Secrets of the copy. Service account tokens and Helm release records belong to the target.

    The items of a Secret of the copy replace the same items of the target Secret. The other items of the target stay,
    because a later release can add an item that an earlier copy does not hold.
    """
    objects = json.loads((folder / 'objects.json').read_text())['items']
    skipped = ('kubernetes.io/service-account-token', 'helm.sh/release.v1')
    for item in objects:
        if item['kind'] != 'Secret' or item.get('type') in skipped:
            continue
        metadata = {k: v for k, v in item['metadata'].items() if k in ('name', 'labels', 'annotations')}
        metadata['namespace'] = zone
        metadata.get('annotations', {}).pop('kubectl.kubernetes.io/last-applied-configuration', None)
        current = kubectl('-n', zone, 'get', 'secret', metadata['name'], '--ignore-not-found', '-o', 'json').strip()
        data = {**((json.loads(current).get('data') or {}) if current else {}), **item.get('data', {})}
        kubectl('apply', '--server-side', '--force-conflicts', '--field-manager=hoover-restore', '-f', '-',
                input=json.dumps({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': metadata,
                                  'type': item.get('type', 'Opaque'), 'data': data}))


def restore_claims(folder, zone, step=None):
    """Replace the content of each claim of the copy. The workloads that mount the claims are stopped.

    step(name, function) records each finished claim, so a second run continues at the first unfinished claim. A write
    whose stream ends early (tar: short read) runs again, up to three times, from an emptied claim.
    """
    claims = json.loads((folder / 'claims.json').read_text())
    for row in claims:
        if step:
            step(f'claim:{zone}/{row["claim"]}', lambda row=row: restore_claim(folder, zone, row))
        else:
            restore_claim(folder, zone, row)


def restore_claim(folder, zone, row):
    claim = {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': row['claim'], 'namespace': zone},
             'spec': {'accessModes': ['ReadWriteOnce'], 'storageClassName': row['storage_class'],
                      'volumeMode': row.get('volume_mode') or 'Filesystem',
                      'resources': {'requests': {'storage': row['size']}}}}
    if kubectl('-n', zone, 'get', 'pvc', row['claim'], '--ignore-not-found', '-o', 'name').strip() == '':
        kubectl('apply', '-f', '-', input=json.dumps(claim))
    for attempt in range(1, 4):
        kubectl('-n', zone, 'delete', 'pod', 'restore-write', '--ignore-not-found', '--wait=true')
        kubectl('apply', '-f', '-', input=json.dumps(restore_pod(zone, row)))
        kubectl('-n', zone, 'wait', '--for=condition=Ready', 'pod/restore-write', '--timeout=300s')
        with open(folder / 'claims' / f'{row["claim"]}.tar', 'rb') as source:
            result = subprocess.run(['kubectl', '--kubeconfig', k3s_settings.KUBECONFIG, '-n', zone, 'exec', '-i',
                                     'restore-write', '--', 'sh', '-c',
                                     'until grep -q " /data " /proc/mounts; do sleep 1; done; '
                                     'find /data -mindepth 1 -maxdepth 1 ! -name lost+found -exec rm -rf {} + && '
                                     'tar -C /data -xpf -'],
                                    stdin=source, stderr=subprocess.PIPE)
        kubectl('-n', zone, 'delete', 'pod', 'restore-write', '--wait=true')
        if result.returncode == 0:
            return
        print(json.dumps({'claim': f'{zone}/{row["claim"]}', 'attempt': attempt,
                          'error': result.stderr.decode(errors='replace').strip()[-300:]}), flush=True)
    raise SystemExit(f'the write of the claim {zone}/{row["claim"]} failed three times. The zone stays closed.')


def restore_databases(folder, zone):
    """Import the dumps into the running database servers of the zone, then restart them with the restored Secrets."""
    if (folder / 'postgresql.sql').exists():
        with open(folder / 'postgresql.sql', 'rb') as dump:
            subprocess.run(['kubectl', '--kubeconfig', k3s_settings.KUBECONFIG, '-n', zone, 'exec', '-i', 'postgresql-0', '-c',
                            'postgresql', '--', 'psql', '-U', 'postgres', '-v', 'ON_ERROR_STOP=0', '-q', '-d', 'postgres'],
                           stdin=dump, check=True, stdout=subprocess.DEVNULL)
    if (folder / 'mariadb.sql').exists():
        with open(folder / 'mariadb.sql', 'rb') as dump:
            subprocess.run(['kubectl', '--kubeconfig', k3s_settings.KUBECONFIG, '-n', zone, 'exec', '-i', 'mariadb-0', '--',
                            'sh', '-c', 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD"'], stdin=dump, check=True)
    for name in ('postgresql-0', 'mariadb-0'):
        kubectl('-n', zone, 'delete', 'pod', name, '--ignore-not-found', '--wait=true')
    for name in ('postgresql', 'mariadb'):
        if kubectl('-n', zone, 'get', 'statefulset', name, '--ignore-not-found', '-o', 'name').strip():
            kubectl('-n', zone, 'rollout', 'status', f'statefulset/{name}', '--timeout=600s')


def option(argv, name):
    """(argv without --name value, value or None)."""
    if name in argv:
        i = argv.index(name)
        if i + 1 >= len(argv):
            raise SystemExit(f'{name} needs a value.')
        return argv[:i] + argv[i + 2:], name_arg(argv[i + 1], 'zone')
    return argv, None


def main(argv):
    argv, source_zone = option(list(argv), '--from')
    # Every argument after the command is a name, except the job key of run and verify, which job_folder() checks.
    if argv and argv[0] in ('run', 'verify'):
        job_folder(argv[1]) if len(argv) > 1 else None
        [name_arg(a) for a in argv[2:]]
    elif argv and argv[0] in ('restore-zone', 'restore-hoover', 'recovery', 'restore-platform'):
        [name_arg(a) for a in argv[1:]]
    if argv == ['tick']:
        print(json.dumps(tick()))
    elif argv == ['status']:
        s = site()
        target, problem = destination(s)
        print(json.dumps({'destination': {'node': target.node.name, 'path': target.path, 'problem': problem}
                          if target else problem, **load_state(s)}, indent=1))
    elif len(argv) == 3 and argv[0] == 'run':
        run_job(argv[1], name_arg(argv[2], 'generation'))
    elif argv == ['enable']:
        target, _ = destination(site())
        if target is None:
            raise SystemExit('the site file has no [backup] section.')
        q = shlex.quote(target.path)
        code, out = target.run(f'mkdir -p {q}/zones {q}/platform && echo "This folder receives the backups of the hoover4 '
                               f'site." > {q}/{schedule.MARKER}')
        if code:
            raise SystemExit(f'the destination {target.path} on {target.node.name} cannot be written: {out[-200:]}')
        print(json.dumps({'destination': target.path, 'node': target.node.name, 'marker': schedule.MARKER}))
    elif argv == ['copies']:
        target, problem = destination(site())
        if problem:
            raise SystemExit(problem)
        print(json.dumps(target.copies(), indent=1))
    elif len(argv) == 3 and argv[0] == 'verify':
        target, problem = destination(site())
        if problem:
            raise SystemExit(problem)
        print(json.dumps(target.check(argv[1], argv[2])))
    elif len(argv) == 3 and argv[0] == 'restore-zone':
        restore_zone(argv[1], argv[2], source_zone)
    elif len(argv) == 4 and argv[0] == 'restore-hoover':
        restore_hoover(argv[1], argv[2], argv[3], source_zone)
    elif len(argv) == 2 and argv[0] == 'recovery':
        s = site()
        print(json.dumps(read_recovery(fetched(s, 'platform', argv[1])), indent=1))
    elif len(argv) == 2 and argv[0] == 'restore-platform':
        print('\n'.join(restore_platform_steps(argv[1])))
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
