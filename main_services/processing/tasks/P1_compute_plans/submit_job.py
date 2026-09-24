"""Submission helper for starting compute-plans workflows."""

from datetime import datetime
import logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

async def submit_compute_plans(collectionname: str, cd: str):
    import temporalio.common
    from tasks.P1_compute_plans.workflows import ComputePlans
    from tasks.temporal_readiness import START_RPC_TIMEOUT, connect_when_ready
    from tasks.visibility import dataset_search_attributes, start_with_attribute_retry

    client = await connect_when_ready()
    log.info("Starting plan computation for %s", cd)
    # `rpc_timeout` limits the start request only. `execute_workflow` does not pass it
    # to the wait for the result.
    await start_with_attribute_retry(lambda: client.execute_workflow(
        ComputePlans.run,
        {"collectionname": collectionname, "collection_dataset": cd},
        id=f"compute-plans-{cd}",
        task_queue="processing-common-queue",
        id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        id_conflict_policy=temporalio.common.WorkflowIDConflictPolicy.USE_EXISTING,
        search_attributes=dataset_search_attributes(cd),
        rpc_timeout=START_RPC_TIMEOUT,
    ))
    log.info("Finished plan computation for %s", cd)
