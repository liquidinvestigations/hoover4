"""The `Operation` workflow: one durable execution per dispatched operation.

The workflow id **is** the operation id, so anything holding the id — an interrupted
CLI, a link in the admin list, a row read months later — can find the execution again
without a lookup table. That identity is the whole reason a caller can be killed
without consequence: the work is not in the caller, and the caller's only unique
knowledge is a string it already printed.

The workflow owns the row's lifecycle. It writes `running` when it starts, samples
progress while the real work runs beneath it, and writes exactly one of `finished`,
`errored` or `cancelled` with `finished_at` set. That terminal write is also what
releases the operations lock, which is why it is on the way out of every path.
"""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from .activities import (
        record_operation_state, reindex_collection_activity, sample_dataset_progress,
    )
    from .params import DatasetProgressParams, OperationParams, OperationStateParams
    from ..heartbeat import HEARTBEAT_TIMEOUT
    from ..visibility import dataset_search_attributes

#: How often a running operation refreshes its progress counters.
#:
#: A compromise, and both ends are real: the admin list is unreadable if it only moves
#: at the end, and every sample is two `FINAL` counts against the collection database,
#: which is the same server the ingest is writing to.
PROGRESS_INTERVAL_SECONDS = 15

#: The row writes are small, idempotent and on the critical path of the lock being
#: released, so they retry patiently rather than giving up and stranding the lock.
ROW_RETRY = RetryPolicy(maximum_attempts=10, initial_interval=timedelta(seconds=1))


@workflow.defn
class Operation:
    """Run one operation of one kind, keeping its row honest from end to end."""

    @workflow.run
    async def run(self, params: OperationParams) -> str:
        await workflow.execute_activity(
            record_operation_state,
            OperationStateParams(op_id=params.op_id, state="running"),
            task_queue="operations-queue",
            start_to_close_timeout=timedelta(minutes=2),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=ROW_RETRY,
        )
        try:
            result = await self._dispatch(params)
        except asyncio.CancelledError:
            # The row is landed in `cancelled` by whoever requested the cancellation:
            # once a workflow is cancelled it cannot schedule further activities, so a
            # cleanup write attempted here would itself be cancelled and the row would
            # be stranded non-terminal, holding the lock for ever.
            raise
        except Exception as exc:
            await workflow.execute_activity(
                record_operation_state,
                OperationStateParams(op_id=params.op_id, state="errored",
                                     error=f"{type(exc).__name__}: {exc}"),
                task_queue="operations-queue",
                start_to_close_timeout=timedelta(minutes=2),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=ROW_RETRY,
            )
            raise
        await workflow.execute_activity(
            record_operation_state,
            OperationStateParams(op_id=params.op_id, state="finished"),
            task_queue="operations-queue",
            start_to_close_timeout=timedelta(minutes=2),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=ROW_RETRY,
        )
        return result

    async def _dispatch(self, params: OperationParams) -> str:
        if params.kind in ("add_dataset", "rescan_dataset"):
            return await self._ingest_dataset(params)
        if params.kind == "reindex_collection":
            queued = await workflow.execute_activity(
                reindex_collection_activity,
                params.collectionname,
                task_queue="operations-queue",
                start_to_close_timeout=timedelta(hours=2),
                heartbeat_timeout=timedelta(minutes=5),
            )
            return f"queued {queued} plan(s) for re-indexing"
        raise ApplicationErrorKind(params.kind)

    async def _ingest_dataset(self, params: OperationParams) -> str:
        """Drive the three ingest stages, sampling progress while they run.

        The child carries this operation's id, so a second dispatch cannot collide with
        this run's children, and the ingest is visible in Temporal under a name that
        leads straight back to the row.

        THE CHILD IS ADDRESSED BY NAME, not by importing its class, and that is not a
        style choice. Importing it drags the whole pipeline module graph — the scan
        activities, the object-store client, its crypto bindings — through the workflow
        sandbox's importer, and a C extension re-imported that way fails with a bare
        `SystemError` from inside CPython that names nothing in this repository. The
        operations container has no business loading the pipeline's dependencies
        either: it schedules that work, it does not run it.
        """
        child = asyncio.ensure_future(workflow.execute_child_workflow(
            "IngestAndProcessDataset",
            {
                "collectionname": params.collectionname,
                "collection_dataset": params.collection_dataset,
                "dataset_path": params.dataset_path,
            },
            id=f"ingest-and-process-{params.op_id}",
            task_queue="processing-common-queue",
            search_attributes=dataset_search_attributes(params.collection_dataset),
        ))
        progress = DatasetProgressParams(
            op_id=params.op_id,
            collectionname=params.collectionname,
            collection_dataset=params.collection_dataset,
        )
        while not child.done():
            # A race, not a sleep-then-check: waiting the full interval after the child
            # finishes would add that interval to every operation's wall clock, and the
            # tail of a short ingest is mostly interval. `wait_condition` is the
            # workflow-safe timer; a plain `asyncio.sleep` here would be the same
            # length but would not wake when the child does.
            try:
                await workflow.wait_condition(
                    child.done, timeout=timedelta(seconds=PROGRESS_INTERVAL_SECONDS))
            except asyncio.TimeoutError:
                pass
            await workflow.execute_activity(
                sample_dataset_progress, progress,
                task_queue="operations-queue",
                start_to_close_timeout=timedelta(minutes=2),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=ROW_RETRY,
            )
        await child
        return f"ingested and processed {params.collection_dataset}"


def ApplicationErrorKind(kind: str) -> Exception:
    """The error for a kind the workflow has no driver for.

    A named function rather than a bare `raise` so the message is identical wherever a
    kind is registered in the table but not yet dispatched here — the operations log
    accepts more kinds than this workflow can currently run, on purpose, so a row can
    be written for work that another surface performs.
    """
    from temporalio.exceptions import ApplicationError

    return ApplicationError(
        f"Operation kind '{kind}' has no driver in the operations workflow.",
        non_retryable=True,
    )
