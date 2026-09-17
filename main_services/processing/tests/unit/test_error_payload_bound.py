"""Error recording keeps every Temporal activity argument below the payload limit."""

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import json
import hashlib

import pytest

from temporalio import workflow

from tasks.P3_parse_files import parse_common
from tasks.operation_failure_capture import TEMPORAL_BLOB_LIMIT_BYTES


def _record_errors(monkeypatch, count: int, error_log: str):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    scheduled = []
    results = [RuntimeError("failed") for _ in range(count)]

    class _WorkflowInfo:
        run_id = "workflow-run"

    async def execute_activity(*args, **kwargs):
        scheduled.append(args[1])
        return len(args[1].errors)

    monkeypatch.setattr(workflow, "now", lambda: now)
    monkeypatch.setattr(workflow, "info", lambda: _WorkflowInfo())
    monkeypatch.setattr(workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(parse_common, "format_temporal_exception_chain", lambda error: error_log)

    inserted = asyncio.run(
        parse_common.record_errors_from_results(
            results,
            task_ids=["P4_ExtractEntities"] * count,
            starts=[now] * count,
            collectionname="collection",
            collection_dataset="dataset",
            item_hashes=[f"hash-{index}" for index in range(count)],
            source_execution_ids=[f"source-{index}" for index in range(count)],
            op_id="operation-1",
        )
    )
    return inserted, scheduled


def _serialized_size(params) -> int:
    return len(json.dumps(asdict(params)).encode("utf-8"))


def test_short_errors_use_one_activity(monkeypatch):
    inserted, scheduled = _record_errors(monkeypatch, 10, "short error")

    assert inserted == 10
    assert len(scheduled) == 1
    assert _serialized_size(scheduled[0]) < TEMPORAL_BLOB_LIMIT_BYTES


def test_production_sized_errors_are_split_below_the_limit(monkeypatch):
    production_chain = "m" * 418 + "s" * 1902
    inserted, scheduled = _record_errors(monkeypatch, 5000, production_chain)

    assert inserted == 5000
    assert len(scheduled) > 1
    assert all(_serialized_size(params) < TEMPORAL_BLOB_LIMIT_BYTES for params in scheduled)


def test_oversized_error_log_is_truncated_before_scheduling(monkeypatch):
    inserted, scheduled = _record_errors(monkeypatch, 1, "x" * (4 * 1024 * 1024))

    assert inserted == 1
    assert len(scheduled) == 1
    assert parse_common.ERROR_PAYLOAD_TRUNCATION_MARKER in scheduled[0].errors[0]["error_logs"]
    assert _serialized_size(scheduled[0]) < TEMPORAL_BLOB_LIMIT_BYTES


def test_no_errors_does_not_schedule_an_activity(monkeypatch):
    inserted, scheduled = _record_errors(monkeypatch, 0, "")

    assert inserted == 0
    assert scheduled == []


def test_source_identity_uses_run_call_site_and_schedule_ordinal():
    first = parse_common.source_execution_id("run", "P4.entities", 0)
    assert first == '["run","P4.entities",0]'
    assert parse_common.source_execution_id("run", "P4.entities", 0) == first
    assert parse_common.source_execution_id("run", "P4.entities", 1) != first
    assert parse_common.source_execution_id("run-2", "P4.entities", 0) != first
    assert parse_common.source_execution_id("run", "P4.regex", 0) != first


def test_error_identity_includes_source_task_dataset_and_hash(monkeypatch):
    _, scheduled = _record_errors(monkeypatch, 2, "failed")
    rows = scheduled[0].errors
    expected = hashlib.sha256(json.dumps(
        ["source-0", "P4_ExtractEntities", "dataset", "hash-0"],
        ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    assert rows[0]["error_identity"] == expected
    assert rows[1]["error_identity"] != expected


def test_helper_rejects_missing_source_ids_before_writing(monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(workflow, "now", lambda: now)
    with pytest.raises(ValueError, match="source execution id"):
        asyncio.run(parse_common.record_errors_from_results(
            [RuntimeError("failed")], task_ids=["P4_ExtractEntities"],
            starts=[now], collectionname="collection", collection_dataset="dataset",
            item_hashes=["hash"], source_execution_ids=[], op_id="op"))
