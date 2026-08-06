"""Temporal workflows for collection database lifecycle."""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from tasks.P_admin.activities import (
        CollectionDatabaseParams,
        PurgeDatasetParams,
        collect_eta_samples,
        drop_collection_database,
        ensure_collection_database,
        purge_dataset_from_clickhouse,
        purge_dataset_from_manticore,
        recompute_shard_ledger_activity,
    )
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
            retry_policy=RetryPolicy(maximum_attempts=3),
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
            retry_policy=RetryPolicy(maximum_attempts=3),
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
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        await workflow.execute_activity(
            purge_dataset_from_clickhouse,
            PurgeDatasetParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset),
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return await workflow.execute_activity(
            recompute_shard_ledger_activity,
            CollectionDatabaseParams(collectionname=params.collectionname),
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


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
    the workflow history.
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
                workflow.continue_as_new(state)

            await asyncio.sleep(next_interval_seconds(state.recent_durations_ms))
