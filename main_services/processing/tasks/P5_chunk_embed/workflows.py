"""Chunk+embed stage (P5) workflow: embed every text segment of a plan.

Runs after P4 (entity extraction) and before P6 (indexing) in the ExecuteSinglePlan
chain: P6's vector indexer copies the ``text_chunk_vectors`` rows this stage writes
into the shard's HNSW table, so an index that ran before embedding would come up with
empty ``_vectors`` tables.
"""

import logging
from asyncio import gather
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

log = logging.getLogger(__name__)


with workflow.unsafe.imports_passed_through():
    from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT
    from tasks.plan_utils import FetchPlanHashesParams, fetch_plan_hashes
    from tasks.P3_parse_files.parse_common import record_errors_from_results
    from .activities import chunk_embed_for_hashes
    from .params import ChunkEmbedForPlanParams, ChunkEmbedParams

EMBED_TASK_QUEUE = "processing-embed-queue"


@dataclass
class ScheduledChunk:
    """One scheduled embed chunk: hashes, start time and future kept together so
    results never rely on positional alignment across parallel lists."""

    hashes: list[str]
    started: datetime
    future: Any


@workflow.defn
class ChunkEmbedForPlan:
    """Chunk and embed all text content of one processing plan."""
    @workflow.run
    async def run(self, params: ChunkEmbedForPlanParams) -> str:
        EMBED_CHUNK_SIZE = 100
        EMBED_TIMEOUT = timedelta(minutes=45)

        plan_hashes = await workflow.execute_activity(
            fetch_plan_hashes,
            FetchPlanHashesParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, plan_hash=params.plan_hash),
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        chunks: list[ScheduledChunk] = []
        for chunk_start in range(0, len(plan_hashes), EMBED_CHUNK_SIZE):
            chunk_hashes = plan_hashes[chunk_start:chunk_start+EMBED_CHUNK_SIZE]
            chunks.append(ScheduledChunk(
                hashes=chunk_hashes,
                started=workflow.now(),
                future=workflow.execute_activity(
                    chunk_embed_for_hashes,
                    ChunkEmbedParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, plan_hash=params.plan_hash, hashes=chunk_hashes),
                    start_to_close_timeout=EMBED_TIMEOUT,
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                    task_queue=EMBED_TASK_QUEUE,
                ),
            ))
        results = await gather(*[c.future for c in chunks], return_exceptions=True)

        # A failed chunk (retries already exhausted by the activity) becomes one
        # processing_errors row per hash in the chunk, so every document that
        # missed embedding is individually visible as a failure.
        failed_results = []
        failed_task_ids = []
        failed_starts = []
        failed_hashes = []
        for res, chunk in zip(results, chunks):
            if isinstance(res, Exception):
                for item_hash in chunk.hashes:
                    failed_results.append(res)
                    failed_task_ids.append("P5_ChunkEmbed")
                    failed_starts.append(chunk.started)
                    failed_hashes.append(item_hash)
        await record_errors_from_results(
            failed_results,
            task_ids=failed_task_ids,
            starts=failed_starts,
            collectionname=params.collectionname,
            collection_dataset=params.collection_dataset,
            item_hashes=failed_hashes,
        )

        log.info(f"[P5] Done: chunk+embed for plan {params.collection_dataset} {params.plan_hash}")
        return f"chunked and embedded {params.plan_hash}"
