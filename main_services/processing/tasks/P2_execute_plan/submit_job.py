"""Submission helper for kicking off plan execution workflows."""

import tempfile
import logging
import os
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

import temporalio.common
from temporalio.client import Client as TemporalClient

from tasks.P2_execute_plan.workflows import ExecutePlans


async def submit_execute_plans(collection_dataset: str):
    client = await TemporalClient.connect("temporal:7233")
    log.info("Starting execute plans for %s", collection_dataset)
    temp = os.path.join( tempfile.gettempdir(), "hoover4")
    await client.execute_workflow(
        ExecutePlans.run,
        {"collection_dataset": collection_dataset, "starting_plan_hash": None, "base_temp_dir": temp},
        id=f"execute-plans-{collection_dataset}",
        task_queue="processing-common-queue",
        id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        id_conflict_policy=temporalio.common.WorkflowIDConflictPolicy.USE_EXISTING,
    )
    log.info("Finished execute plans for %s", collection_dataset)


