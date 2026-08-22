"""Activities that write the operations row and drive the store-specific work.

Everything here runs on the operations queues, in the operations container, so a long
backup or a slow ClickHouse poll cannot take an activity slot away from ingestion.
"""

import logging
import time

from temporalio import activity

from ..heartbeat import with_heartbeat
from .params import DatasetProgressParams, OperationStateParams

log = logging.getLogger(__name__)


@activity.defn
@with_heartbeat
def record_operation_state(params: OperationStateParams) -> str:
    """Move an operations row to a new state, or update its counters in place.

    Separate from the workflow's own progress because a workflow cannot touch a
    database: the row is the only thing outside Temporal that knows this run exists,
    and it has to be written by something that can fail and be retried.
    """
    from database.operations import finish_operation, update_operation, TERMINAL_STATES

    if params.state in TERMINAL_STATES:
        finish_operation(params.op_id, params.state, params.error)
        return params.state
    changes: dict = {}
    if params.state:
        changes["state"] = params.state
    if params.progress_total or params.progress_done:
        changes["progress_done"] = params.progress_done
        changes["progress_total"] = params.progress_total
    if changes:
        update_operation(params.op_id, **changes)
    return params.state or "unchanged"


@activity.defn
@with_heartbeat
def sample_dataset_progress(params: DatasetProgressParams) -> list[int]:
    """Count a dataset's plans and finished plans, and write them onto the row.

    Plans rather than documents, because a plan is the unit the pipeline finishes and
    the only one whose total is known before the work is done. The estimate is derived
    from this operation's own elapsed time rather than from the global sampler, so it
    is right for this run's data even when nothing comparable has ever been ingested.

    Returns `[done, total]`. A dataset whose scan has not produced plans yet is
    `[0, 0]`, which the row records as "no estimate can be made" rather than as zero
    progress out of zero work.
    """
    from database.clickhouse import get_collection_client
    from database.operations import get_operation, update_operation

    done = total = 0
    with get_collection_client(params.collectionname) as client:
        rows = client.query(
            "SELECT count() FROM processing_plans FINAL "
            "WHERE collection_dataset = {cd:String}",
            parameters={"cd": params.collection_dataset},
        ).result_rows
        # An aggregate over an empty match returns one row holding zero, never no
        # rows, so this reads the value rather than testing whether a row came back.
        total = int(rows[0][0]) if rows else 0
        rows = client.query(
            "SELECT count() FROM processing_plan_finished FINAL "
            "WHERE collection_dataset = {cd:String}",
            parameters={"cd": params.collection_dataset},
        ).result_rows
        done = int(rows[0][0]) if rows else 0

    eta = 0
    row = get_operation(params.op_id)
    if row and total and done:
        elapsed = max(1.0, time.time() - row["started_at"].timestamp())
        eta = max(0, int(elapsed / done * (total - done)))
    update_operation(params.op_id, progress_done=done, progress_total=total,
                     eta_seconds=eta)
    return [done, total]


@activity.defn
@with_heartbeat
def reindex_collection_activity(collectionname: str) -> int:
    """Rebuild a collection's Manticore tables and shard ledger from its finished plans.

    Shards are never compacted or renumbered in place; this is how they are rebuilt.
    It truncates the ledger, the assignments and the index state, which is why the
    operations lock over the whole collection is taken before it is dispatched: an
    in-flight writer would record index state into shards this is about to drop, and
    the result is a ledger claiming documents no table holds.

    Returns the number of plans queued for re-indexing.
    """
    import asyncio

    from database.clickhouse import get_collection_client
    from database.manticore import drop_collection_tables

    dropped = drop_collection_tables(collectionname)
    log.info("Dropped %d Manticore shard tables of %s", len(dropped), collectionname)

    with get_collection_client(collectionname) as client:
        client.command("TRUNCATE TABLE manticore_shards")
        client.command("TRUNCATE TABLE manticore_shard_assignments")
        client.command("TRUNCATE TABLE index_state")
        plans = client.query(
            "SELECT collection_dataset, plan_hash FROM processing_plan_finished FINAL "
            "ORDER BY collection_dataset, plan_hash"
        ).result_rows

    if not plans:
        log.warning("No finished plans found for %s - nothing to re-index", collectionname)
        return 0

    async def _queue_them():
        import temporalio.common
        from temporalio.client import Client as TemporalClient
        from ..P6_index_data.params import IndexDatasetPlanParams
        from ..P6_index_data.workflows import IndexDatasetPlan
        from ..visibility import dataset_search_attributes

        client = await TemporalClient.connect("temporal:7233")
        for collection_dataset, plan_hash in plans:
            await client.start_workflow(
                IndexDatasetPlan.run,
                IndexDatasetPlanParams(collectionname=collectionname,
                                       collection_dataset=collection_dataset,
                                       plan_hash=plan_hash),
                id=f"reindex-{collection_dataset}-{plan_hash}",
                task_queue="processing-common-queue",
                # Every dispatch must actually re-index, so the id of a previous
                # completed run may be reused; only a concurrent invocation is deduped.
                id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                id_conflict_policy=temporalio.common.WorkflowIDConflictPolicy.USE_EXISTING,
                search_attributes=dataset_search_attributes(collection_dataset),
            )

    # A sync activity, like everything else here, so it runs in the worker's thread
    # pool and `with_heartbeat` can pump for it. This is the one piece of async work
    # inside it, and it gets a loop of its own rather than the activity becoming async
    # and losing the pump.
    asyncio.run(_queue_them())
    return len(plans)
