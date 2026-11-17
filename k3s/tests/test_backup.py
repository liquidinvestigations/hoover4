"""The backup suite: eligibility, the weekly limit, slots, retention, space, the destination check and the copy manifest.

Time is a parameter of every rule, so each test sets it. The tests use temporary folders and contact no cluster.
"""
import importlib.util
import json
import sys

import pytest

from conftest import K3S

sys.path.insert(0, str(K3S / 'platform' / 'backups'))
import schedule  # noqa: E402

DAY = 24 * 3600
T0 = 1_800_000_000


def backups_module():
    spec = importlib.util.spec_from_file_location('backups', K3S / 'platform' / 'backups' / 'backups.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def op(op_id, kind, dataset, state, started, finished=0):
    return {'op_id': op_id, 'kind': kind, 'collection_dataset': dataset, 'state': state, 'started': started, 'finished': finished}


def test_first_ingestion_gives_a_receipt_only_after_every_dataset_finished():
    receipts = backups_module().receipts_from_operations
    running = [op('a1', 'add_dataset', 'c_a', 'finished', 10, 20), op('b1', 'add_dataset', 'c_b', 'running', 15)]
    assert receipts(running) == []
    done = [op('a1', 'add_dataset', 'c_a', 'finished', 10, 20), op('b1', 'add_dataset', 'c_b', 'finished', 15, 40)]
    found = receipts(done)
    assert [r['kind'] for r in found] == ['ingest'] and found[0]['settled'] == 40


def test_a_partial_update_is_no_reprocessing_receipt_and_a_complete_one_is():
    receipts = backups_module().receipts_from_operations
    base = [op('a1', 'add_dataset', 'c_a', 'finished', 10, 20), op('b1', 'add_dataset', 'c_b', 'finished', 15, 40)]
    # update_collection alone ran its collection prerequisites only.
    partial = base + [op('u1', 'update_collection', '', 'finished', 100, 200), op('d1', 'update_dataset', 'c_a', 'finished', 110, 150)]
    assert [r['kind'] for r in receipts(partial)] == ['ingest']
    failed = partial + [op('d2', 'update_dataset', 'c_b', 'errored', 120, 180)]
    assert [r['kind'] for r in receipts(failed)] == ['ingest']
    complete = partial + [op('d2', 'update_dataset', 'c_b', 'finished', 120, 190)]
    found = [r for r in receipts(complete) if r['kind'] == 'reprocess']
    assert len(found) == 1 and found[0]['settled'] == 200


def hoover_job(receipts):
    return schedule.Job('hoover:zone-a:enron', 2, receipts, estimated_bytes=1000, duration=600)


def test_the_first_ingestion_copy_starts_and_later_ingestion_gives_no_new_copy():
    job = hoover_job([{'kind': 'ingest', 'generation': 'ingest-1', 'settled': T0}])
    assert schedule.due(job, {}, T0 + 10)[:1] == (True,)
    record = {'copies': [{'generation': 'ingest-1', 'finished': T0 + 100, 'verified': True}]}
    later = hoover_job(job.receipts + [{'kind': 'ingest', 'generation': 'ingest-2', 'settled': T0 + 30 * DAY}])
    ready, reason, generation = schedule.due(later, record, T0 + 31 * DAY)
    assert not ready and generation is None


def test_a_reprocessing_waits_for_the_seven_day_limit_and_pending_generations_become_one_copy():
    receipts = [{'kind': 'ingest', 'generation': 'ingest-1', 'settled': T0},
                {'kind': 'reprocess', 'generation': 'reprocess-a', 'settled': T0 + 2 * DAY},
                {'kind': 'reprocess', 'generation': 'reprocess-b', 'settled': T0 + 3 * DAY}]
    record = {'copies': [{'generation': 'ingest-1', 'finished': T0 + 100, 'verified': True}]}
    ready, reason, generation = schedule.due(hoover_job(receipts), record, T0 + 4 * DAY)
    assert not ready and 'weekly limit' in reason and generation == 'reprocess-b'
    ready, _, generation = schedule.due(hoover_job(receipts), record, T0 + 8 * DAY)
    assert ready and generation == 'reprocess-b'


def test_an_unchanged_collection_gets_no_weekly_copy():
    receipts = [{'kind': 'ingest', 'generation': 'ingest-1', 'settled': T0}]
    record = {'copies': [{'generation': 'ingest-1', 'finished': T0 + 100, 'verified': True}]}
    assert schedule.due(hoover_job(receipts), record, T0 + 60 * DAY)[0] is False


def test_weekly_jobs_wait_for_their_slot_and_spread_over_the_week():
    keys = ['opendesk:zone-a', 'opendesk:zone-b', 'opendesk:zone-c', 'platform']
    offsets = [schedule.week_offset(k) for k in keys]
    assert len(set(offsets)) == len(keys) and all(0 <= o < schedule.WEEK for o in offsets)
    job = schedule.Job('opendesk:zone-a', 3)
    slot = schedule.slot_after(job.key, T0)
    assert slot >= T0 and slot - T0 < schedule.WEEK
    assert schedule.due(job, {'slot': slot}, slot - 1)[0] is False
    ready, _, generation = schedule.due(job, {'slot': slot}, slot)
    assert ready and generation == f'week-{slot}'
    done = {'copies': [{'generation': generation, 'finished': slot + 100, 'verified': True}]}
    assert schedule.due(job, done, slot + 3 * DAY)[0] is False


def test_missed_jobs_after_downtime_get_future_slots_one_after_another():
    jobs = [schedule.Job('opendesk:zone-a', 3, duration=1800), schedule.Job('opendesk:zone-b', 3, duration=1800),
            schedule.Job('platform', 3, duration=600)]
    now = T0 + 10 * DAY
    records = {j.key: {'slot': T0} for j in jobs}
    start, blocked, slots = schedule.plan(jobs, records, now, free_bytes=10**12)
    assert len(start) == 1 and not blocked
    first = start[0][0]
    assert sorted(slots) == sorted(j.key for j in jobs if j is not first)
    assert all(s >= now + first.duration for s in slots.values())
    assert len(set(slots.values())) == len(slots)


def test_low_space_blocks_a_job_and_proposes_fewer_copies_without_deleting():
    job = hoover_job([{'kind': 'ingest', 'generation': 'ingest-1', 'settled': T0}])
    job.estimated_bytes = 10**9
    start, blocked, _ = schedule.plan([job], {}, T0 + 10, free_bytes=10**9)
    assert start == [] and blocked[0]['job'] == job.key and 'keep 1 copies' in blocked[0]['proposal']


def test_retention_keeps_the_newest_verified_copies_and_never_the_failed_one():
    record = {'copies': [{'generation': 'a', 'finished': 1, 'verified': True, 'path': '/a'},
                         {'generation': 'b', 'finished': 2, 'verified': True, 'path': '/b'},
                         {'generation': 'c', 'finished': 3, 'verified': False, 'path': '/c'},
                         {'generation': 'd', 'finished': 4, 'verified': True, 'path': '/d'}]}
    removed = {c['generation'] for c in schedule.retention(record, 2)}
    assert removed == {'a', 'c'}
    # A record whose only copy is the last valid copy keeps it, even with copies below one.
    assert schedule.retention({'copies': [record['copies'][0]]}, 0) == []


def test_a_missing_mount_pauses_the_jobs(tmp_path):
    assert 'does not exist' in schedule.destination_problem(str(tmp_path / 'absent'))
    assert 'mount may be missing' in schedule.destination_problem(str(tmp_path))
    (tmp_path / schedule.MARKER).write_text('x')
    assert schedule.destination_problem(str(tmp_path)) == ''


def test_recommendations_follow_the_space():
    sizes = {'hoover': 100, 'opendesk': 50, 'platform': 1}
    copies, needed = schedule.recommend(sizes, free_bytes=10**6)
    assert copies == {'hoover': 2, 'opendesk': 3, 'platform': 3}
    copies, needed = schedule.recommend(sizes, free_bytes=450)
    assert copies['hoover'] >= 1 and copies['opendesk'] >= 2 and needed <= 450 or copies == {'hoover': 1, 'opendesk': 2, 'platform': 1}


def test_a_copy_manifest_finds_a_changed_file_and_keeps_the_export_manifest(tmp_path):
    backups = backups_module()
    (tmp_path / 'a').mkdir()
    (tmp_path / 'a' / 'one.bin').write_bytes(b'one')
    (tmp_path / 'two.sql').write_text('two')
    # A collection export holds its own manifest.json, which the import reads. The copy covers it.
    (tmp_path / 'manifest.json').write_text('{"collectionname": "c"}')
    (tmp_path / backups.MANIFEST).write_text(json.dumps({'files': backups.manifest(tmp_path)}))
    assert 'manifest.json' in [r['path'] for r in backups.manifest(tmp_path)]
    assert backups.verify(tmp_path)['differences'] == []
    (tmp_path / 'two.sql').write_text('changed')
    assert backups.verify(tmp_path)['differences'] == ['two.sql']


@pytest.mark.parametrize('kind,copies', [('hoover', 2), ('opendesk', 3), ('platform', 3)])
def test_the_portal_defaults_of_the_retained_copies(kind, copies):
    from conftest import operator_settings
    scope = 'cluster' if kind == 'platform' else 'zone:zone-a'
    assert operator_settings().effective(scope, {})[f'backup.{kind}.copies'] == str(copies)


def test_a_block_claim_is_read_through_the_store_container_that_mounts_it():
    backups = backups_module()
    store = {'metadata': {'name': 'redis-master-0'}, 'status': {'phase': 'Running'},
             'spec': {'volumes': [{'name': 'redis-data', 'persistentVolumeClaim': {'claimName': 'redis-data-redis-master-0'}}],
                      'containers': [{'name': 'redis', 'volumeDevices': [{'name': 'redis-data', 'devicePath': '/dev/block-redis-data'}],
                                      'env': [{'name': 'BLOCK_MOUNTS', 'value': '/dev/block-redis-data:/data'}]}]}}
    stopped = {**store, 'status': {'phase': 'Pending'}}
    assert backups.block_source('redis-data-redis-master-0', [store]) == ('redis-master-0', 'redis', '/data')
    assert backups.block_source('redis-data-redis-master-0', [stopped]) is None
    assert backups.block_source('other', [store]) is None


def test_a_block_claim_is_restored_in_kata_with_limits_and_a_file_system_claim_without():
    backups = backups_module()
    block = backups.restore_pod('r', {'claim': 'nats-data', 'volume_mode': 'Block'})['spec']
    write = next(c for c in block['containers'] if c['name'] == 'write')
    assert block['runtimeClassName'] == 'kata' and write['resources']['limits']
    assert write['volumeDevices'] == [{'name': 'data', 'devicePath': '/dev/block-data'}]
    plain = backups.restore_pod('r', {'claim': 'xwiki-data', 'volume_mode': 'Filesystem'})['spec']
    assert 'runtimeClassName' not in plain and plain['containers'][0]['volumeMounts'][0]['mountPath'] == '/data'


def test_the_export_check_finds_a_truncated_manticore_meta_file(tmp_path):
    import io
    import subprocess
    import tarfile
    import zstandard
    backups = backups_module()
    (tmp_path / 'manticore').mkdir()
    for name, meta in (('good', b'{"a": 1}\n'), ('cut', b'{"a": 1,\n"soft_ram_limit":13421772')):
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode='w') as tar:
            info = tarfile.TarInfo(f'{name}.meta')
            info.size = len(meta)
            tar.addfile(info, io.BytesIO(meta))
        (tmp_path / 'manticore' / f'{name}.tar.zst').write_bytes(zstandard.ZstdCompressor().compress(raw.getvalue()))
    out = subprocess.run([sys.executable, '-c', backups.META_CHECK, str(tmp_path)], capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) == ['cut.tar.zst:cut.meta']


def test_the_collection_job_copies_the_clickhouse_object_and_removes_it_after_the_copy(monkeypatch):
    backups = backups_module()
    steps = []
    hoover = type('H', (), {'zone': 'zone-a', 'namespace': 'hoover-zone-a'})()
    monkeypatch.setattr(backups.site_config, 'hoovers', lambda _s: {'zone-a': hoover})
    monkeypatch.setattr(backups, 'operations_pod', lambda _ns: 'ops-0')

    def kubectl(*args, **_kw):
        command = list(args[args.index('--') + 1:])
        if backups.CLICKHOUSE_OBJECT in command:
            steps.append(command[3])
        elif backups.META_CHECK in command:
            steps.append('check')
            return '[]'
        else:
            steps.append(command[0] if command[0] == 'rm' else 'export')
        return ''
    monkeypatch.setattr(backups, 'kubectl', kubectl)
    monkeypatch.setattr(backups, 'stream_out', lambda *a: steps.append('stream'))
    backups.run_hoover(None, 'zone-a', 'demo', 'g1', '/partial')
    assert steps == ['export', 'check', 'fetch_clickhouse_object', 'stream', 'remove_clickhouse_object', 'rm']


# The store client, the destination node, the recovery set and the zone closure ---------------------------------------

import config  # noqa: E402
from conftest import site_text, write_site  # noqa: E402


def test_the_clickhouse_client_follows_the_store_layout_and_names_no_password(tmp_path):
    backups = backups_module()
    zones = config.hoovers(config.read(write_site(tmp_path, 'remote.yml')))
    ns, pod, container, command = backups.clickhouse_command(zones['zone-a'])
    assert (ns, pod, container) == ('hoover-stores', 'clickhouse-0', 'clickhouse')
    assert '--user hoover_admin --password "$CH_ADMIN_PASSWORD"' in command
    ns, pod, container, command = backups.clickhouse_command(zones['zone-c'])
    assert (ns, pod, container) == ('hoover-zone-c', 'clickhouse-0', None) and '${CLICKHOUSE_PASSWORD:-hoover4}' in command
    calls = []
    import podexec
    import subprocess

    def call(argv, command, data=b'', timeout=None):
        calls.append((argv, command, data))
        return subprocess.CompletedProcess(argv, 0, '{"a":1}\n', '')
    original, podexec.call = podexec.call, call
    try:
        assert backups.clickhouse(zones['zone-a'], 'SELECT 1') == '{"a":1}\n'
    finally:
        podexec.call = original
    # The standard input stays open until the client ends (podexec.py), because the Kata pod cuts the output.
    argv, command, data = calls[0]
    assert argv[-7:] == ['-n', 'hoover-stores', 'exec', '-i', 'clickhouse-0', '-c', 'clickhouse'] and data == 'SELECT 1'
    assert not any('hoover4' == a for a in argv + command)


@pytest.fixture
def local_destination(tmp_path):
    backups = backups_module()
    dest = tmp_path / 'dest'
    text = site_text('single-node.yml').replace('path: /srv/hoover4-backups', f'path: {dest}')
    s = config.read(write_site(tmp_path, 'single-node.yml', text))
    return backups, s, dest


def copy_folder(backups, folder, files):
    folder.mkdir(parents=True)
    for name, data in files.items():
        (folder / name).write_bytes(data)
    (folder / backups.MANIFEST).write_text(json.dumps({'files': backups.manifest(folder)}))
    return folder


def staged(backups, target, key, generation, files):
    """A staging folder of the destination with a manifest of its files, as run_job() leaves it before publish()."""
    folder = target.staging(key, generation)
    folder.parent.mkdir(parents=True, exist_ok=True)
    return copy_folder(backups, folder, files)


def test_the_mounted_destination_checks_renames_verifies_and_keeps_older_copies(local_destination, tmp_path):
    backups, s, dest = local_destination
    target = backups.Destination(s)
    assert 'is not mounted here' in target.problem()
    dest.mkdir()
    assert 'has no .hoover4-backup-destination' in target.problem()
    target.enable()
    assert target.problem() == '' and target.free_bytes() > 0
    assert {p.name for p in dest.iterdir()} == {'zones', 'platform', 'staging', schedule.MARKER}
    first = staged(backups, target, 'zone:zone-a', 'week-1', {'a.sql': b'one'})
    assert str(first) == f'{dest}/staging/zone_zone-a/week-1.partial'
    inode = (first / 'a.sql').stat().st_ino
    final, checked = target.publish(first, 'zone:zone-a', 'week-1')
    assert final == f'{dest}/zones/zone-a/week-1' and checked['differences'] == [] and checked['bytes'] == 3
    # The copy is renamed into place, so the file is the same file and nothing stays in staging.
    assert (dest / 'zones/zone-a/week-1/a.sql').stat().st_ino == inode and not first.exists()
    # A copy that changed after its manifest, or that holds a file the manifest lacks, is refused and the older copy stays.
    second = staged(backups, target, 'zone:zone-a', 'week-2', {'a.sql': b'two'})
    (second / 'a.sql').write_bytes(b'changed after the manifest')
    with pytest.raises(SystemExit, match='differs from its manifest'):
        target.publish(second, 'zone:zone-a', 'week-2')
    third = staged(backups, target, 'zone:zone-a', 'week-3', {'a.sql': b'three'})
    (third / 'extra').write_bytes(b'x')
    with pytest.raises(SystemExit, match='differs from its manifest'):
        target.publish(third, 'zone:zone-a', 'week-3')
    assert not (dest / 'zones/zone-a/week-2').exists() and not (dest / 'zones/zone-a/week-3').exists()
    assert (dest / 'zones/zone-a/week-1/a.sql').read_bytes() == b'one'
    with pytest.raises(SystemExit, match='not a staging folder'):
        target.publish(tmp_path, 'zone:zone-a', 'week-4')
    assert target.copies() == {'zones/zone-a': ['week-1']}
    assert target.check('zone:zone-a', 'week-1')['differences'] == []
    with pytest.raises(SystemExit, match='does not exist'):
        target.check('zone:zone-a', 'week-9')
    with pytest.raises(SystemExit, match='outside the backup destination'):
        target.remove('/etc')
    target.remove(final)
    assert not (dest / 'zones/zone-a/week-1').exists()


def test_a_job_writes_its_copy_on_the_destination_volume_and_retention_follows_the_check(local_destination, monkeypatch):
    backups, s, dest = local_destination
    dest.mkdir()
    backups.Destination(s).enable()
    monkeypatch.setattr(backups, 'site', lambda: s)
    monkeypatch.setattr(backups, 'applied_values', lambda s, scope: {'backup.opendesk.copies': '2'})
    held = []
    lock = type('Lock', (), {'acquire': lambda self, kind, op: held.append(op), 'release': lambda self: None})()
    monkeypatch.setattr(backups.oplock, 'site_lock', lambda folder: lock)
    # Each job ends at a later time, so retention keeps the newest copies.
    clock = iter(range(T0, T0 + 1000, 10))
    monkeypatch.setattr(backups.time, 'time', lambda: next(clock))
    seen = []

    def run_zone(s, zone, partial, key):
        seen.append(partial)
        partial.mkdir()
        (partial / 'postgresql.sql').write_bytes(f'dump {len(seen)}'.encode())
    monkeypatch.setattr(backups, 'run_zone', run_zone)
    for generation in ('g1', 'g2', 'g3'):
        backups.run_job('zone:zone-a', generation)
    assert all(str(p).startswith(f'{dest}/staging/') for p in seen) and len(held) == 3
    record = backups.load_state(s)['jobs']['zone:zone-a']
    assert [c['generation'] for c in record['copies']] == ['g2', 'g3']
    assert record['copies'][-1]['path'] == f'{dest}/zones/zone-a/g3' and record['copies'][-1]['bytes'] == len(b'dump 3')
    assert backups.Destination(s).copies() == {'zones/zone-a': ['g2', 'g3']}
    assert list((dest / 'staging').rglob('*.partial')) == []


def test_job_folders_put_zones_below_zones_and_refuse_paths():
    backups = backups_module()
    assert backups.job_folder('platform') == 'platform'
    assert backups.job_folder('zone:platform') == 'zones/platform'
    assert backups.job_folder('opendesk:zone-a') == 'zones/zone-a'
    assert backups.job_folder('hoover:zone-a:enron') == 'zones/zone-a/collections/enron'
    for key in ('zone:/etc', 'zone:..', 'zone:a/b', 'hoover:zone-a:../x', 'zone:.hidden', 'files:/tmp'):
        with pytest.raises(SystemExit):
            backups.job_folder(key)
    for generation in ('/tmp/x', '..', 'a/../b', ''):
        with pytest.raises(SystemExit):
            backups.name_arg(generation, 'generation')


def test_the_earlier_opendesk_job_key_reads_as_the_zone_job(local_destination, tmp_path, monkeypatch):
    backups, s, _ = local_destination
    path = tmp_path / 'state.json'
    monkeypatch.setattr(backups, 'state_path', lambda site: path)
    path.write_text(json.dumps({'jobs': {'opendesk:zone-a': {'copies': [{'generation': 'week-1'}]}}, 'blocked': [],
                                'paused': ''}))
    assert backups.load_state(s)['jobs'] == {'zone:zone-a': {'copies': [{'generation': 'week-1'}]}}


def test_restore_commands_refuse_host_paths(local_destination):
    backups, _, _ = local_destination
    for argv in (['restore-zone', '/tmp/copy', 'zone-a'], ['restore-zone', 'zone-a', '../week-1'],
                 ['restore-hoover', 'zone-a', 'enron', '/x'], ['verify', 'zone:zone-a', '/srv/copy'],
                 ['restore-zone', 'zone-a', 'week-1', '--from', '../zone-b']):
        with pytest.raises(SystemExit):
            backups.main(argv)


def test_the_recovery_set_names_etcd_and_reads_the_earlier_format(tmp_path):
    backups = backups_module()
    current = tmp_path / 'current'
    current.mkdir()
    (current / 'recovery.json').write_text(json.dumps({'format': backups.RECOVERY_FORMAT, 'format_version': 2,
                                                        'datastore': 'etcd', 'snapshot': 'etcd/hoover4-platform-x',
                                                        'token': 'etcd/token', 'private': 'private.tar'}))
    assert backups.read_recovery(current)['datastore'] == 'etcd'
    steps = backups.platform_steps(current, 'week-1')
    assert any('sudo python3 - restore restore-week-1 < ' in step and 'k3s-datastore.py' in step for step in steps)
    assert not any('--token-file' in step for step in steps)
    earlier = tmp_path / 'earlier'
    earlier.mkdir()
    (earlier / 'k3s-state.db').write_bytes(b'sqlite')
    assert backups.read_recovery(earlier)['datastore'] == 'sqlite'
    assert 'convert it to etcd' in backups.platform_steps(earlier, 'week-0')[0]
    (current / 'recovery.json').write_text(json.dumps({'format': backups.RECOVERY_FORMAT, 'format_version': 4}))
    with pytest.raises(SystemExit, match='does not read'):
        backups.read_recovery(current)
    assert 'staging/tokens' not in backups.PRIVATE_EXCLUDED and 'build' in backups.PRIVATE_EXCLUDED


def test_the_zone_closure_records_and_restores_replicas_and_cronjobs(local_destination, monkeypatch):
    backups, s, _ = local_destination
    objects = {
        'zone-a': [{'kind': 'Deployment', 'metadata': {'name': 'nextcloud'}, 'spec': {'replicas': 2}},
                   {'kind': 'StatefulSet', 'metadata': {'name': 'postgresql'}, 'spec': {'replicas': 1}},
                   {'kind': 'Deployment', 'metadata': {'name': 'zone-a-gate'}, 'spec': {'replicas': 1}},
                   {'kind': 'CronJob', 'metadata': {'name': 'cleanup'}, 'spec': {'suspend': False}},
                   {'kind': 'CronJob', 'metadata': {'name': 'paused'}, 'spec': {'suspend': True}}],
        'hoover-zone-a': [{'kind': 'StatefulSet', 'metadata': {'name': 'hoover-workers'}, 'spec': {'replicas': 3}},
                          {'kind': 'StatefulSet', 'metadata': {'name': 'clickhouse'}, 'spec': {'replicas': 1}}]}
    calls = []

    def kubectl(*args, input=None, check=True, stdout=None):
        calls.append(args)
        if 'deployments,statefulsets,cronjobs' in args:
            return json.dumps({'items': objects[args[1]]})
        return '0' if 'jsonpath={.status.replicas}' in args else ''
    monkeypatch.setattr(backups, 'kubectl', kubectl)
    closed = backups.close_zone(s, 'zone-a')
    assert closed['workloads'] == {'zone-a/deployment/nextcloud': 2, 'zone-a/deployment/zone-a-gate': 1,
                                   'hoover-zone-a/statefulset/hoover-workers': 3}
    assert closed['cronjobs'] == {'zone-a/cleanup': False, 'zone-a/paused': True}
    backups.apply_closure(closed)
    scaled = [a for a in calls if 'scale' in a]
    assert ('-n', 'zone-a', 'scale', 'deployment', 'nextcloud', '--replicas=0') in scaled
    assert not [a for a in scaled if 'postgresql' in a or 'clickhouse' in a]
    calls.clear()
    backups.reopen(closed)
    assert ('-n', 'hoover-zone-a', 'scale', 'statefulset', 'hoover-workers', '--replicas=3') in calls
    patches = {a[4]: a[-1] for a in calls if 'patch' in a}
    assert json.loads(patches['paused']) == {'spec': {'suspend': True}}
    assert json.loads(patches['cleanup']) == {'spec': {'suspend': False}}


def tar_bytes(members, pad=True):
    """A tar archive of (name, data) members. pad=False keeps only the two zero end blocks, as busybox tar writes."""
    import io
    import tarfile
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w', format=tarfile.GNU_FORMAT) as archive:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        end = archive.offset
    data = raw.getvalue()
    return (data if pad else data[:end + 1024]), end


def test_an_incomplete_tar_file_is_detected(tmp_path):
    import os
    backups = backups_module()
    members = [('./empty', b''), ('./block', os.urandom(512)), ('./odd', os.urandom(1000)), ('./zeros', bytes(1024)),
               ('./large', os.urandom(100000)), ('./tail-zeros', bytes(10240))]
    for pad in (True, False):
        data, end = tar_bytes(members, pad=pad)
        whole = tmp_path / 'whole.tar'
        whole.write_bytes(data)
        assert backups.tar_complete(whole)
        cut = tmp_path / 'cut.tar'
        # Every block boundary, which includes every member boundary, and offsets inside blocks.
        offsets = sorted(set(range(0, len(data), 512)) | set(range(1, len(data), 333)))
        accepted = []
        for offset in offsets:
            cut.write_bytes(data[:offset])
            if backups.tar_complete(cut):
                accepted.append(offset)
        # A cut file passes only when it keeps every member and the two zero end blocks, so only a cut in the padding
        # after the end blocks passes, and it loses no data.
        assert all(offset >= end + 1024 and offset % 512 == 0 for offset in accepted), accepted[:5]
        assert len(offsets) > 200


def test_a_stream_is_unpacked_only_after_its_tar_file_is_complete(tmp_path, monkeypatch):
    backups = backups_module()
    data, end = tar_bytes([('./a', b'first'), ('./b', b'second')])
    streams = [data[:end], data]
    written = []

    def run(argv, stdout=None, **kw):
        if argv[0] == 'kubectl':
            stdout.write(streams[len(written)])
            written.append(argv)
            return backups.subprocess.CompletedProcess(argv, 0)
        return real_run(argv, **kw)
    real_run = backups.subprocess.run
    monkeypatch.setattr(backups.subprocess, 'run', run)
    target = tmp_path / 'export'
    backups.stream_out('ns', 'pod', None, '/backups/x', target)
    # The first stream ended between two members, so the copy ran again before the unpack.
    assert len(written) == 2
    assert (target / 'a').read_bytes() == b'first' and (target / 'b').read_bytes() == b'second'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['export']


def test_a_database_dump_without_its_trailer_is_written_again_and_then_refused(tmp_path, monkeypatch):
    backups = backups_module()
    complete = b'CREATE TABLE t;\n--\n-- PostgreSQL database cluster dump complete\n--\n\n'
    outputs = [complete[:20], complete]
    calls = []

    def kubectl(*args, stdout=None, **kw):
        calls.append(args)
        stdout.write(outputs[min(len(calls), len(outputs)) - 1])
    monkeypatch.setattr(backups, 'kubectl', kubectl)
    target = tmp_path / 'postgresql.sql'
    backups.dump_out('zone-a', ['postgresql-0', '--', 'pg_dumpall'], target)
    assert len(calls) == 2 and backups.dump_complete(target)
    outputs[:] = [complete[:20]]
    calls.clear()
    with pytest.raises(SystemExit, match='incomplete after three attempts'):
        backups.dump_out('zone-a', ['postgresql-0', '--', 'pg_dumpall'], target)
    assert len(calls) == 3
    maria = tmp_path / 'mariadb.sql'
    maria.write_bytes(b'INSERT 1;\n-- Dump completed on 2026-11-14  0:52:04\n')
    assert backups.dump_complete(maria)
    maria.write_bytes(b'INSERT 1;\n')
    assert not backups.dump_complete(maria)


def fake_kubectl(tmp_path, monkeypatch, status):
    """A kubectl on PATH that saves its arguments and its input and ends with status. The input stays open
    (../podexec.py), so the fake reads the byte count that follows the wrapper name podexec, as the wrapper does."""
    import os
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    script = bin_dir / 'kubectl'
    script.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {tmp_path}/argv\n'
                      'size=$(sed -n "/^podexec$/{n;p;}" ' f'{tmp_path}/argv)\nhead -c "$size" > {tmp_path}/input\n'
                      f'echo "psql:<stdin>:3: ERROR:  example failure" >&2\nexit {status}\n')
    script.chmod(0o755)
    monkeypatch.setenv('PATH', f'{bin_dir}{os.pathsep}{os.environ["PATH"]}')


def test_the_postgresql_import_stops_at_the_first_error_and_skips_the_current_user(tmp_path, monkeypatch):
    backups = backups_module()
    dump = tmp_path / 'postgresql.sql'
    dump.write_bytes(b'DROP DATABASE IF EXISTS app;\nDROP ROLE IF EXISTS app;\nDROP ROLE IF EXISTS postgres;\n'
                     b'CREATE ROLE app;\nCREATE ROLE postgres;\nALTER ROLE postgres WITH SUPERUSER;\n')
    fake_kubectl(tmp_path, monkeypatch, 0)
    backups.import_dump('zone-a', ['postgresql-0', '--', 'psql', '-v', 'ON_ERROR_STOP=1'], dump, backups.POSTGRES_SKIPPED)
    assert (tmp_path / 'input').read_bytes() == (b'DROP DATABASE IF EXISTS app;\nDROP ROLE IF EXISTS app;\n'
                                                 b'CREATE ROLE app;\nALTER ROLE postgres WITH SUPERUSER;\n')
    (tmp_path / 'bin' / 'kubectl').unlink()
    (tmp_path / 'bin').rmdir()
    fake_kubectl(tmp_path, monkeypatch, 3)
    with pytest.raises(SystemExit, match='failed with status 3: psql:<stdin>:3: ERROR:  example failure'):
        backups.import_dump('zone-a', ['postgresql-0', '--', 'psql'], dump, backups.POSTGRES_SKIPPED)


def test_the_restore_runs_psql_with_on_error_stop(tmp_path, monkeypatch):
    backups = backups_module()
    (tmp_path / 'postgresql.sql').write_bytes(b'SELECT 1;\n')
    imports = []
    monkeypatch.setattr(backups, 'import_dump', lambda zone, args, path, skipped=frozenset(): imports.append(args))
    monkeypatch.setattr(backups, 'kubectl', lambda *args, **kw: '')
    backups.restore_databases(tmp_path, 'zone-a')
    assert 'ON_ERROR_STOP=1' in imports[0] and 'ON_ERROR_STOP=0' not in imports[0]


def test_a_restore_reads_the_copy_in_place_after_its_check(local_destination):
    backups, s, dest = local_destination
    dest.mkdir()
    target = backups.Destination(s)
    target.enable()
    copy_folder(backups, dest / 'zones/zone-a/g1', {'postgresql.sql': b'dump', 'claims.json': b'[]'})
    assert backups.fetched(s, 'zone:zone-a', 'g1') == dest / 'zones/zone-a/g1'
    (dest / 'zones/zone-a/g1/postgresql.sql').write_bytes(b'damaged')
    with pytest.raises(SystemExit, match='differs from its manifest'):
        backups.fetched(s, 'zone:zone-a', 'g1')
    with pytest.raises(SystemExit, match='does not exist'):
        backups.fetched(s, 'zone:zone-a', 'g2')


def test_a_restored_secret_keeps_the_items_that_the_copy_lacks(tmp_path, monkeypatch):
    backups = backups_module()
    (tmp_path / 'objects.json').write_text(json.dumps({'items': [
        {'kind': 'Secret', 'type': 'Opaque', 'metadata': {'name': 'hoover-runtime'}, 'data': {'a': 'Y29weQ=='}}]}))
    applied = []

    def kubectl(*args, input=None, check=True, stdout=None):
        if 'get' in args:
            return json.dumps({'data': {'a': 'b2xk', 'gpu-token': 'dG9rZW4='}})
        applied.append(json.loads(input))
        return ''
    monkeypatch.setattr(backups, 'kubectl', kubectl)
    backups.restore_secrets(tmp_path, 'hoover-zone-a')
    assert applied[0]['data'] == {'a': 'Y29weQ==', 'gpu-token': 'dG9rZW4='}


def test_the_local_retirement_uses_the_tar_check_of_the_backups():
    import importlib.util
    spec = importlib.util.spec_from_file_location('local_retirement', K3S / 'tools/local-retirement.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.tar_complete.__code__.co_filename == str(K3S / 'platform/backups/backups.py')


# The zone databases and the system bucket of a site zone ---------------------------------------------------------------

def shared_stores_fakes(backups, monkeypatch, tmp_path, databases=('zone_a', 'zone_a_Processing'), fail=None):
    """Fake ClickHouse and Garage client for copy_shared_stores() and restore_shared_stores()."""
    import contextlib
    import io
    import tarfile
    sys.path.insert(0, str(K3S / 'hoover' / 'stores'))
    import garage_client
    calls = []

    def clickhouse(hoover, sql):
        calls.append(('sql', sql))
        if sql.startswith('SELECT name FROM system.databases'):
            return ''.join(json.dumps({'name': n}) + '\n' for n in databases)
        if fail and sql.startswith(fail):
            raise SystemExit(f"kubectl exec failed: Code: 36. (query: {sql})")
        if sql.startswith('BACKUP'):
            return json.dumps({'id': 'x', 'status': 'BACKUP_CREATED'}) + '\n'
        if sql.startswith('RESTORE'):
            return json.dumps({'id': 'x', 'status': 'RESTORED'}) + '\n'
        return ''

    def tar_of(members):
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode='w') as archive:
            for name, data in members:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return raw.getvalue()

    def run(pod, key, command, *args, data=None, out=None):
        calls.append(('s3', key['access_key'], command, *args))
        if command == 'get':
            payload = tar_of([('metadata/zone_a.sql', b'ATTACH DATABASE')])
            open(out, 'wb').write(payload)
            return None, [{'bytes': len(payload)}]
        if command == 'tar':
            open(out, 'wb').write(tar_of([('a/b', b'one'), ('c', b'two')]))
            return None, [{'objects': 2}]
        return '', []
    monkeypatch.setattr(backups, 'clickhouse', clickhouse)

    @contextlib.contextmanager
    def garage_s3(hoover, key):
        yield lambda command, *args, data=None, out=None: run('backup-s3', key, command, *args, data=data, out=out)
    monkeypatch.setattr(backups, 'garage_s3', garage_s3)
    monkeypatch.setattr(garage_client, 'zone_key', lambda zone: {'access_key': f'GK-{zone}', 'secret_key': 'very-secret'})
    return calls


def site_hoover(zone='zone-a'):
    return config.Hoover(zone=zone, stores='site', temporal='site', manticore='site')


def test_the_zone_copy_holds_the_zone_databases_and_the_system_bucket(tmp_path, monkeypatch):
    backups = backups_module()
    calls = shared_stores_fakes(backups, monkeypatch, tmp_path)
    info = backups.copy_shared_stores(site_hoover(), tmp_path / 'shared')
    sql = [c[1] for c in calls if c[0] == 'sql']
    assert sql[1].startswith("BACKUP DATABASE `zone_a`, DATABASE `zone_a_Processing` TO "
                             "S3('http://garage.hoover-stores.svc.cluster.local:3900/zone-a-exports/zone-backups/")
    assert "'GK-zone-a', 'very-secret')" in sql[1] and "SETTINGS id='zone_a-zone-" in sql[1]
    s3 = [c[2:] for c in calls if c[0] == 's3']
    key = s3[0][2]
    assert s3 == [('get', 'zone-a-exports', key), ('delete', 'zone-a-exports', key), ('tar', 'zone-a-system')]
    assert info['databases'] == ['zone_a', 'zone_a_Processing'] and info['system_objects'] == 2
    assert json.loads((tmp_path / 'shared' / 'stores.json').read_text()) == info
    assert (tmp_path / 'shared' / 'clickhouse.tar').exists() and (tmp_path / 'shared' / 'system-bucket.tar').exists()


def test_a_failed_zone_backup_removes_its_object_and_shows_no_key(tmp_path, monkeypatch):
    backups = backups_module()
    calls = shared_stores_fakes(backups, monkeypatch, tmp_path, fail='BACKUP')
    with pytest.raises(SystemExit) as error:
        backups.copy_shared_stores(site_hoover(), tmp_path / 'shared')
    assert 'very-secret' not in str(error.value) and '[HIDDEN]' in str(error.value)
    assert [c[2] for c in calls if c[0] == 's3'] == ['delete']


def test_a_zone_without_its_databases_copies_only_the_system_bucket(tmp_path, monkeypatch):
    backups = backups_module()
    calls = shared_stores_fakes(backups, monkeypatch, tmp_path, databases=('zone_a_Processing',))
    info = backups.copy_shared_stores(site_hoover(), tmp_path / 'shared')
    assert info['databases'] == ['zone_a_Processing']
    calls[:] = []
    shared_stores_fakes(backups, monkeypatch, tmp_path, databases=())
    assert backups.copy_shared_stores(site_hoover(), tmp_path / 'empty')['databases'] == []
    assert not (tmp_path / 'empty' / 'clickhouse.tar').exists()


def test_the_zone_restore_replaces_the_databases_under_the_prefix_of_the_target(tmp_path, monkeypatch):
    backups = backups_module()
    shared_stores_fakes(backups, monkeypatch, tmp_path)
    backups.copy_shared_stores(site_hoover('zone-a'), tmp_path / 'shared')
    calls = shared_stores_fakes(backups, monkeypatch, tmp_path)
    backups.restore_shared_stores(tmp_path / 'shared', site_hoover('zone-b'))
    sql = [c[1] for c in calls if c[0] == 'sql']
    assert sql[:2] == ['DROP DATABASE IF EXISTS `zone_b` SYNC', 'DROP DATABASE IF EXISTS `zone_b_Processing` SYNC']
    assert sql[2].startswith("RESTORE DATABASE `zone_a` AS `zone_b`, DATABASE `zone_a_Processing` AS `zone_b_Processing` FROM "
                             "S3('http://garage.hoover-stores.svc.cluster.local:3900/zone-b-exports/imports/zone-restore-")
    s3 = [c[1:] for c in calls if c[0] == 's3']
    key = s3[0][3]
    assert s3 == [('GK-zone-b', 'put', 'zone-b-exports', key, s3[0][4]), ('GK-zone-b', 'delete', 'zone-b-exports', key),
                  ('GK-zone-b', 'empty', 'zone-b-system'), ('GK-zone-b', 'untar', 'zone-b-system')]


def test_the_zone_job_copies_the_shared_stores_of_a_site_zone_only(tmp_path, monkeypatch):
    backups = backups_module()
    hoovers = {'zone-a': site_hoover('zone-a'), 'zone-c': config.Hoover(zone='zone-c', stores='local')}
    monkeypatch.setattr(backups.site_config, 'hoovers', lambda _s: hoovers)
    monkeypatch.setattr(backups, 'close_zone', lambda s, zone: {'namespaces': [], 'workloads': {'zone-a/deployment/x': 1}, 'cronjobs': {}})
    copied = []
    monkeypatch.setattr(backups, 'copy_namespace', lambda ns, partial, moments, label='': copied.append(ns))
    monkeypatch.setattr(backups, 'copy_shared_stores', lambda hoover, target: copied.append(str(target.relative_to(tmp_path))))
    backups.run_zone(None, 'zone-a', tmp_path / 'a')
    backups.run_zone(None, 'zone-c', tmp_path / 'c')
    assert copied == ['zone-a', 'hoover-zone-a', 'a/hoover/zone-a/shared', 'zone-c', 'hoover-zone-c']
    assert json.loads((tmp_path / 'a' / 'workloads.json').read_text())['workloads'] == {'zone-a/deployment/x': 1}
    moments = json.loads((tmp_path / 'a' / 'moments.json').read_text())
    assert moments['online'] is True and list(moments['parts']) == ['hoover/zone-a/shared']


def test_the_zone_job_stops_no_workload(tmp_path, monkeypatch):
    backups = backups_module()
    monkeypatch.setattr(backups.site_config, 'hoovers', lambda _s: {'zone-a': site_hoover('zone-a')})
    calls = []

    def kubectl(*args, input=None, check=True, stdout=None):
        calls.append(args)
        if 'deployments,statefulsets,cronjobs' in args:
            return json.dumps({'items': [{'kind': 'Deployment', 'metadata': {'name': 'nextcloud'}, 'spec': {'replicas': 1}}]})
        return ''
    monkeypatch.setattr(backups, 'kubectl', kubectl)
    monkeypatch.setattr(backups, 'copy_namespace', lambda ns, partial, moments, label='': None)
    monkeypatch.setattr(backups, 'copy_shared_stores', lambda hoover, target: None)
    backups.run_zone(None, 'zone-a', tmp_path / 'a', key='zone:zone-a')
    assert not [a for a in calls if 'scale' in a or 'patch' in a]


def namespace_objects(store=True):
    pods = [{'metadata': {'name': 'postgresql-0', 'labels': {}}, 'status': {'phase': 'Running'}, 'spec': {}},
            {'metadata': {'name': 'seaweedfs-1', 'labels': {'hoover.dev/store': 'seaweedfs', 'app': 's'}},
             'status': {'phase': 'Running' if store else 'Pending'},
             'spec': {'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'seaweedfs-data'}}]}}]
    claims = [{'metadata': {'name': n, 'annotations': {}}, 'spec': {'volumeMode': 'Filesystem', 'resources': {'requests': {'storage': '1Gi'}}}}
              for n in ('seaweedfs-data', 'shared-data-ldap-0', 'data-postgresql-0')]
    services = [{'metadata': {'name': 'other'}, 'spec': {'selector': {'app': 's'}, 'ports': [{'port': 80}]}},
                {'metadata': {'name': 'seaweedfs'}, 'spec': {'selector': {'app': 's'}, 'ports': [{'port': 8333}]}}]
    return pods, claims, services


def test_the_online_copy_reads_the_databases_first_and_the_object_store_through_s3(tmp_path, monkeypatch):
    backups = backups_module()
    pods, claims, services = namespace_objects()
    order = []

    def kubectl(*args, input=None, check=True, stdout=None):
        if args[-3:] == ('pods', '-o', 'json'):
            return json.dumps({'items': pods})
        if args[-3:] == ('pvc', '-o', 'json'):
            return json.dumps({'items': claims})
        if args[-3:] == ('services', '-o', 'json'):
            return json.dumps({'items': services})
        return '{"items": []}'
    monkeypatch.setattr(backups, 'kubectl', kubectl)
    monkeypatch.setattr(backups, 'dump_out', lambda ns, args, target: order.append(target.name))
    monkeypatch.setattr(backups, 'helper_pod', lambda ns, claim, node: f'reader-{claim}')
    monkeypatch.setattr(backups, 'tar_out', lambda ns, pod, c, folder, target, tar=('tar',), settled=None:
                        order.append((target.name, settled is not None)))
    monkeypatch.setattr(backups, 'copy_objects', lambda ns, store, target: order.append(('objects', store['endpoint'])))
    moments = backups.Moments()
    backups.copy_namespace('zone-a', tmp_path, moments)
    assert order == ['postgresql.sql', ('shared-data-ldap-0.tar', True),
                     ('objects', 'seaweedfs.zone-a.svc.cluster.local:8333')]
    assert [r['claim'] for r in json.loads((tmp_path / 'claims.json').read_text())] == ['shared-data-ldap-0']
    assert list(moments.parts) == ['postgresql.sql', 'claims/', 'objects/']


def test_a_claim_is_read_again_while_its_lmdb_meta_pages_change(tmp_path, monkeypatch):
    backups = backups_module()
    data, _ = tar_bytes([('a', b'x')])
    monkeypatch.setattr(backups, 'tar_command', lambda *a: ['sh', '-c', 'cat "$0"', str(tmp_path / 'src.tar')])
    (tmp_path / 'src.tar').write_bytes(data)
    values = iter(['1', '2', '2', '2'])
    backups.tar_out('zone-a', 'pod', None, '/data', tmp_path / 'out.tar', settled=lambda: next(values))
    assert next(values, 'none') == 'none'
    changing = iter(range(10))
    with pytest.raises(SystemExit, match='changed during the read'):
        backups.tar_out('zone-a', 'pod', None, '/data', tmp_path / 'out.tar', settled=lambda: next(changing))


def test_the_object_store_key_uses_the_admin_identity_and_the_customer_keys(monkeypatch):
    import base64
    backups = backups_module()
    config = {'identities': [{'name': 'nextcloud', 'credentials': [{'accessKey': 'n', 'secretKey': 'ns'}]},
                             {'name': 'admin', 'credentials': [{'accessKey': 'a', 'secretKey': 'as'}]}]}
    secrets = {('seaweedfs-config', 'seaweedfs_s3_config'): json.dumps(config).encode(),
               ('synapse-s3-encryption-customer-key', 's3EncryptionCustomerKey'): b'k' * 32}
    monkeypatch.setattr(backups, 'secret_item', lambda ns, name, item: secrets.get((name, item), b''))
    first = backups.object_store_key('zone-a', {'endpoint': 'e:8333'})
    assert first == {'endpoint': 'e:8333', 'access_key': 'a', 'secret_key': 'as',
                     'sse_c': {'synapse': base64.b64encode(b'k' * 32).decode()}}
    secrets[('synapse-s3-encryption-customer-key', 's3EncryptionCustomerKey')] = b''
    assert backups.object_store_key('zone-a', {'endpoint': 'e:8333'})['sse_c'] == {}


def test_the_restore_of_an_online_copy_puts_the_objects_and_reads_its_replicas(tmp_path, monkeypatch):
    backups = backups_module()
    (tmp_path / 'objects').mkdir()
    (tmp_path / 'objects' / 'buckets.json').write_text(json.dumps([{'bucket': 'nextcloud', 'objects': 2}]))
    pods, _, services = namespace_objects()
    ran = []

    def kubectl(*args, input=None, check=True, stdout=None):
        if args[-3:] == ('pods', '-o', 'json'):
            return json.dumps({'items': pods})
        if args[-3:] == ('services', '-o', 'json'):
            return json.dumps({'items': services})
        return ''
    monkeypatch.setattr(backups, 'kubectl', kubectl)
    monkeypatch.setattr(backups, 'object_store_key', lambda ns, store: {'secret_key': 's'})
    monkeypatch.setattr(backups, 's3_pod', lambda ns: 'backup-s3')
    monkeypatch.setattr(backups, 's3_run', lambda ns, pod, first, *args, data=None, out=None: ran.append(args) or ('', []))
    backups.restore_objects(tmp_path, 'zone-a')
    assert ran == [('mkbucket', 'nextcloud'), ('empty', 'nextcloud'), ('untar', 'nextcloud')]
    pods[1]['status']['phase'] = 'Pending'
    with pytest.raises(SystemExit, match='no running object store'):
        backups.restore_objects(tmp_path, 'zone-a')


def test_a_restored_site_zone_keeps_its_own_tenant_credentials(tmp_path, monkeypatch):
    backups = backups_module()
    (tmp_path / 'objects.json').write_text(json.dumps({'items': [
        {'kind': 'Secret', 'type': 'Opaque', 'metadata': {'name': 'hoover-runtime'},
         'data': {'clickhouse-worker': 'b2xk', 'temporal-api-key': 'b2xk', 'proxy-secret': 'Y29weQ=='}},
        {'kind': 'Secret', 'type': 'Opaque', 'metadata': {'name': 'manticore-schema'}, 'data': {'password': 'b2xk'}},
        {'kind': 'Secret', 'type': 'Opaque', 'metadata': {'name': 'oauth2-proxy'}, 'data': {'proxy-secret': 'Y29weQ=='}}]}))
    applied = []

    def kubectl(*args, input=None, check=True, stdout=None):
        if 'get' in args:
            return json.dumps({'data': {'clickhouse-worker': 'bmV3', 'temporal-api-key': 'bmV3'}})
        applied.append(json.loads(input))
        return ''
    monkeypatch.setattr(backups, 'kubectl', kubectl)
    backups.restore_secrets(tmp_path, 'hoover-zone-a', backups.TENANT_SECRETS)
    assert [a['metadata']['name'] for a in applied] == ['hoover-runtime', 'oauth2-proxy']
    assert applied[0]['data'] == {'clickhouse-worker': 'bmV3', 'temporal-api-key': 'bmV3', 'proxy-secret': 'Y29weQ=='}


def test_a_file_system_claim_is_read_in_the_running_pod_that_mounts_it(monkeypatch):
    backups = backups_module()
    pods = [{'metadata': {'name': 'xwiki-0'}, 'status': {'phase': 'Running'},
             'spec': {'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'xwiki-data'}}],
                      'containers': [{'name': 'xwiki', 'volumeMounts': [{'name': 'data', 'mountPath': '/usr/local/xwiki'}]}]}}]
    answers = {'xwiki': 'yes\n'}
    monkeypatch.setattr(backups, 'kubectl', lambda *a, input=None, check=True, stdout=None: answers.get(a[a.index('-c') + 1], ''))
    assert backups.mount_source('zone-a', 'xwiki-data', pods) == ('xwiki-0', 'xwiki', '/usr/local/xwiki')
    assert backups.mount_source('zone-a', 'other', pods) is None
    answers['xwiki'] = ''
    assert backups.mount_source('zone-a', 'xwiki-data', pods) is None


def test_gnu_tar_may_report_a_changed_file_of_a_running_application():
    backups = backups_module()
    assert backups.tar_status_ok(0, b'')
    assert backups.tar_status_ok(1, b'tar: ./log/x.log: file changed as we read it\ntar: Exiting with failure status due to previous errors\n')
    assert not backups.tar_status_ok(1, b'')
    assert not backups.tar_status_ok(1, b'tar: ./a: File shrank by 10 bytes; padding with zeros\n')
    assert not backups.tar_status_ok(2, b'tar: ./log/x.log: file changed as we read it\n')


def test_the_s3_client_reads_and_writes_an_object_with_a_customer_key(tmp_path):
    import base64
    import http.server
    import subprocess
    import threading
    sys.path.insert(0, str(K3S / 'hoover' / 'stores'))
    import garage_client
    key = base64.b64encode(b'k' * 32).decode()
    stored, puts = {'plain': b'one', 'locked': b'two'}, []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, body=b''):
            self.send_response(code)
            self.send_header('content-length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if '?' in self.path:
                items = ''.join(f'<Contents><Key>{k}</Key><Size>{len(v)}</Size></Contents>' for k, v in stored.items())
                return self.reply(200, f'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">{items}'
                                       '<IsTruncated>false</IsTruncated></ListBucketResult>'.encode())
            name = self.path.rsplit('/', 1)[1]
            given = self.headers.get('x-amz-server-side-encryption-customer-key')
            if name == 'locked' and given != key:
                return self.reply(400)
            self.reply(200, stored[name])

        def do_PUT(self):
            body = self.rfile.read(int(self.headers['content-length']))
            puts.append((self.path, body, self.headers.get('x-amz-server-side-encryption-customer-key')))
            self.reply(200)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    first = json.dumps({'endpoint': f'127.0.0.1:{server.server_port}', 'access_key': 'a', 'secret_key': 's',
                        'sse_c': {'synapse': key}}).encode() + b'\n'
    try:
        tar = subprocess.run([sys.executable, '-I', '-c', garage_client.SCRIPT, 'tar', 'synapse'], input=first,
                             capture_output=True, check=True)
        assert json.loads(tar.stderr.decode().strip().splitlines()[-1]) == {'bucket': 'synapse', 'objects': 2, 'customer_key_objects': 1}
        subprocess.run([sys.executable, '-I', '-c', garage_client.SCRIPT, 'untar', 'synapse'], input=first + tar.stdout,
                       capture_output=True, check=True)
    finally:
        server.shutdown()
    assert sorted(puts) == [('/synapse/locked', b'two', key), ('/synapse/plain', b'one', None)]


def test_the_newest_scheduled_snapshot_is_chosen_and_an_old_one_stops_the_job():
    backups = backups_module()
    names = ['etcd-snapshot-cp-1-1799990000', 'etcd-snapshot-cp-1-1799950000', 'etcd-snapshot-cp-1-1799999000.part',
             'on-demand-cp-1-1799999500', 'etcd-snapshot-cp-1-1799960000.zip', 'notes.txt']
    assert backups.newest_snapshot(names, 1800000000) == ('etcd-snapshot-cp-1-1799990000', 1799990000)
    with pytest.raises(SystemExit, match=r'is 25\.0 hours old, and the limit is 24 hours'):
        backups.newest_snapshot(['etcd-snapshot-cp-1-1799910000'], 1800000000)
    with pytest.raises(SystemExit, match='has no scheduled etcd snapshot'):
        backups.newest_snapshot(['on-demand-cp-1-1799999500', 'etcd-snapshot-cp-1-1799999000.part'], 1800000000)


def runner_rights():
    import yaml
    return list(yaml.safe_load_all((K3S / 'platform/operator/runner-rights.yaml').read_text()))


def test_the_reader_pod_has_the_form_that_the_policy_admits():
    backups = backups_module()
    pod = backups.snapshot_reader('cp-1')
    spec = pod['spec']
    assert pod['metadata']['namespace'] == backups.READER_NAMESPACE == 'platform-backup'
    assert spec['nodeSelector'] == {'kubernetes.io/hostname': 'cp-1'}
    assert spec['serviceAccountName'] == backups.READER_ACCOUNT and spec['automountServiceAccountToken'] is False
    assert {v['hostPath']['path'] for v in spec['volumes']} == {backups.SNAPSHOT_DIR, backups.TOKEN_FILE, backups.K3S_CONFIG}
    [container] = spec['containers']
    assert all(m['readOnly'] for m in container['volumeMounts'])
    assert container['securityContext']['capabilities'] == {'drop': ['ALL']}
    assert container['securityContext']['allowPrivilegeEscalation'] is False
    assert not any(spec.get(k) for k in ('hostNetwork', 'hostPID', 'hostIPC'))
    docs = runner_rights()
    policy = next(d for d in docs if d['kind'] == 'ValidatingAdmissionPolicy' and d['metadata']['name'] == 'k3s-snapshot-reader')
    text = json.dumps(policy)
    assert container['image'] == backups.HELPER_IMAGE and backups.HELPER_IMAGE in text
    paths = next(v['expression'] for v in policy['spec']['variables'] if v['name'] == 'paths')
    assert all(f"'{p}'" in paths for p in (backups.SNAPSHOT_DIR, backups.TOKEN_FILE, backups.K3S_CONFIG))
    assert policy['spec']['matchConditions'][0]['expression'] == "request.namespace == 'platform-backup'"
    account = next(d for d in docs if d['kind'] == 'ServiceAccount' and d['metadata']['name'] == backups.READER_ACCOUNT)
    assert account['automountServiceAccountToken'] is False
    assert not any(d['kind'] in ('RoleBinding', 'ClusterRoleBinding') and any(
        s.get('name') == backups.READER_ACCOUNT for s in d.get('subjects') or []) for d in docs)
    role = next(d for d in docs if d['kind'] == 'Role' and d['metadata']['namespace'] == 'platform-backup')
    assert {r for rule in role['rules'] for r in rule['resources']} == {'pods', 'pods/exec'}
    assert 'platform-backup' in (K3S / 'platform/operator/install-runner.sh').read_text()


def fake_reader(backups, tmp_path, monkeypatch, name, changed=False):
    """The reader pod as fake kubectl calls, and a tar stream of its three files. Return the list of calls."""
    import hashlib
    files = {f'snapshots/{name}': b'etcd-data', 'token': b'K10::server:secret', 'config.yaml': b'cluster-init: true\n'}
    calls = []

    def kubectl(*args, input=None, check=True, stdout=None):
        calls.append(args)
        if 'ls' in args:
            return f'{name}\netcd-snapshot-cp-1-1700000000\n'
        if 'sha256sum' in args:
            return ''.join(f'{hashlib.sha256(files[m]).hexdigest()}  {backups.READER_ROOT}/{m}\n' for m in files)
        if args[:2] == ('get', 'node'):
            return 'v1.36.5+k3s1'
        return ''

    def tar_out(ns, pod, container, folder, target, members=('.',), changed_ok=True, **kw):
        calls.append(('tar', ns, pod, folder, tuple(members), changed_ok))
        sent = dict(files)
        if changed:
            sent['token'] = b'other'
        target.write_bytes(tar_bytes(sorted(sent.items()))[0])
    monkeypatch.setattr(backups, 'kubectl', kubectl)
    monkeypatch.setattr(backups, 'tar_out', tar_out)
    return calls


def test_the_platform_copy_reads_the_scheduled_snapshot_through_the_reader_pod(local_destination, tmp_path, monkeypatch):
    backups, s, _ = local_destination
    name = 'etcd-snapshot-cp-1-1799990000'
    calls = fake_reader(backups, tmp_path, monkeypatch, name)
    private = tmp_path / 'private'
    (private / 'zones').mkdir(parents=True)
    (private / 'zones' / 'secret.yaml').write_text('x')
    monkeypatch.setattr(backups.k3s_settings, 'PRIVATE', private)
    monkeypatch.setattr(backups, 'state_path', lambda site: tmp_path / 'state.json')
    partial = tmp_path / 'partial'
    backups.run_platform(s, partial, now=1800000000)
    create = next(c for c in calls if c[:1] == ('create',))
    assert create == ('create', '-f', '-')
    assert ('tar', 'platform-backup', 'k3s-snapshot-read', '/k3s', (f'snapshots/{name}', 'token', 'config.yaml'), False) in calls
    # The pod goes away after the read.
    assert calls[-2][-4:] == ('delete', 'pod', 'k3s-snapshot-read', '--wait=false')
    etcd = partial / 'etcd'
    assert sorted(p.name for p in etcd.iterdir()) == sorted(['config.yaml', 'host.json', name, 'token'])
    host = json.loads((etcd / 'host.json').read_text())
    assert host['snapshot'] == name and host['created'] == '2027-01-15T05:13:20Z' and host['k3s_version'] == 'v1.36.5+k3s1'
    assert (etcd / 'token').stat().st_mode & 0o777 == 0o600 and not (partial / 'etcd.stream.tar').exists()
    recovery = backups.read_recovery(partial)
    assert recovery['format_version'] == 3 and recovery['snapshot'] == f'etcd/{name}'
    assert recovery['snapshot_created'] == host['created'] and recovery['route'] == 'reader-pod'
    steps = backups.platform_steps(partial, 'week-9')
    assert 'Copy the folder etcd/ of the copy into ~/hoover4-snapshots/restore-week-9/' in steps[0]
    assert not any('nodeshell' in str(c) or 'ssh' in str(c) for c in calls)


def test_a_snapshot_that_changed_in_the_transfer_stops_the_platform_copy(local_destination, tmp_path, monkeypatch):
    backups, s, _ = local_destination
    calls = fake_reader(backups, tmp_path, monkeypatch, 'etcd-snapshot-cp-1-1799990000', changed=True)
    with pytest.raises(SystemExit, match='token changed in the transfer'):
        backups.run_platform(s, tmp_path / 'partial', now=1800000000)
    assert any(c[-4:] == ('delete', 'pod', 'k3s-snapshot-read', '--wait=false') for c in calls)
    old = fake_reader(backups, tmp_path, monkeypatch, 'etcd-snapshot-cp-1-1799900000')
    with pytest.raises(SystemExit, match='hours old'):
        backups.run_platform(s, tmp_path / 'partial-2', now=1800000000)
    assert not any(c[0] == 'tar' for c in old) and old[-1][-4:] == ('delete', 'pod', 'k3s-snapshot-read', '--wait=false')
