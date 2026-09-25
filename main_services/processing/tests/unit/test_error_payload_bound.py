"""Error recording keeps every Temporal activity argument below the payload limit."""

import asyncio
from datetime import datetime, timezone
import json
import hashlib

import pytest

from temporalio import workflow

from temporalio.converter import PayloadConverter

from tasks.P3_parse_files import parse_common
from tasks.payload_guard import payload_size

#: The budget of one record input, in encoded bytes as the payload guard measures it.
BUDGET = 262_144


def _record_errors(monkeypatch, count: int, error_log: str):
    assert parse_common.ERROR_PAYLOAD_BUDGET_BYTES == BUDGET
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
    """The size that the payload guard measures for one activity input."""
    return payload_size(PayloadConverter.default.to_payloads([params])[0])


def test_short_errors_use_one_activity(monkeypatch):
    inserted, scheduled = _record_errors(monkeypatch, 10, "short error")

    assert inserted == 10
    assert len(scheduled) == 1
    assert _serialized_size(scheduled[0]) <= BUDGET


def test_production_sized_errors_are_split_below_the_limit(monkeypatch):
    production_chain = "m" * 418 + "s" * 1902
    inserted, scheduled = _record_errors(monkeypatch, 5000, production_chain)

    assert inserted == 5000
    assert len(scheduled) > 1
    assert all(_serialized_size(params) <= BUDGET for params in scheduled)


def test_oversized_error_log_is_truncated_before_scheduling(monkeypatch):
    inserted, scheduled = _record_errors(monkeypatch, 1, "x" * (4 * 1024 * 1024))

    assert inserted == 1
    assert len(scheduled) == 1
    assert parse_common.ERROR_PAYLOAD_TRUNCATION_MARKER in scheduled[0].errors[0]["error_logs"]
    assert _serialized_size(scheduled[0]) <= BUDGET


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


def test_200_ascii_rows_of_5_kb_stay_under_the_budget(monkeypatch):
    inserted, scheduled = _record_errors(monkeypatch, 200, "e" * 5000)
    assert inserted == 200
    assert sum(len(params.errors) for params in scheduled) == 200
    assert all(_serialized_size(params) <= BUDGET for params in scheduled)


def test_200_arabic_rows_of_5_kb_stay_under_the_budget_in_more_batches(monkeypatch):
    _, ascii_batches = _record_errors(monkeypatch, 200, "e" * 5000)
    inserted, scheduled = _record_errors(monkeypatch, 200, "\u0639" * 5000)
    assert inserted == 200
    assert all(_serialized_size(params) <= BUDGET for params in scheduled)
    assert len(scheduled) > len(ascii_batches)
    # The measure is exact, so a full batch sits close to the budget.
    assert max(_serialized_size(params) for params in scheduled) > BUDGET - 40_000


def test_one_arabic_row_of_1_mb_is_cut_to_fit(monkeypatch):
    inserted, scheduled = _record_errors(monkeypatch, 1, "\u0639" * (1024 * 1024))
    assert inserted == 1
    assert len(scheduled) == 1
    assert scheduled[0].errors[0]["error_logs"].endswith(parse_common.ERROR_PAYLOAD_TRUNCATION_MARKER)
    assert _serialized_size(scheduled[0]) <= BUDGET
