#!/usr/bin/env python3
"""Run the optional backups of a site and restore a copy into an isolated target.

The site file [backup] names the node and the folder of the destination. The operator settings `backup.*` of the
applied revision turn each job on and set its retained copies. Without [backup] or with every job off, nothing runs.
schedule.py holds the rules. This file reads the receipts and the sizes, runs one job at a time and keeps the state in
<operator state>/backups/state.json, which it writes atomically.

Copies, below <destination>/<job key with / for :>/<generation>/:
- hoover:<zone>:<collection>: the collection export of the operations worker (main.py export-collection), streamed out
  of the claim ops-backups. The export directory in the claim is removed after the copy, so no second archive stays.
- opendesk:<zone>: a SQL dump of each database server of the zone, a tar file of each other claim, and the Secrets and
  ConfigMaps of the zone. The tar files keep the owners and modes. A file system claim is read through a short pod in
  the zone namespace while the zone runs. The pod does not ask for a read-only mount of the claim, because the kernel
  refuses a second mount of a mounted ext4 device with other options. Its container mount is read-only. A Block claim
  holds the file system of a Kata store, which only the guest of the store pod mounts, so the copy reads it through
  the store container with the busybox of ../../hoover/stores/podspec.py. A claim that a pod owns (a generic
  ephemeral volume) holds temporary files and is not copied.
- platform: the k3s datastore, the operator state and the private files of the site (credentials included), which
  together restore the cluster settings, the logins and the operator settings.
Each copy is written into <generation>.partial, gets copy-manifest.json with the size and SHA-256 of every file, is read
again against the manifest, and is then renamed. Only then does retention remove older copies.
A runner restart finds a job that runs (its process id and its export operation in the state) and waits for it.
Receipts of a collection come from the table operations of the installation: the first finished add_dataset of each of
its datasets, when none of its dataset operations still runs, is the ingestion receipt. A finished update_collection,
after which every included update_dataset finished without an error, is a complete reprocessing receipt.
Usage: backups.py tick                      start the next due job, as the operator runner does every minute
       backups.py status                    print the state, the next slots and the blocked jobs
       backups.py run <job> <generation>    run one job now, in the foreground
       backups.py enable                    write the marker of the destination folder
       backups.py verify <copy folder>      read a copy again against its manifest
       backups.py restore-hoover <copy folder> <installation>     import a collection copy into an empty installation
       backups.py restore-volumes <copy folder> <namespace>       restore the claims of an openDesk copy into a namespace
"""
import base64
import hashlib
import json
import os
import shutil
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
import config as site_config  # noqa: E402
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
    path = state_path(s)
    return json.loads(path.read_text()) if path.exists() else {'jobs': {}, 'blocked': [], 'paused': ''}


def save_state(s, data):
    path = state_path(s)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + '\n')
    with open(tmp) as f:
        os.fsync(f.fileno())
    os.replace(tmp, path)


def applied_values(s, scope):
    module = operator_module()
    state = module.State(s.operator_state())
    applied = state.applied() if hasattr(state, 'applied') else None
    revision = (applied or {}).get('revision') if isinstance(applied, dict) else None
    overrides = state.overrides(revision) if (s.operator_state() / 'desired.json').exists() else {}
    return module.effective(scope, overrides.get(scope, {}))


def clickhouse(ns, sql):
    return kubectl('-n', ns, 'exec', '-i', 'clickhouse-0', '--', 'clickhouse-client', '--user', 'hoover4', '--password', 'hoover4',
                   '--format', 'JSONEachRow', input=sql)


def receipts(hoover, collection):
    """The ingestion and complete reprocessing receipts of one collection, from the operations table."""
    db = f'{hoover.clickhouse_database_prefix}_Processing'
    rows = [json.loads(line) for line in clickhouse(hoover.namespace, (
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
        hoover.namespace, f'SELECT DISTINCT collectionname FROM {db}.collections FINAL').splitlines() if line.strip()]


def jobs(s, data):
    out = []
    cluster = applied_values(s, 'cluster')
    if cluster['backup.platform.enabled'] == 'true':
        out.append(schedule.Job('platform', int(cluster['backup.platform.copies']), duration=600))
    for hoover in s.hoovers.values():
        zone = applied_values(s, f'zone:{hoover.zone}')
        if zone.get('backup.opendesk.enabled') == 'true':
            out.append(schedule.Job(f'opendesk:{hoover.zone}', int(zone['backup.opendesk.copies'])))
        if zone.get('backup.hoover.enabled') == 'true':
            for collection in collections(hoover):
                key = f'hoover:{hoover.zone}:{collection}'
                last = schedule.last_copy(data['jobs'].get(key, {}))
                out.append(schedule.Job(key, int(zone['backup.hoover.copies']), receipts(hoover, collection),
                                        estimated_bytes=(last or {}).get('bytes', 0)))
    return out


def destination(s):
    if not s.backup:
        return None, 'the site file has no [backup] section.'
    path = s.backup['path']
    return path, schedule.destination_problem(path)


def free_bytes(path):
    usage = shutil.disk_usage(path)
    return usage.free


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
    path, problem = destination(s)
    if path is None:
        return {'state': 'off', 'reason': problem}
    data['paused'] = problem
    if problem:
        save_state(s, data)
        return {'state': 'paused', 'reason': problem}
    if any(running(r) for r in data['jobs'].values()):
        return {'state': 'running', 'job': next(k for k, r in data['jobs'].items() if running(r))}
    selected = jobs(s, data)
    for job in selected:
        record = data['jobs'].setdefault(job.key, {'copies': []})
        if job.weekly and not record.get('slot'):
            last = schedule.last_copy(record)
            record['slot'] = schedule.slot_after(job.key, last['finished'] if last else now)
    start, blocked, slots = schedule.plan(selected, data['jobs'], now, free_bytes(path))
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


def tar_out(ns, pod, container, folder, target, tar=('tar',)):
    """Write a folder of a pod into one host tar file, with its owners and modes."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, 'wb') as out:
        if subprocess.run(tar_command(ns, pod, container, folder, tar), stdout=out).returncode:
            raise SystemExit(f'the copy of {pod}:{folder} failed.')


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


def run_opendesk(s, zone, partial):
    partial.mkdir(parents=True, exist_ok=True)
    pods = json.loads(kubectl('-n', zone, 'get', 'pods', '-o', 'json'))['items']
    names = {p['metadata']['name'] for p in pods}
    if 'postgresql-0' in names:
        with open(partial / 'postgresql.sql', 'wb') as out:
            kubectl('-n', zone, 'exec', 'postgresql-0', '-c', 'postgresql', '--', 'pg_dumpall', '-U', 'postgres', stdout=out)
    if 'mariadb-0' in names:
        with open(partial / 'mariadb.sql', 'wb') as out:
            kubectl('-n', zone, 'exec', 'mariadb-0', '--', 'sh', '-c',
                    'mariadb-dump --all-databases --single-transaction -uroot -p"$MARIADB_ROOT_PASSWORD"', stdout=out)
    claims = json.loads(kubectl('-n', zone, 'get', 'pvc', '-o', 'json'))['items']
    databases = ('postgresql', 'mariadb')
    rows = []
    for item in claims:
        claim = item['metadata']['name']
        if any(d in claim for d in databases) or any(o['kind'] == 'Pod' for o in item['metadata'].get('ownerReferences', [])):
            continue
        mode = item['spec'].get('volumeMode') or 'Filesystem'
        target = partial / 'claims' / f'{claim}.tar'
        if mode == 'Block':
            source = block_source(claim, pods)
            if source is None:
                raise SystemExit(f'no running store pod mounts the Block claim {claim}. Start the zone and run the job again.')
            tar_out(zone, *source, target, tar=('/tools/busybox', 'tar'))
        else:
            node = (item['metadata'].get('annotations') or {}).get('volume.kubernetes.io/selected-node')
            pod = helper_pod(zone, claim, node)
            try:
                tar_out(zone, pod, None, '/data', target)
            finally:
                kubectl('-n', zone, 'delete', 'pod', pod, '--wait=false')
        rows.append({'claim': claim, 'size': item['spec']['resources']['requests']['storage'],
                     'storage_class': item['spec'].get('storageClassName'), 'volume_mode': mode})
    (partial / 'claims.json').write_text(json.dumps(rows, indent=1))
    (partial / 'objects.json').write_text(kubectl('-n', zone, 'get', 'secrets,configmaps', '-o', 'json'))
    os.chmod(partial / 'objects.json', 0o600)


def run_platform(s, partial):
    partial.mkdir(parents=True, exist_ok=True)
    # The SQLite backup API gives a consistent copy of the datastore while k3s runs.
    script = ('import sqlite3,sys;src=sqlite3.connect("file:/var/lib/rancher/k3s/server/db/state.db?mode=ro",uri=True);'
              'dst=sqlite3.connect(sys.argv[1]);src.backup(dst);dst.close()')
    target = partial / 'k3s-state.db'
    subprocess.run(['sudo', '-n', sys.executable, '-c', script, str(target)], check=True)
    subprocess.run(['sudo', '-n', 'chown', f'{os.getuid()}:{os.getgid()}', str(target)], check=True)
    private = k3s_settings.PRIVATE
    excluded = ['build', 'bin', 'browser-venv', 'checks', 'staging', 'operator/backups']
    subprocess.run(['tar', '-C', str(private), '-cf', str(partial / 'private.tar'), *[f'--exclude=./{e}' for e in excluded], '.'], check=True)
    os.chmod(partial / 'private.tar', 0o600)


def run_job(key, generation):
    s = site()
    path, problem = destination(s)
    if problem:
        raise SystemExit(problem)
    data = load_state(s)
    record = data['jobs'].setdefault(key, {'copies': []})
    folder = Path(path) / key.replace(':', '/')
    partial = folder / f'{generation}.partial'
    shutil.rmtree(partial, ignore_errors=True)
    started = time.time()
    try:
        kind, _, rest = key.partition(':')
        if kind == 'hoover':
            zone, collection = rest.split(':')
            run_hoover(s, zone, collection, generation, partial)
        elif kind == 'opendesk':
            run_opendesk(s, rest, partial)
        else:
            run_platform(s, partial)
        rows = manifest(partial)
        (partial / MANIFEST).write_text(json.dumps({'job': key, 'generation': generation, 'files': rows}, indent=1))
        checked = verify(partial)
        if checked['differences']:
            raise SystemExit(f'the copy {partial} differs from its manifest: {checked["differences"][:5]}')
        final = folder / generation
        shutil.rmtree(final, ignore_errors=True)
        os.replace(partial, final)
        copy = {'generation': generation, 'path': str(final), 'finished': int(time.time()), 'bytes': checked['bytes'],
                'seconds': round(time.time() - started), 'verified': True}
    except BaseException as error:
        data = load_state(s)
        data['jobs'].setdefault(key, {'copies': []})['last_error'] = str(error)[:500]
        data['jobs'][key].pop('running', None)
        save_state(s, data)
        shutil.rmtree(partial, ignore_errors=True)
        raise
    data = load_state(s)
    record = data['jobs'].setdefault(key, {'copies': []})
    record['copies'].append(copy)
    record.pop('running', None)
    record.pop('slot', None)
    record.pop('last_error', None)
    copies = {'hoover': 'backup.hoover.copies', 'opendesk': 'backup.opendesk.copies', 'platform': 'backup.platform.copies'}[key.split(':')[0]]
    scope = 'cluster' if key == 'platform' else f'zone:{key.split(":")[1]}'
    for old in schedule.retention(record, int(applied_values(s, scope)[copies])):
        shutil.rmtree(old['path'], ignore_errors=True)
        record['copies'].remove(old)
        # A platform recovery set names the collection copies that it needs. A removed copy makes those sets obsolete.
    save_state(s, data)
    print(json.dumps({'job': key, **copy}))


def restore_hoover(folder, installation):
    """Import a collection copy into an installation that has no collection of that name."""
    s = site()
    hoover = next(h for h in s.hoovers.values() if installation in (h.name, h.zone))
    meta = json.loads((Path(folder) / MANIFEST).read_text())
    collection = meta['job'].split(':')[2]
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


def restore_volumes(folder, namespace):
    """Create the claims of an openDesk copy in a namespace and fill each claim from its tar file."""
    claims = json.loads((Path(folder) / 'claims.json').read_text())
    if verify(folder)['differences']:
        raise SystemExit(f'the copy {folder} differs from its manifest.')
    kubectl('create', 'namespace', namespace, check=False)
    for row in claims:
        claim = {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': row['claim'], 'namespace': namespace},
                 'spec': {'accessModes': ['ReadWriteOnce'], 'storageClassName': row['storage_class'],
                          'volumeMode': row.get('volume_mode') or 'Filesystem',
                          'resources': {'requests': {'storage': row['size']}}}}
        kubectl('apply', '-f', '-', input=json.dumps(claim))
        kubectl('-n', namespace, 'delete', 'pod', 'restore-write', '--ignore-not-found', '--wait=true')
        kubectl('apply', '-f', '-', input=json.dumps(restore_pod(namespace, row)))
        kubectl('-n', namespace, 'wait', '--for=condition=Ready', 'pod/restore-write', '--timeout=300s')
        with open(Path(folder) / 'claims' / f'{row["claim"]}.tar', 'rb') as source:
            subprocess.run(['kubectl', '--kubeconfig', k3s_settings.KUBECONFIG, '-n', namespace, 'exec', '-i', 'restore-write', '--',
                            # The Kata wrapper mounts a Block claim over a memory folder after the container starts.
                            'sh', '-c', 'until grep -q " /data ext4 " /proc/mounts; do sleep 1; done; tar -C /data -xf -'],
                           stdin=source, check=True)
        kubectl('-n', namespace, 'delete', 'pod', 'restore-write', '--wait=true')
    print(json.dumps({'namespace': namespace, 'claims': len(claims)}))


def main(argv):
    if argv == ['tick']:
        print(json.dumps(tick()))
    elif argv == ['status']:
        s = site()
        print(json.dumps({'destination': destination(s), **load_state(s)}, indent=1))
    elif len(argv) == 3 and argv[0] == 'run':
        run_job(argv[1], argv[2])
    elif argv == ['enable']:
        path, _ = destination(site())
        if path is None:
            raise SystemExit('the site file has no [backup] section.')
        Path(path).mkdir(parents=True, exist_ok=True)
        (Path(path) / schedule.MARKER).write_text('This folder receives the backups of the hoover4 site.\n')
        print(json.dumps({'destination': path, 'marker': schedule.MARKER}))
    elif len(argv) == 2 and argv[0] == 'verify':
        print(json.dumps(verify(argv[1])))
    elif len(argv) == 3 and argv[0] == 'restore-hoover':
        restore_hoover(argv[1], argv[2])
    elif len(argv) == 3 and argv[0] == 'restore-volumes':
        restore_volumes(argv[1], argv[2])
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
