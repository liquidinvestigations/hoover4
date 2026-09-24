"""Fail a workflow on its first attempt when one of its commands is too large.

Temporal refuses a command whose payload passes the server's blob limit, and it refuses a
workflow task whose commands together pass the gRPC message limit. The server then fails
the workflow task, and Temporal 1.23 retries a failed workflow task at once and without a
limit. The workflow never fails, and it never makes progress.

This interceptor measures each command's input before the SDK sends it, and the
workflow's own result after the workflow returns. It raises a non-retryable
``ApplicationError`` of type ``PayloadTooLarge`` when one payload passes
``MAX_PAYLOAD_BYTES``, or when the commands of one workflow task pass
``MAX_ACTIVATION_BYTES`` together. An ``ApplicationError`` in workflow code fails the
workflow, so the parent sees a child failure that names the call and both sizes.

No interceptor method of SDK 1.16 runs at the start of an activation. The guard keys its
running sum on ``workflow.info().get_current_history_length()``, which the SDK sets from
each activation. When the value changes, a new workflow task has begun and the sum starts
again at 0. A refused call is not added to the sum, because the SDK does not send it.

The guard measures with the worker's own converter, ``workflow.payload_converter()``.
The size of a payload is the byte size of its ``data`` and of its ``metadata``.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from temporalio import workflow
from temporalio.exceptions import ApplicationError
from temporalio.worker import (
    ContinueAsNewInput,
    ExecuteWorkflowInput,
    Interceptor,
    SignalChildWorkflowInput,
    SignalExternalWorkflowInput,
    StartActivityInput,
    StartChildWorkflowInput,
    StartLocalActivityInput,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
    WorkflowOutboundInterceptor,
)

#: The largest single payload that a command may carry. The server's blob limit is 2 MB.
MAX_PAYLOAD_BYTES = 512 * 1024
#: The largest sum of payload sizes over the commands of one workflow task.
MAX_ACTIVATION_BYTES = 1024 * 1024

PAYLOAD_TOO_LARGE = "PayloadTooLarge"


def payload_size(payload: Any) -> int:
    """The byte size of the data and the metadata of one payload."""
    size = len(payload.data)
    for key, value in payload.metadata.items():
        size += len(key.encode("utf-8")) + len(value)
    return size


class PayloadGuardInterceptor(Interceptor):
    """Install on every ``Worker``. One guard state exists for each workflow run."""

    def workflow_interceptor_class(self, input: WorkflowInterceptorClassInput):
        return _PayloadGuardInbound


class _PayloadGuardInbound(WorkflowInboundInterceptor):
    """The SDK creates one instance for each workflow run, so it holds the running sum."""

    def __init__(self, next: WorkflowInboundInterceptor) -> None:
        super().__init__(next)
        self.sum_at: Optional[int] = None
        self.sum = 0

    def init(self, outbound: WorkflowOutboundInterceptor) -> None:
        super().init(_PayloadGuardOutbound(outbound, self))

    async def execute_workflow(self, input: ExecuteWorkflowInput) -> Any:
        result = await self.next.execute_workflow(input)
        self.check("result", getattr(input.type, "__name__", "") or "", [result])
        return result

    def check(self, call_name: str, target_type: str, args: Sequence[Any]) -> None:
        """Raise ``PayloadTooLarge`` when this call would pass a limit."""
        length = workflow.info().get_current_history_length()
        if length != self.sum_at:
            self.sum_at, self.sum = length, 0
        encoded = workflow.payload_converter().to_payloads(list(args))
        sizes = [payload_size(p) for p in encoded]
        largest = max(sizes, default=0)
        total = self.sum + sum(sizes)
        if largest > MAX_PAYLOAD_BYTES or total > MAX_ACTIVATION_BYTES:
            raise ApplicationError(
                f"{call_name} of {target_type} was refused: its largest payload is "
                f"{largest} bytes and this workflow task's commands hold {total} bytes, "
                f"and the limits are {MAX_PAYLOAD_BYTES} and {MAX_ACTIVATION_BYTES}.",
                type=PAYLOAD_TOO_LARGE,
                non_retryable=True,
            )
        self.sum = total


class _PayloadGuardOutbound(WorkflowOutboundInterceptor):
    def __init__(self, next: WorkflowOutboundInterceptor, guard: _PayloadGuardInbound) -> None:
        super().__init__(next)
        self._guard = guard

    def continue_as_new(self, input: ContinueAsNewInput):
        target = input.workflow or workflow.info().workflow_type
        self._guard.check("continue_as_new", str(target), input.args)
        return self.next.continue_as_new(input)

    def start_activity(self, input: StartActivityInput):
        self._guard.check("start_activity", input.activity, input.args)
        return self.next.start_activity(input)

    def start_local_activity(self, input: StartLocalActivityInput):
        self._guard.check("start_local_activity", input.activity, input.args)
        return self.next.start_local_activity(input)

    async def start_child_workflow(self, input: StartChildWorkflowInput):
        self._guard.check("start_child_workflow", input.workflow, input.args)
        return await self.next.start_child_workflow(input)

    async def signal_child_workflow(self, input: SignalChildWorkflowInput) -> None:
        self._guard.check("signal_child_workflow", input.signal, input.args)
        return await self.next.signal_child_workflow(input)

    async def signal_external_workflow(self, input: SignalExternalWorkflowInput) -> None:
        self._guard.check("signal_external_workflow", input.signal, input.args)
        return await self.next.signal_external_workflow(input)
