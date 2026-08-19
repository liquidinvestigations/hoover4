import asyncio, sys
from temporalio.client import Client as TemporalClient
import temporalio.common
from tasks.P6_index_data.workflows import IndexDatasetPlan
from tasks.P6_index_data.params import IndexDatasetPlanParams
from tasks.visibility import dataset_search_attributes
from database.clickhouse import get_collection_client

collectionname, collection_dataset = sys.argv[1], sys.argv[2]

with get_collection_client(collectionname) as client:
    plans = [r[0] for r in client.query(
        "SELECT plan_hash FROM processing_plan_finished FINAL WHERE collection_dataset = "
        "{cd:String} ORDER BY plan_hash", parameters={"cd": collection_dataset}).result_rows]
print("plans:", [p[:8] for p in plans], flush=True)

async def main():
    client = await TemporalClient.connect("temporal:7233")
    for plan_hash in plans:
        handle = await client.start_workflow(
            IndexDatasetPlan.run,
            IndexDatasetPlanParams(collectionname=collectionname, collection_dataset=collection_dataset, plan_hash=plan_hash),
            id=f"smoke-{collection_dataset}-{plan_hash}",
            task_queue="processing-common-queue",
            id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            id_conflict_policy=temporalio.common.WorkflowIDConflictPolicy.USE_EXISTING,
            search_attributes=dataset_search_attributes(collection_dataset),
        )
        print("result:", await handle.result(), flush=True)

asyncio.run(main())
