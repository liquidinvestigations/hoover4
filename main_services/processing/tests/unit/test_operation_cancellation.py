import asyncio
import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from database.operations import VERSION_BITS, next_row_version, update_operation
from tasks.P_admin.rerun_params import SelectionResult
from tasks.P_ops.params import OperationParams


def test_terminal_version_exceeds_late_open_insert(monkeypatch):
    import database.operations as operations

    row = {
        "state": "running", "row_version": next_row_version("running"),
        "detail": "{}", "started_at": datetime(2026, 1, 1),
    }
    writes = []
    monkeypatch.setattr(operations, "get_operation", lambda _op_id: row)
    monkeypatch.setattr(operations, "_insert_row", lambda new: writes.append(new))

    update_operation("op", state="cancelled")
    update_operation("op", base_row=row, progress_done=4)

    assert writes[0]["row_version"] >> VERSION_BITS == 2
    assert writes[1]["row_version"] >> VERSION_BITS == 0
    assert writes[0]["row_version"] > writes[1]["row_version"]


def test_terminal_row_refuses_progress_insert(monkeypatch):
    import database.operations as operations

    row = {"state": "cancelled", "row_version": next_row_version("cancelled")}
    monkeypatch.setattr(operations, "get_operation", lambda _op_id: row)
    monkeypatch.setattr(operations, "_insert_row", lambda _row: pytest.fail("late insert"))
    assert update_operation("op", progress_done=8) is row


def test_cancel_finalizer_samples_before_terminal_row(monkeypatch):
    from tasks.P_ops import workflows

    calls = []
    samples = []

    async def activity_call(name, params, **_kwargs):
        calls.append(name.__name__)
        if name.__name__ == "sample_dataset_progress":
            samples.append(params)
        if name.__name__ == "cancel_target_operation":
            return {
                "state": "running", "collectionname": "c",
                "collection_dataset": "d", "history_missing": False,
                "target_status": "CANCELED",
            }
        return "cancelled"

    monkeypatch.setattr(workflows.workflow, "execute_activity", activity_call)
    result = asyncio.run(workflows.CancelOperation().run("op"))
    assert result == "cancelled"
    assert calls == [
        "cancel_target_operation", "sample_dataset_progress", "record_operation_state",
    ]
    assert samples[0].terminal_state == "cancelled"


def test_cancel_finalizer_records_absent_history_as_cancelled(monkeypatch):
    from tasks.P_ops import workflows

    calls = []

    async def activity_call(name, params, **_kwargs):
        calls.append((name.__name__, params))
        if name.__name__ == "cancel_target_operation":
            return {
                "state": "running", "collectionname": "c",
                "collection_dataset": "d", "history_missing": True,
            }
        return "cancelled"

    monkeypatch.setattr(workflows.workflow, "execute_activity", activity_call)
    assert asyncio.run(workflows.CancelOperation().run("op")) == "cancelled"
    assert [name for name, _params in calls] == [
        "cancel_target_operation", "record_operation_state",
    ]
    assert calls[1][1].state == "cancelled"
    assert calls[1][1].error == (
        "The workflow of this operation did not exist in Temporal, so nothing ran to cancel."
    )


def test_final_sample_writes_counts_with_terminal_state(monkeypatch):
    from tasks.P_ops.activities import sample_dataset_progress
    from tasks.P_ops.params import DatasetProgressParams
    import database.clickhouse as clickhouse
    import database.operation_ledger as ledger
    import database.operations as operations

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def query(self, *_args, **_kwargs):
            return SimpleNamespace(result_rows=[(2, 3)])

    row = {
        "state": "running", "row_version": 10,
        "started_at": datetime(2026, 1, 1), "detail": "{}",
    }
    writes = []
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: Client())
    monkeypatch.setattr(ledger, "run_plan_counts", lambda *_args: (0, 2))
    monkeypatch.setattr(operations, "get_operation", lambda _op_id: row)
    monkeypatch.setattr(operations, "update_operation", lambda _op_id, **kw: writes.append(kw))
    sample_dataset_progress(DatasetProgressParams(
        "op", "c", "d", terminal_state="cancelled",
        terminal_error="Cancelled by request.",
    ))
    assert len(writes) == 1
    assert writes[0]["base_row"] is row
    assert writes[0]["state"] == "cancelled"
    assert json.loads(writes[0]["detail"])["failed_tasks"] == 3


def test_progress_sample_stops_on_terminal_row(monkeypatch):
    from tasks.P_ops.activities import sample_dataset_progress
    from tasks.P_ops.params import DatasetProgressParams
    import database.clickhouse as clickhouse
    import database.operations as operations

    monkeypatch.setattr(operations, "get_operation", lambda _op_id: {
        "state": "cancelled", "progress_done": 1, "progress_total": 2,
    })
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name:
                        pytest.fail("terminal sample reached collection database"))
    assert sample_dataset_progress(DatasetProgressParams("op", "c", "d")) == [1, 2]


def _pass_the_readiness_gate(monkeypatch) -> list:
    """Replace the readiness gate with one that passes at once and records each call."""
    import tasks.temporal_readiness as readiness

    calls = []

    async def wait_for_temporal(client):
        calls.append(client)

    monkeypatch.setattr(readiness, "wait_for_temporal", wait_for_temporal)
    return calls


def test_cli_starts_one_finalizer_and_waits(monkeypatch):
    import temporalio.client
    import database.operations as operations
    from tasks.P_ops.cli import request_cancel

    starts = []

    class Handle:
        async def result(self):
            return "cancelled"

    class Client:
        async def start_workflow(self, *args, **kwargs):
            starts.append((args, kwargs))
            return Handle()

    async def connect(_target):
        return Client()

    monkeypatch.setattr(temporalio.client.Client, "connect", staticmethod(connect))
    gated = _pass_the_readiness_gate(monkeypatch)
    monkeypatch.setattr(operations, "get_operation", lambda _op_id: {"state": "running"})
    assert request_cancel("op") == "cancelled"
    assert starts[0][1]["id"] == "cancel-op"
    assert starts[0][1]["rpc_timeout"].total_seconds() == 30
    assert len(gated) == 1


def test_cli_reuses_finished_finalizer(monkeypatch):
    import temporalio.client
    from temporalio.exceptions import WorkflowAlreadyStartedError
    import database.operations as operations
    from tasks.P_ops.cli import request_cancel

    class Handle:
        async def result(self):
            return "finished"

    class Client:
        async def start_workflow(self, *_args, **_kwargs):
            raise WorkflowAlreadyStartedError("cancel-op", "CancelOperation")

        def get_workflow_handle(self, workflow_id):
            assert workflow_id == "cancel-op"
            return Handle()

    async def connect(_target):
        return Client()

    monkeypatch.setattr(temporalio.client.Client, "connect", staticmethod(connect))
    gated = _pass_the_readiness_gate(monkeypatch)
    monkeypatch.setattr(operations, "get_operation", lambda _op_id: {"state": "finished"})
    assert request_cancel("op") == "finished"
    assert len(gated) == 1


def test_cancel_target_waits_for_closed_history(monkeypatch):
    import temporalio.client
    import database.operations as operations
    from tasks.P_ops.activities import cancel_target_operation

    calls = []

    class Handle:
        async def describe(self):
            calls.append("describe")
            status = (temporalio.client.WorkflowExecutionStatus.RUNNING
                      if calls.count("describe") == 1 else
                      temporalio.client.WorkflowExecutionStatus.CANCELED)
            return SimpleNamespace(status=status)

        async def cancel(self):
            calls.append("cancel")

        async def result(self):
            calls.append("result")
            raise temporalio.client.WorkflowFailureError(cause=Exception("cancelled"))

    class Client:
        def get_workflow_handle(self, _op_id):
            return Handle()

    async def connect(_target):
        return Client()

    monkeypatch.setattr(temporalio.client.Client, "connect", staticmethod(connect))
    monkeypatch.setattr(operations, "get_operation", lambda _op_id: {
        "state": "running", "collectionname": "c", "collection_dataset": "d",
    })
    result = cancel_target_operation("op")
    assert result["target_status"] == "CANCELED"
    assert calls == ["describe", "cancel", "result", "describe"]


@pytest.mark.parametrize("failed_activity", ["select_historical_errors", "reconcile_selected_errors"])
def test_dedicated_retry_reaches_fourth_attempt(monkeypatch, failed_activity):
    from tasks.P_ops import workflows

    attempts = {"select_historical_errors": 0, "reconcile_selected_errors": 0}

    async def activity_call(name, _params, **kwargs):
        if isinstance(name, str) and name in attempts:
            assert kwargs["retry_policy"].maximum_attempts == 5
            limit = kwargs["retry_policy"].maximum_attempts
            for attempt in range(1, limit + 1):
                attempts[name] += 1
                if name != failed_activity or attempt == 4:
                    break
            else:
                pytest.fail("activity stopped before attempt four")
            if name == "select_historical_errors":
                return SelectionResult(selected_errors=1, errors_before_run=1)
            return {"still_failing_errors": 0}
        return [0, 1]

    async def child_call(*_args, **_kwargs):
        return "completed"

    async def sample_counts(_self, _params, _counts):
        return None

    monkeypatch.setattr(workflows.workflow, "execute_activity", activity_call)
    monkeypatch.setattr(workflows.workflow, "execute_child_workflow", child_call)
    monkeypatch.setattr(workflows.Operation, "_sample_selector_counts", sample_counts)
    params = OperationParams(
        op_id="op", kind="retry_failed_files", collectionname="c",
        collection_dataset="d", detail={"hash": "hash"},
    )
    assert asyncio.run(workflows.Operation()._retry_failed_files(params)) == "completed"
    assert attempts[failed_activity] == 4


def test_all_six_selector_calls_use_shared_attempt_limit():
    root = Path(__file__).resolve().parents[2] / "tasks"
    found = []
    for path in (root / "P0_scan_disk/workflows.py", root / "P_ops/workflows.py"):
        tree = ast.parse(path.read_text())
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            if not call.args:
                continue
            name = call.args[0]
            activity = name.id if isinstance(name, ast.Name) else name.value if isinstance(name, ast.Constant) else ""
            if activity not in ("select_historical_errors", "reconcile_selected_errors"):
                continue
            policy = next(k.value for k in call.keywords if k.arg == "retry_policy")
            attempts = next(k.value for k in policy.keywords if k.arg == "maximum_attempts")
            assert isinstance(attempts, ast.Name)
            assert attempts.id == "ACTIVITY_MAX_ATTEMPTS"
            found.append((path.name, activity))
    assert len(found) == 6
