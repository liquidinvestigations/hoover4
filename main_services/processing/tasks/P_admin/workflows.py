"""Temporal workflows for collection database lifecycle."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from tasks.P_admin.activities import (
        CollectionDatabaseParams,
        PurgeDatasetParams,
        drop_collection_database,
        ensure_collection_database,
        purge_dataset_from_clickhouse,
        purge_dataset_from_manticore,
        recompute_shard_ledger_activity,
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
