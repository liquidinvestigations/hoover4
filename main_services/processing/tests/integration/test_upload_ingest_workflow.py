"""Verify upload preparation across a worker restart and legacy history replay."""

import asyncio
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from datetime import timedelta
from uuid import uuid4

import pytest
from temporalio import activity, workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.client import Client
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from tasks.P_admin.rerun_params import SelectionResult
from tasks.P_upload import workflows
from tasks.P_upload.params import IngestUploadBatchesParams, UploadBatchLimitsResult

pytestmark = pytest.mark.integration


@workflow.defn(name="ComputePlans")
class Compute:
    @workflow.run
    async def run(self, _params: dict) -> dict:
        return {}


@workflow.defn(name="ExecutePlans")
class Execute:
    @workflow.run
    async def run(self, _params: dict) -> dict:
        return {"finished": 1}


class World:
    def __init__(self, queue="processing-common-queue"):
        self.queue = queue
        self.op_id = "review-" + uuid4().hex
        self.ingested = set()
        self.selected = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    @activity.defn(name="upload_batch_limits")
    async def limits(self, _params: dict) -> UploadBatchLimitsResult:
        return UploadBatchLimitsResult(ingest_seconds=60)

    @activity.defn(name="ingest_upload_paths")
    async def ingest(self, params: dict) -> dict:
        if params["batch_id"] == "b2":
            self.entered.set()
            while not self.release.is_set():
                activity.heartbeat()
                await asyncio.sleep(0.05)
        self.ingested.add(params["batch_id"])
        return {}

    @activity.defn(name="select_historical_errors")
    async def select(self, _params: dict) -> SelectionResult:
        self.selected.append(sorted(self.ingested))
        return SelectionResult(selected_errors=len(self.ingested))

    @activity.defn(name="finish_upload_batches")
    async def finish(self, _params: dict) -> dict:
        return {"completed": 1}

    @activity.defn(name="reconcile_selected_errors")
    async def reconcile(self, _params: dict) -> dict:
        return {}

    def worker(self, client):
        return Worker(client, task_queue=self.queue,
                      workflows=[workflows.IngestUploadBatches, Compute, Execute],
                      activities=[self.limits, self.ingest, self.select, self.finish, self.reconcile],
                      workflow_runner=UnsandboxedWorkflowRunner(),
                      graceful_shutdown_timeout=timedelta(seconds=0))


@pytest.mark.parametrize("restart", [False, True])
def test_all_batches_are_selected_after_preparation_and_worker_restart(monkeypatch, restart):
    monkeypatch.setattr(workflows, "dataset_search_attributes", lambda _dataset: {})
    address = os.environ.get("HOOVER4_TEST_TEMPORAL_ADDRESS") if restart else None
    if restart and not address:
        pytest.skip("Set HOOVER4_TEST_TEMPORAL_ADDRESS for the real-server worker restart case.")
    queue = "review-upload-" + uuid4().hex if restart else "processing-common-queue"
    original_child = workflow.execute_child_workflow
    original_activity = workflow.execute_activity

    async def child(*args, **kwargs):
        kwargs["task_queue"] = queue
        return await original_child(*args, **kwargs)

    monkeypatch.setattr(workflow, "execute_child_workflow", child)

    async def execute(*args, **kwargs):
        kwargs["task_queue"] = queue
        return await original_activity(*args, **kwargs)

    monkeypatch.setattr(workflow, "execute_activity", execute)

    @asynccontextmanager
    async def environment():
        if address:
            yield SimpleNamespace(client=await Client.connect(address))
        else:
            async with await WorkflowEnvironment.start_time_skipping() as env:
                yield env

    async def run():
        world = World(queue)
        if restart:
            world.release.clear()
        async with environment() as env:
            async with world.worker(env.client):
                handle = await env.client.start_workflow(
                    workflows.IngestUploadBatches.run,
                    IngestUploadBatchesParams("c", "c_d", world.op_id, ["b1", "b2"]),
                    id="upload-review-" + uuid4().hex, task_queue=world.queue)
                if restart:
                    await asyncio.wait_for(world.entered.wait(), timeout=20)
                    assert world.ingested == {"b1"}
                    assert world.selected == []
                    # Let the current activity finish while the first worker drains.
                    # Its workflow task resumes only after the replacement worker starts.
                    asyncio.get_running_loop().call_later(0.2, world.release.set)
                else:
                    result = await asyncio.wait_for(handle.result(), timeout=30)
            if restart:
                world.release.set()
                async with world.worker(env.client):
                    result = await asyncio.wait_for(handle.result(), timeout=30)
            assert world.selected == [["b1", "b2"]]
            assert result["batch_states"] == {"completed": 2}
            assert result["execution_counts"] == {"finished": 2}
            await Replayer(workflows=[workflows.IngestUploadBatches],
                           workflow_runner=UnsandboxedWorkflowRunner()).replay_workflow(await handle.fetch_history())

    asyncio.run(run())


def test_history_without_the_preparation_patch_replays_on_current_code(monkeypatch):
    monkeypatch.setattr(workflows, "dataset_search_attributes", lambda _dataset: {})
    original_patched = workflow.patched

    async def run():
        world = World()
        async with await WorkflowEnvironment.start_time_skipping() as env:
            monkeypatch.setattr(workflow, "patched", lambda marker: False if marker == "upload-prepare-all-batches" else original_patched(marker))
            async with world.worker(env.client):
                handle = await env.client.start_workflow(
                    workflows.IngestUploadBatches.run,
                    IngestUploadBatchesParams("c", "c_d", world.op_id, ["b1", "b2"]),
                    id="upload-review-legacy-" + uuid4().hex, task_queue=world.queue)
                await handle.result()
            assert world.selected == [["b1"]]
            history = await handle.fetch_history()
            monkeypatch.setattr(workflow, "patched", original_patched)
            await Replayer(workflows=[workflows.IngestUploadBatches],
                           workflow_runner=UnsandboxedWorkflowRunner()).replay_workflow(history)

    asyncio.run(run())
