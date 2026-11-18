#!/usr/bin/env python3
"""The openDesk object storage of a zone in the shared Garage of the site.

A zone of the store layout site keeps the objects of its openDesk applications in the shared Garage of the site
(../hoover/stores/shared.py). It runs no SeaweedFS. Each openDesk bucket of BUCKETS is the Garage bucket
<zone>-opendesk-<bucket>. The Garage key <zone>-opendesk reads and writes only these buckets. It has a local alias with
the openDesk name for each of them (for example nextcloud), so the applications keep their bucket names. Nextcloud
names its root storage by the bucket name, and a new name would hide its earlier application data. The key cannot
create a bucket, change a bucket setting, or reach any other bucket. zones.py writes the key into secrets.json and the
openDesk values of the zone (values()). The values set the region of Garage (REGION), because Garage refuses a
request signed for another region.

The applications reach Garage at the object storage host of the zone, <zone>-objectstorage.<suffix>, through the HTTPS
frontend. The browser of a user reaches it too, for example when it opens an OpenProject attachment. The Ingress
opendesk-<zone> in the namespace of the shared stores (ingress()) gives the S3 port of Garage only the paths of the
zone buckets and the bucket list (/). The network policy garage-clients of shared.py admits the ingress controller on
that port. The Ingress answers the CORS requests of the OpenProject pages of the zone, because a Garage
bucket without a CORS setting refuses them, and only an owner key can set one.

The zone state entry has objectstore = garage for a zone on Garage. zone.py apply gives it to each new zone of the
store layout site. A zone of an earlier version runs SeaweedFS in its namespace and has no value. zone.py apply moves
such a zone with the admin kubeconfig (move()):
  1. The Ingress opendesk-<zone> takes the paths of the buckets. From this moment the applications reach Garage with
     their SeaweedFS key, which Garage refuses, so no application changes an object until the switch ends.
  2. Every bucket of SeaweedFS is copied into Garage (empty first, then the objects).
  3. The object count and the byte count of each bucket must be equal in both stores. Else the Ingress goes away, the
     applications use SeaweedFS again, and the command stops with the counts.
  4. The volume of SeaweedFS gets the reclaim policy Retain and the label LABEL, so its data stays when Helm removes
     SeaweedFS. The record zones/<zone>/objectstore-move.json of the state folder holds the counts and the times.
  5. The zone state gets objectstore = garage. zones.py then writes the values with Garage and without SeaweedFS, and
     the openDesk waves of zone.py apply them. Helm removes SeaweedFS. The entries of SECOND_PASS run once more.
  6. Each workload whose configuration holds the key of the zone, and Nextcloud, which reads its object store
     configuration from its database at its start, restart once (restart_consumers()). The switch ends when they are
     ready.
A zone runner without the right to change a volume leaves the zone on SeaweedFS, and deploy-k3s up moves it.
After a check of the applications, drop-seaweedfs deletes the kept volume. zone.py delete deletes it too.

Usage: objectstore.py show <zone>              print the buckets and the counts of the zone in Garage
       objectstore.py check <zone>             compare the counts of SeaweedFS and Garage, without a change
       objectstore.py drop-seaweedfs <zone>    delete the SeaweedFS volume that a move kept
"""
import base64
import json
import re
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent
sys.path.insert(0, str(SOURCE))
sys.path.insert(0, str(SOURCE / 'hoover' / 'stores'))
import settings  # noqa: E402

# The openDesk object stores of a zone (objectstores.yaml.gotmpl of the release, without the enterprise ones), and the
# bucket of each. test_zones.py compares the list with the release.
BUCKETS = {'migrations': 'migrations', 'nextcloud': 'nextcloud', 'notes': 'notes', 'nubus': 'ums',
           'openproject': 'openproject', 'openxchange': 'openxchange', 'synapse': 'synapse'}
STORES_NS = 'hoover-stores'
GARAGE_PORT = 3900
# The region of the shared Garage (s3_region of ../hoover/stores/config/garage/garage.toml).
REGION = re.search(r'^s3_region\s*=\s*"([^"]+)"', (SOURCE / 'hoover/stores/config/garage/garage.toml').read_text(), re.M).group(1)
# The label of a SeaweedFS volume that a move kept. Its value is the zone.
LABEL = 'hoover.dev/seaweedfs-of'
RECORD = 'objectstore-move.json'
# The openDesk entries that zone.py runs once more after the waves of a move. The chart of the element release hashes
# a ConfigMap of the release opendesk-element-customization with a lookup. In the first run the lookup reads the
# ConfigMap before the move, so only the next run gives the element release its final form.
SECOND_PASS = ('element',)
# The workload of Nextcloud, which reads its object store configuration from its database at its start.
NEXTCLOUD = 'deployment/opendesk-nextcloud-aio'


def key_name(zone):
    return f'{zone}-opendesk'


def global_name(zone, bucket):
    return f'{zone}-opendesk-{bucket}'


def new_key():
    """A Garage key in the form of garage key import: GK and 24 hexadecimal digits, and a secret of 64."""
    return {'access_key': 'GK' + secrets.token_hex(12), 'secret_key': secrets.token_hex(32)}


def on_garage(entry):
    """True when the zone state entry keeps the openDesk objects in Garage."""
    return entry.get('stores') == 'site' and entry.get('objectstore') == 'garage'


def values(zone, key):
    """The openDesk values of a zone on Garage: each object store with the host, the region and the key."""
    host = settings.zone_host(zone, 'objectstorage')
    return {'objectstores': {name: {'endpoint': host, 'region': REGION, 'username': key['access_key'],
                                    'secretKey': {'value': key['secret_key']}} for name in BUCKETS}}


def ingress(zone):
    """The Ingress of the object storage host of a zone: the paths of the zone buckets go to the S3 port of Garage."""
    projects = f"https://{settings.zone_host(zone, 'projects')}"
    backend = {'service': {'name': 'garage', 'port': {'number': GARAGE_PORT}}}
    # The bucket list (GET /) answers with the buckets of the key only. The Nubus portal consumer waits for it at its start.
    paths = [{'path': '/', 'pathType': 'Exact', 'backend': backend}]
    paths += [{'path': f'/{bucket}', 'pathType': 'Prefix', 'backend': backend} for bucket in sorted(BUCKETS.values())]
    prefix = 'haproxy-ingress.github.io/'
    return {'apiVersion': 'networking.k8s.io/v1', 'kind': 'Ingress',
            'metadata': {'name': f'opendesk-{zone}', 'namespace': STORES_NS, 'labels': {'hoover.dev/opendesk-objects': zone},
                         'annotations': {
                             # A large Nextcloud upload part can take longer than the default of 50 s.
                             prefix + 'timeout-server': '600s',
                             # The OpenProject pages read attachments from the bucket, and a direct upload sends a form to it.
                             prefix + 'cors-enable': 'true',
                             prefix + 'cors-allow-origin': projects,
                             prefix + 'cors-allow-credentials': 'true',
                             prefix + 'cors-allow-methods': 'GET, HEAD, PUT, POST, DELETE, OPTIONS',
                             prefix + 'cors-allow-headers': 'Authorization, Content-Type, Content-Disposition, Content-MD5, '
                                                            'X-Requested-With, X-Amz-Date, X-Amz-Content-Sha256, X-Amz-Acl',
                             prefix + 'cors-expose-headers': 'ETag, Location'}},
            'spec': {'ingressClassName': 'haproxy',
                     'rules': [{'host': settings.zone_host(zone, 'objectstorage'), 'http': {'paths': paths}}]}}


# ----------------------------------------------------------------------------------------------------------------------
# Garage


def shared():
    import shared as module
    return module


def key_rows(info):
    """The rows of the bucket table of garage key info: (permissions, global aliases and local aliases)."""
    rows, inside = [], False
    for line in info.splitlines():
        if 'BUCKETS FOR THIS KEY' in line:
            inside = True
            continue
        if inside and line.strip() and not line.startswith('Permissions'):
            columns = line.split()
            rows.append((columns[0], columns[2:]))
    return rows


def ensure(zone, key):
    """Create the key and the buckets of a zone in Garage, give the key read and write on each bucket and its local
    alias. Only a missing part is created, so an unchanged zone changes nothing. Return the changed parts."""
    cli = shared().garage_cli
    table = shared().table
    changed = []
    keys = {row[0]: row[2] for row in table(cli('key', 'list')) if len(row) > 2}
    if key['access_key'] not in keys:
        if key_name(zone) in keys.values():
            raise SystemExit(f'Garage has a key {key_name(zone)} with another id than zones/secrets.json. Delete the Garage '
                             'key or restore the zone secrets.')
        cli('key', 'import', '--yes', '-n', key_name(zone), key['access_key'], key['secret_key'])
        changed.append(f'key {key_name(zone)}')
    elif keys[key['access_key']] != key_name(zone):
        raise SystemExit(f'the Garage key of {zone} has the name {keys[key["access_key"]]}, and {key_name(zone)} was expected.')
    present = {alias for row in table(cli('bucket', 'list')) for alias in row[2:] if ':' not in alias}
    granted = {aliases[0]: (permissions, aliases[1:]) for permissions, aliases in key_rows(cli('key', 'info', key['access_key']))
               if aliases}
    for bucket in BUCKETS.values():
        name = global_name(zone, bucket)
        if name not in present:
            cli('bucket', 'create', name)
            changed.append(f'bucket {name}')
        permissions, aliases = granted.get(name, ('', []))
        if not ('R' in permissions and 'W' in permissions):
            cli('bucket', 'allow', '--read', '--write', name, '--key', key['access_key'])
            changed.append(f'read and write on {name}')
        if bucket not in aliases:
            cli('bucket', 'alias', '--local', key['access_key'], name, bucket)
            changed.append(f'alias {bucket} of {name}')
    return changed


def garage_run(key, *args, data=None, out=None, sse_c=None):
    """One command of the S3 client of a Garage pod (../hoover/stores/garage_client.py) with the key of the zone."""
    import garage_client
    with garage_client.client() as pod:
        return garage_client.run(pod, key, *args, data=data, out=out, sse_c=sse_c)


def garage_counts(key):
    """{bucket: {objects, bytes}} of the zone buckets in Garage, by their local alias."""
    out = {}
    for bucket in BUCKETS.values():
        text, _ = garage_run(key, 'count', bucket)
        row = json.loads(text.strip().splitlines()[-1])
        out[bucket] = {'objects': row['objects'], 'bytes': row['bytes']}
    return out


# ----------------------------------------------------------------------------------------------------------------------
# SeaweedFS of a zone of an earlier version


def backups():
    sys.path.insert(0, str(SOURCE / 'platform' / 'backups'))
    import backups as module
    return module


def kubectl(*args, input=None, check=True):
    r = subprocess.run(['kubectl', '--kubeconfig', str(settings.KUBECONFIG), *args], input=input, text=True, capture_output=True)
    if check and r.returncode:
        raise SystemExit(f'kubectl {" ".join(args[:4])} failed: {r.stderr.strip()[-400:]}')
    return r.stdout


def seaweedfs(zone):
    """{'pod', 'claims', 'endpoint'} of the running SeaweedFS of a zone, or None (../platform/backups/backups.py)."""
    pods = json.loads(kubectl('-n', zone, 'get', 'pods', '-o', 'json'))['items']
    return backups().object_store(zone, pods)


def seaweedfs_installed(zone):
    return bool(kubectl('-n', zone, 'get', 'deployment', '-l', 'app.kubernetes.io/name=seaweedfs', '-o', 'name').strip())


def seaweedfs_counts(zone, store):
    """{bucket: {objects, bytes}} of every bucket of the SeaweedFS of a zone, read with its admin key."""
    b = backups()
    first = b.object_store_key(zone, store)
    pod = b.s3_pod(zone)
    try:
        listed, _ = b.s3_run(zone, pod, first, 'buckets')
        out = {}
        for bucket in json.loads(listed.strip().splitlines()[-1]):
            text, _ = b.s3_run(zone, pod, first, 'count', b.name_arg(bucket, 'bucket'))
            row = json.loads(text.strip().splitlines()[-1])
            out[bucket] = {'objects': row['objects'], 'bytes': row['bytes']}
        return out
    finally:
        kubectl('-n', zone, 'delete', 'pod', pod, '--wait=false', check=False)


def differences(source, target):
    """The buckets whose object or byte count differs, as messages. A source bucket outside BUCKETS is a difference,
    because no application of the zone would find it in Garage."""
    problems = [f'{bucket}: SeaweedFS has {source[bucket]["objects"]} objects and {source[bucket]["bytes"]} bytes, Garage '
                f'{target.get(bucket, {}).get("objects")} objects and {target.get(bucket, {}).get("bytes")} bytes'
                for bucket in sorted(source) if source[bucket] != target.get(bucket)]
    problems += [f'{bucket}: Garage has {target[bucket]["objects"]} objects, and SeaweedFS has no bucket {bucket}'
                 for bucket in sorted(set(target) - set(source)) if target[bucket]['objects']]
    return problems


def volumes(zone, store):
    """The persistent volumes of the claims of SeaweedFS."""
    names = []
    for claim in store['claims']:
        volume = kubectl('-n', zone, 'get', 'pvc', claim, '-o', 'jsonpath={.spec.volumeName}').strip()
        if volume:
            names.append(volume)
    return names


def can_keep_volumes():
    return kubectl('auth', 'can-i', 'patch', 'persistentvolumes', check=False).strip() == 'yes'


def record_path(zone):
    return settings.PRIVATE / 'zones' / zone / RECORD


def write_record(zone, record):
    path = record_path(zone)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600)
    path.write_text(json.dumps(record, indent=1, sort_keys=True) + '\n')


def read_record(zone):
    try:
        return json.loads(record_path(zone).read_text())
    except (OSError, ValueError):
        return None


def step(name, **fields):
    print(json.dumps({'at': time.strftime('%H:%M:%S'), 'step': name, **fields}), flush=True)


def apply_ingress(zone):
    kubectl('apply', '-f', '-', input=json.dumps(ingress(zone)))


def delete_ingress(zone):
    kubectl('-n', STORES_NS, 'delete', 'ingress', f'opendesk-{zone}', '--ignore-not-found')


def move(zone, key):
    """Copy the objects of the SeaweedFS of a zone into Garage, check the counts, and keep the SeaweedFS volume
    (steps 1 to 4 of the module text). Return the record. The caller sets objectstore = garage and runs the waves."""
    b = backups()
    store = seaweedfs(zone)
    if store is None:
        raise SystemExit(f'{zone} has no running SeaweedFS, and the move of its objects to Garage needs it. Start it and '
                         'run zone.py apply again.')
    record = {'zone': zone, 'switch_started': time.time()}
    apply_ingress(zone)
    step('objectstore-switch', zone=zone, result='the applications reach Garage, the copy starts')
    try:
        sse_c = b.object_store_key(zone, store).get('sse_c') or {}
        with tempfile.TemporaryDirectory(prefix=f'objectstore-{zone}-') as folder:
            b.copy_objects(zone, store, Path(folder))
            listed = json.loads((Path(folder) / 'buckets.json').read_text())
            unknown = sorted(row['bucket'] for row in listed if row['bucket'] not in BUCKETS.values())
            if unknown:
                raise SystemExit(f'SeaweedFS of {zone} has the buckets {", ".join(unknown)}, which no openDesk object store '
                                 'names. Move their objects by hand and run zone.py apply again.')
            for row in listed:
                bucket = row['bucket']
                garage_run(key, 'empty', bucket)
                garage_run(key, 'untar', bucket, data=Path(folder) / f'{bucket}.tar',
                           sse_c={bucket: sse_c[bucket]} if bucket in sse_c else None)
        record['copied'] = time.time()
        source, target = seaweedfs_counts(zone, store), garage_counts(key)
        record['buckets'] = {bucket: {'seaweedfs': source.get(bucket), 'garage': target.get(bucket)}
                             for bucket in sorted(set(source) | set(target))}
        problems = differences(source, target)
        if problems:
            raise SystemExit(f'the copy of the objects of {zone} differs: {"; ".join(problems)}. The zone stays on SeaweedFS.')
    except BaseException:
        delete_ingress(zone)
        step('objectstore-switch', zone=zone, result='ended without a move, the applications use SeaweedFS again')
        raise
    record['checked'] = time.time()
    record['volumes'] = volumes(zone, store)
    for volume in record['volumes']:
        kubectl('patch', 'pv', volume, '-p', json.dumps({'metadata': {'labels': {LABEL: zone}},
                                                          'spec': {'persistentVolumeReclaimPolicy': 'Retain'}}))
    write_record(zone, record)
    step('objectstore-copy', zone=zone, buckets=record['buckets'], seconds=round(record['checked'] - record['switch_started'], 1))
    return record


def config_names(spec):
    """(Secret names, ConfigMap names) that a pod spec reads."""
    found = {'secret': set(), 'configmap': set()}
    for container in spec.get('initContainers', []) + spec.get('containers', []):
        for env in container.get('env', []):
            ref = env.get('valueFrom') or {}
            if 'secretKeyRef' in ref:
                found['secret'].add(ref['secretKeyRef']['name'])
            if 'configMapKeyRef' in ref:
                found['configmap'].add(ref['configMapKeyRef']['name'])
        for source in container.get('envFrom', []):
            if 'secretRef' in source:
                found['secret'].add(source['secretRef']['name'])
            if 'configMapRef' in source:
                found['configmap'].add(source['configMapRef']['name'])
    for volume in spec.get('volumes', []):
        if 'secret' in volume:
            found['secret'].add(volume['secret']['secretName'])
        if 'configMap' in volume:
            found['configmap'].add(volume['configMap']['name'])
        for source in (volume.get('projected') or {}).get('sources', []):
            if 'secret' in source:
                found['secret'].add(source['secret']['name'])
            if 'configMap' in source:
                found['configmap'].add(source['configMap']['name'])
    return found['secret'], found['configmap']


def consumers(workloads, secrets_, configmaps, key_id):
    """The workloads (kind/name) whose pod template, Secrets or ConfigMaps hold the key id, and Nextcloud."""
    def holds(data, decode):
        return any(key_id in (base64.b64decode(v).decode(errors='replace') if decode else v) for v in (data or {}).values())
    holding = {('secret', s['metadata']['name']) for s in secrets_ if holds(s.get('data'), True)}
    holding |= {('configmap', c['metadata']['name']) for c in configmaps if holds(c.get('data'), False)}
    found = []
    for item in workloads:
        name = f"{item['kind'].lower()}/{item['metadata']['name']}"
        spec = item['spec']['template']['spec']
        used_secrets, used_maps = config_names(spec)
        if (name == NEXTCLOUD or key_id in json.dumps(spec) or any(('secret', s) in holding for s in used_secrets)
                or any(('configmap', c) in holding for c in used_maps)):
            found.append(name)
    return sorted(found)


def restart_consumers(zone, key, since):
    """Restart each consumer of the key whose pods started before since (Unix seconds), and wait for it (step 6)."""
    import datetime
    workloads = [dict(i, kind=kind) for kind, plural in (('Deployment', 'deployments'), ('StatefulSet', 'statefulsets'))
                 for i in json.loads(kubectl('-n', zone, 'get', plural, '-o', 'json'))['items'] if i['spec'].get('replicas', 1)]
    secrets_ = json.loads(kubectl('-n', zone, 'get', 'secrets', '-o', 'json'))['items']
    configmaps = json.loads(kubectl('-n', zone, 'get', 'configmaps', '-o', 'json'))['items']
    pods = json.loads(kubectl('-n', zone, 'get', 'pods', '-o', 'json'))['items']

    def started(pod):
        text = (pod.get('status') or {}).get('startTime')
        return datetime.datetime.fromisoformat(text.replace('Z', '+00:00')).timestamp() if text else since

    restarted = []
    for name in consumers(workloads, secrets_, configmaps, key['access_key']):
        kind, workload = name.split('/')
        item = next(i for i in workloads if i['kind'].lower() == kind and i['metadata']['name'] == workload)
        selector = item['spec']['selector'].get('matchLabels') or {}
        own = [p for p in pods if selector and all((p['metadata'].get('labels') or {}).get(k) == v for k, v in selector.items())]
        if any(started(p) < since for p in own):
            kubectl('-n', zone, 'rollout', 'restart', name)
            restarted.append(name)
    for name in restarted:
        kubectl('-n', zone, 'rollout', 'status', name, '--timeout=900s')
    return restarted


def finish(zone, key):
    """Restart the consumers of the key after the waves of a move, and record the end of the switch (step 6). A zone
    without an open switch in its record is left as it is."""
    record = read_record(zone)
    if not record or record.get('switch_ended'):
        return None
    record['waves_done'] = time.time()
    record['restarted'] = restart_consumers(zone, key, record['switch_started'])
    record['switch_ended'] = time.time()
    record['pause_seconds'] = round(record['switch_ended'] - record['switch_started'], 1)
    write_record(zone, record)
    step('objectstore-switch', zone=zone, result='done', restarted=record['restarted'], pause_seconds=record['pause_seconds'])
    return record


def kept_volumes(zone):
    return [line.split('/', 1)[1] for line in kubectl('get', 'pv', '-l', f'{LABEL}={zone}', '-o', 'name').split()]


def drop_seaweedfs(zone):
    """Delete the SeaweedFS volumes that a move of a zone on Garage kept. TopoLVM then deletes the logical volumes."""
    import zonestate
    entry = zonestate.load()['zones'].get(zone)
    if entry is not None and not on_garage(entry):
        raise SystemExit(f'{zone} still uses SeaweedFS, so its volume stays.')
    if entry is not None and seaweedfs_installed(zone):
        raise SystemExit(f'{zone} still runs SeaweedFS. Run zone.py apply {zone} first.')
    return drop_kept(zone)


def drop_kept(zone, timeout=300):
    """Delete the SeaweedFS volumes with the label LABEL of a zone, with their logical volumes on the node. Return their
    names.

    A kept volume has the reclaim policy Retain, and a delete of such a PersistentVolume leaves its logical volume on
    the node. The policy changes to Delete first: the provisioner then deletes the logical volume and the
    PersistentVolume. A LogicalVolume of TopoLVM whose PersistentVolume is already gone (an earlier version deleted
    only the PersistentVolume) is deleted directly, and TopoLVM removes its logical volume."""
    names = kept_volumes(zone)
    for name in names:
        kubectl('patch', 'pv', name, '--type=merge', '-p', json.dumps({'spec': {'persistentVolumeReclaimPolicy': 'Delete'}}))
    deadline = time.monotonic() + timeout
    while names and set(kept_volumes(zone)) & set(names):
        if time.monotonic() >= deadline:
            raise SystemExit(f'the SeaweedFS volumes of {zone} were not deleted in {timeout} s: {", ".join(names)}')
        time.sleep(3)
    orphans = orphan_logical_volumes(zone)
    for name in orphans:
        kubectl('delete', 'logicalvolumes.topolvm.io', name, '--wait=true', f'--timeout={timeout}s')
    step('objectstore-seaweedfs-dropped', zone=zone, volumes=names, orphan_logical_volumes=orphans)
    return names + orphans


def orphan_logical_volumes(zone):
    """The TopoLVM LogicalVolumes of SeaweedFS claims of a zone without a PersistentVolume. TopoLVM names a
    LogicalVolume like its PersistentVolume and records the claim in the annotations of the PersistentVolume only, so
    the claim name comes from the earlier record of the move."""
    volumes = (read_record(zone) or {}).get('volumes') or []
    present = set(kubectl('get', 'pv', '-o', 'name').replace('persistentvolume/', '').split())
    logical = set(kubectl('get', 'logicalvolumes.topolvm.io', '-o', 'name', check=False).replace(
        'logicalvolume.topolvm.io/', '').split())
    return sorted(v for v in volumes if v in logical and v not in present)


def zone_key(zone):
    data = json.loads((settings.PRIVATE / 'zones' / 'secrets.json').read_text())
    try:
        return data[zone]['objectstore_key']
    except KeyError:
        raise SystemExit(f'zones/secrets.json has no object store key of {zone}. Run zone.py apply {zone}.') from None


def main(argv):
    if len(argv) != 2 or argv[0] not in ('show', 'check', 'drop-seaweedfs'):
        raise SystemExit(__doc__)
    command, zone = argv
    import zones
    if not zones.ZONE_NAME.fullmatch(zone):
        raise SystemExit(f'{zone!r} is not a zone id.')
    settings.use_kubeconfig()
    if command == 'drop-seaweedfs':
        drop_seaweedfs(zone)
        return
    key = zone_key(zone)
    target = garage_counts(key)
    if command == 'show':
        print(json.dumps({'zone': zone, 'key': key_name(zone),
                          'buckets': {b: dict(target[b], garage=global_name(zone, b)) for b in target}}, indent=1))
        return
    store = seaweedfs(zone)
    if store is None:
        raise SystemExit(f'{zone} has no running SeaweedFS to compare with.')
    source = seaweedfs_counts(zone, store)
    problems = differences(source, target)
    print(json.dumps({'zone': zone, 'seaweedfs': source, 'garage': target, 'differences': problems}, indent=1))
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main(sys.argv[1:])
