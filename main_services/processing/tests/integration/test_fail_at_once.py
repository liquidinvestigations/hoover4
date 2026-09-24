"""Verify that a workflow fails on its first attempt for a large command or a code error.

Each test runs a `Worker` on its own task queue against the stack's Temporal. The worker
has the payload guard, the failure types of `tasks/run_worker.py` and test workflows only.
"Attempt 1" means that the history holds no `WorkflowTaskFailed` event.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from temporalio import activity, workflow
from temporalio.api.enums.v1 import EventType
from temporalio.client import Client, WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker

from tasks.payload_guard import PAYLOAD_TOO_LARGE, PayloadGuardInterceptor
from tasks.run_worker import WORKFLOW_FAILURE_EXCEPTION_TYPES

pytestmark = [pytest.mark.integration, pytest.mark.timeout(120)]

KB = 1000


@activity.defn
def p17_echo_size(text: str) -> int:
    return len(text)


def _start(text: str):
    return workflow.start_activity(
        p17_echo_size, text, start_to_close_timeout=timedelta(seconds=30))


@workflow.defn
class _P17OneLargeInput:
    @workflow.run
    async def run(self) -> int:
        return await _start("x" * (600 * KB))


@workflow.defn
class _P17ManySmallInputs:
    @workflow.run
    async def run(self) -> int:
        handles = [_start("x" * (100 * KB)) for _ in range(12)]
        return sum(await asyncio.gather(*handles))


@workflow.defn
class _P17SmallInputsOverTwoTasks:
    @workflow.run
    async def run(self) -> int:
        handles = [_start("x" * (100 * KB)) for _ in range(6)]
        await workflow.sleep(timedelta(seconds=1))
        handles += [_start("x" * (100 * KB)) for _ in range(6)]
        return sum(await asyncio.gather(*handles))


@workflow.defn
class _P17LargeResult:
    @workflow.run
    async def run(self) -> str:
        return "x" * (600 * KB)


@workflow.defn
class _P17CodeError:
    @workflow.run
    async def run(self) -> None:
        raise ValueError("p17 test code error")


WORKFLOWS = [_P17OneLargeInput, _P17ManySmallInputs, _P17SmallInputsOverTwoTasks,
             _P17LargeResult, _P17CodeError]


async def _run(workflow_run, check) -> None:
    task_queue = f"p17-test-{uuid4()}"
    client = await Client.connect("temporal:7233")
    handle = None
    try:
        async with Worker(
            client, task_queue=task_queue,
            workflows=WORKFLOWS,
            activities=[p17_echo_size],
            activity_executor=ThreadPoolExecutor(4),
            interceptors=[PayloadGuardInterceptor()],
            workflow_failure_exception_types=WORKFLOW_FAILURE_EXCEPTION_TYPES,
        ):
            handle = await client.start_workflow(
                workflow_run, id=f"p17-fail-at-once-{uuid4()}", task_queue=task_queue,
                execution_timeout=timedelta(seconds=60),
            )
            await check(handle)
    finally:
        if handle is not None:
            try:
                await handle.terminate(reason="p17 integration cleanup")
            except Exception:
                pass


async def _task_failures(handle) -> int:
    history = await handle.fetch_history()
    return sum(1 for event in history.events
               if event.event_type == EventType.EVENT_TYPE_WORKFLOW_TASK_FAILED)


async def _expect_failure(handle, failure_type: str | None) -> BaseException:
    with pytest.raises(WorkflowFailureError) as raised:
        await asyncio.wait_for(handle.result(), timeout=30)
    cause = raised.value.cause
    if failure_type is not None:
        assert isinstance(cause, ApplicationError), cause
        assert cause.type == failure_type, cause
        assert cause.non_retryable
    assert await _task_failures(handle) == 0
    return cause


def test_one_large_payload_fails_at_once():
    async def check(handle):
        cause = await _expect_failure(handle, PAYLOAD_TOO_LARGE)
        assert "start_activity of p17_echo_size" in str(cause)

    asyncio.run(_run(_P17OneLargeInput.run, check))


def test_many_small_payloads_in_one_task_fail_at_once():
    async def check(handle):
        cause = await _expect_failure(handle, PAYLOAD_TOO_LARGE)
        assert "and the limits are 524288 and 1048576" in str(cause)

    asyncio.run(_run(_P17ManySmallInputs.run, check))


def test_small_payloads_over_two_tasks_complete():
    async def check(handle):
        result = await asyncio.wait_for(handle.result(), timeout=30)
        assert result == 12 * 100 * KB

    asyncio.run(_run(_P17SmallInputsOverTwoTasks.run, check))


def test_large_result_fails():
    async def check(handle):
        cause = await _expect_failure(handle, PAYLOAD_TOO_LARGE)
        assert "result of _P17LargeResult" in str(cause)

    asyncio.run(_run(_P17LargeResult.run, check))


def test_code_error_fails_on_first_attempt():
    async def check(handle):
        cause = await _expect_failure(handle, None)
        assert isinstance(cause, ApplicationError), cause
        assert cause.type == "ValueError", cause

    asyncio.run(_run(_P17CodeError.run, check))
