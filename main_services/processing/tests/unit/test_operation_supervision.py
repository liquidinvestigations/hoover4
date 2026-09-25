import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest


def _row(state="running", *, op_id="op", kind="reindex_collection", age=121):
    return {
        "op_id": op_id,
        "state": state,
        "kind": kind,
        "started_at": datetime(2026, 1, 1) - timedelta(seconds=age),
        "collectionname": "collection",
        "collection_dataset": "dataset",
        "progress_total": 10,
    }


class _Handle:
    def __init__(self, description):
        self.description = description
        self.cancelled = False
        self.terminated = []

    async def describe(self):
        if isinstance(self.description, Exception):
            raise self.description
        return self.description

    async def result(self):
        return None

    async def cancel(self):
        self.cancelled = True

    async def terminate(self, *, reason):
        self.terminated.append(reason)


class _Client:
    def __init__(self, handles, executions=()):
        self.handles = handles
        self.executions = executions
        self.queries = []

    def get_workflow_handle(self, workflow_id, run_id=None):
        return self.handles[(workflow_id, run_id)]

    async def list_workflows(self, query, *, limit):
        self.queries.append((query, limit))
        for execution in self.executions:
            yield execution


def _description(status, attempt=0):
    return SimpleNamespace(
        status=status,
        raw_description=SimpleNamespace(
            pending_workflow_task=SimpleNamespace(attempt=attempt),
        ),
    )


def test_supervise_keeps_young_pending_row(monkeypatch):
    from tasks.P_ops import activities

    client = _Client({})
    asyncio.run(activities.supervise(
        client, datetime(2026, 1, 1), [_row("pending", age=599)],
    ))
    assert client.queries == []


def test_supervise_marks_old_absent_row_errored(monkeypatch):
    from tasks.P_ops import activities
    import database.operations as operations

    writes = []
    monkeypatch.setattr(operations, "finish_operation", lambda *args: writes.append(args))

    class NotFound(Exception):
        status = activities.RPCStatusCode.NOT_FOUND

    monkeypatch.setattr(activities, "RPCError", NotFound)
    row = _row("pending", age=601)
    client = _Client({("op", None): _Handle(NotFound())})
    asyncio.run(activities.supervise(client, datetime(2026, 1, 1), [row]))
    assert writes == [("op", "errored", activities.WORKFLOW_ABSENT_ERROR)]


def test_supervise_reconciles_closed_rows(monkeypatch):
    from temporalio.client import WorkflowExecutionStatus
    from tasks.P_ops import activities
    import database.operations as operations

    writes = []
    monkeypatch.setattr(operations, "finish_operation", lambda *args: writes.append(args))
    complete = _row(op_id="complete")
    terminated = _row(op_id="terminated")
    client = _Client({
        ("complete", None): _Handle(_description(WorkflowExecutionStatus.COMPLETED)),
        ("terminated", None): _Handle(_description(WorkflowExecutionStatus.TERMINATED)),
    })
    asyncio.run(activities.supervise(client, datetime(2026, 1, 1), [complete, terminated]))
    assert writes[0] == ("complete", "finished")
    assert writes[1][0:2] == ("terminated", "errored")
    assert "TERMINATED" in writes[1][2]


def test_supervise_skips_terminal_rows():
    from tasks.P_ops import activities

    asyncio.run(activities.supervise(
        _Client({}), datetime(2026, 1, 1), [_row("finished")],
    ))


def test_supervise_terminates_every_stuck_descendant(monkeypatch):
    from temporalio.client import WorkflowExecutionStatus
    from tasks.P_ops import activities
    import database.operations as operations

    writes = []
    monkeypatch.setattr(operations, "finish_operation", lambda *args: writes.append(args))
    operation = _Handle(_description(WorkflowExecutionStatus.RUNNING))
    first = SimpleNamespace(id="one", run_id="run-one", workflow_type="Grandchild")
    second = SimpleNamespace(id="two", run_id="run-two", workflow_type="Grandchild")
    first_handle = _Handle(_description(WorkflowExecutionStatus.RUNNING, attempt=5))
    second_handle = _Handle(_description(WorkflowExecutionStatus.RUNNING, attempt=5))
    client = _Client({
        ("op", None): operation,
        ("one", "run-one"): first_handle,
        ("two", "run-two"): second_handle,
    }, [first, second])
    asyncio.run(activities.supervise(client, datetime(2026, 1, 1), [_row()]))
    assert len(first_handle.terminated) == 1
    assert len(second_handle.terminated) == 1
    assert operation.cancelled
    assert writes == [(
        "op", "errored",
        "Workflow Grandchild one failed its workflow task 5 times, and 1 other workflows "
        "of this dataset were stuck. The worker log names the cause.",
    )]


def test_supervise_keeps_row_running_when_terminate_fails(monkeypatch):
    from temporalio.client import WorkflowExecutionStatus
    from tasks.P_ops import activities
    import database.operations as operations

    writes = []
    monkeypatch.setattr(operations, "finish_operation", lambda *args: writes.append(args))

    class Failure(Exception):
        status = object()

    monkeypatch.setattr(activities, "RPCError", Failure)
    operation = _Handle(_description(WorkflowExecutionStatus.RUNNING))
    child = _Handle(_description(WorkflowExecutionStatus.RUNNING, attempt=5))
    child.terminate = lambda **_kwargs: (_ for _ in ()).throw(Failure())
    execution = SimpleNamespace(id="child", run_id="run", workflow_type="Grandchild")
    client = _Client({("op", None): operation, ("child", "run"): child}, [execution])
    asyncio.run(activities.supervise(client, datetime(2026, 1, 1), [_row()]))
    assert writes == []
    assert not operation.cancelled


def test_supervise_continues_after_one_row_fails(monkeypatch):
    from tasks.P_ops import activities
    import database.operations as operations

    writes = []
    monkeypatch.setattr(operations, "finish_operation", lambda *args: writes.append(args))

    class NotFound(Exception):
        status = activities.RPCStatusCode.NOT_FOUND

    monkeypatch.setattr(activities, "RPCError", NotFound)
    first = _row(op_id="first")
    second = _row(op_id="second")
    client = _Client({
        ("first", None): _Handle(ValueError("bad row")),
        ("second", None): _Handle(NotFound()),
    })
    asyncio.run(activities.supervise(client, datetime(2026, 1, 1), [first, second]))
    assert writes == [("second", "errored", activities.WORKFLOW_ABSENT_ERROR)]


def test_supervise_refreshes_plan_progress(monkeypatch):
    from tasks.P_ops import activities

    calls = []
    monkeypatch.setattr(activities, "sample_dataset_progress", lambda params: calls.append(params))
    asyncio.run(activities.supervise(
        _Client({}), datetime(2026, 1, 1), [_row(kind="add_dataset", age=1)],
    ))
    assert calls[0].op_id == "op"


class _ActivityFailure(Exception):
    def __init__(self, cause=None):
        self.cause = cause


def test_collector_runs_supervision_after_sampling_failure(monkeypatch):
    from tasks.P_admin import workflows

    calls = []

    async def execute_activity(name, *_args, **_kwargs):
        calls.append(name.__name__)
        if name.__name__ == "collect_eta_samples":
            raise _ActivityFailure()
        return None

    async def stop(_seconds):
        raise RuntimeError("stop")

    monkeypatch.setattr(workflows, "ActivityError", _ActivityFailure)
    monkeypatch.setattr(workflows.workflow, "now", lambda: datetime(2026, 1, 1))
    monkeypatch.setattr(
        workflows.workflow, "logger", SimpleNamespace(warning=lambda *_args: None),
    )
    monkeypatch.setattr(workflows.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(workflows.workflow, "patched", lambda _patch_id: True)
    monkeypatch.setattr(workflows.asyncio, "sleep", stop)
    with pytest.raises(RuntimeError, match="stop"):
        asyncio.run(workflows.CollectEtaSamples().run())
    assert calls == ["collect_eta_samples", "supervise_operations", "supervise_agent_runs"]


def test_collector_starts_next_pass_after_supervision_failure(monkeypatch):
    from tasks.P_admin import workflows

    calls = []

    async def execute_activity(name, *_args, **_kwargs):
        calls.append(name.__name__)
        if name.__name__ == "supervise_operations":
            raise _ActivityFailure()
        return SimpleNamespace(
            duration_ms=1, completed_collections=[], active_collections=[],
        )

    async def stop(_seconds):
        raise RuntimeError("stop")

    monkeypatch.setattr(workflows, "ActivityError", _ActivityFailure)
    monkeypatch.setattr(workflows.workflow, "now", lambda: datetime(2026, 1, 1))
    monkeypatch.setattr(
        workflows.workflow, "logger", SimpleNamespace(warning=lambda *_args: None),
    )
    monkeypatch.setattr(workflows.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(workflows.workflow, "patched", lambda _patch_id: True)
    monkeypatch.setattr(workflows.asyncio, "sleep", stop)
    with pytest.raises(RuntimeError, match="stop"):
        asyncio.run(workflows.CollectEtaSamples().run())
    assert calls == ["collect_eta_samples", "supervise_operations", "supervise_agent_runs"]


def test_collector_reraises_a_cancelled_activity(monkeypatch):
    from tasks.P_admin import workflows

    async def execute_activity(_name, *_args, **_kwargs):
        raise _ActivityFailure(asyncio.CancelledError())

    monkeypatch.setattr(workflows, "ActivityError", _ActivityFailure)
    monkeypatch.setattr(workflows.workflow, "now", lambda: datetime(2026, 1, 1))
    monkeypatch.setattr(workflows.workflow, "execute_activity", execute_activity)
    with pytest.raises(_ActivityFailure):
        asyncio.run(workflows.CollectEtaSamples().run())


def test_a_collector_that_replays_with_no_patch_marker_skips_the_agent_run_sweep(monkeypatch):
    from tasks.P_admin import workflows

    calls = []
    patches = []

    async def execute_activity(name, *_args, **_kwargs):
        calls.append(name.__name__)
        return SimpleNamespace(duration_ms=1, completed_collections=[], active_collections=[])

    async def stop(_seconds):
        raise RuntimeError("stop")

    monkeypatch.setattr(workflows.workflow, "now", lambda: datetime(2026, 1, 1))
    monkeypatch.setattr(workflows.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(workflows.workflow, "patched",
                        lambda patch_id: patches.append(patch_id) or False)
    monkeypatch.setattr(workflows.asyncio, "sleep", stop)
    with pytest.raises(RuntimeError, match="stop"):
        asyncio.run(workflows.CollectEtaSamples().run())
    assert calls == ["collect_eta_samples", "supervise_operations"]
    assert patches == ["agent-run-sweep"]
