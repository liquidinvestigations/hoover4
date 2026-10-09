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


@pytest.mark.parametrize("patched", [True, False])
def test_the_plan_workflow_passes_receipts_only_behind_its_patch(monkeypatch, patched):
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
            if fn is index_workflows.index_text_pages:
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
    monkeypatch.setattr(w, "patched", lambda name: patched or name != index_workflows.OCR_TEXT_VERSIONS_PATCH)
    monkeypatch.setattr(index_workflows, "record_errors_from_results", no_errors)
    asyncio.run(index_workflows.IndexDatasetPlan().run(
        IndexDatasetPlanParams("c", CD, "plan", "op")))
    writer_fn = (index_workflows.index_text_pages_with_versions if patched
                 else index_workflows.index_text_pages)
    assert writer_fn in scheduled
    assert recorded[0].entries == [("c_1", "img")]
    assert recorded[0].ocr_text_versions == (
        [("img", "ocr_tesseract_eng", 1, 9)] if patched else [])


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
