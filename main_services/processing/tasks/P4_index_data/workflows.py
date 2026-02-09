"""Indexing workflows for processing plan content and metadata."""

from dataclasses import dataclass
import logging
from asyncio import gather
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

log = logging.getLogger(__name__)


with workflow.unsafe.imports_passed_through():
    from .params import IndexDatasetPlanParams, IndexTextContentParams
    from .activities import fetch_plan_hashes, index_metadatas, index_text_content


@workflow.defn
class IndexDatasetPlan:
    """Workflow that indexes a dataset plan."""
    @workflow.run
    async def run(self, params: IndexDatasetPlanParams) -> str:
        INDEXING_CHUNK_SIZE = 100
        INDEXING_TIMEOUT = timedelta(minutes=45)

        plan_hashes = await workflow.execute_activity(
            fetch_plan_hashes,
            IndexDatasetPlanParams(collection_dataset=params.collection_dataset, plan_hash=params.plan_hash),
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        fut = []
        for chunk in range(0, len(plan_hashes), INDEXING_CHUNK_SIZE):
            chunk_hashes = plan_hashes[chunk:chunk+INDEXING_CHUNK_SIZE]
            fut.append(workflow.execute_activity(
                index_text_content,
                IndexTextContentParams(collection_dataset=params.collection_dataset, plan_hash=params.plan_hash, hashes=chunk_hashes),
                start_to_close_timeout=INDEXING_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=2),
                task_queue="processing-indexing-queue",
            ))
            fut.append(workflow.execute_activity(
                index_metadatas,
                IndexTextContentParams(collection_dataset=params.collection_dataset, plan_hash=params.plan_hash, hashes=chunk_hashes),
                start_to_close_timeout=INDEXING_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=2),
            ))
        await gather(*fut, return_exceptions=True)
        log.info(f"[P4] Done: Indexing dataset plan {params.collection_dataset} {params.plan_hash}")
        return f"indexed {params.plan_hash}"