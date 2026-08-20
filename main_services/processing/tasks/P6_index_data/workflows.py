"""Indexing workflows for processing plan content and metadata."""

from dataclasses import dataclass
from datetime import datetime
import logging
from asyncio import gather
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy
from typing import Any

log = logging.getLogger(__name__)


with workflow.unsafe.imports_passed_through():
    from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT
    from tasks.plan_utils import FetchPlanHashesParams, fetch_plan_hashes
    from tasks.P3_parse_files.parse_common import record_errors_from_results
    from .params import (
        BuildEmailGraphParams,
        FinalizeIndexBatchParams,
        IndexDatasetPlanParams,
        IndexShardParams,
        PlanShardsParams,
        RecordIndexedParams,
    )
    from .activities import (
        build_email_graph,
        index_text_pages,
        index_vectors,
        optimize_shard_tables,
    )
    from .params import OptimizeShardsParams
    from .shard_planner import finalize_index_batch, plan_shards, record_indexed

# plan_shards mutates the shard ledger and must never run concurrently for the
# same collection: it goes to a dedicated queue served by exactly one worker
# with max_concurrent_activities=1. See shard_planner.py's module docstring.
PLANNER_TASK_QUEUE = "processing-index-planner-queue"
INDEXING_TASK_QUEUE = "processing-indexing-queue"


@dataclass
class ScheduledChunk:
    """One writer chunk scheduled against one shard: both writer activities for the same
    hashes, kept together so results never rely on positional alignment across parallel
    lists."""

    shard_name: str
    hashes: list[str]
    started: datetime
    pages_future: Any
    vectors_future: Any


@workflow.defn
class IndexDatasetPlan:
    """Workflow that indexes a dataset plan into per-collection Manticore shards."""
    @workflow.run
    async def run(self, params: IndexDatasetPlanParams) -> str:
        INDEXING_CHUNK_SIZE = 100
        INDEXING_TIMEOUT = timedelta(minutes=45)

        plan_hashes = await workflow.execute_activity(
            fetch_plan_hashes,
            FetchPlanHashesParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, plan_hash=params.plan_hash),
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        # ClickHouse vfs_nodes and the canonical file type are built once per
        # ExecutePlans batch, before these per-plan children run. Manticore vfs is
        # upserted once on the terminal batch. This workflow writes shards and the
        # email graph.

        assignments = await workflow.execute_activity(
            plan_shards,
            PlanShardsParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, plan_hash=params.plan_hash, hashes=plan_hashes),
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
            task_queue=PLANNER_TASK_QUEUE,
        )

        chunks: list[ScheduledChunk] = []
        for assignment in assignments:
            for chunk_start in range(0, len(assignment.hashes), INDEXING_CHUNK_SIZE):
                chunk_hashes = assignment.hashes[chunk_start:chunk_start+INDEXING_CHUNK_SIZE]
                shard_params = IndexShardParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    plan_hash=params.plan_hash,
                    shard_name=assignment.shard_name,
                    hashes=chunk_hashes,
                )
                chunks.append(ScheduledChunk(
                    shard_name=assignment.shard_name,
                    hashes=chunk_hashes,
                    started=workflow.now(),
                    pages_future=workflow.execute_activity(
                        index_text_pages,
                        shard_params,
                        start_to_close_timeout=INDEXING_TIMEOUT,
                        heartbeat_timeout=HEARTBEAT_TIMEOUT,
                        retry_policy=RetryPolicy(maximum_attempts=2),
                        task_queue=INDEXING_TASK_QUEUE,
                    ),
                    vectors_future=workflow.execute_activity(
                        index_vectors,
                        shard_params,
                        start_to_close_timeout=INDEXING_TIMEOUT,
                        heartbeat_timeout=HEARTBEAT_TIMEOUT,
                        retry_policy=RetryPolicy(maximum_attempts=2),
                        task_queue=INDEXING_TASK_QUEUE,
                    ),
                ))
        pages_results = await gather(*[c.pages_future for c in chunks], return_exceptions=True)
        vectors_results = await gather(*[c.vectors_future for c in chunks], return_exceptions=True)

        # A failed writer chunk (retries already exhausted) becomes one
        # processing_errors row per hash in the chunk, so every document that
        # missed indexing is individually visible as a failure.
        failed_results = []
        failed_task_ids = []
        failed_starts = []
        failed_hashes = []
        # index_state entries: the union of the hashes each successful writer
        # reports as written. A permanently failed writer chunk contributes nothing.
        indexed_entries: set[tuple[str, str]] = set()
        for chunk, pages_res, vectors_res in zip(chunks, pages_results, vectors_results):
            for res, task_id in ((pages_res, "P6_IndexTextPages"),
                                 (vectors_res, "P6_IndexVectors")):
                if isinstance(res, Exception):
                    for item_hash in chunk.hashes:
                        failed_results.append(res)
                        failed_task_ids.append(task_id)
                        failed_starts.append(chunk.started)
                        failed_hashes.append(item_hash)
                else:
                    for item_hash in res:
                        indexed_entries.add((chunk.shard_name, item_hash))
        await record_errors_from_results(
            failed_results,
            task_ids=failed_task_ids,
            starts=failed_starts,
            collectionname=params.collectionname,
            collection_dataset=params.collection_dataset,
            item_hashes=failed_hashes,
        )

        # Record what actually reached a shard before refreshing the ledger:
        # recompute_shard_ledger counts from index_state, so a permanently failed
        # writer chunk never inflates the shard budget.
        if indexed_entries:
            await workflow.execute_activity(
                record_indexed,
                RecordIndexedParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    plan_hash=params.plan_hash,
                    entries=sorted(indexed_entries),
                ),
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                task_queue=PLANNER_TASK_QUEUE,
            )

        await workflow.execute_activity(
            finalize_index_batch,
            FinalizeIndexBatchParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, plan_hash=params.plan_hash),
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
            task_queue=PLANNER_TASK_QUEUE,
        )

        # Compaction, once per plan and only for the shards it wrote to — never in the
        # per-chunk loop, where it would compete with the writer for I/O on the table
        # being written. The statement itself is asynchronous, so this returns as soon as
        # the merges are queued.
        if chunks:
            await workflow.execute_activity(
                optimize_shard_tables,
                OptimizeShardsParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    plan_hash=params.plan_hash,
                    shard_names=sorted({c.shard_name for c in chunks}),
                ),
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=2),
                task_queue=INDEXING_TASK_QUEUE,
            )

        # The email connection graph, last: it reads `email_identity` for the whole
        # collection and the identity rows for THIS dataset are refreshed by the same
        # activity, so running it before the writers would only mean running it on a
        # dataset that had not finished arriving. Collection-scoped, idempotent, and
        # cheap on a collection with no email in it.
        await workflow.execute_activity(
            build_email_graph,
            BuildEmailGraphParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset),
            start_to_close_timeout=timedelta(minutes=60),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
            task_queue=INDEXING_TASK_QUEUE,
        )

        log.info(f"[P6] Done: Indexing dataset plan {params.collection_dataset} {params.plan_hash}")
        return f"indexed {params.plan_hash}"
