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
