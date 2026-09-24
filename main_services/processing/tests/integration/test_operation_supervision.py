"""Verify that supervision terminates every stuck workflow in an operation tree."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from temporalio import workflow
from temporalio.client import Client, WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.worker import Worker

from tasks.P_ops.activities import supervise, supervise_operations
from tasks.visibility import dataset_search_attributes, ensure_search_attributes
from tasks.workflow_window import run_with_window

pytestmark = [pytest.mark.integration, pytest.mark.timeout(60)]


@workflow.defn
class _P17StuckGrandchild:
    @workflow.run
    async def run(self) -> None:
        raise RuntimeError("p17 test workflow task failure")


@workflow.defn
class _P17StuckChild:
    @workflow.run
    async def run(self, dataset: str, task_queue: str) -> None:
        await run_with_window([
            lambda: workflow.execute_child_workflow(
                _P17StuckGrandchild.run, id=f"p17-grandchild-a-{dataset}",
                task_queue=task_queue,
                search_attributes=dataset_search_attributes(dataset),
            ),
            lambda: workflow.execute_child_workflow(
                _P17StuckGrandchild.run, id=f"p17-grandchild-b-{dataset}",
                task_queue=task_queue,
                search_attributes=dataset_search_attributes(dataset),
            ),
        ], limit=2)


@workflow.defn
class _P17OperationShape:
    @workflow.run
    async def run(self, dataset: str, task_queue: str) -> None:
        await workflow.execute_child_workflow(
            _P17StuckChild.run, args=[dataset, task_queue], id=f"p17-child-{dataset}",
            task_queue=task_queue,
        )


@workflow.defn
class _P17SuperviseOnce:
    @workflow.run
    async def run(self) -> None:
        return await workflow.execute_activity(
            supervise_operations,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


def test_registered_supervise_activity_completes_on_worker(monkeypatch):
    """Run the registered activity the way the collector does, through a worker."""
    import database.operations as operations

    monkeypatch.setattr(operations, "live_operations", lambda limit=500: [])

    async def run() -> None:
        task_queue = f"p17-test-{uuid4()}"
        client = await Client.connect("temporal:7233")
        async with Worker(
            client, task_queue=task_queue,
            workflows=[_P17SuperviseOnce],
            activities=[supervise_operations],
            activity_executor=ThreadPoolExecutor(2),
        ):
            result = await client.execute_workflow(
                _P17SuperviseOnce.run, id=f"p17-supervise-{uuid4()}",
                task_queue=task_queue,
            )
        assert result is None

    asyncio.run(run())


def test_supervision_terminates_stuck_operation_tree(monkeypatch):
    async def run() -> None:
        from tasks.P_ops import activities
        import database.operations as operations

        task_queue = f"p17-test-{uuid4()}"
        dataset = f"p17-dataset-{uuid4()}"
        op_id = f"p17-operation-{uuid4()}"
        writes = []
        monkeypatch.setattr(operations, "finish_operation", lambda *args: writes.append(args))
        monkeypatch.setattr(activities, "sample_dataset_progress", lambda _params: None)
        client = await Client.connect("temporal:7233")
        await ensure_search_attributes(client)
        root = await client.start_workflow(
            _P17OperationShape.run, args=[dataset, task_queue], id=op_id,
            task_queue=task_queue,
        )
        row = {
            "op_id": op_id,
            "state": "running",
            "kind": "add_dataset",
            "started_at": datetime.now() - timedelta(seconds=121),
            "collectionname": "p17",
            "collection_dataset": dataset,
            "progress_total": 0,
        }
        try:
            async with Worker(
                client, task_queue=task_queue,
                workflows=[_P17OperationShape, _P17StuckChild, _P17StuckGrandchild],
            ):
                for _ in range(60):
                    await supervise(client, datetime.now(), [row], stuck_workflow_attempts=2)
                    if writes:
                        break
                    await asyncio.sleep(1)
                assert writes and writes[0][0:2] == (op_id, "errored")
                assert "and 1 other workflows" in writes[0][2]
                with pytest.raises(WorkflowFailureError):
                    await asyncio.wait_for(root.result(), timeout=20)
        finally:
            try:
                await root.terminate(reason="p17 integration cleanup")
            except Exception:
                pass

    asyncio.run(run())
