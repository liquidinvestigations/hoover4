"""The `Operation` workflow: one durable execution per dispatched operation.

The workflow id **is** the operation id, so anything holding the id (an interrupted
CLI, a link in the admin list, a row read months later) can find the execution again
without a lookup table. That identity is the whole reason a caller can be killed
without consequence: the work is not in the caller, and the caller's only unique
knowledge is a string it already printed.

The workflow owns the row's lifecycle. It writes `running` when it starts, waits for
its child, and writes `finished` or `errored` with `finished_at` set. The collector
updates progress. The cancellation finalizer writes `cancelled`. That write releases
the operations lock, which is why it is on the way out of every path.
"""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from .activities import (
        cancel_target_operation, count_dataset_rows_activity, record_operation_state,
        reindex_collection_activity, sample_dataset_progress,
        tombstone_dataset_row,
    )
    from tasks.operation_failure_capture import capture_failure_best_effort
    from .backup import (
        begin_export, export_clickhouse, export_manticore, export_object_store,
        finish_export,
    )
    from .params import (
        DatasetProgressParams, DatasetRegistryParams, ExportParams, ImportParams,
        OperationParams, OperationStateParams,
    )
    from tasks.P_admin.rerun_params import ReconcileErrorsParams, SelectErrorsParams, SelectionResult
    from tasks.P_admin.collection_backfill import CollectionBackfillParams, FinishedPlanPage
    from .restore import (
        begin_import, finish_import, import_clickhouse, import_manticore,
        import_object_store,
    )
    from ..heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT
    from ..visibility import dataset_search_attributes

#: How long the purge settle loop waits between row counts.
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
COLLECTION_PLANS_PER_RUN = 500


@workflow.defn
class CancelOperation:
    """Close one target and write its final sampled operation row."""

    @workflow.run
    async def run(self, op_id: str) -> str:
        context = await workflow.execute_activity(
            cancel_target_operation, op_id,
            task_queue="operations-queue",
            start_to_close_timeout=timedelta(hours=24),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=ROW_RETRY,
        )
        if context["state"] in ("finished", "errored", "cancelled"):
            return context["state"]
        target_status = context.get("target_status", "")
        if context["history_missing"]:
            return await workflow.execute_activity(
                record_operation_state,
                OperationStateParams(
                    op_id=op_id,
                    state="cancelled",
                    error=("The workflow of this operation did not exist in Temporal, "
                           "so nothing ran to cancel."),
                ),
                task_queue="operations-queue",
                start_to_close_timeout=timedelta(minutes=2),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=ROW_RETRY,
            )
        state = ("finished" if target_status == "COMPLETED" else
                 "errored" if target_status in ("FAILED", "TIMED_OUT", "TERMINATED") else
                 "cancelled")
        error = ("Cancelled by request." if state == "cancelled" else
                 "Target workflow ended with an error." if state == "errored" else "")
        result = await workflow.execute_activity(
            record_operation_state,
            OperationStateParams(op_id=op_id, state=state,
                                 error=error),
            task_queue="operations-queue",
            start_to_close_timeout=timedelta(minutes=2),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=ROW_RETRY,
        )
        return result


@workflow.defn
class Operation:
    """Run one operation of one kind, keeping its row accurate from end to end."""

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
            # The separate finalizer writes the terminal row after this workflow closes.
            raise
        except Exception as exc:
            if _is_cancellation(exc):
                raise
            await workflow.execute_activity(
                record_operation_state,
                OperationStateParams(op_id=params.op_id, state="errored",
                                     error=_failure_message(exc)),
                task_queue="operations-queue",
                start_to_close_timeout=timedelta(minutes=2),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=ROW_RETRY,
            )
            await capture_failure_best_effort(
                exc,
                op_id=params.op_id,
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                stage="",
                task_name="Operation",
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
        if params.kind == "purge_unattributed_entities":
            return await self._purge_unattributed_entities(params)
        if params.kind == "backfill_vectors":
            return await self._backfill_vectors(params)
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
        if params.kind == "refresh_document_locations":
            result = await workflow.execute_child_workflow(
                "RefreshDocumentLocations",
                {
                    "collectionname": params.collectionname,
                    "collection_dataset": params.collection_dataset,
                    "item_hashes": list(params.detail.get("item_hashes") or []),
                },
                id=f"refresh-document-locations-{params.op_id}",
                task_queue="processing-common-queue",
                search_attributes=dataset_search_attributes(params.collection_dataset),
            )
            return result
        raise ApplicationErrorKind(params.kind)

    async def _ingest_dataset(self, params: OperationParams) -> str:
        """Drive the three ingest stages and wait for their result.

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
                "op_id": params.op_id,
            },
            id=f"ingest-and-process-{params.op_id}",
            task_queue="processing-common-queue",
            search_attributes=dataset_search_attributes(params.collection_dataset),
        ))
        child_result = await child
        await self._sample_selector_counts(params, child_result["selector_counts"])
        return f"ingested and processed {params.collection_dataset}"

    async def _sample_selector_counts(self, params: OperationParams,
                                      counts: dict[str, int]) -> None:
        """Write final selector counts through the progress activity."""
        await workflow.execute_activity(
            sample_dataset_progress,
            DatasetProgressParams(params.op_id, params.collectionname,
                                  params.collection_dataset, counts),
            task_queue="operations-queue",
            start_to_close_timeout=timedelta(minutes=2),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=ROW_RETRY,
        )

    async def _compute_plans(self, params: OperationParams) -> str:
        """Turn the blobs a scan recorded into the dataset's processing plans.

        **This kind has no progress fraction, and that is deliberate.** Planning is one
        activity that writes every plan in a single statement, behind one that counts
        the new blobs, so nothing finishes repeatedly and there is no accurate
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
        discovered, not the counter reporting a wrong number: the number moves in both parts.
        """
        selection = await workflow.execute_activity(
            "select_historical_errors",
            SelectErrorsParams(
                op_id=params.op_id,
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                task_name=str(params.detail.get("task_name", "")),
                hash=str(params.detail.get("hash", "")),
            ),
            result_type=SelectionResult,
            task_queue="processing-common-queue",
            start_to_close_timeout=timedelta(minutes=60),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        child = asyncio.ensure_future(workflow.execute_child_workflow(
            "ExecutePlans",
            {
                "collectionname": params.collectionname,
                "collection_dataset": params.collection_dataset,
                "base_temp_dir": "/tmp/hoover4",
                "op_id": params.op_id,
            },
            id=f"execute-plans-{params.op_id}",
            task_queue="processing-common-queue",
            search_attributes=dataset_search_attributes(params.collection_dataset),
        ))
        result = await child
        reconciliation = await workflow.execute_activity(
            "reconcile_selected_errors",
            ReconcileErrorsParams(
                op_id=params.op_id,
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
            ),
            result_type=dict,
            task_queue="processing-common-queue",
            start_to_close_timeout=timedelta(minutes=60),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        await self._sample_selector_counts(params, {
            "errors_before_run": selection.errors_before_run,
            "selected_errors": selection.selected_errors,
            "removed_stage_off_errors": selection.removed_stage_off_errors,
            "without_plan_errors": selection.without_plan_errors,
            **reconciliation,
        })
        return result

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

        Progress is the dataset's plans. The collector refreshes the plan counters while
        the child re-processes the dataset.
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
        re-running it from a clean directory is both cheaper and safer than
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
        """Run selected historical Error rows through plan execution and reconciliation."""
        task_name = str(params.detail.get("task_name", ""))
        doc_hash = str(params.detail.get("hash", ""))
        if not task_name and not doc_hash:
            raise ApplicationErrorDetail(params.kind, "task_name or hash")
        selection = await workflow.execute_activity(
            "select_historical_errors",
            SelectErrorsParams(
                op_id=params.op_id,
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                task_name=task_name,
                hash=doc_hash,
            ),
            result_type=SelectionResult,
            task_queue="processing-common-queue",
            start_to_close_timeout=timedelta(minutes=60),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        child = asyncio.ensure_future(workflow.execute_child_workflow(
            "ExecutePlans",
            {
                "collectionname": params.collectionname,
                "collection_dataset": params.collection_dataset,
                "base_temp_dir": "/tmp/hoover4",
                "op_id": params.op_id,
            },
            id=f"retry-failed-files-{params.op_id}",
            task_queue="processing-common-queue",
            search_attributes=dataset_search_attributes(params.collection_dataset),
        ))
        result = await child
        reconciliation = await workflow.execute_activity(
            "reconcile_selected_errors",
            ReconcileErrorsParams(
                op_id=params.op_id,
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
            ),
            result_type=dict,
            task_queue="processing-common-queue",
            start_to_close_timeout=timedelta(minutes=60),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        await self._sample_selector_counts(params, {
            "errors_before_run": selection.errors_before_run,
            "selected_errors": selection.selected_errors,
            "removed_stage_off_errors": selection.removed_stage_off_errors,
            "without_plan_errors": selection.without_plan_errors,
            **reconciliation,
        })
        return result

    async def _purge_unattributed_entities(self, params: OperationParams) -> str:
        """Re-run entity extraction and indexing after unattributed rows are deleted."""
        if not params.clear_complete:
            await workflow.execute_activity(
                "clear_unattributed_entities",
                CollectionBackfillParams(params.op_id, params.collectionname),
                task_queue="processing-common-queue",
                start_to_close_timeout=timedelta(minutes=60),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            params.clear_complete = True
        return await self._run_collection_plans(params, "purge-unattributed")

    async def _backfill_vectors(self, params: OperationParams) -> str:
        """Run embedding and indexing for every finished plan in a collection."""
        return await self._run_collection_plans(params, "backfill")

    async def _run_collection_plans(self, params: OperationParams, mode: str) -> str:
        """Process bounded pages and continue before the history grows too large."""
        run_done = 0
        while True:
            page = await workflow.execute_activity(
                "list_finished_plans",
                CollectionBackfillParams(
                    params.op_id, params.collectionname, params.plan_cursor, params.plan_total,
                ),
                result_type=FinishedPlanPage,
                task_queue="processing-common-queue",
                start_to_close_timeout=timedelta(minutes=60),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            params.plan_total = page.total
            if not page.plans:
                break
            for collection_dataset, plan_hash in page.plans:
                child_params = {
                    "collectionname": params.collectionname,
                    "collection_dataset": collection_dataset,
                    "plan_hash": plan_hash,
                    "op_id": params.op_id,
                }
                first = ("ExtractEntitiesForPlan" if mode == "purge-unattributed"
                         else "ChunkEmbedForPlan")
                prefix = ("purge-unattributed-ner" if mode == "purge-unattributed"
                          else "backfill-embed")
                await workflow.execute_child_workflow(
                    first, child_params,
                    id=f"{prefix}-{params.op_id}-{collection_dataset}-{plan_hash}",
                    task_queue="processing-common-queue",
                    search_attributes=dataset_search_attributes(collection_dataset),
                )
                await workflow.execute_child_workflow(
                    "IndexDatasetPlan", child_params,
                    id=f"{mode}-index-{params.op_id}-{collection_dataset}-{plan_hash}",
                    task_queue="processing-common-queue",
                    search_attributes=dataset_search_attributes(collection_dataset),
                )
                params.plan_done += 1
                run_done += 1
                params.plan_cursor = [collection_dataset, plan_hash]
                await self._record(params.op_id, params.plan_done, params.plan_total)
                if run_done >= COLLECTION_PLANS_PER_RUN and params.plan_done < params.plan_total:
                    workflow.continue_as_new(params)
            if params.plan_done >= params.plan_total:
                break
        if mode == "purge-unattributed":
            return f"re-ran entity extraction and indexing for {params.plan_done} plan(s)"
        return f"backfilled vectors and indexing for {params.plan_done} plan(s)"


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
