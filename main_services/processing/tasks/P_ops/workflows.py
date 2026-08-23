"""The `Operation` workflow: one durable execution per dispatched operation.

The workflow id **is** the operation id, so anything holding the id (an interrupted
CLI, a link in the admin list, a row read months later) can find the execution again
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
        begin_failed_file_retry, count_dataset_rows_activity,
        finish_failed_file_retry, record_operation_state,
        reindex_collection_activity, sample_dataset_progress,
        tombstone_dataset_row,
    )
    from .backup import (
        begin_export, export_clickhouse, export_manticore, export_object_store,
        finish_export,
    )
    from .params import (
        DatasetProgressParams, DatasetRegistryParams, ExportParams, FinishRetryParams,
        ImportParams, OperationParams, OperationStateParams, RetryFailedFilesParams,
    )
    from .restore import (
        begin_import, finish_import, import_clickhouse, import_manticore,
        import_object_store,
    )
    from ..heartbeat import HEARTBEAT_TIMEOUT
    from ..visibility import dataset_search_attributes

#: How often a running operation refreshes its progress counters.
#:
#: A compromise, and both ends are real: the admin list is unreadable if it only moves
#: at the end, and every sample is two `FINAL` counts against the collection database,
#: which is the same server the ingest is writing to.
PROGRESS_INTERVAL_SECONDS = 15

#: How many more times a finished purge re-counts before it reports what is left.
#:
#: Deletes land asynchronously in ClickHouse, so the count taken the moment the purge
#: returns is not the answer. Bounded rather than a wait for zero: a row that survives is
#: something a person has to see, not something to hang on.
PURGE_SETTLE_SAMPLES = 8

#: How long one store's export may take before it is treated as hung.
#:
#: Generous because it is a whole-store budget, not a per-file one: at the measured rates
#: a terabyte-scale collection is hours per store, and the liveness question is answered
#: by the heartbeat deadline instead, which is what actually catches an activity that
#: has stopped doing anything.
EXPORT_STORE_TIMEOUT = timedelta(hours=24)

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
            # A cancellation reaches this branch wrapped, as an activity failure whose
            # cause is a cancellation, so it is not caught above. It is still a
            # cancellation and the row must say so: writing `errored` here races the
            # `cancelled` the canceller writes from outside, and whichever lands second
            # decides the state. Deciding it from the failure chain instead means both
            # writers agree and there is nothing left to race.
            state = "cancelled" if _is_cancellation(exc) else "errored"
            await workflow.execute_activity(
                record_operation_state,
                OperationStateParams(op_id=params.op_id, state=state,
                                     error=_failure_message(exc)),
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
        if params.kind == "compute_plans":
            return await self._compute_plans(params)
        if params.kind == "execute_plans":
            return await self._execute_plans(params)
        if params.kind == "purge_dataset":
            return await self._purge_dataset(params)
        if params.kind == "delete_dataset":
            return await self._delete_dataset(params)
        if params.kind == "change_ocr_languages":
            return await self._change_ocr_languages(params)
        if params.kind == "retry_failed_files":
            return await self._retry_failed_files(params)
        if params.kind in ("ensure_collection", "drop_collection_database"):
            return await self._collection_database(params)
        if params.kind == "export_collection":
            return await self._export_collection(params)
        if params.kind == "import_collection":
            return await self._import_collection(params)
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
        style choice. Importing it drags the whole pipeline module graph (the scan
        activities, the object-store client, its crypto bindings) through the workflow
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
        await self._sample_plans_until_done(child, params)
        await child
        return f"ingested and processed {params.collection_dataset}"

    async def _sample_plans_until_done(self, child, params: OperationParams) -> None:
        """Refresh the row's plan counters until the child workflow finishes.

        Plans are the only unit whose total is known before the work is done, so every
        kind that drives the pipeline over a dataset counts the same thing here.
        """
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

    async def _compute_plans(self, params: OperationParams) -> str:
        """Turn the blobs a scan recorded into the dataset's processing plans.

        **This kind has no progress fraction, and that is deliberate.** Planning is one
        activity that writes every plan in a single statement, behind one that counts
        the new blobs, so nothing finishes repeatedly and there is no honest
        denominator. The row's counters stay at zero and the result says how many items
        were planned. A bar invented here would sit empty and then be full, which
        reports less than no bar at all.
        """
        return await workflow.execute_child_workflow(
            "ComputePlans",
            {
                "collectionname": params.collectionname,
                "collection_dataset": params.collection_dataset,
            },
            id=f"compute-plans-{params.op_id}",
            task_queue="processing-common-queue",
            search_attributes=dataset_search_attributes(params.collection_dataset),
        )

    async def _execute_plans(self, params: OperationParams) -> str:
        """Run the dataset's unfinished plans, sampling plans finished against plans held.

        Progress means something here, and it is the counter the ingest driver already
        uses. The denominator can grow while the operation runs (a plan that opens an
        archive computes plans for what was inside it), and that is the corpus being
        discovered, not the counter lying: the number moves in both parts.
        """
        child = asyncio.ensure_future(workflow.execute_child_workflow(
            "ExecutePlans",
            {
                "collectionname": params.collectionname,
                "collection_dataset": params.collection_dataset,
                "base_temp_dir": "/tmp/hoover4",
            },
            id=f"execute-plans-{params.op_id}",
            task_queue="processing-common-queue",
            search_attributes=dataset_search_attributes(params.collection_dataset),
        ))
        await self._sample_plans_until_done(child, params)
        return await child

    async def _record(self, op_id: str, done: int, total: int) -> None:
        """Write progress counters onto the row, without changing its state."""
        await workflow.execute_activity(
            record_operation_state,
            OperationStateParams(op_id=op_id, progress_done=done,
                                 progress_total=total),
            task_queue="operations-queue",
            start_to_close_timeout=timedelta(minutes=2),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=ROW_RETRY,
        )

    async def _count_rows(self, params: OperationParams) -> int:
        return await workflow.execute_activity(
            count_dataset_rows_activity,
            DatasetProgressParams(op_id=params.op_id,
                                  collectionname=params.collectionname,
                                  collection_dataset=params.collection_dataset),
            task_queue="operations-queue",
            start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=ROW_RETRY,
        )

    async def _purge_dataset(self, params: OperationParams) -> str:
        """Delete a dataset's rows from both stores and rebuild the shard ledger.

        Progress is rows, and it is counted rather than staged: the total is what the
        dataset holds before anything is deleted, and each sample re-counts what is
        left, so the bar moves with the deletion instead of with the number of
        activities that have returned. It reaches its total only when the stores agree
        the dataset is gone.
        """
        total = await self._count_rows(params)
        await self._record(params.op_id, 0, total)
        child = asyncio.ensure_future(workflow.execute_child_workflow(
            "PurgeDataset",
            {
                "collectionname": params.collectionname,
                "collection_dataset": params.collection_dataset,
            },
            id=f"purge-dataset-{params.op_id}",
            task_queue="processing-common-queue",
            search_attributes=dataset_search_attributes(params.collection_dataset),
        ))
        while not child.done():
            try:
                await workflow.wait_condition(
                    child.done, timeout=timedelta(seconds=PROGRESS_INTERVAL_SECONDS))
            except asyncio.TimeoutError:
                pass
            remaining = await self._count_rows(params)
            await self._record(params.op_id, max(0, total - remaining), total)
        await child
        # ClickHouse lightweight deletes are asynchronous, so the last count is polled
        # rather than read once: a purge that has done everything asked of it still
        # shows rows for a while, and reporting that as work left undone is wrong.
        remaining = await self._count_rows(params)
        for _ in range(PURGE_SETTLE_SAMPLES):
            if not remaining:
                break
            await workflow.sleep(timedelta(seconds=PROGRESS_INTERVAL_SECONDS))
            remaining = await self._count_rows(params)
            await self._record(params.op_id, max(0, total - remaining), total)
        await self._record(params.op_id, max(0, total - remaining), total)
        return f"purged {total - remaining} row(s) of {params.collection_dataset}"

    async def _delete_dataset(self, params: OperationParams) -> str:
        """Retire a dataset: tombstone its registry row, then purge what it holds.

        The order is what makes an interrupted deletion safe. Once the registry row is
        tombstoned the dataset is offered nowhere, so a purge that stops half way
        leaves rows nothing routes to rather than a live dataset missing half its data.
        The tombstone is idempotent, so a re-run of this row finishes the purge instead
        of failing on a dataset that is already gone from the registry.

        Progress is the purge's, because the purge is all of the work: rows still in
        the stores against rows the dataset held when it started.
        """
        await workflow.execute_activity(
            tombstone_dataset_row,
            DatasetRegistryParams(op_id=params.op_id,
                                  collectionname=params.collectionname,
                                  collection_dataset=params.collection_dataset),
            task_queue="operations-queue",
            start_to_close_timeout=timedelta(minutes=5),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=ROW_RETRY,
        )
        return await self._purge_dataset(params)

    async def _change_ocr_languages(self, params: OperationParams) -> str:
        """Apply a dataset's new OCR languages: settings, re-run, purge, in that order.

        The languages travel in the operation's `detail`, which is also what the row
        records, so the log says what was asked for and a re-run of that row asks for
        the same thing rather than for whatever the dataset is set to now.

        Progress is the dataset's plans, sampled while the child runs: the expensive
        part of a language change is the re-processing, and that is exactly what the
        plan counters measure.
        """
        tesseract = str(params.detail.get("tesseract_languages", ""))
        easyocr = str(params.detail.get("easyocr_languages", ""))
        if not tesseract and not easyocr:
            raise ApplicationErrorDetail(
                params.kind, "tesseract_languages and easyocr_languages")
        child = asyncio.ensure_future(workflow.execute_child_workflow(
            "ChangeOcrLanguages",
            {
                "collectionname": params.collectionname,
                "collection_dataset": params.collection_dataset,
                "op_id": params.op_id,
                "tesseract_languages": tesseract,
                "easyocr_languages": easyocr,
            },
            id=f"ocr-languages-{params.op_id}",
            task_queue="processing-common-queue",
            search_attributes=dataset_search_attributes(params.collection_dataset),
        ))
        await self._sample_plans_until_done(child, params)
        return await child

    async def _collection_database(self, params: OperationParams) -> str:
        """Provision a collection's database, or drop it and its Manticore tables.

        **Neither kind has a progress fraction, and that is deliberate.** Each is a
        single activity that either has run or has not, and those two states are
        exactly what the row's `state` column already says. The only thing a bar could
        report here is the state, twice.

        The child's id carries the operation id rather than the collection name, so a
        repeated create or delete of the same collection is its own execution with a
        history of its own, which is the same rule every other kind follows.
        """
        workflow_type = {
            "ensure_collection": "EnsureCollectionDatabase",
            "drop_collection_database": "DropCollectionDatabase",
        }[params.kind]
        return await workflow.execute_child_workflow(
            workflow_type,
            {"collectionname": params.collectionname},
            id=f"{params.kind}-{params.op_id}",
            task_queue="processing-common-queue",
        )

    async def _export_collection(self, params: OperationParams) -> str:
        """Write one collection's backup: object store, then ClickHouse, then Manticore.

        **The order is the only cross-store consistency there is.** No store can be
        snapshotted together with another, so an export taken while the pipeline runs is
        going to be inconsistent somewhere; taking the objects first puts the inconsistency
        where a restore survives it. An orphaned blob rather than a row pointing at a blob that
        was never copied.

        Each store runs on its own queue, so a slow object copy cannot hold the single
        ClickHouse slot, and the store activities do not retry. A backup that failed part
        way through leaves a staging directory naming the operation that wrote it, and
        re-running it from a clean directory is both cheaper and easier to trust than
        resuming into a tree whose half-written artifacts nothing has checked.
        """
        destination = str(params.detail.get("destination", "")) or params.op_id
        export = ExportParams(op_id=params.op_id,
                              collectionname=params.collectionname,
                              destination=destination)
        export.directory = await workflow.execute_activity(
            begin_export, export,
            task_queue="operations-queue",
            start_to_close_timeout=timedelta(minutes=5),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        for step, queue in ((export_object_store, "operations-garage-queue"),
                            (export_clickhouse, "operations-clickhouse-queue"),
                            (export_manticore, "operations-manticore-queue")):
            await workflow.execute_activity(
                step, export,
                task_queue=queue,
                start_to_close_timeout=EXPORT_STORE_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        directory = await workflow.execute_activity(
            finish_export, export,
            task_queue="operations-queue",
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        return f"exported {params.collectionname} to {directory}"

    async def _import_collection(self, params: OperationParams) -> str:
        """Restore one collection from a backup directory, in the export's own order.

        **Object store, then ClickHouse, then Manticore, and the order is the guarantee.**
        Reversing it would put searchable rows in front of the blobs they point at, so
        an interrupted restore would offer documents that cannot be opened; this way it
        leaves blobs nothing points at, which is invisible rather than broken.

        The configuration rows come last, in `finish_import`, because they are what
        offers the collection to the rest of the system: until they are written a
        half-finished restore is a collection nobody is shown.

        Nothing retries, for the same reason the export does not: every phase writes into
        a store, and re-running a phase over a target it has already half filled is the
        one thing the clean-target rule exists to prevent.
        """
        source = str(params.detail.get("source", ""))
        if not source:
            raise ApplicationErrorDetail(params.kind, "source")
        restore = ImportParams(op_id=params.op_id,
                               collectionname=params.collectionname,
                               source=source)
        restore.directory = await workflow.execute_activity(
            begin_import, restore,
            task_queue="operations-queue",
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        for step, queue in ((import_object_store, "operations-garage-queue"),
                            (import_clickhouse, "operations-clickhouse-queue"),
                            (import_manticore, "operations-manticore-queue")):
            await workflow.execute_activity(
                step, restore,
                task_queue=queue,
                start_to_close_timeout=EXPORT_STORE_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        return await workflow.execute_activity(
            finish_import, restore,
            task_queue="operations-queue",
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

    async def _retry_failed_files(self, params: OperationParams) -> str:
        """Re-run one failed stage for the documents `processing_errors` names.

        Three phases, and the order is what makes the result trustworthy: decide what
        to re-run and clear the state that would make it a no-op, re-run it plan by
        plan, then verify and clear only the error rows of the documents that are
        demonstrably fixed. Deciding after the re-run would read a corpus that has
        already changed.

        Progress is plans: the plan is the unit the pipeline finishes, and it is the
        unit this operation submits. A parse-stage retry has no per-plan entry point --
        one `ExecutePlans` run picks up every reopened plan -- so its counter stays at
        zero until that run returns and then jumps to the total.
        """
        plan = await workflow.execute_activity(
            begin_failed_file_retry,
            RetryFailedFilesParams(
                op_id=params.op_id,
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                task_name=str(params.detail.get("task_name", "")),
            ),
            task_queue="operations-queue",
            start_to_close_timeout=timedelta(minutes=60),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        total = len(plan.plan_hashes)
        await self._record(params.op_id, 0, total)
        if not total:
            return f"nothing to retry for {plan.task_name}"

        common = {
            "collectionname": params.collectionname,
            "collection_dataset": params.collection_dataset,
        }
        attributes = dataset_search_attributes(params.collection_dataset)
        if plan.retry_kind == "plan":
            await workflow.execute_child_workflow(
                "ExecutePlans",
                {**common, "base_temp_dir": "/tmp/hoover4"},
                id=f"retry-execute-plans-{params.op_id}",
                task_queue="processing-common-queue",
                search_attributes=attributes,
            )
            await self._record(params.op_id, total, total)
        else:
            for done, plan_hash in enumerate(plan.plan_hashes, 1):
                if plan.retry_kind == "nlp":
                    # P4 then P6, in that order: Manticore's entity attributes and term
                    # dictionary are built from the rows P4 writes.
                    await workflow.execute_child_workflow(
                        "ExtractEntitiesForPlan", {**common, "plan_hash": plan_hash},
                        id=f"retry-ner-{params.op_id}-{plan_hash}",
                        task_queue="processing-common-queue",
                        search_attributes=attributes,
                    )
                elif plan.retry_kind == "embed":
                    await workflow.execute_child_workflow(
                        "ChunkEmbedForPlan", {**common, "plan_hash": plan_hash},
                        id=f"retry-embed-{params.op_id}-{plan_hash}",
                        task_queue="processing-common-queue",
                        search_attributes=attributes,
                    )
                await workflow.execute_child_workflow(
                    "IndexDatasetPlan", {**common, "plan_hash": plan_hash},
                    id=f"retry-index-{params.op_id}-{plan_hash}",
                    task_queue="processing-common-queue",
                    search_attributes=attributes,
                )
                await self._record(params.op_id, done, total)

        return await workflow.execute_activity(
            finish_failed_file_retry,
            FinishRetryParams(
                op_id=params.op_id,
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                task_name=plan.task_name,
                retry_kind=plan.retry_kind,
                hashes=plan.hashes,
                started_at=plan.started_at,
            ),
            task_queue="operations-queue",
            start_to_close_timeout=timedelta(minutes=60),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


def _failure_message(exc: Exception) -> str:
    """The failure, down to the exception that actually caused it.

    An activity failure arrives at the workflow wrapped: the outer exception says only
    "Activity task failed", and the sentence naming the missing column, the refused path
    or the store that answered an error is the innermost cause. The row is the one place
    a person reads afterwards, so it carries the whole chain rather than the wrapper.
    """
    parts, seen = [], 0
    current: BaseException | None = exc
    while current is not None and seen < 5:
        text = str(current).strip()
        label = f"{type(current).__name__}: {text}" if text else type(current).__name__
        if label not in parts:
            parts.append(label)
        current = current.__cause__
        seen += 1
    return " <- ".join(parts)


def _is_cancellation(exc: BaseException) -> bool:
    """Whether a failure chain is really a cancellation wearing an error's clothes.

    Matched on the exception's *name* rather than on an imported class, because three
    different cancellations arrive here: `asyncio.CancelledError`, the SDK's own
    `CancelledError` and the `ActivityError` that wraps either, and importing the SDK's
    exception module into a workflow file only to compare against it drags more through
    the sandbox importer than the comparison is worth.
    """
    seen = 0
    current: BaseException | None = exc
    while current is not None and seen < 5:
        if type(current).__name__ == "CancelledError":
            return True
        current = current.__cause__
        seen += 1
    return False


def ApplicationErrorDetail(kind: str, missing: str) -> Exception:
    """The error for a dispatch that arrived without the parameters its kind needs.

    Non-retryable, because no number of attempts adds a field to a row that was written
    without it: the fix is a fresh dispatch carrying the parameters, and saying so once
    is more useful than saying it ten times.
    """
    from temporalio.exceptions import ApplicationError

    return ApplicationError(
        f"Operation kind '{kind}' was dispatched without {missing} in its detail.",
        non_retryable=True,
    )


def ApplicationErrorKind(kind: str) -> Exception:
    """The error for a kind the workflow has no driver for.

    A named function rather than a bare `raise` so the message is identical wherever a
    kind is registered in the table but not yet dispatched here. The operations log
    accepts more kinds than this workflow can currently run, on purpose, so a row can
    be written for work that another surface performs.
    """
    from temporalio.exceptions import ApplicationError

    return ApplicationError(
        f"Operation kind '{kind}' has no driver in the operations workflow.",
        non_retryable=True,
    )
