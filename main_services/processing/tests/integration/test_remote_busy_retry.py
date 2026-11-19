"""Verify Temporal retries preserve busy state, outage state and ordinary failure counts."""

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
    from tasks.remote import RemoteBusy, RemoteOutage, RemoteReadTimeout
    from tasks.remote_busy_retry import with_remote_busy_retry, with_remote_outage_retry

pytestmark = pytest.mark.integration
calls = {}
clock = [0.0]


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


@activity.defn
@with_remote_outage_retry
@with_heartbeat
def request_ner(kind: str) -> int:
    calls[kind] = calls.get(kind, 0) + 1
    if kind == "outage" and calls[kind] <= 8:
        raise RemoteOutage("connection refused")
    if kind == "expiry":
        # The wrapper reads the wall clock, which time skipping does not move.
        clock[0] += 3600
        raise RemoteOutage("connection refused")
    if kind == "timeout":
        raise RemoteReadTimeout("read timed out")
    return calls[kind]


@workflow.defn
class OutageRetryWorkflow:
    @workflow.run
    async def run(self, kind: str) -> int:
        return await workflow.execute_activity(request_ner, kind,
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=0))


@pytest.mark.parametrize("kind, expected, error", [
    ("outage", 9, ""), ("timeout", 5, "RemoteReadTimeout"), ("expiry", None, "ServiceOutage")])
def test_temporal_outage_retries(kind, expected, error, monkeypatch):
    """An outage waits beyond five attempts, and the 12-hour budget then ends it."""
    import types

    import tasks.remote_busy_retry as retry

    calls.clear()
    clock[0] = 1000.0
    monkeypatch.setattr(retry, "time", types.SimpleNamespace(time=lambda: clock[0]))

    async def run():
        async with await WorkflowEnvironment.start_time_skipping() as env:
            with ThreadPoolExecutor(max_workers=2) as executor:
                async with Worker(env.client, task_queue="remote-outage-test",
                    workflows=[OutageRetryWorkflow], activities=[request_ner],
                    activity_executor=executor):
                    handle = await env.client.start_workflow(OutageRetryWorkflow.run, kind,
                        id=uuid4().hex, task_queue="remote-outage-test")
                    if error:
                        with pytest.raises(WorkflowFailureError) as excinfo:
                            await asyncio.wait_for(handle.result(), 300)
                        cause = excinfo.value.cause.cause
                        assert cause.type == error
                    else:
                        assert await asyncio.wait_for(handle.result(), 300) == expected
    asyncio.run(run())
    if expected is not None:
        assert calls[kind] == expected
    else:
        # Each attempt moves the clock one hour. The budget starts at the first refusal,
        # so the thirteenth attempt is 12 hours after it.
        assert calls[kind] == 13
