"""The openDesk object storage of a zone in the shared Garage: the values, the Ingress, the Garage tenant, the move
from SeaweedFS and the backup of the openDesk buckets (../zones/objectstore.py)."""
import base64
import json
import re
import sys

import pytest

from conftest import K3S

sys.path.insert(0, str(K3S / 'zones'))
sys.path.insert(0, str(K3S / 'platform' / 'backups'))
import backups  # noqa: E402
import objectstore  # noqa: E402
import shared  # noqa: E402
import zone  # noqa: E402
import zones  # noqa: E402

KEY = {'access_key': 'GK' + 'a' * 24, 'secret_key': 'b' * 64}


def test_the_buckets_are_the_object_stores_of_the_release():
    path = zones.OPENDESK / 'helmfile/environments/default/objectstores.yaml.gotmpl'
    if not path.exists():
        pytest.skip('the openDesk release is not unpacked in this checkout')
    text = path.read_text().split('objectstores:', 1)[1]
    found = {}
    for name, body in re.findall(r'^  (\w+):\n((?:    .*\n|\n)+)', text, re.M):
        if 'enterprise: true' not in body:
            found[name] = re.search(r'bucket: "([^"]+)"', body).group(1)
    assert found == objectstore.BUCKETS


def test_the_region_is_the_region_of_the_shared_garage():
    toml = (K3S / 'hoover/stores/config/garage/garage.toml').read_text()
    assert f's3_region = "{objectstore.REGION}"' in toml and objectstore.REGION == 'us-east-1'


def test_a_new_key_has_the_form_that_garage_imports():
    key = objectstore.new_key()
    assert re.fullmatch(r'GK[0-9a-f]{24}', key['access_key']) and re.fullmatch(r'[0-9a-f]{64}', key['secret_key'])
    assert objectstore.new_key() != key


@pytest.fixture
def render(monkeypatch):
    monkeypatch.setattr(zones, 'reduced_resources', lambda: {})
    monkeypatch.setattr(zones, 'ai_values', lambda: {})
    monkeypatch.setattr(zones, 'local_ca', lambda: {})
    monkeypatch.setattr(zones.settings, 'zone_host', lambda z, app: f'{z}-{app}.test')
    monkeypatch.setattr(objectstore.settings, 'zone_host', lambda z, app: f'{z}-{app}.test')
    data = {'zone-a': {'master_password': 'm', 'turn_secret': 't', 'objectstore_key': KEY},
            'calls': {'livekit_secret': 'l', 'jvb_password': 'j'}}
    return lambda entry: zones.zone_values('zone-a', data, 'ssd-ext4', entry)


def test_a_zone_on_garage_renders_its_key_and_host_and_no_seaweedfs(render):
    values = render({'stores': 'site', 'objectstore': 'garage'})
    assert values['apps']['seaweedfs'] == {'enabled': False}
    stores = values['objectstores']
    assert set(stores) == set(objectstore.BUCKETS)
    for store in stores.values():
        assert store == {'endpoint': 'zone-a-objectstorage.test', 'region': 'us-east-1', 'username': KEY['access_key'],
                         'secretKey': {'value': KEY['secret_key']}}
    # The bucket names stay those of openDesk: the key has a local alias for each.
    assert all('bucket' not in s for s in stores.values())


@pytest.mark.parametrize('entry', [{'stores': 'site'}, {'stores': 'local', 'objectstore': 'garage'}, {}])
def test_a_zone_before_its_move_or_of_the_layout_local_keeps_seaweedfs(render, entry):
    values = render(entry)
    assert 'seaweedfs' not in values['apps'] and 'objectstores' not in values


def test_the_ingress_sends_only_the_zone_buckets_to_garage(monkeypatch):
    monkeypatch.setattr(objectstore.settings, 'zone_host', lambda z, app: f'{z}-{app}.test')
    ingress = objectstore.ingress('zone-a')
    assert ingress['metadata']['namespace'] == 'hoover-stores' and ingress['metadata']['name'] == 'opendesk-zone-a'
    rule, = ingress['spec']['rules']
    assert rule['host'] == 'zone-a-objectstorage.test'
    paths = {p['path']: p['pathType'] for p in rule['http']['paths']}
    # The bucket list of the key, and each bucket of the zone.
    assert paths == {'/': 'Exact', **{f'/{b}': 'Prefix' for b in objectstore.BUCKETS.values()}}
    assert {json.dumps(p['backend']) for p in rule['http']['paths']} == {json.dumps({'service': {'name': 'garage', 'port': {'number': 3900}}})}
    annotations = ingress['metadata']['annotations']
    assert annotations['haproxy-ingress.github.io/cors-allow-origin'] == 'https://zone-a-projects.test'


def test_the_ingress_controller_reaches_only_the_s3_port_of_garage():
    policies = {p['metadata']['name']: p['spec'] for p in shared.network()}
    rules = policies['garage-clients']['ingress']
    s3 = next(r for r in rules if r['ports'] == [{'port': 3900}])
    assert shared.INGRESS_NS in s3['from']
    assert all(shared.INGRESS_NS not in r['from'] for r in rules if r is not s3)
    assert all(shared.INGRESS_NS not in r.get('from', []) for name, spec in policies.items() if name != 'garage-clients'
               for r in spec.get('ingress', []))


class Garage:
    """The Garage CLI over keys {id: name} and buckets {global name: {'keys': {id: (permissions, local alias)}}}."""

    def __init__(self):
        self.keys, self.buckets, self.calls = {}, {}, []

    def cli(self, *args, pod=None, check=True):
        self.calls.append(args)
        if args[:2] == ('key', 'list'):
            return 'ID  Created  Name  Expiration\n' + ''.join(f'{i}  2026-11-17  {n}  never\n' for i, n in self.keys.items())
        if args[:2] == ('key', 'import'):
            self.keys[args[5]] = args[4]
        if args[:2] == ('bucket', 'list'):
            rows = ''.join(f'b{n}  2026-11-17  {g}  ' + '  '.join(f'{k}:{a}' for k, (p, a) in b['keys'].items() if a) + '\n'
                           for n, (g, b) in enumerate(self.buckets.items()))
            return 'ID  Created  Global aliases  Local aliases\n' + rows
        if args[:2] == ('bucket', 'create'):
            self.buckets[args[2]] = {'keys': {}}
        if args[:2] == ('bucket', 'allow'):
            key, name = args[-1], args[args.index('--key') - 1]
            permissions, alias = self.buckets[name]['keys'].get(key, ('', ''))
            self.buckets[name]['keys'][key] = ('RW', alias)
        if args[:2] == ('bucket', 'alias'):
            key, name, alias = args[3], args[4], args[5]
            permissions, _ = self.buckets[name]['keys'].get(key, ('', ''))
            self.buckets[name]['keys'][key] = (permissions, alias)
        if args[:2] == ('key', 'info'):
            rows = ''.join(f'{b["keys"][args[2]][0]}  b{n}  {g}  {b["keys"][args[2]][1]}\n'
                           for n, (g, b) in enumerate(self.buckets.items()) if args[2] in b['keys'])
            return f'Key ID: {args[2]}\n\n==== BUCKETS FOR THIS KEY ====\nPermissions  ID  Global aliases  Local aliases\n{rows}'
        return ''


@pytest.fixture
def garage(monkeypatch):
    fake = Garage()
    monkeypatch.setattr(shared, 'garage_cli', fake.cli)
    return fake


def test_the_zone_gets_its_key_and_buckets_once_and_a_second_run_changes_nothing(garage):
    changed = objectstore.ensure('zone-a', KEY)
    assert changed[0] == 'key zone-a-opendesk'
    assert garage.keys == {KEY['access_key']: 'zone-a-opendesk'}
    assert sorted(garage.buckets) == sorted(f'zone-a-opendesk-{b}' for b in objectstore.BUCKETS.values())
    for name, bucket in garage.buckets.items():
        assert bucket['keys'] == {KEY['access_key']: ('RW', name.removeprefix('zone-a-opendesk-'))}
    # The key gets no owner right and no right to create buckets.
    assert not any('--owner' in c or '--create-bucket' in c for c in garage.calls)
    garage.calls.clear()
    assert objectstore.ensure('zone-a', KEY) == []
    assert all(c[:2] in (('key', 'list'), ('bucket', 'list'), ('key', 'info')) for c in garage.calls)


def test_a_key_of_the_zone_with_another_id_stops_the_step(garage):
    garage.keys['GK' + 'c' * 24] = 'zone-a-opendesk'
    with pytest.raises(SystemExit, match='another id'):
        objectstore.ensure('zone-a', KEY)


def test_the_openDesk_buckets_count_once_and_their_key_goes_before_the_purge(garage, monkeypatch):
    objectstore.ensure('zone-a', KEY)
    garage.keys['GKz'] = 'zone-a'
    garage.buckets['zone-a-system'] = {'keys': {'GKz': ('RW', '')}}
    keys, buckets = shared.garage_tenant('zone-a')
    assert keys == {KEY['access_key']: 'zone-a-opendesk', 'GKz': 'zone-a'}
    assert set(buckets) == {'zone-a-system', *(f'zone-a-opendesk-{b}' for b in objectstore.BUCKETS.values())}
    assert set(buckets.values()) == {''}

    deleted = []

    def cli(*args, pod=None, check=True):
        if args[:2] == ('key', 'delete'):
            deleted.append(args[3])
            garage.keys.pop(args[3])
            for bucket in garage.buckets.values():
                bucket['keys'].pop(args[3], None)
            return ''
        if args[:2] == ('key', 'create'):
            garage.keys['GKpurge'] = args[2]
            return 'Key ID: GKpurge\nSecret key: s\n'
        if args[:2] == ('bucket', 'delete'):
            if any(alias for _, alias in garage.buckets[args[3]]['keys'].values()):
                raise SystemExit('still has other local aliases')
            garage.buckets.pop(args[3])
            return ''
        return garage.cli(*args)
    purged = []
    monkeypatch.setattr(shared, 'garage_cli', cli)
    monkeypatch.setattr(shared.garage_client, 'run', lambda pod, key, command, *names, **kw: purged.append((key['access_key'], names)) or ('', []))
    monkeypatch.setattr(shared.garage_client, 'client', lambda: __import__('contextlib').nullcontext('garage-0'))
    monkeypatch.setattr(shared.common, 'log', lambda *a, **k: None)
    shared.remove_garage('zone-a')
    assert deleted[0] == KEY['access_key']
    assert purged == [('GKpurge', tuple(sorted(buckets)))]
    assert garage.buckets == {} and set(garage.keys) == set()


def test_the_counts_must_match_for_each_bucket():
    same = {'nextcloud': {'objects': 2, 'bytes': 10}, 'ums': {'objects': 0, 'bytes': 0}}
    assert objectstore.differences(same, dict(same)) == []
    problems = objectstore.differences(same, {**same, 'nextcloud': {'objects': 2, 'bytes': 9}})
    assert problems == ['nextcloud: SeaweedFS has 2 objects and 10 bytes, Garage 2 objects and 9 bytes']
    assert objectstore.differences({**same, 'extra': {'objects': 1, 'bytes': 1}}, same) == [
        'extra: SeaweedFS has 1 objects and 1 bytes, Garage None objects and None bytes']
    assert objectstore.differences(same, {**same, 'notes': {'objects': 1, 'bytes': 3}}) == [
        'notes: Garage has 1 objects, and SeaweedFS has no bucket notes']


def workload(kind, name, spec):
    return {'kind': kind, 'metadata': {'name': name}, 'spec': {'template': {'spec': spec}}}


def test_the_consumers_are_the_workloads_that_read_the_key_and_nextcloud():
    secret = {'metadata': {'name': 'openproject-s3'}, 'data': {'ID': base64.b64encode(KEY['access_key'].encode()).decode()}}
    other = {'metadata': {'name': 'xwiki'}, 'data': {'x': base64.b64encode(b'y').decode()}}
    config = {'metadata': {'name': 'synapse-storage'}, 'data': {'storage.yaml': f'access_key_id: {KEY["access_key"]}'}}
    found = objectstore.consumers([
        workload('Deployment', 'openproject-web', {'containers': [{'envFrom': [{'secretRef': {'name': 'openproject-s3'}}]}]}),
        workload('StatefulSet', 'synapse', {'containers': [{}], 'volumes': [{'name': 'c', 'configMap': {'name': 'synapse-storage'}}]}),
        workload('Deployment', 'notes', {'containers': [{'env': [{'name': 'ID', 'value': KEY['access_key']}]}]}),
        workload('Deployment', 'opendesk-nextcloud-aio', {'containers': [{}]}),
        workload('Deployment', 'xwiki', {'containers': [{'envFrom': [{'secretRef': {'name': 'xwiki'}}]}]}),
    ], [secret, other], [config], KEY['access_key'])
    assert found == ['deployment/notes', 'deployment/opendesk-nextcloud-aio', 'deployment/openproject-web', 'statefulset/synapse']


@pytest.fixture
def zone_state(monkeypatch, tmp_path):
    state = {'schemaVersion': 1, 'zones': {'zone-a': {'enabled': True, 'namespaces': ['zone-a', 'hoover-zone-a'], 'stores': 'site'}}}
    monkeypatch.setattr(zone.zonestate, 'load', lambda: json.loads(json.dumps(state)))
    monkeypatch.setattr(zone.zonestate, 'save', lambda data: state.update(data))
    monkeypatch.setattr(zone.clusterstate, 'checkpoint', lambda folder: None)
    folder = tmp_path / 'zones'
    folder.mkdir()
    (folder / 'secrets.json').write_text(json.dumps({'zone-a': {'objectstore_key': KEY}}))
    monkeypatch.setattr(zone, 'PRIVATE', tmp_path)
    monkeypatch.setattr(objectstore, 'ensure', lambda z, key: [])
    calls = []
    monkeypatch.setattr(zone, 'run', lambda *args, **kw: calls.append([str(a).rsplit('/', 1)[-1] for a in args[1:]]))
    monkeypatch.setattr(zone, 'apply_manifest', lambda text, ns=None: calls.append(['apply', json.loads(text)['metadata']['name'], ns]))
    monkeypatch.setattr(objectstore, 'move', lambda z, key: calls.append(['move', z]))
    return state, calls


def test_a_zone_of_an_earlier_version_moves_and_then_names_garage(zone_state, monkeypatch):
    state, calls = zone_state
    monkeypatch.setattr(objectstore, 'seaweedfs_installed', lambda z: True)
    monkeypatch.setattr(objectstore, 'can_keep_volumes', lambda: True)
    assert zone.objects('zone-a') is True
    assert state['zones']['zone-a']['objectstore'] == 'garage'
    assert calls == [['move', 'zone-a'], ['zones.py'], ['apply', 'opendesk-zone-a', 'hoover-stores']]
    calls.clear()
    # A zone on Garage keeps its Ingress and does not move again.
    assert zone.objects('zone-a') is False
    assert calls == [['apply', 'opendesk-zone-a', 'hoover-stores']]


def test_the_zone_runner_leaves_a_zone_of_an_earlier_version_on_seaweedfs(zone_state, monkeypatch):
    state, calls = zone_state
    monkeypatch.setattr(objectstore, 'seaweedfs_installed', lambda z: True)
    monkeypatch.setattr(objectstore, 'can_keep_volumes', lambda: False)
    assert zone.objects('zone-a') is False
    assert 'objectstore' not in state['zones']['zone-a'] and calls == []


def test_a_zone_of_the_layout_local_keeps_seaweedfs(zone_state):
    state, calls = zone_state
    state['zones']['zone-a']['stores'] = 'local'
    assert zone.objects('zone-a') is False and calls == []


def test_a_new_zone_of_the_layout_site_starts_on_garage(monkeypatch):
    saved = {}
    monkeypatch.setattr(zone.zonestate, 'load', lambda: {'schemaVersion': 1, 'zones': {}})
    monkeypatch.setattr(zone.zonestate, 'save', lambda data: saved.update(data))
    import config
    monkeypatch.setattr(config, 'zone_problems', lambda *a: [])
    zone.register('zone-n')
    assert saved['zones']['zone-n']['objectstore'] == 'garage'
    zone.register('zone-l', values={'stores': 'local'})
    assert 'objectstore' not in saved['zones']['zone-l']


def test_the_move_record_is_no_input_of_the_waves():
    source = (K3S / 'zones/zone.py').read_text()
    assert 'path.name not in (RECORD_NAME, objectstore.RECORD)' in source


def test_a_failed_copy_check_gives_the_routes_back_to_seaweedfs(monkeypatch, tmp_path):
    steps = []
    monkeypatch.setattr(objectstore, 'seaweedfs', lambda z: {'pod': 'p', 'claims': ['data'], 'endpoint': 'e:8333'})
    monkeypatch.setattr(objectstore, 'apply_ingress', lambda z: steps.append('ingress'))
    monkeypatch.setattr(objectstore, 'delete_ingress', lambda z: steps.append('no ingress'))
    monkeypatch.setattr(backups, 'object_store_key', lambda ns, store: {'sse_c': {}})

    def copy(ns, store, target):
        (target / 'buckets.json').write_text(json.dumps([{'bucket': 'nextcloud', 'objects': 1}]))
        (target / 'nextcloud.tar').write_bytes(b'')
    monkeypatch.setattr(backups, 'copy_objects', copy)
    monkeypatch.setattr(objectstore, 'garage_run', lambda key, *args, **kw: steps.append(args[0]) or ('', []))
    monkeypatch.setattr(objectstore, 'seaweedfs_counts', lambda z, s: {'nextcloud': {'objects': 1, 'bytes': 5}})
    monkeypatch.setattr(objectstore, 'garage_counts', lambda key: {'nextcloud': {'objects': 0, 'bytes': 0}})
    monkeypatch.setattr(objectstore, 'kubectl', lambda *a, **kw: steps.append(a[:2]) or '')
    with pytest.raises(SystemExit, match='stays on SeaweedFS'):
        objectstore.move('zone-a', KEY)
    assert steps == ['ingress', 'empty', 'untar', 'no ingress']


def test_the_zone_backup_copies_the_openDesk_buckets_from_garage(monkeypatch, tmp_path):
    pods = {'items': [{'metadata': {'name': 'postgresql-0'}, 'status': {'phase': 'Running'}, 'spec': {}}]}
    monkeypatch.setattr(backups, 'kubectl', lambda *a, **kw: json.dumps(pods if a[3] == 'pods' else {'items': []})
                        if a[2] == 'get' else '{"items": []}')
    monkeypatch.setattr(backups, 'dump_out', lambda ns, args, target: target.write_text('dump'))
    monkeypatch.setattr(backups, 'opendesk_garage_key', lambda ns: KEY if ns == 'zone-a' else None)
    copied = []
    monkeypatch.setattr(backups, 'copy_garage_objects', lambda ns, key, target: copied.append((ns, key['access_key'], target.name)))
    monkeypatch.setattr(backups, 'copy_objects', lambda *a: pytest.fail('no SeaweedFS runs'))
    backups.copy_namespace('zone-a', tmp_path)
    assert copied == [('zone-a', KEY['access_key'], 'objects')]


def test_the_garage_copy_has_the_form_of_the_seaweedfs_copy(monkeypatch, tmp_path):
    import garage_client
    ran = []

    def run(pod, key, command, bucket, out=None, sse_c=None):
        ran.append((command, bucket, sse_c))
        import tarfile
        with tarfile.open(out, 'w') as tar:
            pass
        return None, [{'bucket': bucket, 'objects': 0, 'customer_key_objects': 0}]
    monkeypatch.setattr(garage_client, 'run', run)
    monkeypatch.setattr(garage_client, 'client', lambda: __import__('contextlib').nullcontext('garage-0'))
    monkeypatch.setattr(backups, 'customer_keys', lambda ns: {'synapse': 'c2Vj'})
    backups.copy_garage_objects('zone-a', KEY, tmp_path)
    rows = json.loads((tmp_path / 'buckets.json').read_text())
    assert [r['bucket'] for r in rows] == sorted(objectstore.BUCKETS.values())
    assert ('tar', 'synapse', {'synapse': 'c2Vj'}) in ran and ('tar', 'ums', None) in ran


def test_the_restore_writes_the_copy_into_the_garage_buckets_of_the_zone(monkeypatch, tmp_path):
    import garage_client
    (tmp_path / 'objects').mkdir()
    (tmp_path / 'objects' / 'buckets.json').write_text(json.dumps([{'bucket': 'nextcloud'}, {'bucket': 'ums'}]))
    monkeypatch.setattr(backups, 'kubectl', lambda *a, **kw: '{"items": []}')
    monkeypatch.setattr(backups, 'opendesk_garage_key', lambda ns: KEY)
    monkeypatch.setattr(backups, 'customer_keys', lambda ns: {})
    ran = []
    monkeypatch.setattr(garage_client, 'run', lambda pod, key, command, bucket, **kw: ran.append((command, bucket)) or ('', []))
    monkeypatch.setattr(garage_client, 'client', lambda: __import__('contextlib').nullcontext('garage-0'))
    backups.restore_objects(tmp_path, 'zone-a')
    assert ran == [('empty', 'nextcloud'), ('untar', 'nextcloud'), ('empty', 'ums'), ('untar', 'ums')]
    (tmp_path / 'objects' / 'buckets.json').write_text(json.dumps([{'bucket': 'other'}]))
    with pytest.raises(SystemExit, match='other'):
        backups.restore_objects(tmp_path, 'zone-a')


def test_a_zone_delete_drops_the_kept_volume_with_the_admin_kubeconfig_only(monkeypatch, capsys):
    state = {'schemaVersion': 1, 'zones': {'zone-a': {'enabled': True, 'namespaces': ['zone-a', 'hoover-zone-a'], 'stores': 'local'}}}
    monkeypatch.setattr(zone.zonestate, 'load', lambda: json.loads(json.dumps(state)))
    monkeypatch.setattr(zone.zonestate, 'save', lambda data: None)
    monkeypatch.setattr(zone.clusterstate, 'checkpoint', lambda folder: None)
    monkeypatch.setattr(zone, 'kubectl', lambda *a, **kw: '')
    monkeypatch.setattr(zone, 'run', lambda *a, **kw: None)
    monkeypatch.setattr(zone, 'pools', lambda: None)
    dropped = []
    monkeypatch.setattr(objectstore, 'drop_kept', lambda z: dropped.append(z))
    monkeypatch.setattr(objectstore, 'read_record', lambda z: {'zone': z})
    monkeypatch.setattr(objectstore, 'can_keep_volumes', lambda: True)
    zone.delete('zone-a')
    assert dropped == ['zone-a']
    dropped.clear()
    monkeypatch.setattr(objectstore, 'can_keep_volumes', lambda: False)
    zone.delete('zone-a')
    assert dropped == [] and 'hoover.dev/seaweedfs-of=zone-a can stay' in capsys.readouterr().out


@pytest.mark.parametrize('moved', [True, False])
def test_the_element_entry_runs_once_more_after_a_move(monkeypatch, moved):
    calls = []
    for name in ('register', 'images', 'cluster', 'namespaces', 'finish_move', 'hoover'):
        monkeypatch.setattr(zone, name, lambda *a, **kw: None)
    monkeypatch.setattr(zone, 'objects', lambda z: moved)
    monkeypatch.setattr(zone.clusterstate, 'checkpoint', lambda folder: None)
    monkeypatch.setattr(zone.zonestate, 'enabled', lambda z: True)
    monkeypatch.setattr(zone, 'run', lambda *a, **kw: None)
    monkeypatch.setattr(zone, 'apply_manifest', lambda *a, **kw: None)
    monkeypatch.setattr(zone, 'opendesk_inputs', lambda z: {})
    monkeypatch.setattr(zone, 'helm_revisions', lambda z: {})
    monkeypatch.setattr(zone, 'opendesk_changes', lambda z, inputs, releases: ['zone-state changed'])
    monkeypatch.setattr(zone, 'opendesk', lambda z: calls.append('waves'))
    monkeypatch.setattr(zone, 'install_entry', lambda z, entry: calls.append(entry))
    monkeypatch.setattr(zone, 'write_record', lambda z, inputs: calls.append('record'))
    gate = type(sys)('gate')
    gate.objects = lambda z: []
    monkeypatch.setitem(sys.modules, 'gate', gate)
    zone.apply('zone-a')
    assert calls == (['waves', 'element', 'record'] if moved else ['waves', 'record'])


def test_a_drop_deletes_the_logical_volumes_of_the_kept_volumes(monkeypatch):
    # A kept volume has the policy Retain: the drop sets Delete, so the provisioner removes the logical volume, and a
    # LogicalVolume left by an earlier drop without its PersistentVolume is deleted directly.
    pvs = {'pv-kept'}
    calls = []

    def kubectl(*args, **kw):
        calls.append(args)
        if args[:2] == ('get', 'pv') and '-l' in args:
            return ''.join(f'persistentvolume/{n}\n' for n in sorted(pvs))
        if args[:2] == ('get', 'pv'):
            return ''.join(f'persistentvolume/{n}\n' for n in sorted(pvs | {'pv-other'}))
        if args[:2] == ('get', 'logicalvolumes.topolvm.io'):
            return 'logicalvolume.topolvm.io/pv-orphan\nlogicalvolume.topolvm.io/pv-other\n'
        if args[:2] == ('patch', 'pv'):
            assert json.loads(args[-1]) == {'spec': {'persistentVolumeReclaimPolicy': 'Delete'}}
            pvs.discard(args[2])
        return ''
    monkeypatch.setattr(objectstore, 'kubectl', kubectl)
    monkeypatch.setattr(objectstore, 'read_record', lambda z: {'volumes': ['pv-kept', 'pv-orphan', 'pv-other']})
    monkeypatch.setattr(objectstore, 'step', lambda *a, **k: None)
    monkeypatch.setattr(objectstore.time, 'sleep', lambda s: None)
    assert objectstore.drop_kept('zone-a') == ['pv-kept', 'pv-orphan']
    assert ('delete', 'logicalvolumes.topolvm.io', 'pv-orphan', '--wait=true', '--timeout=300s') in calls
