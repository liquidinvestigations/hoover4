"""`UploadQueue` against the Temporal time-skipping server, with in-memory activities.

The fake activities keep the waiting batches, the claims and the operation states in one
`World`, as ClickHouse does for the real ones. A fake `Operation` stays running while the
world blocks it. No datastore is used, but the test server binary must be available.
"""

import asyncio
import collections
import json
import sys
from datetime import timedelta
from uuid import uuid4

import pytest
from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from tasks.P_ops.params import OperationParams
from tasks.P_upload import workflows as upload_workflows
from tasks.P_upload.params import UploadClaimResult, UploadOperationParams, UploadQueueParams

pytestmark = pytest.mark.integration

DATASET = "coll_uploads"
#: The wait of the fake operation between two checks of the block.
OPERATION_POLL = timedelta(seconds=45)
QUEUE_ID = "upload-queue-" + DATASET


class World:
    def __init__(self, batches=0, partial_failure=False):
        self.queued = [f"b{i:04d}" for i in range(batches)]
        self.claims: dict[str, str] = {}
        self.ops: dict[str, str] = {}
        self.op_batches: dict[str, list[str]] = {}
        self.settled = collections.Counter()
        self.starts = collections.Counter()
        self.cancelled: list[str] = []
        self.block = False
        self.partial_failure = partial_failure
        self.claim_calls = 0
        self.after_idle = None
        self.client = None
        self.added = 0
        self.dataset = DATASET
        self.queue_id = QUEUE_ID
        self.task_queue = "processing-common-queue"

    def add(self, count):
        for _ in range(count):
            self.queued.append(f"n{self.added:04d}")
            self.added += 1


world = World()


@activity.defn(name="open_upload_operation")
async def open_upload_operation(params: UploadOperationParams) -> UploadClaimResult:
    world.claim_calls += 1
    if world.after_idle is not None and not world.queued and not [
            op for op, state in world.ops.items() if state in ("pending", "queued", "running")]:
        hook, world.after_idle = world.after_idle, None
        await hook()
        return UploadClaimResult()
    for op_id, state in world.ops.items():
        if state in ("pending", "queued", "running"):
            for batch in world.op_batches[op_id]:
                if batch in world.queued:
                    world.queued.remove(batch)
                    world.claims[batch] = op_id
            return UploadClaimResult(op_id, [b for b, o in world.claims.items() if o == op_id
                                       and not world.settled[b]], state)
    if not world.queued:
        return UploadClaimResult()
    group = world.queued[:50]
    world.ops[params.op_id] = "pending"
    world.op_batches[params.op_id] = list(group)
    if world.partial_failure:
        world.partial_failure = False
        for batch in group[: len(group) // 2]:
            world.queued.remove(batch)
            world.claims[batch] = params.op_id
        raise RuntimeError("the worker stopped during the claim")
    for batch in group:
        world.queued.remove(batch)
        world.claims[batch] = params.op_id
    return UploadClaimResult(params.op_id, list(group), "pending")


@activity.defn(name="upload_operation_state")
async def upload_operation_state(op_id: str) -> str:
    return world.ops.get(op_id, "missing")


@activity.defn(name="settle_upload_operation")
async def settle_upload_operation(params: UploadOperationParams) -> dict:
    for batch, op_id in world.claims.items():
        if op_id == params.op_id and world.ops[op_id] in ("finished", "errored", "cancelled"):
            world.settled[batch] += 1
    return {}


@activity.defn(name="cancel_upload_operation")
async def cancel_upload_operation(op_id: str) -> str:
    world.cancelled.append(op_id)
    world.ops[op_id] = "cancelled"
    return "cancelled"


@activity.defn(name="fake_operation_step")
async def fake_operation_step(op_id: str) -> bool:
    if world.ops.get(op_id) == "pending":
        world.ops[op_id] = "running"
    if world.block:
        return False
    if world.ops.get(op_id) == "running":
        world.ops[op_id] = "finished"
    return True


@workflow.defn(name="Operation")
class FakeOperation:
    @workflow.run
    async def run(self, params: OperationParams) -> str:
        await workflow.execute_activity(
            "fake_operation_started", params.op_id, start_to_close_timeout=timedelta(seconds=10))
        while not await workflow.execute_activity(
                fake_operation_step, params.op_id, start_to_close_timeout=timedelta(seconds=10)):
            await workflow.sleep(OPERATION_POLL)
        return "done"


@activity.defn(name="fake_operation_started")
async def fake_operation_started(op_id: str) -> None:
    world.starts[op_id] += 1


class _ServerEnv:
    """The local Temporal server, for a case that the test server does not support."""

    def __init__(self, client):
        self.client = client


async def _workers(client, body, env, queue_name, operations_name):
    runner = SandboxedWorkflowRunner(restrictions=SandboxRestrictions.default.with_passthrough_modules(
        "tasks", "database", __name__))
    world.client = client
    queue = Worker(client, task_queue=queue_name,
                   workflows=[upload_workflows.UploadQueue],
                   activities=[open_upload_operation, upload_operation_state,
                               settle_upload_operation, cancel_upload_operation],
                   workflow_runner=runner)
    ops = Worker(client, task_queue=operations_name, workflows=[FakeOperation],
                 activities=[fake_operation_step, fake_operation_started],
                 workflow_runner=runner)
    async with queue, ops:
        return await body(env)


async def _with_env(body):
    world.task_queue = "processing-common-queue"
    async with await WorkflowEnvironment.start_time_skipping() as env:
        return await _workers(env.client, body, env, world.task_queue, "operations-queue")


async def _with_server(body, monkeypatch):
    """Run on the local Temporal server with task queues that no deployed worker polls."""
    from temporalio.client import Client

    suffix = uuid4().hex[:12]
    world.task_queue = f"test-upload-queue-{suffix}"
    operations_name = f"test-upload-operations-{suffix}"
    monkeypatch.setattr(upload_workflows, "OPERATION_TASK_QUEUE", operations_name)
    client = await Client.connect("temporal:7233")
    return await _workers(client, body, _ServerEnv(client), world.task_queue, operations_name)


async def _signal(env, batch_id="x"):
    return await env.client.start_workflow(
        "UploadQueue", UploadQueueParams("coll", world.dataset), id=world.queue_id,
        task_queue=world.task_queue, start_signal="upload_committed",
        start_signal_args=[{"batch_id": batch_id}])


async def _runs(env):
    """Every run of the queue, oldest first: (run_id, events, continuation input bytes)."""
    runs = []
    handle = env.client.get_workflow_handle(world.queue_id)
    run_id = (await handle.describe()).run_id
    while run_id:
        history = await env.client.get_workflow_handle(world.queue_id, run_id=run_id).fetch_history()
        events = history.events
        first = events[0].workflow_execution_started_event_attributes
        last = events[-1]
        size = 0
        if last.HasField("workflow_execution_continued_as_new_event_attributes"):
            size = sum(len(p.data) for p in
                       last.workflow_execution_continued_as_new_event_attributes.input.payloads)
        runs.append((run_id, len(events), size,
                     max((len(p.data) for e in events for p in _payloads(e)), default=0)))
        run_id = first.continued_execution_run_id
    return list(reversed(runs))


def _payloads(event):
    for field in ("workflow_execution_signaled_event_attributes",
                  "activity_task_scheduled_event_attributes",
                  "activity_task_completed_event_attributes",
                  "start_child_workflow_execution_initiated_event_attributes",
                  "workflow_execution_continued_as_new_event_attributes",
                  "workflow_execution_started_event_attributes"):
        if event.HasField(field):
            attrs = getattr(event, field)
            for name in ("input", "result"):
                if hasattr(attrs, name):
                    yield from getattr(attrs, name).payloads


def _settled_once():
    assert all(count == 1 for count in world.settled.values()), world.settled
    assert set(world.settled) == set(world.claims)


def test_duplicate_signals_start_one_operation():
    global world
    world = World(batches=1)

    async def body(env):
        handle = await _signal(env, "b0000")
        for _ in range(5):
            await handle.signal("upload_committed", {"batch_id": "b0000"})
        assert await handle.result() == "idle"

    asyncio.run(_with_env(body))
    assert len(world.ops) == 1 and list(world.ops.values()) == ["finished"]
    assert sum(world.starts.values()) == 1
    _settled_once()


def test_an_empty_claim_starts_nothing_and_the_queue_ends_idle():
    global world
    world = World(batches=0)

    async def body(env):
        handle = await _signal(env)
        assert await handle.result() == "idle"

    asyncio.run(_with_env(body))
    assert world.ops == {} and not world.starts


def test_a_partial_claim_is_recovered_by_the_retry():
    global world
    world = World(batches=7, partial_failure=True)

    async def body(env):
        handle = await _signal(env)
        assert await handle.result() == "idle"

    asyncio.run(_with_env(body))
    assert len(world.ops) == 1
    [op_id] = world.ops
    assert sorted(b for b, o in world.claims.items() if o == op_id) == [f"b{i:04d}" for i in range(7)]
    assert world.starts[op_id] == 1
    _settled_once()


def test_a_signal_at_idle_completion_is_not_lost():
    global world
    world = World(batches=0)

    async def commit_now():
        world.add(1)
        await world.client.get_workflow_handle(world.queue_id).signal(
            "upload_committed", {"batch_id": "n0000"})

    world.after_idle = commit_now

    async def body(env):
        handle = await _signal(env)
        assert await handle.result() == "idle"
        # A commit after the queue ended starts a new run through signal-with-start.
        world.add(1)
        second = await _signal(env, "n0001")
        assert await second.result() == "idle"

    asyncio.run(_with_env(body))
    assert sorted(world.claims) == ["n0000", "n0001"]
    assert sum(world.starts.values()) == 2
    _settled_once()


def test_a_blocked_operation_with_many_signals_continues_as_new_and_loses_nothing(monkeypatch):
    # The time-skipping test server fails a workflow task that continues as new while
    # signals arrive ("invalid history builder state for action"), and it skips no time
    # for a chain of runs. This case therefore runs on the local Temporal server, on task
    # queues of its own, on the real clock with short waits.
    monkeypatch.setattr(upload_workflows, "STATUS_POLL", timedelta(seconds=1))
    monkeypatch.setattr(upload_workflows, "IDLE_TIMEOUT", timedelta(seconds=3))
    monkeypatch.setattr(sys.modules[__name__], "OPERATION_POLL", timedelta(seconds=1))
    global world
    world = World(batches=1)
    world.dataset = "test_" + uuid4().hex[:12]
    world.queue_id = "upload-queue-" + world.dataset
    world.block = True
    measured = {}

    async def body(env):
        handle = await _signal(env, "b0000")
        while not world.starts:
            await asyncio.sleep(0.05)
        # More signals than one history threshold, while the operation is blocked, and
        # new batches beside them. Signals keep arriving across the continuations.
        for i in range(1500):
            if i % 10 == 0:
                world.add(1)
            await env.client.get_workflow_handle(world.queue_id).signal(
                "upload_committed", {"batch_id": f"n{i:04d}"})
            await asyncio.sleep(0.002)
        await asyncio.sleep(2)
        runs_while_blocked = await _runs(env)
        world.block = False
        for i in range(30):
            world.add(1)
            await env.client.get_workflow_handle(world.queue_id).signal(
                "upload_committed", {"batch_id": f"late{i}"})
        for _ in range(600):
            description = await env.client.get_workflow_handle(world.queue_id).describe()
            if description.status.name == "COMPLETED":
                break
            await asyncio.sleep(0.5)
        assert description.status.name == "COMPLETED"
        measured["blocked_runs"] = runs_while_blocked
        measured["runs"] = await _runs(env)

    asyncio.run(_with_server(body, monkeypatch))
    runs = measured["runs"]
    print(json.dumps({"runs": len(runs), "events": [r[1] for r in runs],
                      "continuation_input_bytes": [r[2] for r in runs],
                      "largest_payload_bytes": max(r[3] for r in runs)}))
    assert len(measured["blocked_runs"]) >= 3, measured["blocked_runs"]
    # A run continues at the first task after 1,000 events. Signals that the server
    # recorded before that task add to the run, so the bound is above the threshold.
    assert max(r[1] for r in runs) < 2_000
    assert max(r[2] for r in runs) < 512
    assert max(r[3] for r in runs) < 8_192
    # One start of each operation, whatever number of runs the queue had.
    assert set(world.starts.values()) == {1}
    first = next(iter(world.ops))
    assert world.op_batches[first] == ["b0000"]
    assert all(len(batches) <= 50 for batches in world.op_batches.values())
    assert sorted(world.claims) == sorted(["b0000"] + [f"n{i:04d}" for i in range(world.added)])
    assert not world.queued
    _settled_once()


def test_cancelling_the_queue_cancels_its_operation_through_the_finalizer():
    global world
    world = World(batches=2)
    world.block = True

    async def body(env):
        handle = await _signal(env)
        while not world.starts:
            await asyncio.sleep(0.05)
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await handle.result()
        assert (await handle.describe()).status.name == "CANCELED"

    asyncio.run(_with_env(body))
    [op_id] = world.ops
    assert world.cancelled == [op_id]
    assert world.ops[op_id] == "cancelled"
    _settled_once()


def test_a_queue_continued_with_an_active_operation_does_not_start_it_again():
    global world
    world = World(batches=0)
    world.ops["op-old"] = "running"
    world.op_batches["op-old"] = ["b-old"]
    world.claims["b-old"] = "op-old"

    async def body(env):
        handle = await env.client.start_workflow(
            "UploadQueue", UploadQueueParams("coll", DATASET, active_op_id="op-old"),
            id=world.queue_id, task_queue=world.task_queue)
        await env.sleep(timedelta(minutes=5))
        world.ops["op-old"] = "finished"
        assert await handle.result() == "idle"

    asyncio.run(_with_env(body))
    assert not world.starts
    assert world.settled["b-old"] == 1
