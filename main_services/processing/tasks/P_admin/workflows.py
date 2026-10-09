"""Temporal workflows for collection database lifecycle."""

import asyncio
import dataclasses
import functools
import json
import math
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, CancelledError

with workflow.unsafe.imports_passed_through():
    from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT
    from tasks.P_admin.activities import (
        CollectionDatabaseParams,
        PurgeDatasetParams,
        collect_eta_samples,
        drop_collection_database,
        ensure_collection_database,
        purge_dataset_from_clickhouse,
        purge_dataset_from_manticore,
        recompute_shard_ledger_activity,
        sweep_chat_artifacts,
        sweep_orphan_table_cells,
    )
    from tasks.P_ops.activities import supervise_operations
    from tasks.P_agent.supervise import supervise_agent_runs
    from tasks.P_admin.ocr_languages import (
        ApplyOcrLanguagesParams,
        OcrStageParams,
        PurgeVariantsParams,
        ReopenParams,
        begin_ocr_language_job,
        delete_orphaned_derived_pdfs,
        purge_dropped_ocr_variants,
        reopen_plans_for_ocr_change,
        report_ocr_language_progress,
    )
    from tasks.P_admin.ocr_rerun import (
        OCR_RUN_INCOMPLETE,
        OCR_RUN_PAGE,
        ListOcrRunPlansParams,
        OcrRunFile,
        OcrRunPlanParams,
        OcrTextPendingParams,
        RerunOcrParams,
        SettleOcrRunTargetsParams,
        VerifyOcrRunParams,
        list_ocr_run_plans,
        load_ocr_run_plan,
        ocr_text_pending_index,
        record_ocr_run_targets,
        reopen_plans_for_ocr_rerun,
        settle_ocr_run_targets,
        verify_ocr_run_completion,
    )
    from tasks.P1_compute_plans.activities import CountNewBlobsParams, count_new_blobs
    from tasks.P2_execute_plan.activities import (
        CleanupPlanDirParams,
        DownloadPlanFilesParams,
        EnsureTempDirExistsParams,
        ListPendingPlansParams,
        cleanup_plan_dir,
        download_plan_files,
        ensure_temp_dir_exists,
        list_pending_plans,
    )
    from tasks.P2_execute_plan.workflows import (
        MAX_PLAN_DRIVERS,
        PLAN_GROUP_SIZE,
        ExecutePlans,
        ExecutePlansParams,
        execute_dataset_step,
    )
    from tasks.P3_parse_files.batch_runner import (
        FILE_BASE_SECONDS,
        STAGE_QUEUES,
        BatchFile,
        BatchResult,
        StageBatchParams,
        file_error,
        stage_failure_results,
        stage_timeout_seconds,
    )
    from tasks.P3_parse_files.parse_common import record_errors_from_results, source_execution_id
    from tasks.P3_parse_files.workflows import ocr_error_name, ocr_pdf_error_name
    from tasks.P4_extract_entities.workflows import (
        ExtractEntitiesForPlan,
        ExtractEntitiesForPlanParams,
        ScanRegexEntitiesForPlan,
        ScanRegexEntitiesForPlanParams,
    )
    from tasks.P5_chunk_embed.workflows import ChunkEmbedForPlan, ChunkEmbedForPlanParams
    from tasks.P6_index_data.activities import compact_collection_shards, index_entity_terms
    from tasks.P6_index_data.params import BuildVfsNodesParams, CompactCollectionShardsParams
    from tasks.P6_index_data.workflows import IndexDatasetPlan, IndexDatasetPlanParams
    from tasks.failure_chain import is_cancellation
    from tasks.text_sources import OCR_ENGINES
    from tasks.workflow_window import run_with_window
    from tasks.visibility import dataset_search_attributes
    from tasks.P_admin.eta_collector import (
        CONTINUE_AS_NEW_PASSES,
        FINISHED_RECHECK_SECONDS,
        THROTTLE_HISTORY,
        CollectEtaSamplesParams,
        EtaCollectorState,
        next_interval_seconds,
    )


@workflow.defn
class EnsureCollectionDatabase:
    """Provision (create + migrate) a collection's ClickHouse database."""

    @workflow.run
    async def run(self, params: "CollectionDatabaseParams") -> str:
        return await workflow.execute_activity(
            ensure_collection_database,
            CollectionDatabaseParams(collectionname=params.collectionname),
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )


@workflow.defn
class DropCollectionDatabase:
    """Drop a deleted collection's ClickHouse database and Manticore tables."""

    @workflow.run
    async def run(self, params: "CollectionDatabaseParams") -> str:
        return await workflow.execute_activity(
            drop_collection_database,
            CollectionDatabaseParams(collectionname=params.collectionname),
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )


@workflow.defn
class PurgeDataset:
    """Purge a soft-deleted dataset's data from its collection.

    Triggered by `admin_delete_dataset` after the registry row is soft-deleted:
    (a) deletes the dataset's rows from every Manticore shard table of the
    collection, (b) deletes its rows from every collection-DB table with a
    `collection_dataset` column, (c) recomputes the shard ledger's fill levels
    from the remaining `manticore_shard_assignments`. Shards are never compacted
    or renumbered.
    """

    @workflow.run
    async def run(self, params: "PurgeDatasetParams") -> str:
        await workflow.execute_activity(
            purge_dataset_from_manticore,
            PurgeDatasetParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset),
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        await workflow.execute_activity(
            purge_dataset_from_clickhouse,
            PurgeDatasetParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset),
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        # The cell table has no `collection_dataset` column -- one parse serves every
        # dataset holding the same file -- so the purge above cannot reach it and the
        # sweeper is what releases the cells no surviving dataset claims.
        await workflow.execute_activity(
            sweep_orphan_table_cells,
            CollectionDatabaseParams(collectionname=params.collectionname),
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        return await workflow.execute_activity(
            recompute_shard_ledger_activity,
            CollectionDatabaseParams(collectionname=params.collectionname),
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )


#: The patch id of the target-based OCR run. A RerunOcr that started before it replays the
#: whole-plan path.
RUN_OCR_TARGETS_PATCH = "run-ocr-targets"
#: The download folder of the target phase. ExecutePlans uses the plan folders beside it.
OCR_RUN_TEMP_DIR = "/tmp/hoover4/ocr-run"
#: Plans of the target phase that run at once, the window of ExecutePlans.
OCR_RUN_PLAN_WINDOW = 16


@workflow.defn
class RerunOcr:
    """Bring every OCR target of a dataset to done: the "Run OCR" action.

    See `tasks/P_admin/ocr_rerun.py`. It first runs the unfinished plans with every stage,
    then records the open targets, runs one `OcrRunPlan` for each plan with an open
    target, and fails while any target stays open. It continues as new after each full
    page of plans. It is always a child of the `rerun_ocr` operation, which owns the row's
    state and its progress.
    """

    @workflow.run
    async def run(self, params: "RerunOcrParams") -> dict:
        if not workflow.patched(RUN_OCR_TARGETS_PATCH):
            return await self._whole_plans(params)
        if not params.listed:
            params = await self._phase_one(params)
        page = await workflow.execute_activity(
            list_ocr_run_plans,
            ListOcrRunPlansParams(params.collectionname, params.collection_dataset,
                                  params.op_id, params.after),
            start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        results = await run_with_window(
            [functools.partial(self._plan, params, plan_hash) for plan_hash in page],
            OCR_RUN_PLAN_WINDOW,
        )
        failed = 0
        for result in results:
            if isinstance(result, BaseException):
                if is_cancellation(result):
                    raise result
                failed += 1
        params = dataclasses.replace(params, plans=params.plans + len(page),
                                     failed_plans=params.failed_plans + failed)
        if len(page) == OCR_RUN_PAGE:
            workflow.continue_as_new(dataclasses.replace(params, after=page[-1]))
        failed_steps = params.failed_dataset_steps
        if params.plans:
            failed_steps += await self._dataset_steps(params)
        await workflow.execute_activity(
            verify_ocr_run_completion,
            VerifyOcrRunParams(params.collectionname, params.collection_dataset, params.op_id),
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        return {
            "plans": params.phase_one_plans + params.plans,
            "targets_plans": params.plans,
            "execution_counts": {
                "plans_run": params.phase_one_plans + params.plans,
                "failed_plans": params.failed_plans,
                "failed_dataset_steps": failed_steps,
            },
        }

    async def _whole_plans(self, params: "RerunOcrParams") -> dict:
        """The run of executions that started before the target-based run. Replay only."""
        reopened = await workflow.execute_activity(
            reopen_plans_for_ocr_rerun,
            params,
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        execution_counts = {}
        if reopened:
            execution_counts = await workflow.execute_child_workflow(
                ExecutePlans.run,
                ExecutePlansParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    base_temp_dir="/tmp/hoover4",
                    op_id=params.op_id,
                ),
                id=f"ocr-rerun-execute-{params.op_id}",
                task_queue="processing-common-queue",
                search_attributes=dataset_search_attributes(params.collection_dataset),
            )
        return {"plans": reopened, "execution_counts": execution_counts}

    async def _phase_one(self, params: "RerunOcrParams") -> "RerunOcrParams":
        """Run the unfinished plans and the blobs without a plan, then record the targets."""
        # No operation id: this read only decides whether ExecutePlans runs, and an id
        # would record the listed plans against the operation a second time.
        pending = await workflow.execute_activity(
            list_pending_plans,
            ListPendingPlansParams(params.collectionname, params.collection_dataset, op_id=""),
            start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        new_blobs = await workflow.execute_activity(
            count_new_blobs,
            CountNewBlobsParams(params.collectionname, params.collection_dataset),
            start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        await workflow.execute_activity(
            ensure_temp_dir_exists,
            EnsureTempDirExistsParams(base_temp_dir=OCR_RUN_TEMP_DIR),
            start_to_close_timeout=timedelta(minutes=12),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        counts: dict = {}
        if pending or new_blobs:
            counts = await workflow.execute_child_workflow(
                ExecutePlans.run,
                ExecutePlansParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    base_temp_dir="/tmp/hoover4",
                    op_id=params.op_id,
                ),
                id=f"run-ocr-plans-{params.op_id}",
                task_queue="processing-common-queue",
                search_attributes=dataset_search_attributes(params.collection_dataset),
            )
        await workflow.execute_activity(
            record_ocr_run_targets,
            params,
            start_to_close_timeout=timedelta(minutes=120),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        return dataclasses.replace(
            params,
            listed=True,
            phase_one_plans=int(counts.get("plans_run", 0)),
            failed_plans=params.failed_plans + int(counts.get("failed_plans", 0)),
            failed_dataset_steps=(params.failed_dataset_steps
                                  + int(counts.get("failed_dataset_steps", 0))),
        )

    async def _plan(self, params: "RerunOcrParams", plan_hash: str):
        return await workflow.execute_child_workflow(
            OcrRunPlan.run,
            OcrRunPlanParams(params.collectionname, params.collection_dataset,
                             params.op_id, plan_hash),
            id=f"run-ocr-plan-{params.op_id}-{plan_hash}",
            task_queue="processing-common-queue",
            search_attributes=dataset_search_attributes(params.collection_dataset),
        )

    async def _dataset_steps(self, params: "RerunOcrParams") -> int:
        """Refresh the entity terms and compact the shards. Returns the failed steps."""
        failed = await execute_dataset_step(
            index_entity_terms,
            BuildVfsNodesParams(params.collectionname, params.collection_dataset), 30,
            params.collectionname, params.collection_dataset, params.op_id,
        )
        failed += await execute_dataset_step(
            compact_collection_shards,
            CompactCollectionShardsParams(params.collectionname, False, params.op_id), 10,
            params.collectionname, params.collection_dataset, params.op_id,
        )
        return failed


@workflow.defn
class OcrRunPlan:
    """The open OCR targets of one plan: OCR stages, then text steps, then settlement.

    See `tasks/P_admin/ocr_rerun.py`. It reads and writes no plan-finished marker. It
    fails when a target of the plan is still open after its work, and the parent
    `RerunOcr` counts it as a failed plan.
    """

    @workflow.run
    async def run(self, params: "OcrRunPlanParams") -> dict:
        work = await workflow.execute_activity(
            load_ocr_run_plan,
            params,
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        total_bytes = sum(file.file_size_bytes for file in work.files)
        if work.files:
            downloaded = await workflow.execute_activity(
                download_plan_files,
                DownloadPlanFilesParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    plan_hash=params.plan_hash,
                    items=[{"item_hash": file.item_hash,
                            "file_size_bytes": file.file_size_bytes,
                            "s3_url": file.s3_url} for file in work.files],
                    base_temp_dir=OCR_RUN_TEMP_DIR,
                ),
                # The rule of ExecuteSinglePlan: 900 s and the size at 100 kbit/s.
                start_to_close_timeout=timedelta(seconds=900 + math.ceil(total_bytes / 12_500)),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            )
            groups = [work.files[i:i + PLAN_GROUP_SIZE]
                      for i in range(0, len(work.files), PLAN_GROUP_SIZE)]
            results = await run_with_window(
                [functools.partial(self._group, params, downloaded.get("out_dir"), index, group)
                 for index, group in enumerate(groups)],
                MAX_PLAN_DRIVERS,
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result

        candidates = sorted({file.item_hash for file in work.files if file.image_engines}
                            | set(work.index_hashes))
        pending: list = []
        if candidates:
            pending = await workflow.execute_activity(
                ocr_text_pending_index,
                OcrTextPendingParams(params.collectionname, params.collection_dataset,
                                     params.op_id, params.plan_hash, candidates),
                start_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            )
        if pending:
            await self._text_steps(params, pending)

        settlement = await workflow.execute_activity(
            settle_ocr_run_targets,
            SettleOcrRunTargetsParams(params.collectionname, params.collection_dataset,
                                      params.op_id, params.plan_hash),
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        if work.files:
            await workflow.execute_activity(
                cleanup_plan_dir,
                CleanupPlanDirParams(params.collectionname, params.collection_dataset,
                                     params.plan_hash, OCR_RUN_TEMP_DIR),
                start_to_close_timeout=timedelta(seconds=900 + math.ceil(total_bytes / 12_500)),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            )
        if settlement.remaining:
            raise ApplicationError(
                f"{settlement.remaining} OCR targets of plan {params.plan_hash} are not done "
                "after its run",
                type=OCR_RUN_INCOMPLETE,
                non_retryable=True,
            )
        return {"files": len(work.files), "indexed": len(pending),
                "settled": settlement.settled}

    async def _group(self, params: "OcrRunPlanParams", out_dir: str, index: int,
                     files: list) -> None:
        """Preview and OCR of one group of files, its errors, and its settlement."""
        starts: dict = {}

        def batch_file(file: "OcrRunFile", **fields) -> "BatchFile":
            return BatchFile(item_hash=file.item_hash, file_path=f"{out_dir}/{file.item_hash}",
                             file_size_bytes=file.file_size_bytes, **fields)

        async def run_stage(name: str, chosen: list, items: list, engine: str = "") -> list:
            """One stage activity, as `(file, result)` pairs. A failed activity fails each file."""
            if not chosen:
                return []
            starts[name, engine] = workflow.now()
            try:
                batch = await workflow.execute_activity(
                    name,
                    StageBatchParams(
                        collectionname=params.collectionname,
                        collection_dataset=params.collection_dataset,
                        plan_hash=params.plan_hash,
                        files=items,
                        op_id=params.op_id,
                        engine=engine,
                    ),
                    result_type=BatchResult,
                    start_to_close_timeout=timedelta(seconds=stage_timeout_seconds(
                        name, [item.file_size_bytes for item in items])),
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    # No attempt limit, as in the group workflow of ingestion. The runner
                    # fails the stage after consecutive attempts that finish no new file.
                    retry_policy=RetryPolicy(maximum_attempts=0),
                    task_queue=STAGE_QUEUES[name],
                )
                return list(zip(chosen, batch.results))
            except ActivityError as exc:
                return list(zip(chosen, stage_failure_results(
                    name, [file.item_hash for file in chosen], exc)))

        images = [file for file in files if file.image_engines]
        outcomes: dict = {}

        async def image_ocr() -> None:
            # OCR reads the preview of an uncommon image format, so it waits for it. A
            # failed preview has no error name, and the OCR stage reads the original.
            await run_stage("make_image_preview_batch", images, [
                batch_file(file, mime_types=list(file.mime_types), routes=["image"])
                for file in images])

            async def engine_ocr(engine: str) -> None:
                chosen = [file for file in images if engine in file.image_engines]
                outcomes["run_ocr_batch", engine] = await run_stage(
                    "run_ocr_batch", chosen, [batch_file(file) for file in chosen], engine)

            await asyncio.gather(*[engine_ocr(engine) for engine in OCR_ENGINES])

        async def pdf_ocr(engine: str) -> None:
            chosen = [file for file in files if engine in file.pdf_engines]
            outcomes["run_ocr_pdf_batch", engine] = await run_stage(
                "run_ocr_pdf_batch", chosen, [batch_file(file) for file in chosen], engine)

        await asyncio.gather(image_ocr(), *[pdf_ocr(engine) for engine in OCR_ENGINES])

        # One error row for each failed file of each stage, in a fixed order. The groups of
        # one plan share a run id, so the call site of each source id names the group.
        run_id = workflow.info().run_id
        errors, task_ids, error_starts, hashes = [], [], [], []
        for name, error_name in (("run_ocr_batch", ocr_error_name),
                                 ("run_ocr_pdf_batch", ocr_pdf_error_name)):
            for engine in OCR_ENGINES:
                for file, result in outcomes.get((name, engine), []):
                    if result.status != "failed":
                        continue
                    errors.append(file_error(result))
                    task_ids.append(error_name(engine))
                    error_starts.append(starts.get((name, engine), workflow.now()))
                    hashes.append(file.item_hash)
        await record_errors_from_results(
            errors,
            source_execution_ids=[source_execution_id(run_id, f"P3.ocr_run.{index}", n)
                                  for n in range(len(errors))],
            task_ids=task_ids,
            starts=error_starts,
            collectionname=params.collectionname,
            collection_dataset=params.collection_dataset,
            item_hashes=hashes,
            op_id=params.op_id,
            start_to_close_timeout_seconds=FILE_BASE_SECONDS,
        )

        # New OCR text opens its index target before the OCR targets settle, so the
        # progress total grows before the progress can reach it.
        if images:
            await workflow.execute_activity(
                ocr_text_pending_index,
                OcrTextPendingParams(params.collectionname, params.collection_dataset,
                                     params.op_id, params.plan_hash,
                                     [file.item_hash for file in images]),
                start_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            )
        await workflow.execute_activity(
            settle_ocr_run_targets,
            SettleOcrRunTargetsParams(params.collectionname, params.collection_dataset,
                                      params.op_id, params.plan_hash,
                                      [file.item_hash for file in files]),
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )

    async def _text_steps(self, params: "OcrRunPlanParams", hashes: list) -> None:
        """P4 and P5 together, then P6, for the files whose OCR text is not indexed.

        Date resolution and the canonical type do not run: OCR text changes neither.
        """
        attributes = dataset_search_attributes(params.collection_dataset)
        common = dict(task_queue="processing-common-queue", search_attributes=attributes)
        results = await asyncio.gather(
            workflow.execute_child_workflow(
                ExtractEntitiesForPlan.run,
                ExtractEntitiesForPlanParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    plan_hash=params.plan_hash, op_id=params.op_id, item_hashes=hashes),
                id=f"run-ocr-entities-{params.op_id}-{params.plan_hash}", **common),
            workflow.execute_child_workflow(
                ScanRegexEntitiesForPlan.run,
                ScanRegexEntitiesForPlanParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    plan_hash=params.plan_hash, op_id=params.op_id, item_hashes=hashes),
                id=f"run-ocr-regex-{params.op_id}-{params.plan_hash}", **common),
            workflow.execute_child_workflow(
                ChunkEmbedForPlan.run,
                ChunkEmbedForPlanParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    plan_hash=params.plan_hash, op_id=params.op_id, item_hashes=hashes),
                id=f"run-ocr-embed-{params.op_id}-{params.plan_hash}", **common),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result
        await workflow.execute_child_workflow(
            IndexDatasetPlan.run,
            IndexDatasetPlanParams(
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                plan_hash=params.plan_hash, op_id=params.op_id, item_hashes=hashes),
            id=f"run-ocr-index-{params.op_id}-{params.plan_hash}", **common)


@workflow.defn
class ChangeOcrLanguages:
    """Apply a dataset's new OCR language settings, end to end.

    See `tasks/P_admin/ocr_languages.py` for why the order of the stages below is not
    interchangeable. Every stage merges its name and its counters into the operation
    row's `detail` before it starts, so a change that is still running says which of the
    four stages it is in rather than only that it has not finished.

    It is always a child of the `change_ocr_languages` operation, and the operation owns
    the row's state: this workflow reports stages and raises, and the parent is what
    writes `finished` or `errored`. Writing a terminal state from in here would release
    the operations lock while this workflow was still deleting variants.
    """

    @workflow.run
    async def run(self, params: "ApplyOcrLanguagesParams") -> dict:
        async def progress(stage: str, extra: dict | None = None) -> None:
            await workflow.execute_activity(
                report_ocr_language_progress,
                OcrStageParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    op_id=params.op_id,
                    stage=stage,
                    detail=json.dumps(extra or {}),
                ),
                start_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            )

        diff = await workflow.execute_activity(
            begin_ocr_language_job,
            params,
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )

        if not diff.changed_engines:
            # The settings are already what was asked for. Saying so is better than
            # re-running the corpus to reach the state it is already in.
            await progress("no change")
            return {"execution_counts": {}}

        reopened = await workflow.execute_activity(
            reopen_plans_for_ocr_change,
            ReopenParams(
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                engines=diff.changed_engines,
            ),
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        await progress("reopened plans", {"plans": reopened})

        execution_counts = {}
        if reopened:
            # The re-run carries the whole downstream chain with it. Parse, OCR, NER,
            # chunk+embed and index are all stages of ExecutePlans, so "re-run" and
            # "reindex" in the spec are one call, not two.
            await progress("reprocessing")
            execution_counts = await workflow.execute_child_workflow(
                ExecutePlans.run,
                ExecutePlansParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    base_temp_dir="/tmp/hoover4",
                    op_id=params.op_id,
                ),
                id=f"ocr-languages-execute-{params.op_id}",
                task_queue="processing-common-queue",
                search_attributes=dataset_search_attributes(params.collection_dataset),
            )

        purged = {}
        if diff.removed_variants:
            await progress("purging dropped variants",
                           {"removed": diff.removed_variants})
            purged = await workflow.execute_activity(
                purge_dropped_ocr_variants,
                PurgeVariantsParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    variants=diff.removed_variants,
                    removed_pairs=diff.removed_pairs,
                ),
                start_to_close_timeout=timedelta(minutes=60),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            )

            await progress("deleting derived objects")
            await workflow.execute_activity(
                delete_orphaned_derived_pdfs,
                PurgeVariantsParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    variants=diff.removed_variants,
                    removed_pairs=diff.removed_pairs,
                ),
                start_to_close_timeout=timedelta(minutes=60),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            )

        await progress("done", {
            "plans": reopened,
            "added": diff.added_variants,
            "removed": diff.removed_variants,
            "purged": purged,
        })
        return {"execution_counts": execution_counts}


@workflow.defn
class CollectEtaSamples:
    """Self-scheduling ETA sampler for the admin processing page.

    Runs one sampling pass (the ``collect_eta_samples`` activity), then sleeps
    for ``20 x mean(last 10 pass durations)``. See ``eta_collector`` for the
    estimate and throttle rules. A singleton: started once at worker bootstrap
    with workflow id ``collect-eta-samples`` and ``USE_EXISTING`` conflict
    policy, so worker restarts never duplicate it.

    State (throttle history and the finished-collection skip set) is carried
    across ``continue_as_new`` every ``CONTINUE_AS_NEW_PASSES`` passes to bound
    the workflow history. ``passes`` is reset to 0 before that call, otherwise
    the next run is already at the threshold and continue-as-news every pass
    with no sleep.
    """

    @workflow.run
    async def run(self, state: "EtaCollectorState | None" = None) -> str:
        if state is None:
            state = EtaCollectorState()

        while True:
            now = workflow.now().timestamp()
            skip = [c for c, recheck_at in state.finished.items() if recheck_at > now]

            try:
                result = await workflow.execute_activity(
                    collect_eta_samples,
                    CollectEtaSamplesParams(skip_collections=skip),
                    start_to_close_timeout=timedelta(minutes=30),
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
            except ActivityError as exc:
                if _is_cancellation(exc):
                    raise
                workflow.logger.warning("ETA sampling failed: %s", exc)
            else:
                state.recent_durations_ms.append(result.duration_ms)
                state.recent_durations_ms = state.recent_durations_ms[-THROTTLE_HISTORY:]
                for c in result.completed_collections:
                    state.finished[c] = now + FINISHED_RECHECK_SECONDS
                for c in result.active_collections:
                    state.finished.pop(c, None)

            try:
                await workflow.execute_activity(
                    supervise_operations,
                    task_queue="operations-queue",
                    start_to_close_timeout=timedelta(minutes=30),
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
            except ActivityError as exc:
                if _is_cancellation(exc):
                    raise
                workflow.logger.warning("Operation supervision failed: %s", exc)

            # The agent run sweep. A run that was open before this call existed replays
            # with no marker and skips it until its next continue-as-new.
            if workflow.patched("agent-run-sweep"):
                try:
                    await workflow.execute_activity(
                        supervise_agent_runs,
                        task_queue="operations-queue",
                        start_to_close_timeout=timedelta(minutes=10),
                        heartbeat_timeout=HEARTBEAT_TIMEOUT,
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )
                except ActivityError as exc:
                    if _is_cancellation(exc):
                        raise
                    workflow.logger.warning("Agent run supervision failed: %s", exc)
            state.passes += 1

            if state.passes >= CONTINUE_AS_NEW_PASSES:
                # continue_as_new carries this dataclass into the next run. Leaving
                # `passes` at the threshold makes the next run continue-as-new on
                # every pass with no sleep, so the 60 s floor never applies.
                state.passes = 0
                workflow.continue_as_new(state)

            await asyncio.sleep(next_interval_seconds(state.recent_durations_ms))


def _is_cancellation(exc: BaseException) -> bool:
    """Return whether an activity failure contains a cancellation."""
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, (CancelledError, asyncio.CancelledError)):
            return True
        cause = getattr(current, "cause", None)
        current = cause if isinstance(cause, BaseException) else None
    return False


@workflow.defn
class SweepChatArtifacts:
    """Daily retention pass over `chat_artifacts`.

    A singleton like ``CollectEtaSamples``, started once at worker bootstrap with
    ``USE_EXISTING`` so worker restarts never duplicate it. It sleeps rather than using a
    Temporal cron schedule for the same reason that one does: the state and the cadence
    stay in one place, and a missed day is caught by the next pass rather than piling up
    as overlapping cron executions.
    """

    @workflow.run
    async def run(self) -> str:
        last = ""
        # 24 passes, then continue_as_new: bounded history, one month of it.
        for _ in range(24):
            await workflow.sleep(timedelta(hours=24))
            last = await workflow.execute_activity(
                sweep_chat_artifacts,
                start_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            workflow.logger.info("chat artifact sweep: %s", last)
        workflow.continue_as_new()
        return last
