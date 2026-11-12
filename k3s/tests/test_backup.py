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


# The store client, the destination node, the recovery set and the zone closure ---------------------------------------

import config  # noqa: E402
from conftest import site_text  # noqa: E402


def test_the_clickhouse_client_follows_the_store_layout_and_names_no_password():
    backups = backups_module()
    remote = config.parse(site_text('remote.ini'))
    ns, pod, container, command = backups.clickhouse_command(remote.hoovers['zone-a'])
    assert (ns, pod, container) == ('zone-a', 'clickhouse-0', 'clickhouse')
    assert '--user zone_a --password "$CH_ZONE_PASSWORD"' in command
    ns, pod, container, command = backups.clickhouse_command(remote.hoovers['research'])
    assert (ns, pod, container) == ('hoover-zone-c', 'clickhouse-0', None) and '${CLICKHOUSE_PASSWORD:-hoover4}' in command
    calls = []
    backups.kubectl = lambda *args, **kw: calls.append(args) or ''
    backups.clickhouse(remote.hoovers['zone-a'], 'SELECT 1')
    assert calls[0][:8] == ('-n', 'zone-a', 'exec', '-i', 'clickhouse-0', '-c', 'clickhouse', '--')
    assert not any('hoover4' == a for a in calls[0])


@pytest.fixture
def local_destination(tmp_path):
    backups = backups_module()
    dest = tmp_path / 'dest'
    text = site_text('single-node.ini').replace('path = /srv/hoover4-backups', f'path = {dest}')
    s = config.parse(text)
    return backups, s, dest


def copy_folder(backups, folder, files):
    folder.mkdir(parents=True)
    for name, data in files.items():
        (folder / name).write_bytes(data)
    (folder / backups.MANIFEST).write_text(json.dumps({'files': backups.manifest(folder)}))
    return folder


def test_the_destination_node_checks_writes_verifies_and_keeps_older_copies(local_destination, tmp_path):
    backups, s, dest = local_destination
    target = backups.Destination(s)
    assert 'does not exist' in target.problem()
    dest.mkdir()
    assert 'has no .hoover4-backup-destination' in target.problem()
    (dest / schedule.MARKER).write_text('x')
    assert target.problem() == '' and target.free_bytes() > 0
    first = copy_folder(backups, tmp_path / 'one', {'a.sql': b'one'})
    final, checked = target.publish(first, 'zone:zone-a', 'week-1')
    assert final == f'{dest}/zones/zone-a/week-1' and checked['differences'] == []
    assert (dest / 'zones/zone-a/week-1/a.sql').read_bytes() == b'one'
    # A copy that changes in the transfer is refused on the node, and the older copy stays.
    second = copy_folder(backups, tmp_path / 'two', {'a.sql': b'two'})
    (second / 'a.sql').write_bytes(b'changed after the manifest')
    with pytest.raises(SystemExit, match='differs from its manifest'):
        target.publish(second, 'zone:zone-a', 'week-2')
    assert not (dest / 'zones/zone-a/week-2.partial').exists()
    assert (dest / 'zones/zone-a/week-1/a.sql').read_bytes() == b'one'
    assert target.copies() == {'zones/zone-a': ['week-1']}
    assert target.check('zone:zone-a', 'week-1')['differences'] == []
    with pytest.raises(SystemExit, match='outside the backup destination'):
        target.remove('/etc')
    target.remove(final)
    assert not (dest / 'zones/zone-a/week-1').exists()


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
    assert any('--restore-snapshot restore-week-1' in step and '--bundle backup' in step for step in steps)
    assert not any('--token-file' in step for step in steps)
    earlier = tmp_path / 'earlier'
    earlier.mkdir()
    (earlier / 'k3s-state.db').write_bytes(b'sqlite')
    assert backups.read_recovery(earlier)['datastore'] == 'sqlite'
    assert 'convert it to etcd' in backups.platform_steps(earlier, 'week-0')[0]
    (current / 'recovery.json').write_text(json.dumps({'format': backups.RECOVERY_FORMAT, 'format_version': 3}))
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


def test_an_incomplete_tar_file_is_detected(tmp_path):
    import io
    import tarfile
    backups = backups_module()
    good = tmp_path / 'good.tar'
    with tarfile.open(good, 'w') as archive:
        data = b'x' * 100000
        info = tarfile.TarInfo('./file')
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    assert backups.tar_complete(good)
    cut = tmp_path / 'cut.tar'
    cut.write_bytes(good.read_bytes()[:50000])
    assert not backups.tar_complete(cut)


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
