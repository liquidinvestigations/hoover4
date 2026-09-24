"""Submission helper for kicking off plan execution workflows."""

import tempfile
import logging
import os
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

import temporalio.common

from tasks.P2_execute_plan.workflows import ExecutePlans
from tasks.temporal_readiness import START_RPC_TIMEOUT, connect_when_ready
from tasks.visibility import dataset_search_attributes, start_with_attribute_retry


async def submit_execute_plans(collectionname: str, collection_dataset: str):
    client = await connect_when_ready()
    log.info("Starting execute plans for %s", collection_dataset)
    temp = os.path.join( tempfile.gettempdir(), "hoover4")
    await start_with_attribute_retry(lambda: client.execute_workflow(
        ExecutePlans.run,
        {"collectionname": collectionname, "collection_dataset": collection_dataset, "starting_plan_hash": None, "base_temp_dir": temp},
        id=f"execute-plans-{collection_dataset}",
        task_queue="processing-common-queue",
        id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        id_conflict_policy=temporalio.common.WorkflowIDConflictPolicy.USE_EXISTING,
        search_attributes=dataset_search_attributes(collection_dataset),
        # The limit of the start request only. `execute_workflow` does not pass it to
        # the wait for the result.
        rpc_timeout=START_RPC_TIMEOUT,
    ))
    log.info("Finished execute plans for %s", collection_dataset)


