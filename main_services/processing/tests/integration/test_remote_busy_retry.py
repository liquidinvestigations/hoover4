"""Verify Temporal retries preserve busy state and ordinary failure counts."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

with workflow.unsafe.imports_passed_through():
    from tasks.heartbeat import with_heartbeat
    from tasks.remote import RemoteBusy
    from tasks.remote_busy_retry import with_remote_busy_retry

pytestmark = pytest.mark.integration
calls = {}


@activity.defn
@with_remote_busy_retry
@with_heartbeat
def request_service(kind: str) -> int:
    calls[kind] = calls.get(kind, 0) + 1
    if kind == "failure":
        raise ValueError("Request failed.")
    if calls[kind] <= 6:
        raise RemoteBusy(5)
    return calls[kind]


@workflow.defn
class BusyRetryWorkflow:
    @workflow.run
    async def run(self, kind: str) -> int:
        return await workflow.execute_activity(request_service, kind,
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=0))


@pytest.mark.parametrize("kind, expected", [("busy", 7), ("failure", 5)])
def test_temporal_retry_limits(kind, expected):
    calls.clear()
    async def run():
        async with await WorkflowEnvironment.start_time_skipping() as env:
            with ThreadPoolExecutor(max_workers=2) as executor:
                async with Worker(env.client, task_queue="remote-busy-test",
                    workflows=[BusyRetryWorkflow], activities=[request_service],
                    activity_executor=executor):
                    handle = await env.client.start_workflow(BusyRetryWorkflow.run, kind,
                        id=uuid4().hex, task_queue="remote-busy-test")
                    if kind == "failure":
                        with pytest.raises(WorkflowFailureError):
                            await asyncio.wait_for(handle.result(), 60)
                    else:
                        assert await asyncio.wait_for(handle.result(), 60) == 7
    asyncio.run(run())
    assert calls[kind] == expected
