"""Temporal workflows for collection database lifecycle."""

import asyncio
import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

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
    from tasks.P_admin.ocr_languages import (
        ApplyOcrLanguagesParams,
        JobProgressParams,
        PurgeVariantsParams,
        ReopenParams,
        begin_ocr_language_job,
        delete_orphaned_derived_pdfs,
        purge_dropped_ocr_variants,
        reopen_plans_for_ocr_change,
        report_ocr_language_progress,
    )
    from tasks.P2_execute_plan.workflows import ExecutePlans, ExecutePlansParams
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


@workflow.defn
class ChangeOcrLanguages:
    """Apply a dataset's new OCR language settings, end to end.

    See `tasks/P_admin/ocr_languages.py` for why the order of the stages below is not
    interchangeable. Every stage writes the `dataset_jobs` row before it starts, because
    a form that disables itself on a job it cannot see is a form that locks forever — the
    strip on the dataset page polls exactly this row, and a `running` row that has stopped
    advancing is what it renders as stuck.

    A failure marks the row `failed` with the message and re-raises, so the form unlocks
    and the admin can read what went wrong instead of waiting on a job that ended
    silently.
    """

    @workflow.run
    async def run(self, params: "ApplyOcrLanguagesParams") -> str:
        async def progress(stage: str, extra: dict | None = None) -> None:
            await workflow.execute_activity(
                report_ocr_language_progress,
                JobProgressParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    job_id=params.job_id,
                    state="running",
                    detail=json.dumps({"stage": stage, **(extra or {})}),
                ),
                start_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            )

        try:
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
                await workflow.execute_activity(
                    report_ocr_language_progress,
                    JobProgressParams(
                        collectionname=params.collectionname,
                        collection_dataset=params.collection_dataset,
                        job_id=params.job_id,
                        state="done",
                        detail=json.dumps({"stage": "no change"}),
                    ),
                    start_to_close_timeout=timedelta(minutes=5),
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                )
                return "no change"

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

            if reopened:
                # The re-run carries the whole downstream chain with it — parse, OCR, NER,
                # chunk+embed and index are all stages of ExecutePlans, so "re-run" and
                # "reindex" in the spec are one call, not two.
                await progress("reprocessing")
                await workflow.execute_child_workflow(
                    ExecutePlans.run,
                    ExecutePlansParams(
                        collectionname=params.collectionname,
                        collection_dataset=params.collection_dataset,
                        base_temp_dir="/tmp/hoover4",
                    ),
                    id=f"ocr-languages-execute-{params.collection_dataset}-{params.job_id}",
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

            await workflow.execute_activity(
                report_ocr_language_progress,
                JobProgressParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    job_id=params.job_id,
                    state="done",
                    detail=json.dumps({
                        "stage": "done",
                        "plans": reopened,
                        "added": diff.added_variants,
                        "removed": diff.removed_variants,
                        "purged": purged,
                    }),
                ),
                start_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            )
            return "done"
        except Exception as exc:
            # The row is what unlocks the form. Marking it failed is more important than
            # the exception surviving cleanly, so this write gets its own retries and the
            # original error is re-raised afterwards.
            await workflow.execute_activity(
                report_ocr_language_progress,
                JobProgressParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    job_id=params.job_id,
                    state="failed",
                    detail=json.dumps({"stage": "failed"}),
                    error=str(exc)[:2000],
                ),
                start_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=5),
            )
            raise


@workflow.defn
class CollectEtaSamples:
    """Self-scheduling ETA sampler for the admin processing page.

    Runs one sampling pass (the ``collect_eta_samples`` activity), then sleeps
    for ``20 x mean(last 10 pass durations)`` — see ``eta_collector`` for the
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

            result = await workflow.execute_activity(
                collect_eta_samples,
                CollectEtaSamplesParams(skip_collections=skip),
                start_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            state.recent_durations_ms.append(result.duration_ms)
            state.recent_durations_ms = state.recent_durations_ms[-THROTTLE_HISTORY:]
            for c in result.completed_collections:
                state.finished[c] = now + FINISHED_RECHECK_SECONDS
            for c in result.active_collections:
                state.finished.pop(c, None)
            state.passes += 1

            if state.passes >= CONTINUE_AS_NEW_PASSES:
                # continue_as_new carries this dataclass into the next run. Leaving
                # `passes` at the threshold makes the next run continue-as-new on
                # every pass with no sleep, so the 60 s floor never applies.
                state.passes = 0
                workflow.continue_as_new(state)

            await asyncio.sleep(next_interval_seconds(state.recent_durations_ms))


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
