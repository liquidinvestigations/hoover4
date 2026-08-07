"""The activity-timing interceptor: what it records, and that it never gets in the way.

Two properties matter more than the happy path here:

* an instrumentation failure must not fail an ingest, and
* it must never fail *silently* -- the O2 defect this plan fixed was a bare
  ``except: pass`` losing error rows.

So the drop paths (unroutable activity, buffer overflow, failed insert) are tested for
their log output as much as for their behaviour.
"""

import ast
import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

import pytest

from tasks import task_timing
from tasks.task_timing import (
    MAX_BUFFERED_ROWS,
    TaskTimingInterceptor,
    _Recorder,
    _TimingActivityInbound,
    identify,
)
from temporalio.worker import ActivityInboundInterceptor, ExecuteActivityInput

TASKS_ROOT = Path(__file__).resolve().parents[2] / "tasks"


@dataclass
class _DocParams:
    collectionname: str = "testdata"
    collection_dataset: str = "testdata_testfiles"
    file_hash: str = "abc123"


@dataclass
class _PlanParams:
    collectionname: str = "testdata"
    collection_dataset: str = "testdata_testfiles"
    plan_hash: str = "planhash"


@dataclass
class _NoCollectionParams:
    base_temp_dir: str = "/tmp/x"


class _FakeNext(ActivityInboundInterceptor):
    """Terminal interceptor: returns a value, or raises what it was given."""

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    async def execute_activity(self, input):
        if self.error is not None:
            raise self.error
        return self.result


def _input(fn_name, params):
    def fn(_params):
        return None

    fn.__name__ = fn_name
    return ExecuteActivityInput(fn=fn, args=[params], executor=None, headers={})


@pytest.fixture
def recorder(monkeypatch):
    """A fresh recorder whose inserts are captured instead of sent to ClickHouse."""
    rec = _Recorder()
    inserts = []
    rec._insert = lambda collectionname, table, columns, rows: inserts.append(
        (collectionname, table, columns, list(rows))
    )
    # No flusher thread in unit tests: `flush()` is called explicitly so the assertions
    # are not racing a 5-second timer.
    rec.ensure_started = lambda: None
    monkeypatch.setattr(task_timing, "_recorder", rec)
    rec.inserts = inserts
    return rec


def _row(recorder, table="processing_task_runs"):
    recorder.flush()
    rows = [r for (_c, t, _cols, rs) in recorder.inserts if t == table for r in rs]
    return rows


# -- parameter introspection -------------------------------------------------


def test_identify_reads_collection_dataset_and_document_hash():
    assert identify([_DocParams()]) == ("testdata", "testdata_testfiles", "abc123")


def test_identify_falls_back_to_the_plan_hash():
    """P4/P5/P6 activities work on a whole plan and have no document of their own."""
    assert identify([_PlanParams()])[2] == "planhash"


def test_identify_reports_no_collection_when_the_params_have_none():
    assert identify([_NoCollectionParams()]) == ("", "", "")


# -- the interceptor ---------------------------------------------------------


def test_a_successful_execution_is_recorded_and_its_result_passed_through(recorder):
    interceptor = _TimingActivityInbound(_FakeNext(result=42))
    result = asyncio.run(interceptor.execute_activity(_input("parse_thing", _DocParams())))

    assert result == 42
    rows = _row(recorder)
    assert len(rows) == 1
    dataset, task_name, item_hash, outcome, run_time_ms, *_rest = rows[0]
    assert (dataset, task_name, item_hash, outcome) == (
        "testdata_testfiles",
        "parse_thing",
        "abc123",
        "ok",
    )
    assert run_time_ms >= 0


def test_a_failed_execution_is_recorded_in_the_same_table_and_still_raises(recorder):
    """Failures live in the aggregate, not beside it -- that is the whole point.

    `processing_errors` keeps the stack trace, `processing_task_runs` keeps the time,
    and a report of "where did the time go" that dropped failures would understate
    exactly the tasks worth fixing.
    """
    interceptor = _TimingActivityInbound(_FakeNext(error=RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(interceptor.execute_activity(_input("parse_thing", _DocParams())))

    rows = _row(recorder)
    assert len(rows) == 1
    assert rows[0][3] == "error"


def test_an_unroutable_activity_is_skipped_but_logged(recorder, caplog):
    """No collectionname means no database to write to. Dropping is correct here --
    doing it quietly is not."""
    interceptor = _TimingActivityInbound(_FakeNext(result="ok"))
    with caplog.at_level(logging.INFO, logger="tasks.task_timing"):
        result = asyncio.run(
            interceptor.execute_activity(_input("cleanup_temp_dir", _NoCollectionParams()))
        )

    assert result == "ok"
    assert _row(recorder) == []
    assert any("cleanup_temp_dir" in r.getMessage() for r in caplog.records)


def test_an_insert_failure_cannot_fail_the_activity_and_is_logged(monkeypatch, caplog):
    rec = _Recorder()
    rec.ensure_started = lambda: None
    monkeypatch.setattr(task_timing, "_recorder", rec)

    def explode(*_args, **_kwargs):
        raise ConnectionError("clickhouse is down")

    monkeypatch.setattr(
        "database.clickhouse.get_collection_client", explode, raising=False
    )

    interceptor = _TimingActivityInbound(_FakeNext(result=1))
    assert asyncio.run(interceptor.execute_activity(_input("t", _DocParams()))) == 1

    with caplog.at_level(logging.WARNING, logger="tasks.task_timing"):
        rec.flush()
    assert any("rows dropped" in r.message for r in caplog.records)


def test_the_buffer_is_capped_and_says_so(recorder, caplog):
    """A ClickHouse outage must cost rows, never the worker's memory."""
    for i in range(MAX_BUFFERED_ROWS + 25):
        recorder.record("testdata", [str(i)])
    assert recorder._row_count == MAX_BUFFERED_ROWS
    assert recorder._overflow_dropped == 25

    with caplog.at_level(logging.WARNING, logger="tasks.task_timing"):
        recorder.flush()
    assert any("buffer full" in r.message for r in caplog.records)


# -- in-flight sampling ------------------------------------------------------


def test_inflight_samples_are_written_only_while_something_is_running(recorder):
    recorder._sample_inflight()
    assert recorder.inserts == [], "an idle worker must write no in-flight rows"

    token = recorder.begin("testdata", "testdata_testfiles", "run_ocr_and_store")
    recorder._sample_inflight()
    rows = [r for (_c, t, _cols, rs) in recorder.inserts if t == "processing_task_inflight" for r in rs]
    assert len(rows) == 1
    assert rows[0][0] == "testdata_testfiles"
    assert rows[0][1] == "run_ocr_and_store"
    assert rows[0][4] == 1

    recorder.end(token)
    recorder.inserts.clear()
    recorder._sample_inflight()
    assert recorder.inserts == []


# -- wiring ------------------------------------------------------------------


def test_every_worker_installs_the_timing_interceptor():
    """The interceptor is only worth having if no worker can forget it.

    An AST check rather than a grep: `Worker(...)` spans dozens of lines here, and a
    regex over that is a false-negative generator (same reasoning as
    ``test_heartbeat_coverage``).
    """
    tree = ast.parse((TASKS_ROOT / "run_worker.py").read_text())
    workers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Worker"
    ]
    assert workers, "no Worker(...) construction found in run_worker.py"
    for call in workers:
        interceptors = next(
            (kw.value for kw in call.keywords if kw.arg == "interceptors"), None
        )
        assert interceptors is not None, (
            f"Worker at line {call.lineno} has no interceptors= argument: its activity "
            "executions would be missing from processing_task_runs"
        )
        names = {
            n.func.id
            for n in ast.walk(interceptors)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "TaskTimingInterceptor" in names, (
            f"Worker at line {call.lineno} does not install TaskTimingInterceptor"
        )


def test_the_interceptor_returns_the_timing_wrapper():
    wrapped = TaskTimingInterceptor().intercept_activity(_FakeNext())
    assert isinstance(wrapped, _TimingActivityInbound)
