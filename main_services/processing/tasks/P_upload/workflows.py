"""`UploadQueue` and `IngestUploadBatches`: the targeted ingest of committed uploads.

One `UploadQueue` runs for each upload dataset, under the id `upload-queue-<dataset>`.
The website starts it with signal-with-start after each commit. The signal
`upload_committed` is a wake-up only. The queue reads the waiting batches from
ClickHouse, takes up to 50 of them as one `ingest_upload` operation, starts that
`Operation` as a child, waits for its terminal row, settles the batches that the
operation left open, and takes the next group. With nothing to do for ten minutes it
ends. The next commit starts it again.

`Operation` of kind `ingest_upload` passes admission and then runs `IngestUploadBatches`,
which ingests the placed files of each batch, computes and executes the plans of the
dataset, and writes the batch outcome. It lists no folder and reconciles no deletion.

No path enters a payload of these workflows. They carry dataset ids, operation ids, batch
ids and counts.
"""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from tasks.failure_chain import is_cancellation as _is_cancellation
    from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT
    from tasks.visibility import dataset_search_attributes
    from tasks.P_ops.params import OperationParams
    from tasks.P_admin.rerun_params import ReconcileErrorsParams, SelectErrorsParams, SelectionResult
    from .activities import (
        cancel_upload_operation, finish_upload_batches, ingest_upload_paths,
        open_upload_operation, settle_upload_operation, upload_batch_limits,
        upload_operation_state,
    )
    from .params import (
        FinishUploadBatchesParams, IngestUploadBatchesParams, UploadBatchLimitsResult,
        UploadBatchParams, UploadClaimResult, UploadOperationParams, UploadQueueParams,
    )

#: History events after which the queue continues as new. Document 7 of the upload
#: design sets 1,000 events for queue workflows.
QUEUE_HISTORY_EVENTS = 1_000

#: History events after which `IngestUploadBatches` continues as new between batches.
INGEST_HISTORY_EVENTS = 10_000

#: How long an idle queue waits for a wake-up before it ends.
IDLE_TIMEOUT = timedelta(minutes=10)

#: The longest wait between two reads of the operations row while an operation runs.
STATUS_POLL = timedelta(seconds=60)

#: The task queue of the `Operation` workflow.
OPERATION_TASK_QUEUE = "operations-queue"

#: Row reads and writes: short, idempotent, retried patiently.
ROW_RETRY = RetryPolicy(maximum_attempts=10, initial_interval=timedelta(seconds=1))

TERMINAL = ("finished", "errored", "cancelled", "missing")


def _queue_history_full() -> bool:
    info = workflow.info()
    return (info.get_current_history_length() >= QUEUE_HISTORY_EVENTS
            or info.is_continue_as_new_suggested())


@workflow.defn
class UploadQueue:
    """Run the committed batches of one upload dataset in order, one operation at a time."""

    def __init__(self) -> None:
        self._woken = False

    @workflow.signal(name="upload_committed")
    def upload_committed(self, payload: dict) -> None:
        """A batch was committed. The payload names it and is not stored."""
        self._woken = True

    async def _row_activity(self, fn, arg, result_type=None):
        return await workflow.execute_activity(
            fn, arg,
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=ROW_RETRY,
            result_type=result_type,
        )

    @workflow.run
    async def run(self, params: UploadQueueParams) -> str:
        op_id = params.active_op_id
        handle = None
        try:
            while True:
                if not op_id:
                    claim: UploadClaimResult = await self._row_activity(
                        open_upload_operation,
                        UploadOperationParams(params.collectionname, params.upload_dataset,
                                              self._new_op_id(params.upload_dataset)),
                        UploadClaimResult)
                    if not claim.op_id:
                        if not claim.dataset_live:
                            return "the dataset was deleted"
                        if _queue_history_full():
                            workflow.continue_as_new(
                                UploadQueueParams(params.collectionname, params.upload_dataset))
                        self._woken = False
                        try:
                            await workflow.wait_condition(
                                lambda: self._woken or _queue_history_full(),
                                timeout=IDLE_TIMEOUT)
                        except asyncio.TimeoutError:
                            # A wake-up that arrives with the timer is handled first in
                            # its activation, so `_woken` is already set then.
                            if self._woken:
                                continue
                            # A batch committed without a delivered signal is still found.
                            claim = await self._row_activity(
                                open_upload_operation,
                                UploadOperationParams(params.collectionname,
                                                      params.upload_dataset,
                                                      self._new_op_id(params.upload_dataset)),
                                UploadClaimResult)
                            if not claim.op_id and not self._woken:
                                return "idle"
                        if not claim.op_id:
                            continue
                    op_id = claim.op_id
                    if claim.op_state == "pending":
                        handle = await self._start_operation(params, claim)
                state = await self._wait_for(params, op_id, handle)
                await self._row_activity(
                    settle_upload_operation,
                    UploadOperationParams(params.collectionname, params.upload_dataset, op_id))
                workflow.logger.info("upload operation %s ended %s", op_id, state)
                op_id, handle = "", None
        except asyncio.CancelledError:
            if op_id:
                await self._cancel(params, op_id)
            raise

    def _new_op_id(self, upload_dataset: str) -> str:
        """A random operation id, fixed in history, with the shape of `new_op_id`."""
        stamp = int(workflow.now().timestamp() * 1_000_000)
        return f"ingest_upload-{upload_dataset}-{stamp}-{workflow.uuid4().hex[:12]}"

    async def _start_operation(self, params: UploadQueueParams, claim: UploadClaimResult):
        """Start the `Operation` child, or find that it started already.

        The child outlives the queue run (`ABANDON`), so a continue-as-new keeps it. A
        start refused because the id exists means that an earlier run started it.
        """
        try:
            return await workflow.start_child_workflow(
                "Operation",
                OperationParams(op_id=claim.op_id, kind="ingest_upload",
                                collectionname=params.collectionname,
                                collection_dataset=params.upload_dataset,
                                detail={"batch_ids": list(claim.batch_ids)}),
                id=claim.op_id,
                task_queue=OPERATION_TASK_QUEUE,
                parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        except WorkflowAlreadyStartedError:
            workflow.logger.info("operation %s started earlier", claim.op_id)
            return None

    async def _wait_for(self, params: UploadQueueParams, op_id: str, handle) -> str:
        """Wait for the terminal row of the operation, in bounded waits.

        The queue continues as new at its history limit and carries the operation id, so
        a long operation and a burst of signals never grow one history without bound.
        """
        while True:
            state = await self._row_activity(upload_operation_state, op_id, str)
            if state in TERMINAL:
                return state
            if _queue_history_full():
                workflow.continue_as_new(UploadQueueParams(
                    params.collectionname, params.upload_dataset, active_op_id=op_id))
            try:
                await workflow.wait_condition(
                    lambda: _queue_history_full() or (handle is not None and handle.done()),
                    timeout=STATUS_POLL)
            except asyncio.TimeoutError:
                pass
            if handle is not None and handle.done():
                # The child closed. Its row is terminal, or the finalizer writes it.
                handle = None

    async def _cancel(self, params: UploadQueueParams, op_id: str) -> None:
        """Ask the operation finalizer to cancel the operation, then settle its batches."""
        await workflow.execute_activity(
            cancel_upload_operation, op_id,
            start_to_close_timeout=timedelta(hours=24),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=ROW_RETRY,
        )
        await self._row_activity(
            settle_upload_operation,
            UploadOperationParams(params.collectionname, params.upload_dataset, op_id))


@workflow.defn
class IngestUploadBatches:
    """Ingest, plan and execute each claimed batch, then write its outcome.

    New runs ingest every claimed batch before planning and selecting historical errors.
    Each batch then runs `ComputePlans`, `ExecutePlans`, and `finish_upload_batches`.
    The patch preserves the original activity order for existing histories.
    Error reconciliation runs after the last batch.
    Search attributes, selection, and cancellation follow `IngestAndProcessDataset`:
    a cancellation propagates to the running child or activity and is not caught here.
    The upload queue settles the batches after a cancelled or failed operation.
    """

    @workflow.run
    async def run(self, params: IngestUploadBatchesParams) -> dict:
        with workflow.unsafe.imports_passed_through():
            from tasks.P1_compute_plans.activities import ComputePlansParams
            from tasks.P2_execute_plan.workflows import ExecutePlansParams

        attributes = dataset_search_attributes(params.upload_dataset)
        if workflow.patched("upload-prepare-all-batches") and not params.paths_prepared:
            for batch_id in params.batch_ids:
                await self._ingest(params, batch_id)
            params.paths_prepared = True
        remaining = list(params.batch_ids)
        while remaining:
            batch_id = remaining[0]
            one = UploadBatchParams(params.collectionname, params.upload_dataset,
                                    params.op_id, batch_id)
            if params.paths_prepared:
                limits: UploadBatchLimitsResult = await workflow.execute_activity(
                    upload_batch_limits, one,
                    start_to_close_timeout=timedelta(minutes=5),
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                    result_type=UploadBatchLimitsResult,
                )
                ingested = not limits.skip
            else:
                ingested = await self._ingest(params, batch_id)
            if ingested:
                await workflow.execute_child_workflow(
                    "ComputePlans",
                    ComputePlansParams(collectionname=params.collectionname,
                                       collection_dataset=params.upload_dataset),
                    id=f"upload-compute-plans-{params.op_id}-{batch_id}",
                    task_queue="processing-common-queue",
                    search_attributes=attributes,
                )
                if not params.selection_done:
                    selection = await workflow.execute_activity(
                        "select_historical_errors",
                        SelectErrorsParams(op_id=params.op_id,
                                           collectionname=params.collectionname,
                                           collection_dataset=params.upload_dataset),
                        result_type=SelectionResult,
                        task_queue="processing-common-queue",
                        start_to_close_timeout=timedelta(minutes=60),
                        heartbeat_timeout=HEARTBEAT_TIMEOUT,
                        retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                    )
                    params.selection_done = True
                    params.selector_counts = {
                        "errors_before_run": selection.errors_before_run,
                        "selected_errors": selection.selected_errors,
                        "removed_stage_off_errors": selection.removed_stage_off_errors,
                        "without_plan_errors": selection.without_plan_errors,
                    }
                counts = await workflow.execute_child_workflow(
                    "ExecutePlans",
                    ExecutePlansParams(collectionname=params.collectionname,
                                       collection_dataset=params.upload_dataset,
                                       base_temp_dir="/tmp/hoover4", op_id=params.op_id),
                    id=f"upload-execute-plans-{params.op_id}-{batch_id}",
                    task_queue="processing-common-queue",
                    search_attributes=attributes,
                    result_type=dict,
                )
                for key, value in (counts or {}).items():
                    if isinstance(value, int) and not isinstance(value, bool):
                        params.execution_counts[key] = params.execution_counts.get(key, 0) + value
                await self._finish(params, batch_id, "running")
            remaining.pop(0)
            info = workflow.info()
            if remaining and (info.get_current_history_length() >= INGEST_HISTORY_EVENTS
                              or info.is_continue_as_new_suggested()):
                params.batch_ids = remaining
                workflow.continue_as_new(params)

        if params.selection_done:
            reconciliation = await workflow.execute_activity(
                "reconcile_selected_errors",
                ReconcileErrorsParams(op_id=params.op_id,
                                      collectionname=params.collectionname,
                                      collection_dataset=params.upload_dataset),
                result_type=dict,
                task_queue="processing-common-queue",
                start_to_close_timeout=timedelta(minutes=60),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            )
            params.selector_counts.update(reconciliation or {})
        if not params.batch_states:
            raise ApplicationError("No claimed upload batch was waiting for this operation.",
                                   non_retryable=True)
        return {
            "message": f"settled {sum(params.batch_states.values())} upload batches",
            "execution_counts": params.execution_counts,
            "selector_counts": params.selector_counts,
            "batch_states": params.batch_states,
        }

    async def _ingest(self, params: IngestUploadBatchesParams, batch_id: str) -> bool:
        one = UploadBatchParams(params.collectionname, params.upload_dataset, params.op_id, batch_id)
        limits: UploadBatchLimitsResult = await workflow.execute_activity(
            upload_batch_limits, one,
            start_to_close_timeout=timedelta(minutes=5),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            result_type=UploadBatchLimitsResult,
        )
        ingested = False
        if not limits.skip:
            try:
                await workflow.execute_activity(
                    ingest_upload_paths, one,
                    start_to_close_timeout=timedelta(seconds=limits.ingest_seconds),
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                )
                ingested = True
            except Exception as exc:
                if _is_cancellation(exc):
                    raise
                # One batch that cannot be ingested fails alone. Its placed files
                # stay in the folder, and the next batch continues.
                workflow.logger.warning("upload batch %s was not ingested: %s",
                                        batch_id, exc)
                await self._finish(params, batch_id, "errored")
        return ingested

    async def _finish(self, params: IngestUploadBatchesParams, batch_id: str,
                      operation_state: str) -> None:
        states = await workflow.execute_activity(
            finish_upload_batches,
            FinishUploadBatchesParams(params.collectionname, params.upload_dataset,
                                      params.op_id, [batch_id], operation_state),
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            result_type=dict,
        )
        for state, number in (states or {}).items():
            params.batch_states[state] = params.batch_states.get(state, 0) + int(number)
