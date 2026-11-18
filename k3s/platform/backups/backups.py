#!/usr/bin/env python3
"""Run the optional backups of a site and restore a copy into an isolated target.

vars.backup of the site file names the node and the folder of the destination. The operator settings `backup.*` of the
applied revision turn each job on and set its retained copies. Without vars.backup or with every job off, nothing runs.
schedule.py holds the rules. This file reads the receipts and the sizes, runs one job at a time and keeps the state in
<operator state>/backups/state.json, which it writes atomically.

Arguments are names: a zone, a collection, a job and a generation (the name of a copy). No command takes a host path.
The operator pod runs on the backup node of vars.backup and mounts the folder at the same path in its runner
container (../operator/backup-mount.py), so this file reads and writes the copies as local files and needs no SSH, no
user entry and no key for them. The operator makes sure that the folder is on another host. The
copies of a zone are in <folder>/zones/<zone>/<generation>/,
the collection exports of a zone in <folder>/zones/<zone>/collections/<collection>/<generation>/, and the platform
copies in <folder>/platform/<generation>/. The level zones/ keeps a zone named platform apart from the platform copies.
The commands run in the runner container: kubectl -n operator-portal exec deploy/portal -c runner -- python3
/opt/hoover4/k3s/platform/backups/backups.py <command>. On a host without the folder, every command that reads the
destination stops with a message.

Jobs:
- zone:<zone>: the complete zone, which is its openDesk namespace and its complete Hoover installation. The copy holds
  a SQL dump of each database server of the zone namespace, or of each openDesk database of the zone on the shared
  PostgreSQL of the site (postgresql/<database>.sql, ../../zones/postgresql.py), the objects of the openDesk object
  store (the openDesk buckets of the zone in the shared Garage, or the SeaweedFS of a zone that has not moved), a tar
  file of each other claim, and the Secrets and ConfigMaps of the namespace. The folder hoover/<installation>/ holds the same
  parts of the Hoover namespace: its claims, Secrets and ConfigMaps. The tar files keep the owners and modes. A file
  system claim is read with tar in a running container that mounts it (mount_source()), so the copy needs no free
  memory on its node. A claim that no running container with tar mounts is read through a short pod in its namespace.
  That pod does not ask for a read-only mount of the claim, because the kernel refuses a second mount of a mounted
  ext4 device with other options. Its container mount is read-only. A Block claim holds the file system of a Kata store, which only the guest of the store pod mounts, so the
  copy reads it through the store container with the busybox of ../../hoover/stores/podspec.py. A claim that a pod
  owns (a generic ephemeral volume) holds temporary files and is not copied. The earlier job key opendesk:<zone> reads
  as zone:<zone>.
  The job copies a running zone (online_parts()): no application stops. The parts of the copy are read one after the
  other, so each part holds its own moment. moments.json of the copy names the start and the end of each part.
  A zone of the store layout site keeps its ClickHouse databases, Manticore tables and Garage buckets in the shared
  stores of the site (../../hoover/stores/shared.py). The folder hoover/<installation>/shared/ of the zone copy holds
  the ClickHouse databases <prefix> and <prefix>_Processing (users, groups, chats, boards, settings, operation history)
  and the objects of the bucket <zone>-system (copy_shared_stores()). The collection copies of the next job hold the
  collection databases, tables and buckets.
- hoover:<zone>:<collection>: the collection export of the operations worker (main.py export-collection), streamed out
  of the claim ops-backups. In a zone of the store layout site the ClickHouse archive of the export is an object of the
  export bucket of the zone, and the job first copies it into the export directory. The export directory in the claim
  and the object are removed after the copy, so no second archive stays.
- platform: the newest scheduled etcd snapshot of the control-plane server with its token and k3s configuration, the
  operator state and the private files of the site (credentials included), and recovery.json. k3s saves a snapshot
  every 12 hours and keeps 5. The job starts a short pod on the control plane (snapshot_reader()), which mounts the
  snapshot folder, the token and the configuration read-only, reads the files with tar through kubectl exec and
  deletes the pod. The runner needs no SSH and no access to a host. A newest snapshot older than SNAPSHOT_MAX_AGE
  stops the job with a message that names its age. The snapshot is normally up to 12 hours older than the private files,
  and recovery.json names its time. recovery.json has format_version 3, the datastore etcd, the execution host, the
  control plane, the destination node, the k3s version, the applied source and settings revisions, the pinned tool
  versions and the application copies that a complete recovery needs. An etcd snapshot holds no claim data, so the
  application copies are part of the recovery set. read_recovery() also reads format_version 2, whose snapshot the
  job saved over SSH, and a copy of the earlier format with the SQLite file k3s-state.db, for the conversion of an
  earlier installation. No new copy uses SQLite.
A job writes its copy into <folder>/staging/<job>/<generation>.partial, on the volume of the copies. Each tar stream
of a pod must reach its end-of-archive marker and each database dump must end with the trailer line of its dump tool,
or the part is read again. The copy then gets copy-manifest.json with the size and SHA-256 of every file, is read
again against it, and is renamed into its folder. Only then does retention remove older copies. A failed job or check
leaves the older copies. The destination folder must hold the marker file of schedule.py, which the host step of the
backup node writes (../../ansible/roles/hoover4_host/tasks/backup.yml), so a missing mount pauses the jobs.
The zone job records the replicas of each workload of the zone in workloads.json, which restore-zone applies. It stops
and scales no workload. A job of an earlier version closed the zone during the copy. A runner that finds such a
recorded closure without a running job restores it.
The zone and platform jobs hold the site operation lock (../../oplock.py), so no deployment, Apply or Compose import
changes the site during the copy.
restore-zone restores a complete zone copy into an installed zone: the Secrets, the claims, the objects of the
object store and the database dumps of the zone namespace and of its Hoover installation, with the applications and
the other stores stopped. For a site
zone it also replaces the zone databases and the objects of the system bucket with the shared/ part of the copy, and
it keeps the tenant credentials of the target zone (TENANT_SECRETS). --from names
the zone of the copy when it differs. On a failure the zone stays closed, and the state file names the step.
A runner restart finds a job that runs (its process id and its export operation in the state) and waits for it.
Receipts of a collection come from the table operations of the installation: the first finished add_dataset of each of
its datasets, when none of its dataset operations still runs, is the ingestion receipt. A finished update_collection,
after which every included update_dataset finished without an error, is a complete reprocessing receipt.
Usage: backups.py tick                      start the next due job, as the operator runner does every minute
       backups.py status                    print the state, the next slots and the blocked jobs
       backups.py run <job> <generation>    run one job now, in the foreground
       backups.py enable                    write the folders and the marker of the destination
       backups.py copies                    list the copies of the destination
       backups.py verify <job> <generation>                        read a copy again against its manifest
       backups.py restore-zone <zone> <generation> [--from <zone>]  restore a complete zone copy into a zone
       backups.py restore-hoover <zone> <collection> <generation> [--from <zone>]
                                                                    import a collection copy into the zone's Hoover
       backups.py recovery <generation>                             print the recovery set of a platform copy
       backups.py restore-platform <generation>                     print the root steps that restore a platform copy
"""
import base64
import contextlib
import hashlib
import json
import os
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

# The ClickHouse part of an export of a site zone is an object of the export bucket of the zone
# (main_services/processing/tasks/P_ops/backup.py). It runs in the operations pod, which holds the zone key. Arguments:
# fetch_clickhouse_object or remove_clickhouse_object, and the export folder. fetch copies the object into the export
# folder, so the copy holds it. remove deletes the object after the copy. An export without an object changes nothing.
CLICKHOUSE_OBJECT = """
import sys
from tasks.P_ops import backup
print(getattr(backup, sys.argv[1])(sys.argv[2]))
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
    site layout uses the shared ClickHouse of the namespace hoover-stores (../../hoover/stores/shared.py), and the
    client uses its admin, whose password the store container holds in CH_ADMIN_PASSWORD. The queries name the
    databases of the zone. No password appears in a command argument of this host.
    """
    if hoover.stores != 'local':
        return ('hoover-stores', 'clickhouse-0', 'clickhouse',
                'exec clickhouse-client --user hoover_admin --password "$CH_ADMIN_PASSWORD" --format JSONEachRow')
    return (hoover.namespace, 'clickhouse-0', None,
            'exec clickhouse-client --user "${CLICKHOUSE_USER:-hoover4}" --password "${CLICKHOUSE_PASSWORD:-hoover4}" '
            '--format JSONEachRow')


def clickhouse(hoover, sql):
    """The output of sql in the ClickHouse of the installation. The standard input stays open until the client ends
    (../../podexec.py), because the output of a Kata pod stops after 32 KiB once kubectl closes it."""
    import podexec
    ns, pod, container, command = clickhouse_command(hoover)
    r = podexec.call(['kubectl', '--kubeconfig', k3s_settings.KUBECONFIG, '-n', ns, 'exec', '-i', pod,
                      *(['-c', container] if container else [])], ['sh', '-c', command], sql, timeout=3600)
    if r.returncode:
        raise SystemExit(f'ClickHouse of {hoover.name} refused the query: {r.stderr.strip()[-500:]}')
    return r.stdout


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
    for hoover in site_config.hoovers(s).values():
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
    """The destination folder of vars.backup, mounted at the same path in the runner container of the operator pod.

    The operator pod runs on the backup node and mounts the folder of that node (../operator/backup-mount.py). Every
    check, write, rename, removal and read is a file operation of this process, so no copy needs SSH. A command that runs
    on a host without the folder reports the problem of a missing destination.
    """

    def __init__(self, s):
        self.node = s.nodes[s.backup['node']]
        self.path = s.backup['path']

    def problem(self):
        if not os.path.isdir(self.path):
            return (f'the backup destination {self.path} of {self.node.name} is not mounted here. Run backups.py in the '
                    'runner container of the operator pod.')
        problem = schedule.destination_problem(self.path)
        return f'{self.node.name}: {problem}' if problem else ''

    def free_bytes(self):
        stat = os.statvfs(self.path)
        return stat.f_bavail * stat.f_frsize

    def folder(self, key, generation):
        return f'{self.path}/{job_folder(key)}/{name_arg(generation, "generation")}'

    def staging(self, key, generation):
        """The folder in which a job writes its copy. It is on the volume of the copies, so publish() renames it."""
        return Path(self.path) / STAGING / key.replace(':', '_') / f'{name_arg(generation, "generation")}.partial'

    def copies(self):
        """{job folder: [generations]} of the destination, from its folders."""
        found = {}
        for top in ('platform', 'zones'):
            root = Path(self.path) / top
            for manifest_path in root.rglob(MANIFEST) if root.is_dir() else ():
                relative = manifest_path.parent.relative_to(self.path)
                if len(relative.parts) < 2 or len(relative.parts) > 5:
                    continue
                folder, generation = '/'.join(relative.parts[:-1]), relative.parts[-1]
                if not generation.endswith('.partial'):
                    found.setdefault(folder, []).append(generation)
        return {k: sorted(v) for k, v in sorted(found.items())}

    def check(self, key, generation):
        """Read a copy again against its manifest."""
        path = self.folder(key, generation)
        if not os.path.isfile(os.path.join(path, MANIFEST)):
            raise SystemExit(f'the copy {path} does not exist.')
        return verify(path)

    def publish(self, partial, key, generation):
        """Rename a staging folder that verify() accepted into the folder of its copy.

        The staging folder is on the same file system, so the rename moves no data, and the copy is not read again.
        """
        final = self.folder(key, generation)
        partial = Path(partial)
        if not str(partial).startswith(str(Path(self.path) / STAGING) + '/'):
            raise SystemExit(f'{partial} is not a staging folder of the backup destination {self.path}.')
        checked = verify(partial)
        if checked['differences']:
            raise SystemExit(f'the copy {partial} differs from its manifest: {checked["differences"][:5]}')
        Path(final).parent.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(final, ignore_errors=True)
        os.rename(partial, final)
        return final, checked

    def remove(self, path):
        if not path.startswith(self.path.rstrip('/') + '/'):
            raise SystemExit(f'{path} is outside the backup destination {self.path}.')
        shutil.rmtree(path, ignore_errors=True)

    def enable(self):
        """Write the folders and the marker. The host step of the backup node writes them too."""
        for name in ('zones', 'platform', STAGING):
            os.makedirs(os.path.join(self.path, name), exist_ok=True)
        Path(self.path, schedule.MARKER).write_text('This folder receives the backups of the hoover4 site.\n')


# The folder of the destination in which a job writes its copy before the rename.
STAGING = 'staging'


def destination(s):
    """(Destination, problem). The Destination is None when the site file has no vars.backup."""
    if not s.backup:
        return None, 'the site file has no vars.backup.'
    target = Destination(s)
    return target, target.problem()


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
    holder = oplock.site_lock(s.operator_state()).busy()
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
    """The file count, the byte count and the paths that differ from the manifest, files that it lacks included."""
    wanted = json.loads((Path(folder) / MANIFEST).read_text())
    found = {r['path']: r for r in manifest(folder)}
    differences = [r['path'] for r in wanted['files'] if found.get(r['path']) != r]
    differences += sorted(set(found) - {r['path'] for r in wanted['files']})
    return {'files': len(wanted['files']), 'bytes': sum(r['bytes'] for r in wanted['files']), 'differences': differences}


# GNU tar ends with status 1 and these messages when a file of a running application changed or went away while it
# read it. The archive is complete, and the copy of a running zone accepts that (online_parts()).
TAR_CHANGED = (b'file changed as we read it', b'File removed before we read it')


def tar_status_ok(code, stderr):
    if code == 0:
        return True
    lines = [line for line in (stderr or b'').splitlines() if line.strip()]
    return code == 1 and bool(lines) and all(any(m in line for m in TAR_CHANGED) or line.endswith(b'Exiting with failure status due to previous errors') for line in lines)


def tar_command(ns, pod, container, folder, tar=('tar',), members=('.',)):
    return ['kubectl', '--kubeconfig', k3s_settings.KUBECONFIG, '-n', ns, 'exec', pod,
            *(['-c', container] if container else []), '--', *tar, '-C', folder, '-cf', '-', *members]


def stream_out(ns, pod, container, folder, target):
    """Copy a folder of a pod into a host folder with tar over kubectl exec.

    tar -x accepts a stream that ends between two members, so the stream goes into a host tar file first. tar_out()
    checks that file to its end-of-archive marker, and only a complete file is unpacked.
    """
    target.mkdir(parents=True, exist_ok=True)
    archive = target.parent / f'{target.name}.stream.tar'
    try:
        tar_out(ns, pod, container, folder, archive)
        subprocess.run(['tar', '-C', str(target), '-xf', str(archive), '--no-same-owner'], check=True)
    finally:
        archive.unlink(missing_ok=True)


# The block size of a tar file. tar ends an archive with two zero blocks and can pad it with more zero blocks.
TAR_BLOCK = 512


def tar_complete(path):
    """True when the tar file at path holds every member and the end-of-archive marker after the last member.

    tarfile stops without an error at the end of the file, also when a cut stream ends between two members. So the
    file must also be a whole number of blocks, and the bytes after the last member must be at least two blocks and
    all zero.
    """
    import tarfile
    try:
        with tarfile.open(path, mode='r:') as archive:
            for _ in archive:
                pass
            end = archive.offset
    except (tarfile.TarError, EOFError, OSError):
        return False
    size = os.path.getsize(path)
    if size % TAR_BLOCK or size - end < 2 * TAR_BLOCK:
        return False
    with open(path, 'rb') as f:
        f.seek(end)
        while chunk := f.read(1 << 20):
            if chunk.count(0) != len(chunk):
                return False
    return True


def tar_out(ns, pod, container, folder, target, tar=('tar',), settled=None, members=('.',), changed_ok=True):
    """Write a folder of a pod, or the members of the folder, into one host tar file, with their owners and modes.

    kubectl exec can end with status 0 after a stream reset, so the file is read to its end. An incomplete file is
    written again, up to three times. settled() gives a value before and after the read. When the two differ, a file
    changed during the read, and the file is written again (lmdb_meta()). Without changed_ok, a file that changed or
    went away during the read also makes the file written again.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        before = settled() if settled else None
        with open(target, 'wb') as out:
            result = subprocess.run(tar_command(ns, pod, container, folder, tar, members), stdout=out, stderr=subprocess.PIPE)
        status = tar_status_ok(result.returncode, result.stderr) if changed_ok else result.returncode == 0
        if status and tar_complete(target) and (settled is None or settled() == before):
            return
    raise SystemExit(f'the copy of {pod}:{folder} failed, stayed incomplete or changed during the read after three attempts.')


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
    hoover = next(h for h in site_config.hoovers(s).values() if h.zone == zone)
    ns = hoover.namespace
    pod = operations_pod(ns)
    name = f'backup-{collection}-{generation}'
    kubectl('-n', ns, 'exec', pod, '--', 'sh', '-c', f'cd /app && {" ".join(PYTHON)} export-collection {collection} --destination {name} --wait')
    problems = json.loads(kubectl('-n', ns, 'exec', pod, '--', PYTHON[0], '-c', META_CHECK, f'/backups/{name}').strip() or '[]')

    def remove_export():
        kubectl('-n', ns, 'exec', pod, '--', PYTHON[0], '-c', CLICKHOUSE_OBJECT, 'remove_clickhouse_object', f'/backups/{name}')
        kubectl('-n', ns, 'exec', pod, '--', 'rm', '-rf', f'/backups/{name}')
    if problems:
        remove_export()
        raise SystemExit(f'the export of {collection} holds Manticore metadata that the import cannot read: {problems}. '
                         f'The copy is not kept. Run the job again.')
    kubectl('-n', ns, 'exec', pod, '--', PYTHON[0], '-c', CLICKHOUSE_OBJECT, 'fetch_clickhouse_object', f'/backups/{name}')
    stream_out(ns, pod, None, f'/backups/{name}', partial)
    remove_export()


# The shared stores of a site zone (../../hoover/stores/shared.py) hold the zone databases and the system bucket. The
# zone job copies them into hoover/<installation>/shared/ of the copy: the archive of the ClickHouse databases
# <prefix> and <prefix>_Processing (clickhouse.tar), the objects of the bucket <zone>-system (system-bucket.tar) and
# stores.json. The shared ClickHouse writes the archive with BACKUP ... TO S3 into the export bucket of the zone with
# the zone key, as the collection export does. The S3 client of ../../hoover/stores/garage_client.py copies the
# archive and the bucket out and deletes the archive object. It runs in a short pod of the Hoover namespace
# (garage_s3()), not in the Garage pod: kubectl exec with standard input into a Kata pod stopped its output after
# 32 KiB on the test site. The collection buckets and the Manticore tables are in
# the collection copies (job hoover:<zone>:<collection>).
SHARED_PART = 'shared'
GARAGE_ENDPOINT = 'garage.hoover-stores.svc.cluster.local:3900'
GARAGE_S3 = f'http://{GARAGE_ENDPOINT}'


@contextlib.contextmanager
def garage_s3(hoover, zone_key):
    """Yield run(command, *args, data=None, out=None) of the S3 client with the zone key against the shared Garage,
    in a short pod of the Hoover namespace of the zone, which the network policies of the stores admit."""
    first = {'endpoint': GARAGE_ENDPOINT, **{k: zone_key[k] for k in ('access_key', 'secret_key')}}
    pod = s3_pod(hoover.namespace)
    try:
        yield lambda command, *args, data=None, out=None: s3_run(hoover.namespace, pod, first, command, *args, data=data, out=out)
    finally:
        kubectl('-n', hoover.namespace, 'delete', 'pod', pod, '--wait=false', check=False)


def zone_databases(hoover):
    prefix = hoover.clickhouse_database_prefix
    return [prefix, f'{prefix}_Processing']


def sql_text(text):
    return "'" + text.replace('\\', '\\\\').replace("'", "\\'") + "'"


def s3_target(bucket, key, zone_key):
    return f"S3({sql_text(f'{GARAGE_S3}/{bucket}/{key}')}, {sql_text(zone_key['access_key'])}, {sql_text(zone_key['secret_key'])})"


def clickhouse_with_key(hoover, sql, zone_key):
    """clickhouse() for a statement that holds the zone key. The client repeats a failed statement in its error, so
    the error loses the secret."""
    try:
        return clickhouse(hoover, sql)
    except SystemExit as error:
        raise SystemExit(str(error).replace(zone_key['secret_key'], '[HIDDEN]')) from None


@contextlib.contextmanager
def archive_object(run, bucket, key):
    """Delete the archive object after the block. After a failure in the block, a failed delete does not hide it."""
    try:
        yield
    except BaseException:
        with contextlib.suppress(SystemExit):
            run('delete', bucket, key)
        raise
    run('delete', bucket, key)


def clickhouse_status(output, wanted):
    """The status of a BACKUP or RESTORE answer, or SystemExit when it is not wanted."""
    rows = [json.loads(line) for line in output.splitlines() if line.strip().startswith('{')]
    status = rows[-1].get('status') if rows else None
    if status != wanted:
        raise SystemExit(f'ClickHouse answered {status or output.strip()[-300:]!r} instead of {wanted}.')
    return status


def copy_shared_stores(hoover, target):
    """Copy the zone databases and the system bucket of a site zone into target. The zone is closed."""
    import garage_client
    target.mkdir(parents=True, exist_ok=True)
    wanted = zone_databases(hoover)
    present = [json.loads(line)['name'] for line in clickhouse(
        hoover, f"SELECT name FROM system.databases WHERE name IN ({', '.join(sql_text(n) for n in wanted)})").splitlines()
        if line.strip()]
    databases = [n for n in wanted if n in present]
    bucket = f'{hoover.zone}-exports'
    run_id = f'{int(time.time())}-{os.urandom(3).hex()}'
    key = f'zone-backups/{run_id}/clickhouse.tar'
    zone_key = garage_client.zone_key(hoover.zone)
    info = {'zone': hoover.zone, 'prefix': hoover.clickhouse_database_prefix, 'databases': databases,
            'system_bucket': hoover.system_bucket}
    with garage_s3(hoover, zone_key) as run:
        if databases:
            with archive_object(run, bucket, key):
                answer = clickhouse_with_key(hoover, f"BACKUP {', '.join(f'DATABASE `{n}`' for n in databases)} TO "
                                                     f"{s3_target(bucket, key, zone_key)} SETTINGS id='{info['prefix']}-zone-{run_id}'",
                                             zone_key)
                clickhouse_status(answer, 'BACKUP_CREATED')
                _, got = run('get', bucket, key, out=target / 'clickhouse.tar')
            # The copy must have the size of the object and the tar end marker.
            info['clickhouse_bytes'] = (target / 'clickhouse.tar').stat().st_size
            if (info['clickhouse_bytes'] != next((r['bytes'] for r in got if 'bytes' in r), -1)
                    or not tar_complete(target / 'clickhouse.tar')):
                raise SystemExit(f'the copy of the ClickHouse archive of {hoover.zone} is incomplete. Run the job again.')
        _, reports = run('tar', hoover.system_bucket, out=target / 'system-bucket.tar')
    if not tar_complete(target / 'system-bucket.tar'):
        raise SystemExit(f'the copy of {hoover.system_bucket} has no tar end. Run the job again.')
    info['system_objects'] = next((r['objects'] for r in reports if 'objects' in r), 0)
    (target / 'stores.json').write_text(json.dumps(info, indent=1))
    return info


def restore_shared_stores(folder, hoover):
    """Replace the zone databases and the objects of the system bucket of a site zone with a copy of
    copy_shared_stores(). A copy of another zone restores under the prefix of this zone. The zone is closed."""
    import garage_client
    info = json.loads((folder / 'stores.json').read_text())
    source, prefix = info['prefix'], hoover.clickhouse_database_prefix
    names = [(n, prefix + n[len(source):]) for n in info['databases']]
    bucket = f'{hoover.zone}-exports'
    key = f'imports/zone-restore-{int(time.time())}-{os.urandom(3).hex()}/clickhouse.tar'
    zone_key = garage_client.zone_key(hoover.zone)
    with garage_s3(hoover, zone_key) as run:
        if names:
            archive = folder / 'clickhouse.tar'
            with archive_object(run, bucket, key):
                run('put', bucket, key, str(archive.stat().st_size), data=archive)
                for _, name in names:
                    clickhouse(hoover, f'DROP DATABASE IF EXISTS `{name}` SYNC')
                answer = clickhouse_with_key(hoover, f"RESTORE {', '.join(f'DATABASE `{a}` AS `{b}`' for a, b in names)} FROM "
                                                     f"{s3_target(bucket, key, zone_key)} SETTINGS id='{prefix}-zone-restore-{key.split('/')[1]}'",
                                             zone_key)
                clickhouse_status(answer, 'RESTORED')
        run('empty', hoover.system_bucket)
        run('untar', hoover.system_bucket, data=folder / 'system-bucket.tar')


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
    try:
        kubectl('-n', ns, 'wait', '--for=condition=Ready', f'pod/{name}', '--timeout=300s')
    except SystemExit:
        # A reader that did not start, for example without free memory on the node of the claim, does not stay.
        kubectl('-n', ns, 'delete', 'pod', name, '--wait=false', check=False)
        raise
    return name


DATABASES = ('postgresql', 'mariadb')


def tier_of(namespace, name):
    sys.path.insert(0, str(K3S / 'driver'))
    import deploy
    return deploy.tier(namespace, name)


def close_zone(s, zone):
    """The record of the replicas of the applications, gates and workers of a zone and its Hoover installation, and of
    the suspension of their CronJobs. apply_closure() closes the zone with it, and reopen() restores it. The stores are
    not in it."""
    namespaces = [zone] + [h.namespace for h in site_config.hoovers(s).values() if h.zone == zone]
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


# The parts of an online zone copy and the moment of each. The copy reads a running zone, so the parts hold different
# moments. The order puts each database before the files and objects that its rows name: an object that a row names
# was written before the row, so the later object copy holds it, unless the application deleted it in between. The
# copy then holds objects without a row, which the applications ignore.
#   postgresql.sql, mariadb.sql  pg_dumpall and mariadb-dump --single-transaction: each database at one moment.
#   postgresql/<database>.sql   pg_dump of each openDesk database of a zone on the shared PostgreSQL, without owner
#                                and rights: each database at one moment.
#   claims/                      a tar file of each claim. A file can change while tar reads it. An LMDB file of
#                                OpenLDAP is read again until no write committed during its read (lmdb_meta()). A
#                                Block claim of Redis or NATS holds their append files: both stores read a file with a
#                                cut last record at their start.
#   objects/                     the objects of each bucket of the openDesk object store, through its S3 API: the
#                                openDesk buckets of the zone in Garage, or SeaweedFS in a zone that has not moved.
#   hoover/<name>/shared/        BACKUP of the zone databases in ClickHouse (each table at one moment), then the objects
#                                of the system bucket.
# restore-zone writes every part while the zone is closed, then opens it. Each application starts from the restored
# parts.
def online_parts():
    return ['postgresql.sql', 'postgresql/', 'mariadb.sql', 'claims/', 'objects/', 'hoover/<name>/claims/', 'hoover/<name>/shared/']


class Moments:
    """The start and the end of each part of a copy, in Unix seconds, for moments.json."""

    def __init__(self):
        self.parts = {}

    @contextlib.contextmanager
    def part(self, name):
        started = time.time()
        yield
        self.parts[name] = {'started': round(started, 1), 'finished': round(time.time(), 1)}


def run_zone(s, zone, partial, key=None):
    """Copy a running zone: its namespace into partial, and each Hoover installation into partial/hoover/<name>/.

    No workload stops. workloads.json records the replicas, and moments.json the time of each part.
    """
    partial.mkdir(parents=True, exist_ok=True)
    moments = Moments()
    workloads = close_zone(s, zone)
    copy_namespace(zone, partial, moments)
    for hoover in (h for h in site_config.hoovers(s).values() if h.zone == zone):
        copy_namespace(hoover.namespace, partial / 'hoover' / hoover.name, moments, f'hoover/{hoover.name}/')
        if hoover.stores == 'site':
            with moments.part(f'hoover/{hoover.name}/{SHARED_PART}'):
                copy_shared_stores(hoover, partial / 'hoover' / hoover.name / SHARED_PART)
    (partial / 'workloads.json').write_text(json.dumps(workloads, indent=1))
    (partial / 'moments.json').write_text(json.dumps({'online': True, 'parts': moments.parts}, indent=1))


# The last line that each dump tool writes. A dump without it ended early, for example after a stream reset of
# kubectl exec, which can end with status 0.
DUMP_TRAILERS = {'postgresql.sql': b'-- PostgreSQL database cluster dump complete', 'mariadb.sql': b'-- Dump completed on '}
# The folder of the dumps of the openDesk databases of a zone on the shared PostgreSQL, and the trailer of pg_dump.
SHARED_DUMPS = 'postgresql'
SHARED_DUMP_TRAILER = b'-- PostgreSQL database dump complete'


def dump_complete(path):
    """True when the database dump at path ends with the trailer line of its dump tool."""
    path = Path(path)
    trailer = SHARED_DUMP_TRAILER if path.parent.name == SHARED_DUMPS else DUMP_TRAILERS[path.name]
    with open(path, 'rb') as f:
        f.seek(max(0, path.stat().st_size - 4096))
        return trailer in f.read()


def shared_databases(zone):
    """The postgresql module (../../zones/postgresql.py) when the zone keeps its openDesk databases on the shared
    PostgreSQL, else None."""
    sys.path.insert(0, str(K3S / 'zones'))
    import postgresql
    import zonestate
    try:
        entry = zonestate.load()['zones'].get(zone) or {}
    except zonestate.ZoneStateError:
        return None
    return postgresql if postgresql.on_shared(entry) else None


def copy_shared_databases(zone, module, target):
    """Write a pg_dump of each openDesk database of a zone on the shared PostgreSQL into target/<database>.sql. Each
    dump holds one moment of its database, without owner and rights, so it restores into the database of any zone."""
    target.mkdir(parents=True, exist_ok=True)
    pod = module.shared().ready_pod('postgresql')
    for key, (name, _) in sorted(module.DATABASES.items()):
        dump_out(module.STORES_NS, [pod, '-c', 'postgresql', '--', 'pg_dump', '-U', 'postgres', '--no-owner', '--no-acl',
                                    '-d', module.database_name(zone, key)], target / f'{name}.sql')


def dump_out(ns, exec_args, target):
    """Write the output of a dump command in a pod into target. An incomplete dump is written again, up to three times."""
    for attempt in range(3):
        with open(target, 'wb') as out:
            kubectl('-n', ns, 'exec', *exec_args, stdout=out)
        if dump_complete(target):
            return
    raise SystemExit(f'the dump {target.name} of {ns} stayed incomplete after three attempts.')


def copy_namespace(ns, partial, moments=None, label=''):
    """Copy the database dumps, the claims, the object store, the Secrets and the ConfigMaps of one running namespace
    into partial, in the order of online_parts()."""
    moments = moments or Moments()
    partial.mkdir(parents=True, exist_ok=True)
    pods = json.loads(kubectl('-n', ns, 'get', 'pods', '-o', 'json'))['items']
    names = {p['metadata']['name'] for p in pods if p['status'].get('phase') == 'Running'}
    module = shared_databases(ns)
    if module:
        with moments.part(label + SHARED_DUMPS + '/'):
            copy_shared_databases(ns, module, partial / SHARED_DUMPS)
    elif 'postgresql-0' in names:
        # --clean lets restore-zone replace the databases of a zone that the installer created.
        with moments.part(label + 'postgresql.sql'):
            dump_out(ns, ['postgresql-0', '-c', 'postgresql', '--', 'pg_dumpall', '-U', 'postgres', '--clean', '--if-exists'],
                     partial / 'postgresql.sql')
    if 'mariadb-0' in names:
        with moments.part(label + 'mariadb.sql'):
            dump_out(ns, ['mariadb-0', '--', 'sh', '-c',
                          'mariadb-dump --all-databases --single-transaction -uroot -p"$MARIADB_ROOT_PASSWORD"'],
                     partial / 'mariadb.sql')
    store = object_store(ns, pods)
    garage_key = None if store else opendesk_garage_key(ns)
    claims = json.loads(kubectl('-n', ns, 'get', 'pvc', '-o', 'json'))['items']
    rows = []
    with moments.part(label + 'claims/'):
        for item in claims:
            claim = item['metadata']['name']
            if any(d in claim for d in DATABASES) or any(o['kind'] == 'Pod' for o in item['metadata'].get('ownerReferences', [])):
                continue
            if store and claim in store['claims']:
                # The object store is copied through its S3 API (copy_objects()). Its files change while it runs.
                continue
            mode = item['spec'].get('volumeMode') or 'Filesystem'
            target = partial / 'claims' / f'{claim}.tar'
            if mode == 'Block':
                source = block_source(claim, pods)
                if source is None:
                    raise SystemExit(f'no running store pod mounts the Block claim {ns}/{claim}. Start the zone and run the job again.')
                tar_out(ns, *source, target, tar=('/tools/busybox', 'tar'))
            elif mounted := mount_source(ns, claim, pods):
                # The running pod of the claim reads it with its own tar, so the copy needs no free memory on the
                # node of the claim.
                tar_out(ns, *mounted, target, settled=lambda m=mounted: lmdb_meta(ns, *m))
            else:
                node = (item['metadata'].get('annotations') or {}).get('volume.kubernetes.io/selected-node')
                pod = helper_pod(ns, claim, node)
                try:
                    tar_out(ns, pod, None, '/data', target, settled=lambda pod=pod: lmdb_meta(ns, pod, None, '/data'))
                finally:
                    kubectl('-n', ns, 'delete', 'pod', pod, '--wait=false')
            rows.append({'claim': claim, 'size': item['spec']['resources']['requests']['storage'],
                         'storage_class': item['spec'].get('storageClassName'), 'volume_mode': mode})
    (partial / 'claims.json').write_text(json.dumps(rows, indent=1))
    if store:
        with moments.part(label + 'objects/'):
            copy_objects(ns, store, partial / 'objects')
    elif garage_key:
        with moments.part(label + 'objects/'):
            copy_garage_objects(ns, garage_key, partial / 'objects')
    (partial / 'objects.json').write_text(kubectl('-n', ns, 'get', 'secrets,configmaps', '-o', 'json'))
    os.chmod(partial / 'objects.json', 0o600)


# The check of the LMDB files of a claim: the SHA-256 of the two meta pages of each data.mdb below the folder. LMDB
# writes one meta page at each commit, so equal values before and after a read show that no write committed during the
# read, and the copy of the file is one state of the database. It uses find, head and sha256sum of the container.
LMDB_META = 'find "$0" -name data.mdb -type f | sort | while read -r f; do printf "%s " "$f"; head -c 8192 "$f" | sha256sum; done'


def lmdb_meta(ns, pod, container, folder):
    return kubectl('-n', ns, 'exec', pod, *(['-c', container] if container else []), '--', 'sh', '-c', LMDB_META,
                   folder).strip()


def mount_source(ns, claim, pods):
    """(pod, container, folder) of a running pod whose container mounts the file system claim and has tar, or None."""
    for pod in pods:
        if pod['status'].get('phase') != 'Running' or pod['metadata'].get('deletionTimestamp'):
            continue
        volumes = [v['name'] for v in pod['spec'].get('volumes', []) if (v.get('persistentVolumeClaim') or {}).get('claimName') == claim]
        for c in pod['spec'].get('containers', []) if volumes else []:
            for mount in c.get('volumeMounts', []):
                if mount['name'] in volumes and not mount.get('subPath'):
                    found = kubectl('-n', ns, 'exec', pod['metadata']['name'], '-c', c['name'], '--', 'sh', '-c',
                                    'command -v tar >/dev/null && echo yes', check=False)
                    if (found or '').strip() == 'yes':
                        return pod['metadata']['name'], c['name'], mount['mountPath']
    return None


# The openDesk object store of a zone that has not moved to Garage: the SeaweedFS pod of the zone (pod label
# hoover.dev/store=seaweedfs). Its S3 configuration (the Secret OBJECT_STORE_CONFIG) has the identity admin, which reads
# and writes every bucket. A zone on Garage keeps its openDesk buckets in the shared Garage with the key <zone>-opendesk
# (../../zones/objectstore.py), and the S3 client of a Garage pod copies them (copy_garage_objects()). A bucket whose
# application encrypts its objects with a customer key (SSE-C) names the Secret and the item of that key.
OBJECT_STORE_CONFIG = ('seaweedfs-config', 'seaweedfs_s3_config')
OBJECT_STORE_PORT = 8333
CUSTOMER_KEYS = {'synapse': ('synapse-s3-encryption-customer-key', 's3EncryptionCustomerKey')}


def object_store(ns, pods):
    """{'pod', 'claims', 'endpoint'} of the running object store of a namespace, or None."""
    for pod in pods:
        labels = pod['metadata'].get('labels') or {}
        if labels.get('hoover.dev/store') != 'seaweedfs' or pod['status'].get('phase') != 'Running':
            continue
        claims = [v['persistentVolumeClaim']['claimName'] for v in pod['spec'].get('volumes', []) if 'persistentVolumeClaim' in v]
        services = json.loads(kubectl('-n', ns, 'get', 'services', '-o', 'json'))['items']
        service = next((s['metadata']['name'] for s in services
                        if any(p.get('port') == OBJECT_STORE_PORT for p in s['spec'].get('ports', []))
                        and matches(s['spec'].get('selector') or {}, labels)), None)
        if service is None:
            raise SystemExit(f'no Service of {ns} reaches the S3 port {OBJECT_STORE_PORT} of {pod["metadata"]["name"]}.')
        return {'pod': pod['metadata']['name'], 'claims': claims, 'endpoint': f'{service}.{ns}.svc.cluster.local:{OBJECT_STORE_PORT}'}
    return None


def matches(selector, labels):
    return bool(selector) and all(labels.get(k) == v for k, v in selector.items())


def secret_item(ns, name, item):
    raw = kubectl('-n', ns, 'get', 'secret', name, '--ignore-not-found', '-o', 'json').strip()
    value = (json.loads(raw).get('data') or {}).get(item, '') if raw else ''
    return base64.b64decode(value) if value else b''


def customer_keys(ns):
    """{bucket: base64 customer key} of the buckets of ns whose application encrypts with a customer key."""
    sse = {}
    for bucket, (name, item) in CUSTOMER_KEYS.items():
        key = secret_item(ns, name, item)
        if key:
            sse[bucket] = base64.b64encode(key).decode()
    return sse


def object_store_key(ns, store):
    """The first line of the S3 client: the endpoint, the admin key and the customer keys of the buckets."""
    config = json.loads(secret_item(ns, *OBJECT_STORE_CONFIG) or b'{}')
    admin = next((i for i in config.get('identities', []) if i.get('name') == 'admin' and i.get('credentials')), None)
    if admin is None:
        raise SystemExit(f'the S3 configuration {ns}/{OBJECT_STORE_CONFIG[0]} has no identity admin.')
    credential = admin['credentials'][0]
    return {'endpoint': store['endpoint'], 'access_key': credential['accessKey'], 'secret_key': credential['secretKey'],
            'sse_c': customer_keys(ns)}


def opendesk_garage_key(ns):
    """The Garage key of the openDesk buckets of the zone ns, read from the Garage admin, or None. The local zone
    state can be older than the cluster copy, so the key comes from Garage."""
    import garage_client
    found = [key_id for key_id, name in garage_client.keys().items() if name == f'{ns}-opendesk']
    return garage_client.key(found[0]) if found else None


def opendesk_buckets():
    sys.path.insert(0, str(K3S / 'zones'))
    import objectstore
    return sorted(objectstore.BUCKETS.values())


def copy_garage_objects(ns, key, target):
    """Copy each openDesk bucket of the zone ns from Garage into target/<bucket>.tar, and the bucket list into
    target/buckets.json, in the form of copy_objects()."""
    import garage_client
    target.mkdir(parents=True, exist_ok=True)
    sse = customer_keys(ns)
    rows = []
    with garage_client.client() as pod:
        for bucket in opendesk_buckets():
            path = target / f'{bucket}.tar'
            for attempt in range(3):
                _, reports = garage_client.run(pod, key, 'tar', bucket, out=path, sse_c={bucket: sse[bucket]} if bucket in sse else None)
                if tar_complete(path):
                    break
            else:
                raise SystemExit(f'the copy of the bucket {bucket} of {ns} in Garage stayed incomplete after three attempts.')
            report = next((r for r in reports if 'objects' in r), {})
            rows.append({'bucket': bucket, 'objects': report.get('objects', 0),
                         'customer_key_objects': report.get('customer_key_objects', 0)})
    (target / 'buckets.json').write_text(json.dumps(rows, indent=1))


def s3_pod(ns):
    """A short pod in ns that runs the S3 client of ../../hoover/stores/garage_client.py. It mounts nothing."""
    name = 'backup-s3'
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': ns, 'labels': {'app.kubernetes.io/name': 'backup-reader'}},
           'spec': {'restartPolicy': 'Never', 'automountServiceAccountToken': False, 'enableServiceLinks': False,
                    'containers': [{'name': 'read', 'image': HELPER_IMAGE, 'command': ['sleep', '3600'],
                                    'resources': {'limits': {'memory': '256Mi'}}}]}}
    kubectl('-n', ns, 'delete', 'pod', name, '--ignore-not-found', '--wait=true')
    kubectl('apply', '-f', '-', input=json.dumps(pod))
    try:
        kubectl('-n', ns, 'wait', '--for=condition=Ready', f'pod/{name}', '--timeout=300s')
    except SystemExit:
        kubectl('-n', ns, 'delete', 'pod', name, '--wait=false', check=False)
        raise
    return name


def s3_run(ns, pod, first, *args, data=None, out=None):
    """Run one command of the S3 client in pod. Return (standard output, report lines). A secret of first does not
    appear in an error."""
    import tempfile
    import garage_client
    argv = ['kubectl', '--kubeconfig', k3s_settings.KUBECONFIG, '-n', ns, 'exec', '-i', pod, '--', 'python3', '-I', '-c',
            garage_client.SCRIPT, *args]
    with tempfile.TemporaryFile() as errors, (open(out, 'wb') if out else tempfile.TemporaryFile()) as output:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=output, stderr=errors)
        try:
            process.stdin.write(json.dumps(first).encode() + b'\n')
            if data is not None:
                with open(data, 'rb') as source:
                    shutil.copyfileobj(source, process.stdin, 1 << 20)
            process.stdin.close()
        except BrokenPipeError:
            pass
        code = process.wait()
        errors.seek(0)
        text = errors.read().decode(errors='replace')
        for secret in [first['secret_key'], *first.get('sse_c', {}).values()]:
            text = text.replace(secret, '[HIDDEN]')
        if code:
            raise SystemExit(f'the object store command {args[0]} {" ".join(args[1:2])} in {ns} failed: {text.strip()[-400:]}')
        output.seek(0)
        return (None if out else output.read().decode()), [json.loads(l) for l in text.splitlines() if l.startswith('{')]


def copy_objects(ns, store, target):
    """Copy every bucket of the object store of ns into target/<bucket>.tar, and the bucket list into
    target/buckets.json."""
    target.mkdir(parents=True, exist_ok=True)
    first = object_store_key(ns, store)
    pod = s3_pod(ns)
    try:
        listed, _ = s3_run(ns, pod, first, 'buckets')
        buckets = json.loads(listed.strip().splitlines()[-1])
        rows = []
        for bucket in buckets:
            name_arg(bucket, 'bucket')
            path = target / f'{bucket}.tar'
            for attempt in range(3):
                _, reports = s3_run(ns, pod, first, 'tar', bucket, out=path)
                if tar_complete(path):
                    break
            else:
                raise SystemExit(f'the copy of the bucket {bucket} of {ns} stayed incomplete after three attempts.')
            report = next((r for r in reports if 'objects' in r), {})
            rows.append({'bucket': bucket, 'objects': report.get('objects', 0),
                         'customer_key_objects': report.get('customer_key_objects', 0)})
        (target / 'buckets.json').write_text(json.dumps(rows, indent=1))
    finally:
        kubectl('-n', ns, 'delete', 'pod', pod, '--wait=false')


def restore_objects(folder, ns):
    """Replace the objects of each bucket of the copy in the running object store of ns, or in the openDesk buckets of
    the zone in Garage. Other buckets stay. A copy of SeaweedFS and a copy of Garage have the same form."""
    rows = json.loads((folder / 'objects' / 'buckets.json').read_text())
    pods = json.loads(kubectl('-n', ns, 'get', 'pods', '-o', 'json'))['items']
    store = object_store(ns, pods)
    key = None if store else opendesk_garage_key(ns)
    if key:
        import garage_client
        unknown = sorted({row['bucket'] for row in rows} - set(opendesk_buckets()))
        if unknown:
            raise SystemExit(f'the copy has the buckets {", ".join(unknown)}, which the zone has not in Garage. The zone stays closed.')
        sse = customer_keys(ns)
        with garage_client.client() as pod:
            for row in rows:
                bucket = row['bucket']
                garage_client.run(pod, key, 'empty', bucket)
                garage_client.run(pod, key, 'untar', bucket, data=folder / 'objects' / f'{bucket}.tar',
                                  sse_c={bucket: sse[bucket]} if bucket in sse else None)
        return
    if store is None:
        raise SystemExit(f'{ns} has no running object store, which the restore of the objects needs. The zone stays closed.')
    first = object_store_key(ns, store)
    pod = s3_pod(ns)
    try:
        for row in rows:
            bucket = name_arg(row['bucket'], 'bucket')
            s3_run(ns, pod, first, 'mkbucket', bucket)
            s3_run(ns, pod, first, 'empty', bucket)
            s3_run(ns, pod, first, 'untar', bucket, data=folder / 'objects' / f'{bucket}.tar')
    finally:
        kubectl('-n', ns, 'delete', 'pod', pod, '--wait=false')


RECOVERY_FORMAT = 'hoover4-platform-recovery'
# Version 2 holds a snapshot that the job saved over SSH. Version 3 holds the newest scheduled snapshot of k3s with its
# time (snapshot_created). Both hold etcd/ in the same form, so the restore steps are the same.
RECOVERY_VERSIONS = (2, 3)
# The private folders that hold no recovery input: builds, downloads, tool binaries, the staged k3s files of each
# architecture of earlier installers, the node facts and the generated Ansible inventory. staging/tokens holds the site
# tokens and is part of the copy.
PRIVATE_EXCLUDED = ['build', 'bin', 'browser-venv', 'checks', 'downloads', 'operator/backups', 'operator/deploy/logs',
                    'staging/amd64', 'staging/arm64', 'deploy/remote', 'facts', 'ansible']


# The platform job reads the newest scheduled etcd snapshot of the k3s server. k3s saves one every 12 hours with its
# default schedule (etcd-snapshot-schedule-cron "0 */12 * * *") and keeps 5 (etcd-snapshot-retention) in SNAPSHOT_DIR.
# A newest snapshot older than SNAPSHOT_MAX_AGE, two schedule intervals, shows that the schedule does not run, and the
# job fails. k3s saves a snapshot as <name>.part and renames it when it is complete, so SNAPSHOT_FILE does not match an
# incomplete file. The optional .zip is the form of etcd-snapshot-compress.
SNAPSHOT_DIR = '/var/lib/rancher/k3s/server/db/snapshots'
TOKEN_FILE = '/var/lib/rancher/k3s/server/token'
K3S_CONFIG = '/etc/rancher/k3s/config.yaml'
SNAPSHOT_FILE = __import__('re').compile(r'etcd-snapshot-.+-([0-9]{9,})(\.zip)?')
SNAPSHOT_MAX_AGE = 24 * 3600
# The short pod that reads the snapshot on the control plane. The namespace, its ServiceAccount without rights, the
# rights of the runner there and the policy that admits only this pod form are in ../operator/runner-rights.yaml.
READER_NAMESPACE = 'platform-backup'
READER_ACCOUNT = 'k3s-snapshot-reader'
READER_POD = 'k3s-snapshot-read'
READER_ROOT = '/k3s'


def snapshot_reader(node):
    """The pod that mounts the snapshot folder, the token and the k3s configuration of the server read-only.

    It runs as root, because the files belong to root with mode 0600, but with no capability, no privilege escalation
    and a read-only root file system. It has no API token. The runner streams the files out with tar and deletes the
    pod. A weekly job of under a minute needs no pod that stays running, and such a pod would keep the token mounted
    and hold memory on the control plane all the time.
    """
    mounts = [('snapshots', SNAPSHOT_DIR, 'Directory', f'{READER_ROOT}/snapshots'),
              ('token', TOKEN_FILE, 'File', f'{READER_ROOT}/token'),
              ('config', K3S_CONFIG, 'File', f'{READER_ROOT}/config.yaml')]
    return {'apiVersion': 'v1', 'kind': 'Pod',
            'metadata': {'name': READER_POD, 'namespace': READER_NAMESPACE,
                         'labels': {'app.kubernetes.io/name': 'k3s-snapshot-reader'}},
            'spec': {'restartPolicy': 'Never', 'serviceAccountName': READER_ACCOUNT,
                     'automountServiceAccountToken': False, 'enableServiceLinks': False,
                     'activeDeadlineSeconds': 3600, 'nodeSelector': {'kubernetes.io/hostname': node},
                     'tolerations': [{'key': 'node-role.kubernetes.io/control-plane', 'operator': 'Exists',
                                      'effect': 'NoSchedule'}],
                     'securityContext': {'runAsUser': 0, 'runAsGroup': 0, 'seccompProfile': {'type': 'RuntimeDefault'}},
                     'containers': [{'name': 'read', 'image': HELPER_IMAGE, 'command': ['sleep', '3600'],
                                     'resources': {'requests': {'cpu': '10m', 'memory': '32Mi'},
                                                   'limits': {'memory': '256Mi'}},
                                     'securityContext': {'allowPrivilegeEscalation': False, 'privileged': False,
                                                         'readOnlyRootFilesystem': True,
                                                         'capabilities': {'drop': ['ALL']}},
                                     'volumeMounts': [{'name': n, 'mountPath': m, 'readOnly': True}
                                                      for n, _, _, m in mounts]}],
                     'volumes': [{'name': n, 'hostPath': {'path': p, 'type': kind}} for n, p, kind, _ in mounts]}}


def newest_snapshot(names, now):
    """(file name, creation time) of the newest scheduled snapshot of names. The time is in the name."""
    found = sorted((int(m.group(1)), name) for name in names if (m := SNAPSHOT_FILE.fullmatch(name)))
    if not found:
        raise SystemExit(f'the control plane has no scheduled etcd snapshot in {SNAPSHOT_DIR}. k3s saves one every 12 '
                         'hours. Check that the server uses etcd and that etcd-disable-snapshots is not set.')
    created, name = found[-1]
    age = now - created
    if age > SNAPSHOT_MAX_AGE:
        raise SystemExit(f'the newest scheduled etcd snapshot {name} is {age / 3600:.1f} hours old, and the limit is '
                         f'{SNAPSHOT_MAX_AGE // 3600} hours. Check the snapshot schedule in journalctl -u k3s on the '
                         'control plane.')
    return name, created


def reader_exec(*args):
    return kubectl('-n', READER_NAMESPACE, 'exec', READER_POD, '-c', 'read', '--', *args)


def start_snapshot_reader(node):
    """Create the reader pod on the control plane and wait until it runs. A reader of an earlier job goes first."""
    kubectl('-n', READER_NAMESPACE, 'delete', 'pod', READER_POD, '--ignore-not-found', '--wait=true')
    kubectl('create', '-f', '-', input=json.dumps(snapshot_reader(node)))
    try:
        kubectl('-n', READER_NAMESPACE, 'wait', '--for=condition=Ready', f'pod/{READER_POD}', '--timeout=300s')
    except SystemExit:
        kubectl('-n', READER_NAMESPACE, 'delete', 'pod', READER_POD, '--wait=false', check=False)
        raise


def read_snapshot(node, etcd, now):
    """Copy the newest scheduled snapshot, the token and the k3s configuration of the server into the folder etcd.

    The files come as one tar stream that must reach its end-of-archive marker, as the claims of a zone copy do. Each
    file must then have the SHA-256 that the pod computed. etcd/host.json names the snapshot in the form that the restore
    command of k3s-datastore.py reads. The function returns the content of host.json.
    """
    start_snapshot_reader(node)
    try:
        name, created = newest_snapshot(reader_exec('ls', '-1', f'{READER_ROOT}/snapshots').split(), now)
        members = [f'snapshots/{name}', 'token', 'config.yaml']
        digests = {}
        for line in reader_exec('sha256sum', *[f'{READER_ROOT}/{m}' for m in members]).splitlines():
            digest, path = line.split(None, 1)
            digests[Path(path).name] = digest
        archive = etcd.parent / 'etcd.stream.tar'
        tar_out(READER_NAMESPACE, READER_POD, 'read', READER_ROOT, archive, members=members, changed_ok=False)
    finally:
        kubectl('-n', READER_NAMESPACE, 'delete', 'pod', READER_POD, '--wait=false', check=False)
    etcd.mkdir(mode=0o700)
    try:
        subprocess.run(['tar', '-C', str(etcd), '-xf', str(archive), '--no-same-owner'], check=True)
    finally:
        archive.unlink(missing_ok=True)
    (etcd / 'snapshots' / name).rename(etcd / name)
    (etcd / 'snapshots').rmdir()
    for file, digest in digests.items():
        if hashlib.sha256((etcd / file).read_bytes()).hexdigest() != digest:
            raise SystemExit(f'the snapshot file {file} changed in the transfer.')
        os.chmod(etcd / file, 0o600)
    version = kubectl('get', 'node', node, '-o', 'jsonpath={.status.nodeInfo.kubeletVersion}').strip()
    host = {'node': node, 'snapshot': name, 'k3s_version': version, 'datastore': 'etcd',
            'created': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(created)), 'sha256': digests}
    (etcd / 'host.json').write_text(json.dumps(host, indent=1, sort_keys=True) + '\n')
    return host


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


def run_platform(s, partial, now=None):
    """The newest scheduled etcd snapshot of the control plane with its token and configuration, the private files and
    recovery.json."""
    partial.mkdir(parents=True, exist_ok=True)
    node = s.control_plane
    host = read_snapshot(node, partial / 'etcd', now or time.time())
    private = k3s_settings.PRIVATE
    subprocess.run(['tar', '-C', str(private), '-cf', str(partial / 'private.tar'),
                    *[f'--exclude=./{e}' for e in PRIVATE_EXCLUDED], '.'], check=True)
    os.chmod(partial / 'private.tar', 0o600)
    state = s.operator_state()
    applied = json.loads((state / 'deploy' / 'applied.json').read_text()) if (state / 'deploy' / 'applied.json').exists() else {}
    settings_applied = json.loads((state / 'applied.json').read_text()) if (state / 'applied.json').exists() else {}
    recovery = {
        'format': RECOVERY_FORMAT, 'format_version': 3, 'datastore': 'etcd', 'route': 'reader-pod',
        'snapshot_source': 'k3s-schedule', 'snapshot_created': host['created'],
        'execution_host': socket.gethostname(), 'control_plane': node, 'destination_node': s.backup.get('node'),
        'k3s_version': host['k3s_version'], 'snapshot': f'etcd/{host["snapshot"]}', 'token': 'etcd/token',
        'k3s_config': 'etcd/config.yaml', 'private': 'private.tar', 'site': s.id,
        'source_revision': applied.get('revision') or os.environ.get('HOOVER4_REVISION', ''),
        'settings_revision': settings_applied.get('revision', 0),
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
        if data.get('format') != RECOVERY_FORMAT or data.get('format_version') not in RECOVERY_VERSIONS:
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
                'deploy-k3s up --steps hosts:k3s to convert it to etcd.']
    name = f'restore-{name_arg(generation, "generation")}'
    return [f'Copy the folder etcd/ of the copy into ~/hoover4-snapshots/{name}/ of the operator user on the server. '
            f'This host holds it in {folder / "etcd"}.',
            f'On the server, as the operator user: sudo python3 - restore {name} < '
            'k3s/ansible/roles/hoover4_k3s/files/k3s-datastore.py',
            f'Unpack {data["private"]} of the copy into the state folder of the site file.',
            'Restore the application copies that recovery.json names: backups.py restore-zone for each zone copy '
            'and backups.py restore-hoover for each collection copy, then sign in to each zone.']


def run_job(key, generation):
    s = site()
    target, problem = destination(s)
    if problem:
        raise SystemExit(problem)
    data = load_state(s)
    data['jobs'].setdefault(key, {'copies': []})
    partial = target.staging(key, generation)
    shutil.rmtree(partial, ignore_errors=True)
    partial.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    kind, _, rest = key.partition(':')
    lock = oplock.site_lock(s.operator_state())
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
        final, checked = target.publish(partial, key, generation)
        copy = {'generation': generation, 'path': final, 'host': target.node.name,
                'execution_host': socket.gethostname(), 'finished': int(time.time()), 'bytes': checked['bytes'],
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
    # Retention runs only after the new copy was verified.
    for old in schedule.retention(record, int(applied_values(s, scope)[copies])):
        target.remove(old['path'])
        record['copies'].remove(old)
    save_state(s, data)
    print(json.dumps({'job': key, **copy}))


def fetched(s, key, generation):
    """The folder of a copy of the destination, after a check of every file against its manifest."""
    target, problem = destination(s)
    if problem:
        raise SystemExit(problem)
    folder = Path(target.folder(key, generation))
    if not (folder / MANIFEST).exists():
        raise SystemExit(f'the copy {folder} does not exist.')
    differences = verify(folder)['differences']
    if differences:
        raise SystemExit(f'the copy {folder} differs from its manifest: {differences[:5]}')
    return folder


def restore_hoover(zone, collection, generation, source_zone=None):
    """Import a collection copy into the Hoover installation of a zone that has no collection of that name."""
    s = site()
    hoover = next((h for h in site_config.hoovers(s).values() if h.zone == name_arg(zone, 'zone')), None)
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
    targets = [h for h in site_config.hoovers(s).values() if h.zone == zone]
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
    Hoover installation and stop their stores except the zone databases and the object store, replace the objects of
    the object store, apply the Secrets of each part, replace the content of each claim, import the database dumps,
    restart the databases and the object store, and open the zone with the replicas of the copy. Each step is recorded in <operator state>/backups/restore-<zone>.json. A failure leaves the zone closed.
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
    dumps = [folder / name for name in DUMP_TRAILERS] + sorted((folder / SHARED_DUMPS).glob('*.sql'))
    for path in dumps:
        if path.exists() and not dump_complete(path):
            raise SystemExit(f'the dump {path.relative_to(folder)} of this copy has no end line of its dump tool, so it is '
                             'incomplete. Restore another copy.')
    module = shared_databases(zone)
    if module and (folder / 'postgresql.sql').exists():
        raise SystemExit(f'this copy holds the PostgreSQL of the zone namespace from before the move of {zone} to the shared '
                         'PostgreSQL. Restore it into the databases of the zone by hand.')
    if (folder / SHARED_DUMPS).is_dir() and not module:
        raise SystemExit(f'this copy holds the databases of the shared PostgreSQL, and {zone} runs its own PostgreSQL. Apply '
                         'the zone with deploy-k3s up first, which moves its databases.')
    parts = zone_parts(s, folder, zone)

    def step(name, function):
        if name in progress['steps']:
            return
        function()
        progress['steps'].append(name)
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(json.dumps(progress, indent=1))

    lock = oplock.site_lock(s.operator_state())
    lock.acquire('restore', f'restore-{zone}')
    try:
        # An online copy names its replicas in workloads.json, a copy of an earlier version in closure.json.
        recorded = next((folder / n for n in ('workloads.json', 'closure.json') if (folder / n).exists()), None)
        source = json.loads(recorded.read_text()) if recorded else None
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
        target = next((h for h in site_config.hoovers(s).values() if h.zone == zone), None)
        site_zone = target is not None and target.stores == 'site'
        for part, ns in parts:
            label = '' if ns == zone else f':{ns}'
            if (part / 'objects' / 'buckets.json').exists():
                # The object store keeps running in a closed zone. The objects go in with its current admin key,
                # before the Secrets of the copy replace that key.
                step('objects' + label, lambda part=part, ns=ns: restore_objects(part, ns))
            step('secrets' + label, lambda part=part, ns=ns: restore_secrets(part, ns, TENANT_SECRETS if site_zone else {}))
            restore_claims(part, ns, step)
            if site_zone and ns != zone and (part / SHARED_PART / 'stores.json').exists():
                hoover = next(h for h in site_config.hoovers(s).values() if h.namespace == ns)
                step('shared-stores' + label, lambda part=part, hoover=hoover: restore_shared_stores(part / SHARED_PART, hoover))
        step('databases', lambda: restore_databases(folder, zone))
        if (folder / 'objects' / 'buckets.json').exists():
            # The object store reads the S3 configuration of the restored Secrets at its start.
            step('object-store-restart', lambda: restart_object_store(zone))
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


# The Secrets and the Secret items of a site zone that hold the credentials of its tenant in the shared stores
# (../../hoover/stores/creds.py and ../../hoover/setup.py). They belong to the target zone, because the store users
# and the Garage keys of the target have these passwords and keys. None (the value) is the whole Secret, and a tuple
# names the item prefixes of the Secret.
TENANT_SECRETS = {'hoover-stores': None, 'garage-tenants': None, 'manticore-schema': None,
                  'hoover-runtime': ('clickhouse-', 'manticore-', 's3-access-key-', 's3-secret-key-', 'temporal-api-key')}


def restore_secrets(folder, zone, tenant=None):
    """Apply the Secrets of the copy. Service account tokens and Helm release records belong to the target, and so do
    the tenant Secrets of a site zone (tenant, TENANT_SECRETS).

    The items of a Secret of the copy replace the same items of the target Secret. The other items of the target stay,
    because a later release can add an item that an earlier copy does not hold.
    """
    tenant = tenant or {}
    objects = json.loads((folder / 'objects.json').read_text())['items']
    skipped = ('kubernetes.io/service-account-token', 'helm.sh/release.v1')
    for item in objects:
        name = item['metadata']['name']
        if item['kind'] != 'Secret' or item.get('type') in skipped or (name in tenant and tenant[name] is None):
            continue
        if name in tenant:
            item = {**item, 'data': {k: v for k, v in (item.get('data') or {}).items() if not k.startswith(tenant[name])}}
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


# The dump of pg_dumpall drops and creates every role, also postgres, which runs the import. PostgreSQL refuses to drop
# the current user, and the role postgres exists, so the import skips these two lines. ALTER ROLE postgres still applies.
POSTGRES_SKIPPED = {b'DROP ROLE IF EXISTS postgres;\n', b'CREATE ROLE postgres;\n'}


def import_dump(zone, exec_args, path, skipped=frozenset()):
    """Send the dump at path to a database client in a pod of the zone. A client error fails the restore.

    exec_args are the pod, the container option and, after '--', the client command. The standard input stays open until
    the client ends (../../podexec.py), because the output of a Kata container stops after 32 KiB once kubectl closes it."""
    import podexec
    import tempfile
    at = exec_args.index('--')
    argv = ['kubectl', '--kubeconfig', k3s_settings.KUBECONFIG, '-n', zone, 'exec', '-i', *exec_args[:at]]
    with open(path, 'rb') as dump:
        size = sum(len(line) for line in dump if line not in skipped)
    # The client writes a notice for each object that the dump drops and that does not exist. A file holds them, so a
    # full pipe cannot stop the client.
    with open(path, 'rb') as dump, tempfile.TemporaryFile() as errors:
        code = podexec.run(argv, exec_args[at + 1:], (line for line in dump if line not in skipped), stderr=errors,
                           size=size)
        errors.seek(0)
        text = errors.read().decode(errors='replace')
    if code:
        # The client stops at the first error, so the last lines of its output name it.
        raise SystemExit(f'the import of {path.name} into {zone} failed with status {code}: '
                         f'{" ".join(text.strip().splitlines()[-3:])[-500:]}. The zone stays closed.')


def restore_databases(folder, zone):
    """Import the dumps into the running database servers of the zone, then restart them with the restored Secrets.

    psql stops at the first error (ON_ERROR_STOP=1) and the mariadb client stops at the first error by default, so a
    dump that does not apply completely fails the restore.
    """
    if (folder / 'postgresql.sql').exists():
        import_dump(zone, ['postgresql-0', '-c', 'postgresql', '--', 'psql', '-U', 'postgres', '-v', 'ON_ERROR_STOP=1',
                           '-q', '-d', 'postgres'], folder / 'postgresql.sql', POSTGRES_SKIPPED)
    if (folder / SHARED_DUMPS).is_dir():
        restore_shared_databases(folder / SHARED_DUMPS, zone)
    if (folder / 'mariadb.sql').exists():
        import_dump(zone, ['mariadb-0', '--', 'sh', '-c', 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD"'], folder / 'mariadb.sql')
    for name in ('postgresql-0', 'mariadb-0'):
        kubectl('-n', zone, 'delete', 'pod', name, '--ignore-not-found', '--wait=true')
    for name in ('postgresql', 'mariadb'):
        if kubectl('-n', zone, 'get', 'statefulset', name, '--ignore-not-found', '-o', 'name').strip():
            kubectl('-n', zone, 'rollout', 'status', f'statefulset/{name}', '--timeout=600s')


def restore_shared_databases(folder, zone):
    """Replace each openDesk database of a zone on the shared PostgreSQL with its dump in folder. Each database is
    dropped with its connections and created again empty with its user and rights (../../zones/postgresql.py ensure()).
    psql imports the dump as the user of the database, so the user owns every object, and stops at the first error."""
    import podexec
    import tempfile
    module = shared_databases(zone)
    passwords = module.zone_passwords(zone)
    keys = {name: key for key, (name, _) in module.DATABASES.items()}
    dumps = sorted(folder.glob('*.sql'))
    unknown = [p.name for p in dumps if p.stem not in keys]
    if unknown:
        raise SystemExit(f'the copy holds the dumps {", ".join(unknown)}, which name no openDesk database. The zone stays closed.')
    module.drop_databases(zone, [keys[p.stem] for p in dumps])
    module.ensure(zone, passwords)
    for path in dumps:
        key = keys[path.stem]
        role = f'SET ROLE {module.quote(module.user_name(zone, key))};\n'.encode()
        with tempfile.TemporaryFile() as errors:
            code = podexec.run(module.shared_exec(), ['psql', '-U', 'postgres', '-v', 'ON_ERROR_STOP=1', '-X', '-q', '-d',
                                                      module.database_name(zone, key)], [role, path], stdout=None, stderr=errors)
            errors.seek(0)
            text = errors.read().decode(errors='replace')
        if code:
            raise SystemExit(f'the import of {path.name} into {zone} failed with status {code}: '
                             f'{" ".join(text.strip().splitlines()[-3:])[-500:]}. The zone stays closed.')
    # The Nextcloud configuration of a copy of another zone names the database and the user of that zone.
    if 'nextcloud' in [keys[p.stem] for p in dumps]:
        module.nextcloud_config(zone, passwords)


def restart_object_store(ns):
    for item in json.loads(kubectl('-n', ns, 'get', 'deployments', '-o', 'json'))['items']:
        labels = (item['spec']['template'].get('metadata') or {}).get('labels') or {}
        if labels.get('hoover.dev/store') != 'seaweedfs':
            continue
        name = item['metadata']['name']
        kubectl('-n', ns, 'rollout', 'restart', f'deployment/{name}')
        kubectl('-n', ns, 'rollout', 'status', f'deployment/{name}', '--timeout=600s')


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
            raise SystemExit('the site file has no vars.backup.')
        if not os.path.isdir(target.path):
            raise SystemExit(f'the backup destination {target.path} of {target.node.name} is not mounted here. Run '
                             'backups.py in the runner container of the operator pod.')
        target.enable()
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
