"""The progress of "Run OCR": plans while unfinished plans run, then OCR and index targets.

The supervisor's sample stays the only writer of the operation row. A rerun_ocr row counts
its recorded targets once it has any, and its plan counts still decide failed plans.
"""

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import database.clickhouse as clickhouse
import database.operation_ledger as ledger
import database.operations as operations
import tasks.dataset_config as dataset_config
import tasks.ocr_client as ocr_client
import tasks.ocr_pdf_client as ocr_pdf_client
from ocr_store_fake import CD, COLLECTION, FakeOcrStore
from tasks.P_admin import ocr_rerun
from tasks.P_ops.activities import sample_dataset_progress
from tasks.P_ops.params import DatasetProgressParams

OP = "rerun_ocr-c_ds-1"


class _Errors:
    """Answers the error counts of the sample: no failed document."""

    def query(self, query, parameters):
        return SimpleNamespace(result_rows=[(0, 0, 0)] if "uniqExactIf" in query else [])


def sample(monkeypatch, kind, plans=(1, 4), targets=None, verify=False):
    updates = []
    monkeypatch.setattr(operations, "get_operation", lambda _op: {
        "kind": kind, "started_at": datetime.now(timezone.utc), "state": "running",
        "row_version": 1, "progress_done": 0, "progress_total": 0, "detail": "{}"})
    monkeypatch.setattr(operations, "update_operation",
                        lambda _op, **fields: updates.append(fields))
    monkeypatch.setattr(ledger, "run_plan_counts", lambda *_args: plans)
    if targets is not None:
        monkeypatch.setattr(ledger, "ocr_run_target_counts", lambda *_args: targets)

    @contextmanager
    def client(_name):
        yield _Errors()

    monkeypatch.setattr(clickhouse, "get_collection_client", client)
    result = sample_dataset_progress(DatasetProgressParams(
        OP, COLLECTION, CD, verify_plan_completion=verify))
    return result, updates[-1]


def test_plans_count_before_any_target_is_recorded(monkeypatch):
    _, row = sample(monkeypatch, "rerun_ocr", plans=(1, 4), targets=(0, 0))
    assert (row["progress_done"], row["progress_total"]) == (1, 4)


def test_recorded_targets_replace_the_plan_counts(monkeypatch):
    _, row = sample(monkeypatch, "rerun_ocr", plans=(1, 1), targets=(6, 10))
    assert (row["progress_done"], row["progress_total"]) == (6, 10)


def test_failed_plans_still_come_from_the_plan_counts(monkeypatch):
    result, row = sample(monkeypatch, "rerun_ocr", plans=(3, 4), targets=(6, 10), verify=True)
    assert result["failed_plans"] == 1
    assert json.loads(row["detail"])["failed_plans"] == 1


def test_other_kinds_keep_plan_progress(monkeypatch):
    monkeypatch.setattr(ledger, "ocr_run_target_counts",
                        lambda *_a: pytest.fail("an execute_plans row read OCR targets"))
    _, row = sample(monkeypatch, "execute_plans", plans=(2, 5))
    assert (row["progress_done"], row["progress_total"]) == (2, 5)


def test_new_text_raises_the_total_before_the_ocr_targets_settle(monkeypatch):
    store = FakeOcrStore()
    monkeypatch.setattr(clickhouse, "get_collection_client", store.client)
    monkeypatch.setattr(ocr_client, "engine_configured", lambda e: e == "tesseract")
    monkeypatch.setattr(ocr_pdf_client, "service_configured", lambda: False)
    monkeypatch.setattr(dataset_config, "latest_setting_rows", lambda _cd, keys: {
        k: dataset_config.SettingRow("eng", False, 1, True) for k in keys
        if k == "ocr.tesseract.languages"})
    images = [f"i{n}" for n in range(10)]
    for item in images:
        store.add_image(item)
    ocr_rerun.record_ocr_run_targets(ocr_rerun.RerunOcrParams(COLLECTION, CD, OP))
    assert ledger.ocr_run_target_counts(COLLECTION, OP, CD) == (0, 10)

    # Two images get text, and the group records their index targets first.
    for item in images:
        store.raw.append((CD, item, "tesseract", "eng", json.dumps({"text": ""})))
    for item in images[:2]:
        store.text.append((CD, item, "ocr_tesseract_eng", 1, "text", 5))
    ocr_rerun.ocr_text_pending_index(ocr_rerun.OcrTextPendingParams(
        COLLECTION, CD, OP, "p1", images))
    assert ledger.ocr_run_target_counts(COLLECTION, OP, CD) == (0, 12)

    ocr_rerun.settle_ocr_run_targets(ocr_rerun.SettleOcrRunTargetsParams(
        COLLECTION, CD, OP, "p1", images))
    done, total = ledger.ocr_run_target_counts(COLLECTION, OP, CD)
    assert (done, total) == (10, 12)
    assert done < total
