"""Verify ingest rounds, failure counts, retries, and cancellation in Temporal."""

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from tasks.P2_execute_plan import workflows as plans
from tasks.P_ops import workflows as ops
from tasks.P_ops.params import OperationParams

pytestmark = pytest.mark.integration


@dataclass
class World:
    generation: int = 0
    finished: set[str] = field(default_factory=set)
    listed: set[str] = field(default_factory=set)
    runs: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    states: list[str] = field(default_factory=list)
    fail_plan: str = ""
    fail_step: str = ""
    transient: int = 0
    attempts: int = 0
    fail_compute: bool = False
    fail_record: bool = False
    blocked: asyncio.Event | None = None
    block: str = ""
    cancelled: asyncio.Event | None = None
    roots: int = 1
    listings: list[Any] = field(default_factory=list)
    documents: int = 0


world = World()


@activity.defn(name="ensure_temp_dir_exists")
async def ensure_temp(_params: Any) -> str:
    return "ok"


@activity.defn(name="list_pending_plans")
async def list_plans(params: Any) -> list[str]:
    candidates = ([f"p{n:04d}" for n in range(world.roots)] if not world.generation else [f"r{world.generation}"])
    start = params.get("starting_plan_hash") or ""
    exclude = params.get("exclude_failed_of_op", False) and params.get("op_id")
    result = [p for p in candidates if p >= start and p not in world.finished and (not exclude or p not in world.listed)][:1001]
    world.listings.append((start, exclude, result))
    world.listed.update(result)
    return result


@activity.defn(name="plan_body")
async def plan_body(params: Any) -> str:
    plan_hash = params["plan_hash"]
    world.runs.append(plan_hash)
    if world.block == "plan":
        await block()
    if plan_hash == world.fail_plan:
        raise ApplicationError("Plan file is missing.", non_retryable=True)
    world.finished.add(plan_hash)
    return "ok"


async def block():
    world.blocked.set()
    try:
        while True:
            activity.heartbeat()
            await asyncio.sleep(0.05)
    except asyncio.CancelledError:
        world.cancelled.set()
        raise


@activity.defn(name="count_new_blobs")
async def count_blobs(_params: Any) -> int:
    world.steps.append("count_new_blobs")
    return int(world.generation < 2)


@activity.defn(name="compute_body")
async def compute_body(_params: Any) -> str:
    world.steps.append("ComputePlans")
    if world.fail_compute:
        raise ApplicationError("Planning failed.", non_retryable=True)
    world.generation += 1
    return "ok"


@workflow.defn(name="ExecuteSinglePlan")
class Plan:
    @workflow.run
    async def run(self, params: dict) -> str:
        return await workflow.execute_activity("plan_body", params,
            start_to_close_timeout=timedelta(minutes=5), heartbeat_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=1))


@workflow.defn(name="ComputePlans")
class Compute:
    @workflow.run
    async def run(self, params: dict) -> str:
        return await workflow.execute_activity("compute_body", params,
            start_to_close_timeout=timedelta(minutes=5), retry_policy=RetryPolicy(maximum_attempts=1))


def dataset_step(name):
    @activity.defn(name=name)
    async def step(_params: Any) -> Any:
        world.steps.append(name)
        if world.block == name:
            await block()
        if world.fail_step == name:
            world.attempts += 1
            if not world.transient or world.attempts <= world.transient:
                raise RuntimeError("Dataset index failed.")
        if name == "refresh_stale_document_locations":
            return dict(collectionname="collection", collection_dataset="dataset", indexed_documents=0,
                        affected_count=0, refreshed_count=0, mechanism="test")
        return "ok"
    return step


@activity.defn(name="record_processing_errors")
async def record_errors(params: Any) -> int:
    if world.fail_record:
        raise ApplicationError("Failure storage failed.", non_retryable=True)
    world.errors.extend(params["errors"])
    return len(params["errors"])


@activity.defn(name="admit_operation")
async def admit(_op_id: str) -> str:
    return "running"


@activity.defn(name="record_operation_state")
async def state(params: Any) -> str:
    world.states.append(params["state"])
    return params["state"]


@activity.defn(name="sample_dataset_progress")
async def sample(_params: Any) -> dict:
    world.steps.append("sample")
    failed = sorted(world.listed - world.finished)
    return dict(done=len(world.finished), total=len(world.listed), failed_plans=len(failed),
        failed_dataset_steps=len(world.errors), failed_documents=world.documents,
        plan_samples=failed[:5], step_samples=[[r["task_name"], r["error_logs"][:500]] for r in world.errors[:5]])


@activity.defn(name="select_historical_errors")
async def select(_params: Any) -> dict:
    return dict(errors_before_run=0, selected_errors=0, removed_stage_off_errors=0, without_plan_errors=0)


@activity.defn(name="reconcile_selected_errors")
async def reconcile(_params: Any) -> dict:
    world.steps.append("reconcile")
    return {}


@activity.defn(name="capture_operation_failure")
async def capture(_params: Any) -> str:
    return "skipped"


async def run_operation(monkeypatch, configured, *, cancel=False, stop_worker=False):
    global world
    world = configured
    monkeypatch.setattr(plans, "dataset_search_attributes", lambda *_args: None)
    monkeypatch.setattr(ops, "dataset_search_attributes", lambda *_args: None)
    activities = [ensure_temp, list_plans, plan_body, count_blobs, compute_body, record_errors,
        admit, state, sample, select, reconcile, capture] + [dataset_step(name) for name in (
            "build_vfs_nodes", "resolve_canonical_file_type", "refresh_stale_document_locations",
            "index_vfs_structure", "index_entity_terms", "build_email_graph")]
    runner = SandboxedWorkflowRunner(restrictions=SandboxRestrictions.default.with_passthrough_modules(
        "tasks", "database", __name__))
    async with await WorkflowEnvironment.start_time_skipping() as env:
        workers = [Worker(env.client, task_queue=q,
            workflows=[plans.ExecutePlans, ops.Operation, Plan, Compute], activities=activities,
            workflow_runner=runner) for q in ("processing-common-queue", "processing-indexing-queue",
                "processing-email-graph-queue", "operations-queue", "operations-admission-queue")]
        async with workers[0], workers[1], workers[2], workers[3], workers[4]:
            handle = await env.client.start_workflow(ops.Operation.run,
                OperationParams(uuid4().hex, "execute_plans", "collection", "dataset"),
                id=uuid4().hex, task_queue="operations-queue")
            if cancel:
                await asyncio.wait_for(world.blocked.wait(), 30)
                before = (len(world.steps), world.generation, len(world.runs))
                await handle.cancel()
            replacement = None
            replacement_task = None
            if stop_worker:
                await asyncio.wait_for(world.blocked.wait(), 30)
                await workers[1].shutdown()
                world.block = ""
                replacement = Worker(env.client, task_queue="processing-indexing-queue",
                    workflows=[plans.ExecutePlans, ops.Operation, Plan, Compute],
                    activities=activities, workflow_runner=runner)
                replacement_task = asyncio.create_task(replacement.run())
            try:
                try:
                    result = await asyncio.wait_for(handle.result(), 60)
                except WorkflowFailureError:
                    result = None
            finally:
                if replacement:
                    await replacement.shutdown()
                    await replacement_task
            if cancel:
                if world.block != "plan":
                    await asyncio.wait_for(world.cancelled.wait(), 30)
                assert (len(world.steps), world.generation, len(world.runs)) == before
                assert (await handle.describe()).status.name == "CANCELED"
            return result


@pytest.mark.parametrize("failure", ["", "p0000", "r1"])
def test_all_rounds_run_after_plan_failure(monkeypatch, failure):
    configured = World(fail_plan=failure)
    result = asyncio.run(run_operation(monkeypatch, configured))
    assert configured.generation == 2
    assert len(configured.runs) == 3
    assert configured.states[-1] == ("errored" if failure else "finished")
    assert configured.steps[-2:] == ["reconcile", "sample"]
    assert (result is None) == bool(failure)


@pytest.mark.parametrize("transient", [0, 2])
def test_dataset_step_retries_and_preserves_later_rounds(monkeypatch, transient):
    configured = World(fail_step="index_vfs_structure", transient=transient)
    asyncio.run(run_operation(monkeypatch, configured))
    assert configured.generation == 2
    assert configured.states[-1] == ("finished" if transient else "errored")
    assert len(configured.errors) == (0 if transient else 3)
    if not transient:
        assert configured.attempts == 18
        assert all("Dataset index failed" in error["error_logs"] for error in configured.errors)


def test_continuation_runs_listed_sentinel_and_restart_excludes_failed(monkeypatch):
    configured = World(roots=1002, fail_plan="p0000")
    asyncio.run(run_operation(monkeypatch, configured))
    assert configured.runs.count("p0000") == 1
    assert "p1000" in configured.finished
    assert len(configured.runs) == 1004
    assert configured.generation == 2
    assert configured.states[-1] == "errored"
    assert configured.listings[1][0] == "p1000"
    assert configured.listings[1][1] is False
    assert configured.listings[-1][1]


def test_restart_planning_failure_reaches_operation(monkeypatch):
    configured = World(fail_compute=True)
    asyncio.run(run_operation(monkeypatch, configured))
    assert configured.states[-1] == "errored"


def test_missing_failure_ledger_keeps_operation_errored(monkeypatch):
    configured = World(fail_step="index_vfs_structure", fail_record=True)
    asyncio.run(run_operation(monkeypatch, configured))
    assert not configured.errors
    assert configured.generation == 2
    assert configured.states[-1] == "errored"


def test_document_failures_keep_finished_state(monkeypatch):
    configured = World(documents=2)
    result = asyncio.run(run_operation(monkeypatch, configured))
    assert configured.states[-1] == "finished"
    assert "2 document failures" in result


@pytest.mark.parametrize("during", ["index_vfs_structure", "plan"])
def test_cancellation_starts_no_further_work(monkeypatch, during):
    configured = World(block=during, blocked=asyncio.Event(), cancelled=asyncio.Event())
    asyncio.run(run_operation(monkeypatch, configured, cancel=True))
    assert "finished" not in configured.states


def test_worker_stop_retries_dataset_step_on_replacement_worker(monkeypatch):
    configured = World(block="index_vfs_structure", blocked=asyncio.Event(), cancelled=asyncio.Event())
    result = asyncio.run(run_operation(monkeypatch, configured, stop_worker=True))
    assert result is not None
    assert configured.generation == 2
    assert configured.steps.count("index_vfs_structure") == 4
    assert configured.states[-1] == "finished"
    assert not configured.errors
