"""Index receipts: the OCR text versions that a committed text-page writer read.

An OCR index target of "Run OCR" is complete only when each current OCR segment has a
receipt of its current version. The receipts come from the rows the writer indexed, never
from a read after the commit, so text written after that read stays open.
"""

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ocr_store_fake import CD, FakeOcrStore
from tasks.ocr_targets import STAGE_INDEX, SettingVersion, Target, settled
from tasks.P_admin.ocr_languages import EXTRACTED_BY_TABLES
from tasks.P6_index_data import activities
from tasks.P6_index_data import shard_planner
from tasks.P6_index_data import workflows as index_workflows
from tasks.P6_index_data.params import (
    IndexDatasetPlanParams, IndexedTextResult, IndexShardParams, RecordIndexedParams,
)

SEGMENTS = [("doc", "ocr_tesseract_eng", 1, 5_300_000_000),
            ("doc", "tika", 1, 4_000_000_000),
            ("img", "ocr_tesseract_eng", 1, 5_400_000_000),
            ("img", "ocr_tesseract_eng", 2, 5_500_000_000)]


class _Arrow:
    def __init__(self, rows):
        self.rows = rows

    def to_pylist(self):
        return self.rows


class _Collection:
    def query(self, sql, parameters=None):
        from types import SimpleNamespace
        assert "FROM vfs_files FINAL" in sql
        return SimpleNamespace(result_rows=[(h,) for h in parameters["h"]])

    def query_arrow(self, sql, _params):
        if "argMax(text_bytes, version)" in sql:
            return _Arrow([{"file_hash": h, "extracted_by": e, "page_id": p, "text_bytes": 10}
                           for h, e, p, _ in SEGMENTS])
        return _Arrow([])


def writer(monkeypatch, fail=False):
    """Run the shared text writer with every store faked. Returns the indexed rows."""
    written = []

    @contextmanager
    def collection(_name):
        yield _Collection()

    def fetch(_client, _cd, batch):
        versions = {(h, e, p): v for h, e, p, v in SEGMENTS}
        return [{"collection_dataset": CD, "file_hash": h, "extracted_by": e, "page_id": p,
                 "text": "words", "text_version": versions[h, e, p]} for h, e, p in batch]

    def write(_client, _table, _cd, rows):
        if fail:
            raise RuntimeError("the transaction failed")
        written.extend(rows)
        return 1, 10

    import database.manticore as manticore

    @contextmanager
    def manticore_client():
        yield object()

    monkeypatch.setattr(activities, "get_collection_client", collection)
    monkeypatch.setattr(activities, "document_metadata", lambda _p: {})
    monkeypatch.setattr(activities, "read_signal_pages", lambda *_a: ({}, {}))
    monkeypatch.setattr(activities, "get_string_term_ids_by_field",
                        lambda _c, _d, fields: {field: {} for field in fields})
    monkeypatch.setattr(activities, "load_calibration", lambda: {"categories": []})
    monkeypatch.setattr(activities, "page_clusters", lambda *_a: [])
    monkeypatch.setattr(activities, "write_clusters", lambda *_a: None)
    monkeypatch.setattr(activities, "remove_old_clusters", lambda *_a: None)
    monkeypatch.setattr(activities, "fetch_text_batch", fetch)
    monkeypatch.setattr(activities, "write_page_batches", write)
    monkeypatch.setattr(activities, "_delete_obsolete_index_pages", lambda *_a: set())
    monkeypatch.setattr(manticore, "get_manticore_client", manticore_client)
    return written


PARAMS = IndexShardParams("c", CD, "plan", "c_1", ["doc", "img"], "op")


def test_the_writer_returns_the_ocr_versions_that_it_indexed(monkeypatch):
    written = writer(monkeypatch)
    result = activities.index_text_pages_with_versions(PARAMS)
    assert result.committed_hashes == ["doc", "img"]
    assert result.ocr_text_versions == [
        ("doc", "ocr_tesseract_eng", 1, 5_300_000_000),
        ("img", "ocr_tesseract_eng", 1, 5_400_000_000),
        ("img", "ocr_tesseract_eng", 2, 5_500_000_000)]
    assert {row["extracted_by"] for row in written} == {"ocr_tesseract_eng", "tika"}


def test_the_earlier_activity_keeps_its_result(monkeypatch):
    writer(monkeypatch)
    assert activities.index_text_pages(PARAMS) == ["doc", "img"]


def test_a_failed_writer_returns_no_receipt(monkeypatch):
    writer(monkeypatch, fail=True)
    with pytest.raises(RuntimeError, match="transaction failed"):
        activities.index_text_pages_with_versions(PARAMS)


def test_text_written_after_the_writer_read_stays_open():
    store = FakeOcrStore()
    store.text.append((CD, "img", "ocr_tesseract_eng", 1, "old", 5_400_000_000))
    store.index_state.append((CD, "img"))
    store.receipts.append((CD, "img", "ocr_tesseract_eng", 1, 5_400_000_000, 1))
    index = Target("img", STAGE_INDEX)
    assert settled(store, CD, {index: SettingVersion()}) == {index}
    store.text.append((CD, "img", "ocr_tesseract_eng", 1, "new", 5_400_000_001))
    assert settled(store, CD, {index: SettingVersion()}) == set()


class _Ledger:
    def __init__(self, fail_receipts=False):
        self.calls = []
        self.fail_receipts = fail_receipts

    def insert(self, table, rows, column_names=None, settings=None):
        self.calls.append((table, rows, column_names, settings))
        if table == "ocr_indexed_text" and self.fail_receipts:
            self.fail_receipts = False
            raise RuntimeError("receipt insert failed")


def record(monkeypatch, ledger, receipts):
    @contextmanager
    def collection(_name):
        yield ledger

    monkeypatch.setattr(shard_planner, "get_collection_client", collection)
    return shard_planner.record_indexed(RecordIndexedParams(
        "c", CD, "plan", [("c_1", "img")], receipts))


def test_receipts_follow_the_index_rows_and_wait_for_storage(monkeypatch):
    ledger = _Ledger()
    record(monkeypatch, ledger, [("img", "ocr_tesseract_eng", 1, 5_400_000_000)])
    assert [call[0] for call in ledger.calls] == ["index_state", "ocr_indexed_text"]
    table, rows, columns, settings = ledger.calls[1]
    assert rows == [[CD, "img", "ocr_tesseract_eng", 1, 5_400_000_000]]
    assert columns == ["collection_dataset", "file_hash", "extracted_by", "page_id",
                       "text_version"]
    assert settings == {"async_insert": 1, "wait_for_async_insert": 1}


def test_a_failed_receipt_insert_is_retried_after_the_index_row(monkeypatch):
    ledger = _Ledger(fail_receipts=True)
    receipts = [("img", "ocr_tesseract_eng", 1, 5_400_000_000)]
    with pytest.raises(RuntimeError):
        record(monkeypatch, ledger, receipts)
    record(monkeypatch, ledger, receipts)
    assert [call[0] for call in ledger.calls] == [
        "index_state", "ocr_indexed_text", "index_state", "ocr_indexed_text"]


def test_an_argument_without_receipts_writes_only_the_index_rows(monkeypatch):
    ledger = _Ledger()
    record(monkeypatch, ledger, [])
    assert [call[0] for call in ledger.calls] == ["index_state"]


@pytest.mark.parametrize("generation", ["original", "versions", "durable"])
def test_the_plan_workflow_preserves_receipt_contracts(monkeypatch, generation):
    scheduled = []
    recorded = []

    def execute_activity(fn, params, **_kwargs):
        async def result():
            scheduled.append(fn)
            if fn is index_workflows.fetch_plan_hashes:
                return ["img"]
            if fn is index_workflows.plan_shards:
                return [SimpleNamespace(shard_name="c_1", hashes=["img"])]
            if fn is index_workflows.index_text_pages_with_versions:
                return IndexedTextResult(["img"], [("img", "ocr_tesseract_eng", 1, 9)])
            if fn in (index_workflows.index_text_pages,
                      index_workflows.index_text_pages_with_receipts):
                return ["img"]
            if fn is index_workflows.index_vectors:
                return ["img"]
            if fn is index_workflows.record_indexed:
                recorded.append(params)
            return None
        return result()

    async def no_errors(*_args, **_kwargs):
        return 0

    w = index_workflows.workflow
    monkeypatch.setattr(w, "execute_activity", execute_activity)
    monkeypatch.setattr(w, "now", lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(w, "info", lambda: SimpleNamespace(run_id="run"))
    monkeypatch.setattr(w, "patched", lambda name: (
        generation != "original" if name == index_workflows.OCR_TEXT_VERSIONS_PATCH else
        generation == "durable" if name == index_workflows.DURABLE_TEXT_RECEIPTS_PATCH else True))
    monkeypatch.setattr(index_workflows, "record_errors_from_results", no_errors)
    asyncio.run(index_workflows.IndexDatasetPlan().run(
        IndexDatasetPlanParams("c", CD, "plan", "op")))
    writer_fn = (index_workflows.index_text_pages_with_receipts if generation == "durable" else
                 index_workflows.index_text_pages_with_versions if generation == "versions" else
                 index_workflows.index_text_pages)
    assert writer_fn in scheduled
    assert recorded[0].entries == [("c_1", "img")]
    assert recorded[0].ocr_text_versions == (
        [("img", "ocr_tesseract_eng", 1, 9)] if generation == "versions" else [])


def test_a_set_item_list_skips_the_plan_hash_read(monkeypatch):
    scheduled = []

    def execute_activity(fn, params, **_kwargs):
        async def result():
            scheduled.append((fn, params))
            if fn is index_workflows.plan_shards:
                return []
            return None
        return result()

    w = index_workflows.workflow
    monkeypatch.setattr(w, "execute_activity", execute_activity)
    monkeypatch.setattr(w, "patched", lambda _name: True)
    monkeypatch.setattr(w, "info", lambda: SimpleNamespace(run_id="run"))

    async def no_errors(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(index_workflows, "record_errors_from_results", no_errors)
    asyncio.run(index_workflows.IndexDatasetPlan().run(IndexDatasetPlanParams(
        "c", CD, "plan", "op", item_hashes=["b", "a", "b"])))
    assert scheduled[0][0] is index_workflows.plan_shards
    assert scheduled[0][1].hashes == ["a", "b"]


def test_a_language_purge_removes_the_receipts_of_its_variants():
    assert "ocr_indexed_text" in EXTRACTED_BY_TABLES


class _ReceiptCollection(_Collection):
    def __init__(self, segments, calls, fail_batch=0):
        self.segments = segments
        self.calls = calls
        self.fail_batch = fail_batch
        self.insert_count = 0
        self.receipts = {}

    def query_arrow(self, sql, _params):
        if "argMax(text_bytes, version)" in sql:
            return _Arrow([{"file_hash": h, "extracted_by": e, "page_id": p, "text_bytes": 10}
                           for h, e, p, _ in self.segments])
        return _Arrow([])

    def insert(self, table, rows, column_names=None, settings=None):
        assert table == "ocr_indexed_text"
        assert settings == {"async_insert": 1, "wait_for_async_insert": 1}
        assert len(rows) <= activities.INDEX_RECEIPT_BATCH_ROWS
        self.insert_count += 1
        self.calls.append(("receipts", len(rows)))
        if self.insert_count == self.fail_batch:
            raise RuntimeError("receipt insert interrupted")
        for cd, h, e, p, v in rows:
            self.receipts[cd, h, e, p] = v


def durable_writer(monkeypatch, segments, fail_batch=0):
    """Run actual page construction and receipt batching with controlled store failures."""
    monkeypatch.setattr(__import__(__name__), "SEGMENTS", segments)
    writer(monkeypatch)
    calls = []
    store = _ReceiptCollection(segments, calls, fail_batch)

    @contextmanager
    def collection(_name):
        yield store

    monkeypatch.setattr(activities, "get_collection_client", collection)
    monkeypatch.setattr(activities, "write_page_batches",
                        lambda _c, _t, _d, rows: (calls.append(("pages", len(rows))) or (1, 10)))
    monkeypatch.setattr(activities, "_delete_obsolete_index_pages",
                        lambda *_a: calls.append(("page_cleanup", 0)) or set())
    monkeypatch.setattr(activities, "remove_old_clusters",
                        lambda *_a: calls.append(("cluster_cleanup", 0)))
    return store, calls


@pytest.mark.parametrize("documents,pages,sources", [(100, 300, 1), (1000, 12, 3)])
def test_production_scale_receipts_stay_inside_the_writer(monkeypatch, documents, pages, sources):
    hashes = [f"{i:064x}" for i in range(documents)]
    labels = ["pdftotext", "ocr_tesseract_eng", "ocr_easyocr_eng"][:sources]
    segments = [(h, e, p, 5_400_000_000 + p)
                for h in hashes for e in labels for p in range(1, pages + 1)]
    store, calls = durable_writer(monkeypatch, segments)
    params = IndexShardParams("c", CD, "plan", "c_1", hashes, "op")
    result = activities.index_text_pages_with_receipts(params)
    assert result == hashes
    assert len(store.receipts) == documents * pages * sources
    first_insert = next(i for i, call in enumerate(calls) if call[0] == "receipts")
    assert [call[0] for call in calls[first_insert - 2:first_insert]] == [
        "page_cleanup", "cluster_cleanup"]
    assert all(call[0] == "receipts" for call in calls[first_insert:])
    from temporalio.converter import PayloadConverter
    from tasks.payload_guard import payload_size, MAX_PAYLOAD_BYTES
    assert payload_size(PayloadConverter.default.to_payloads([result])[0]) < MAX_PAYLOAD_BYTES


@pytest.mark.parametrize("boundary", ["pages", "page_cleanup", "cluster_cleanup", "stopping"])
def test_no_new_receipts_precede_all_commits_and_cleanup(monkeypatch, boundary):
    store, _calls = durable_writer(monkeypatch, SEGMENTS)

    def fail(*_args):
        raise RuntimeError("interrupted before receipts")

    target = {"pages": "write_page_batches", "page_cleanup": "_delete_obsolete_index_pages",
              "cluster_cleanup": "remove_old_clusters", "stopping": "stop_if_worker_is_stopping"}[boundary]
    monkeypatch.setattr(activities, target, fail)
    with pytest.raises(RuntimeError, match="interrupted before receipts"):
        activities.index_text_pages_with_receipts(PARAMS)
    assert store.receipts == {}


def test_partial_receipt_persistence_and_lost_response_repeat_safe_writes(monkeypatch):
    segments = [("img", "pdftotext", p, 5_400_000_000 + p) for p in range(1, 1201)]
    store, calls = durable_writer(monkeypatch, segments, fail_batch=2)
    with pytest.raises(RuntimeError, match="receipt insert interrupted"):
        activities.index_text_pages_with_receipts(PARAMS)
    assert len(store.receipts) == activities.INDEX_RECEIPT_BATCH_ROWS
    store.fail_batch = 0
    assert activities.index_text_pages_with_receipts(PARAMS) == ["img"]
    receipts = dict(store.receipts)
    # Repeat after a successful insert whose response did not reach the workflow.
    assert activities.index_text_pages_with_receipts(PARAMS) == ["img"]
    assert store.receipts == receipts
    assert sum(1 for call in calls if call[0] == "cluster_cleanup") == 3


def test_existing_index_state_waits_for_every_current_receipt(monkeypatch):
    segments = [("img", "ocr_tesseract_eng", p, 5_400_000_000 + p) for p in range(1, 601)]
    store, _calls = durable_writer(monkeypatch, segments, fail_batch=2)
    completion = FakeOcrStore()
    completion.index_state.append((CD, "img"))
    completion.text.extend((CD, h, e, p, "text", v) for h, e, p, v in segments)
    index = Target("img", STAGE_INDEX)

    def sync_receipts():
        completion.receipts[:] = [(cd, h, e, p, v, 1)
                                 for (cd, h, e, p), v in store.receipts.items()]

    with pytest.raises(RuntimeError):
        activities.index_text_pages_with_receipts(PARAMS)
    sync_receipts()
    assert settled(completion, CD, {index: SettingVersion()}) == set()
    store.fail_batch = 0
    activities.index_text_pages_with_receipts(PARAMS)
    sync_receipts()
    assert settled(completion, CD, {index: SettingVersion()}) == {index}
    completion.text.append((CD, "img", "ocr_tesseract_eng", 1, "new", 5_400_000_999))
    assert settled(completion, CD, {index: SettingVersion()}) == set()


@pytest.mark.parametrize("fragmented,vectors_only", [(True, False), (False, False), (True, True)])
def test_thousand_document_commands_remain_bounded(monkeypatch, fragmented, vectors_only):
    from temporalio.converter import PayloadConverter
    from tasks.payload_guard import MAX_PAYLOAD_BYTES, MAX_ACTIVATION_BYTES, payload_size

    hashes = [f"{i:064x}" for i in range(1000)]
    assignments = ([SimpleNamespace(shard_name=f"c_{i}", hashes=[h])
                    for i, h in enumerate(hashes)] if fragmented else
                   [SimpleNamespace(shard_name="c_1", hashes=hashes)])
    scheduled_bytes = []
    windows = []
    acks = []

    def execute_activity(fn, params, **_kwargs):
        encoded_bytes = payload_size(PayloadConverter.default.to_payloads([params])[0])
        assert encoded_bytes < MAX_PAYLOAD_BYTES
        if fn in (index_workflows.index_text_pages_with_receipts, index_workflows.index_vectors):
            scheduled_bytes.append(encoded_bytes)
        if fn is index_workflows.record_indexed:
            acks.append(params)

        async def result():
            if fn is index_workflows.plan_shards:
                return assignments
            if fn in (index_workflows.index_text_pages_with_receipts, index_workflows.index_vectors):
                if scheduled_bytes:
                    windows.append(list(scheduled_bytes))
                    scheduled_bytes.clear()
                return params.hashes
            return None
        return result()

    async def no_errors(*_args, **_kwargs):
        return 0

    w = index_workflows.workflow
    monkeypatch.setattr(w, "execute_activity", execute_activity)
    monkeypatch.setattr(w, "now", lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(w, "info", lambda: SimpleNamespace(run_id="run"))
    monkeypatch.setattr(w, "patched", lambda _name: True)
    monkeypatch.setattr(index_workflows, "record_errors_from_results", no_errors)
    asyncio.run(index_workflows.IndexDatasetPlan().run(IndexDatasetPlanParams(
        "c", CD, "f" * 40, "op", vectors_only=vectors_only, item_hashes=hashes)))
    assert max(len(window) for window in windows) <= (8 if vectors_only else 16)
    assert max(sum(window) for window in windows) < MAX_ACTIVATION_BYTES // 2
    assert all(not ack.ocr_text_versions and len(ack.entries) <= 100 for ack in acks)
    assert sum(len(ack.entries) for ack in acks) == (0 if vectors_only else 1000)


def test_unexpected_large_compact_result_fails_with_a_small_diagnostic(monkeypatch):
    from temporalio.exceptions import ApplicationError
    monkeypatch.setattr(activities, "write_text_pages",
                        lambda _p: IndexedTextResult(["h" * 600_000], []))
    with pytest.raises(ApplicationError) as failure:
        activities.index_text_pages_with_receipts(PARAMS)
    assert failure.value.type == "PayloadTooLarge"
    assert failure.value.non_retryable
    assert len(str(failure.value)) < 200


def test_text_changed_during_the_writer_does_not_receive_the_new_version(monkeypatch):
    old = [("img", "ocr_tesseract_eng", 1, 5_400_000_000)]
    store, _calls = durable_writer(monkeypatch, old)
    completion = FakeOcrStore()
    completion.index_state.append((CD, "img"))
    completion.text.append((CD, "img", "ocr_tesseract_eng", 1, "old", 5_400_000_000))

    def change_text(*_args):
        completion.text.append((CD, "img", "ocr_tesseract_eng", 1, "new", 5_400_000_001))

    monkeypatch.setattr(activities, "remove_old_clusters", change_text)
    assert activities.index_text_pages_with_receipts(PARAMS) == ["img"]
    completion.receipts.extend((cd, h, e, p, v, 1)
                              for (cd, h, e, p), v in store.receipts.items())
    assert store.receipts[CD, "img", "ocr_tesseract_eng", 1] == 5_400_000_000
    assert settled(completion, CD, {Target("img", STAGE_INDEX): SettingVersion()}) == set()


def test_worker_stop_during_receipts_leaves_a_retryable_partial_insert(monkeypatch):
    from temporalio.exceptions import ApplicationError
    segments = [("img", "pdftotext", p, 5_400_000_000 + p) for p in range(1, 701)]
    store, _calls = durable_writer(monkeypatch, segments)
    boundaries = 0

    def stop_after_first_batch():
        nonlocal boundaries
        boundaries += 1
        if boundaries == 2:
            raise ApplicationError("worker stopped")

    monkeypatch.setattr(activities, "stop_if_worker_is_stopping", stop_after_first_batch)
    with pytest.raises(ApplicationError):
        activities.index_text_pages_with_receipts(PARAMS)
    assert len(store.receipts) == activities.INDEX_RECEIPT_BATCH_ROWS
    monkeypatch.setattr(activities, "stop_if_worker_is_stopping", lambda: None)
    assert activities.index_text_pages_with_receipts(PARAMS) == ["img"]
    assert len(store.receipts) == 700
