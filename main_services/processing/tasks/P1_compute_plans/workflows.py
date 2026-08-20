"""Temporal workflow for counting blobs and scheduling plan computation."""

from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy
import logging
log = logging.getLogger(__name__)

# Import our activities, passing them through the sandbox
with workflow.unsafe.imports_passed_through():
    from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT
    from tasks.P1_compute_plans.activities import count_new_blobs, compute_plans, CountNewBlobsParams, ComputePlansParams
    from dataclasses import dataclass
@dataclass
class ComputePlansWorkflowParams:
    collectionname: str
    collection_dataset: str


@workflow.defn
class ComputePlans:
    """Workflow that counts new blobs and computes processing plans."""
    @workflow.run
    async def run(self, params: "ComputePlansWorkflowParams") -> str:
        # 1) Count new blobs
        count = await workflow.execute_activity(
            count_new_blobs,
            CountNewBlobsParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset),
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )

        if not count:
            log.info("No new blobs for %s; skipping plan computation", params.collection_dataset)
            return "no-op"

        # Throughput target: >= 4000 blobs/sec
        # Compute extra seconds to allow at least 4k blobs/sec beyond base 60s
        # time_budget = 60s + ceil(count / 4000)
        extra_seconds = (int(count) + 3999) // 4000
        time_budget_seconds = 60 + extra_seconds

        planned = await workflow.execute_activity(
            compute_plans,
            ComputePlansParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset),
            start_to_close_timeout=timedelta(seconds=time_budget_seconds),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )

        log.info("Computed plans for %s items in %s", planned, params.collection_dataset)
        return f"planned {planned} items"


