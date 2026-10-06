"""Verify operation outcomes and cancellation across complete exception chains."""

import asyncio

import pytest
from temporalio.exceptions import ApplicationError

from tasks.failure_chain import failure_message, is_cancellation
from tasks.P_admin.rerun_params import SelectionResult
from tasks.P_ops import workflows
from tasks.P_ops.params import OperationParams


@pytest.mark.parametrize("kind", ["add_dataset", "rescan_dataset", "execute_plans", "retry_failed_files", "change_ocr_languages"])
@pytest.mark.parametrize("ledger_has_failure", [True, False])
def test_each_ingest_kind_reports_ledger_or_counter_failure(monkeypatch, kind, ledger_has_failure):
    states = []
    calls = []
    counts = dict(plans_run=3, invocations=3, failed_plans=1, failed_dataset_steps=0)

    async def activity_call(fn, params, **_options):
        name = fn if isinstance(fn, str) else fn.__name__
        calls.append(name)
        if name == "admit_operation":
            return "running"
        if name == "select_historical_errors":
            return SelectionResult()
        if name == "reconcile_selected_errors":
            return {}
        if name == "sample_dataset_progress":
            return dict(failed_plans=int(ledger_has_failure), failed_dataset_steps=0,
                        failed_documents=2, plan_samples=["failed-plan"], step_samples=[])
        if name == "record_operation_state":
            states.append(params.state)

    async def child_call(name, _params, **_options):
        if name == "IngestAndProcessDataset":
            return {"selector_counts": {}, "execution_counts": counts}
        if name == "ChangeOcrLanguages":
            return {"execution_counts": counts}
        return counts

    async def capture(*_args, **_kwargs):
        return None

    monkeypatch.setattr(workflows.workflow, "execute_activity", activity_call)
    monkeypatch.setattr(workflows.workflow, "execute_child_workflow", child_call)
    monkeypatch.setattr(workflows, "capture_failure_best_effort", capture)
    params = OperationParams("operation", kind, "collection", "dataset",
                            detail={"hash": "file", "tesseract_languages": "eng"})
    with pytest.raises(ApplicationError, match="1 plans and 0 dataset steps failed"):
        asyncio.run(workflows.Operation().run(params))
    assert states == ["errored"]
    assert "sample_dataset_progress" in calls
    if kind in ("execute_plans", "retry_failed_files"):
        assert calls.index("reconcile_selected_errors") < calls.index("sample_dataset_progress")


def test_exception_reader_preserves_nested_cancellation_and_stops_cycles():
    inner = asyncio.CancelledError()
    current = inner
    for _ in range(8):
        outer = RuntimeError("Activity wrapper.")
        outer.__cause__ = current
        current = outer
    assert is_cancellation(current)
    assert "CancelledError" in failure_message(current)
    inner.__cause__ = current
    assert is_cancellation(current)
    assert len(failure_message(current)) < 1000


def test_rebuild_reports_failure_after_remaining_pages(monkeypatch):
    class Continued(BaseException):
        pass

    visited = []
    continued = []

    async def list_page(_fn, params, **_kwargs):
        if _fn is workflows.compact_collection_shards:
            visited.append("compaction")
            return []
        if not params.cursor_hash:
            return [("dataset", f"plan-{n:03d}") for n in range(100)]
        return [("dataset", "plan-100")]

    async def child(_fn, params, **_kwargs):
        visited.append(params.plan_hash)
        if params.plan_hash == "plan-000":
            raise RuntimeError("Index failed.")

    def continuation(params):
        continued.append(params)
        raise Continued()

    monkeypatch.setattr(workflows.workflow, "execute_activity", list_page)
    monkeypatch.setattr(workflows.workflow, "execute_child_workflow", child)
    monkeypatch.setattr(workflows.workflow, "continue_as_new", continuation)
    with pytest.raises(Continued):
        asyncio.run(workflows.RebuildCollectionPlans().run(workflows.RebuildPlansParams("operation", "collection", False)))
    assert continued[0].failed == 1
    assert continued[0].completed == 100
    with pytest.raises(ApplicationError, match="1 index plans failed"):
        asyncio.run(workflows.RebuildCollectionPlans().run(continued[0]))
    assert len(visited) == 102
    assert visited[-2:] == ["plan-100", "compaction"]


def test_collection_backfill_finishes_remaining_plans_before_failure(monkeypatch):
    from tasks.P_admin.collection_backfill import FinishedPlanPage
    visited = []

    async def list_page(_fn, _params, **_kwargs):
        return FinishedPlanPage([["dataset", f"plan-{n}"] for n in range(3)], ["dataset", "plan-2"], 3)

    async def child(_fn, params, **_kwargs):
        visited.append((_fn, params["plan_hash"]))
        if params["plan_hash"] == "plan-0":
            raise RuntimeError("Embedding failed.")

    async def record(*_args):
        pass

    monkeypatch.setattr(workflows.workflow, "execute_activity", list_page)
    monkeypatch.setattr(workflows.workflow, "execute_child_workflow", child)
    monkeypatch.setattr(workflows.Operation, "_record", record)
    params = OperationParams("operation", "backfill_vectors", "collection")
    with pytest.raises(ApplicationError, match="1 collection plans failed"):
        asyncio.run(workflows.Operation()._dispatch(params))
    assert params.plan_failed == 1
    assert params.plan_done == 3
    assert visited[-1] == ("IndexDatasetPlan", "plan-2")


def test_purge_deletes_headers_before_values(monkeypatch):
    from types import SimpleNamespace
    from tasks.P_admin.activities import purge_dataset_from_clickhouse, PurgeDatasetParams
    import database.clickhouse as db
    commands = []

    class Client:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def query(self, sql):
            rows = [(name,) for name in ("blob_values", "blobs", "text_content", "vfs_files")] if sql == "SHOW TABLES" else [("collection_dataset",)]
            return SimpleNamespace(result_rows=rows)
        def command(self, sql, **_kwargs):
            commands.append(sql)

    monkeypatch.setattr(db, "get_collection_client", lambda _: Client())
    purge_dataset_from_clickhouse(PurgeDatasetParams("collection", "dataset"))
    assert [sql.split('`')[1] for sql in commands] == ["vfs_files", "blobs", "text_content", "blob_values"]
