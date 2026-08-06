"""Submission helper for starting compute-plans workflows."""

from datetime import datetime
import logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

async def submit_compute_plans(collectionname: str, cd: str):
    import temporalio.common
    from temporalio.client import Client as TemporalClient
    from tasks.P1_compute_plans.workflows import ComputePlans
    from tasks.visibility import dataset_search_attributes, start_with_attribute_retry

    client = await TemporalClient.connect("temporal:7233")
    log.info("Starting plan computation for %s", cd)
    await start_with_attribute_retry(lambda: client.execute_workflow(
        ComputePlans.run,
        {"collectionname": collectionname, "collection_dataset": cd},
        id=f"compute-plans-{cd}",
        task_queue="processing-common-queue",
        id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        id_conflict_policy=temporalio.common.WorkflowIDConflictPolicy.USE_EXISTING,
        search_attributes=dataset_search_attributes(cd),
    ))
    log.info("Finished plan computation for %s", cd)