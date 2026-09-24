"""Activities that write the operations row and drive the store-specific work.

Everything here runs on the operations queues, in the operations container, so a long
backup or a slow ClickHouse poll cannot take an activity slot away from ingestion.

The pipeline modules an activity needs are imported **inside the function**, never at
module scope: this module is loaded by a workflow file that the sandbox re-imports, and
dragging the pipeline's C extensions through that importer fails with a bare
`SystemError` naming nothing in this repository.
"""

import logging
import json
import time
import asyncio
from datetime import datetime

from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus, WorkflowFailureError
from temporalio.service import RPCError, RPCStatusCode

from ..heartbeat import with_heartbeat
from .params import (
    DatasetProgressParams, DatasetRegistryParams, OperationStateParams,
)

log = logging.getLogger(__name__)


@activity.defn
@with_heartbeat
def record_operation_state(params: OperationStateParams) -> str:
    """Move an operations row to a new state, or update its counters in place.

    Separate from the workflow's own progress because a workflow cannot touch a
    database: the row is the only thing outside Temporal that knows this run exists,
    and it has to be written by something that can fail and be retried.

    A terminal row stays terminal. The cancellation finalizer writes it after the target
    closes, and a late target activity cannot change it.
    """
    from database.operations import (
        finish_operation, get_operation, update_operation, TERMINAL_STATES,
    )

    current = get_operation(params.op_id)
    if current and current["state"] in TERMINAL_STATES:
        log.info("operation %s is already %s; leaving the row alone",
                 params.op_id, current["state"])
        return current["state"]
    if params.state in TERMINAL_STATES:
        row = finish_operation(params.op_id, params.state, params.error)
        return row["state"] if row else "missing"
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
def cancel_target_operation(op_id: str) -> dict:
    """Cancel the target, wait for closure, and return its recorded context."""
    return asyncio.run(_cancel_target_operation(op_id))


PENDING_START_GRACE_SECONDS = 600
RUNNING_WORKFLOW_GRACE_SECONDS = 120
STUCK_WORKFLOW_ATTEMPTS = 5
WORKFLOW_ABSENT_ERROR = (
    "The workflow of this operation does not exist in Temporal. It did not start, "
    "or Temporal deleted its history after the retention period."
)


@activity.defn
@with_heartbeat
def supervise_operations() -> None:
    """Sweep live rows, then refresh their progress from the configured source."""
    asyncio.run(_supervise_operations())


async def _supervise_operations() -> None:
    """Use the Temporal client after the activity enters its worker thread."""
    from database.operations import _now, live_operations

    client = await Client.connect("temporal:7233")
    await supervise(client, _now(), live_operations(limit=500))


async def supervise(client, now: datetime, rows: list[dict],
                    *, stuck_workflow_attempts: int = STUCK_WORKFLOW_ATTEMPTS) -> None:
    """Apply one supervisor pass with a supplied Temporal client and operation rows."""
    from database.operations import LIVE_STATES, PROGRESS_SOURCES, update_operation

    for row in rows:
        if row["state"] not in LIVE_STATES:
            continue
        try:
            await _supervise_row(client, now, row, stuck_workflow_attempts)
        except Exception:
            log.exception("operation supervision failed for %s", row["op_id"])

    for row in rows:
        source = PROGRESS_SOURCES[row["kind"]]
        if row["state"] != "running" or source is None:
            continue
        try:
            params = DatasetProgressParams(
                op_id=row["op_id"],
                collectionname=row["collectionname"],
                collection_dataset=row["collection_dataset"],
            )
            if source == "plans":
                sample_dataset_progress(params)
            else:
                remaining = count_dataset_rows_activity(params)
                total = int(row["progress_total"])
                update_operation(
                    row["op_id"], base_row=row,
                    progress_done=max(0, total - remaining), progress_total=total,
                )
        except Exception:
            log.exception("operation progress refresh failed for %s", row["op_id"])


async def _supervise_row(client, now: datetime, row: dict,
                         stuck_workflow_attempts: int) -> None:
    """Reconcile one live row with Temporal and stop each stuck descendant."""
    from database.operations import finish_operation

    age_seconds = (now - row["started_at"]).total_seconds()
    grace = (PENDING_START_GRACE_SECONDS if row["state"] == "pending"
             else RUNNING_WORKFLOW_GRACE_SECONDS)
    if age_seconds <= grace:
        return
    handle = client.get_workflow_handle(row["op_id"])
    try:
        description = await handle.describe()
    except RPCError as exc:
        if exc.status == RPCStatusCode.NOT_FOUND:
            finish_operation(row["op_id"], "errored", WORKFLOW_ABSENT_ERROR)
            return
        raise
    if description.status == WorkflowExecutionStatus.COMPLETED:
        finish_operation(row["op_id"], "finished")
        return
    if description.status != WorkflowExecutionStatus.RUNNING:
        error = ("The workflow of this operation ended with status "
                 f"{description.status.name} and did not record its result.")
        try:
            await handle.result()
        except WorkflowFailureError as exc:
            detail = str(exc.cause or exc)
            if detail:
                error = f"{error} {detail}"
        finish_operation(row["op_id"], "errored", error)
        return
    if not row["collection_dataset"]:
        return

    query_dataset = row["collection_dataset"].replace("\\", "\\\\").replace("'", "\\'")
    query = (
        f"CollectionDataset = '{query_dataset}' AND ExecutionStatus = 'Running'"
    )
    stuck = []
    async for execution in client.list_workflows(query, limit=500):
        descendant = client.get_workflow_handle(execution.id, run_id=execution.run_id)
        description = await descendant.describe()
        attempt = description.raw_description.pending_workflow_task.attempt
        if attempt >= stuck_workflow_attempts:
            stuck.append((execution, attempt))
    if not stuck:
        return
    for execution, attempt in stuck:
        descendant = client.get_workflow_handle(execution.id, run_id=execution.run_id)
        try:
            await descendant.terminate(
                reason=(f"Operation {row['op_id']} stopped workflow task after it "
                        f"failed {attempt} times."),
            )
        except RPCError as exc:
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise
    first, first_attempt = stuck[0]
    others = len(stuck) - 1
    error = (
        f"Workflow {first.workflow_type} {first.id} failed its workflow task "
        f"{first_attempt} times"
    )
    if others:
        error += f", and {others} other workflows of this dataset were stuck."
    else:
        error += "."
    error += " The worker log names the cause."
    finish_operation(row["op_id"], "errored", error)
    await handle.cancel()


async def _cancel_target_operation(op_id: str) -> dict:
    """Use the Temporal client after the activity enters its worker thread."""
    from database.operations import get_operation, TERMINAL_STATES

    row = get_operation(op_id)
    if row is None:
        raise ValueError(f"operation not found: {op_id}")
    context = {
        "state": row["state"],
        "collectionname": row["collectionname"],
        "collection_dataset": row["collection_dataset"],
        "history_missing": False,
    }
    if row["state"] in TERMINAL_STATES:
        return context

    client = await Client.connect("temporal:7233")
    handle = client.get_workflow_handle(op_id)
    try:
        description = await handle.describe()
    except RPCError as exc:
        if exc.status == RPCStatusCode.NOT_FOUND:
            context["history_missing"] = True
            return context
        raise
    if description.status == WorkflowExecutionStatus.RUNNING:
        try:
            await handle.cancel()
        except RPCError as exc:
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise
            try:
                description = await handle.describe()
            except RPCError as lookup_error:
                if lookup_error.status == RPCStatusCode.NOT_FOUND:
                    context["history_missing"] = True
                    return context
                raise
            if description.status == WorkflowExecutionStatus.RUNNING:
                raise
            context["target_status"] = description.status.name
            return context
        try:
            await handle.result()
        except WorkflowFailureError:
            pass
        except RPCError as exc:
            if exc.status == RPCStatusCode.NOT_FOUND:
                context["history_missing"] = True
                return context
            raise
        try:
            description = await handle.describe()
        except RPCError as exc:
            if exc.status == RPCStatusCode.NOT_FOUND:
                context["history_missing"] = True
                return context
            raise
    context["target_status"] = description.status.name
    return context


@activity.defn
@with_heartbeat
def sample_dataset_progress(params: DatasetProgressParams) -> list[int]:
    """Count this operation's plans and Error rows, and write them onto the row.

    Plans rather than documents, because a plan is the unit the pipeline finishes and
    the only one whose total is known before the work is done. The estimate is derived
    from this operation's own elapsed time rather than from the global sampler, so it
    is right for this run's data even when nothing comparable has ever been ingested.

    The Error counts cover this operation. Historical Error rows are recorded at
    selection time, before the run changes them.

    Returns `[done, total]`. A dataset whose scan has not produced plans yet is
    `[0, 0]`, which the row records as "no estimate can be made" rather than as zero
    progress out of zero work.
    """
    from database.clickhouse import get_collection_client
    from database.operation_ledger import run_plan_counts
    from database.operations import get_operation, update_operation, TERMINAL_STATES, _now

    row = get_operation(params.op_id)
    if row is None or row["state"] in ("finished", "errored", "cancelled"):
        return [int(row["progress_done"]), int(row["progress_total"])] if row else [0, 0]

    done = total = 0
    failed_documents = failed_tasks = 0
    if params.op_id:
        done, total = run_plan_counts(
            params.collectionname, params.op_id, params.collection_dataset
        )
    with get_collection_client(params.collectionname) as client:
        rows = client.query(
            "SELECT uniqExactIf(hash, hash != '') AS failed_documents, count() AS failed_tasks "
            "FROM processing_errors FINAL WHERE collection_dataset = {ds:String} "
            "AND op_id = {op:String}",
            parameters={"ds": params.collection_dataset, "op": params.op_id},
        ).result_rows
        failed_documents = int(rows[0][0])
        failed_tasks = int(rows[0][1])

    eta = 0
    if row and total and done:
        elapsed = max(1.0, time.time() - row["started_at"].timestamp())
        eta = max(0, int(elapsed / done * (total - done)))
    detail = json.loads(row.get("detail") or "{}") if row else {}
    detail.update(failed_documents=failed_documents, failed_tasks=failed_tasks)
    detail.update(params.selector_counts)
    changes = {
        "progress_done": done, "progress_total": total,
        "eta_seconds": eta, "detail": json.dumps(detail, sort_keys=True),
    }
    if params.terminal_state:
        if params.terminal_state not in TERMINAL_STATES:
            raise ValueError(f"Invalid terminal state: {params.terminal_state}")
        changes.update(
            state=params.terminal_state, finished_at=_now(),
            error=params.terminal_error[:4000],
        )
    update_operation(params.op_id, base_row=row, **changes)
    return [done, total]


#: Tables the purge deletes from and then writes to again, because they record the purge
#: itself. They are excluded from the progress count for exactly that reason: an
#: operation that counts its own telemetry as work left to do can never reach its total,
#: and a bar that stops short of the end reads as a purge that did not finish.
SELF_WRITTEN_TABLES = ("processing_task_runs", "processing_task_inflight")


@activity.defn
@with_heartbeat
def count_dataset_rows_activity(params: DatasetProgressParams) -> int:
    """How many rows of the dataset's corpus are still in the two stores.

    What the purge driver counts progress with: the total taken before the purge starts
    is the denominator, and the same count taken again while it runs is what is left, so
    `done` is rows actually gone rather than a stage number. Physical rows, not `FINAL`
    rows, which answers "what is still there" and is far cheaper on a large
    collection.
    """
    from tasks.P_admin.activities import count_dataset_rows

    counts = count_dataset_rows(params.collectionname, params.collection_dataset)
    return (sum(counts["manticore"].values())
            + sum(n for table, n in counts["clickhouse"].items()
                  if table not in SELF_WRITTEN_TABLES))


@activity.defn
@with_heartbeat
def tombstone_dataset_row(params: DatasetRegistryParams) -> str:
    """Soft-delete a dataset's row in the global registry, if it is still live.

    What separates `delete_dataset` from `purge_dataset`: the purge empties the stores,
    and this is what makes the dataset stop existing for every surface that lists one.
    The tombstone is a fresh row rather than a mutation, because `dataset` is a
    `ReplacingMergeTree(date_modified, is_deleted)` and the newest row wins.

    Idempotent, and it says which case it met: a dataset whose row is already
    tombstoned is a finished step, not a failure. The admin UI writes the tombstone
    itself before dispatching, so this is usually the second writer and finds nothing
    to do -- the operation must still be able to do it, because a dispatch from the
    command line has no first writer.
    """
    from database.clickhouse import get_global_client

    with get_global_client() as client:
        rows = client.query(
            "SELECT count() FROM dataset FINAL "
            "WHERE collection_dataset = {cd:String} AND is_deleted = 0",
            parameters={"cd": params.collection_dataset},
        ).result_rows
        # An aggregate over an empty match returns one row holding zero, never no rows.
        if not (rows and int(rows[0][0])):
            return "registry row already tombstoned"
        # The whole row is re-inserted with the tombstone set: a ReplacingMergeTree
        # update is an insert, and a column left out of it would be reset to its
        # default rather than carried over.
        client.command(
            "INSERT INTO dataset SELECT collection_dataset, collectionname, "
            "dataset_name, dataset_display_name, dataset_type, dataset_path, "
            "dataset_access_json, user_id, date_created, now(), 1 "
            "FROM dataset FINAL WHERE collection_dataset = {cd:String} "
            "AND is_deleted = 0",
            parameters={"cd": params.collection_dataset},
        )
    log.info("[P_ops] tombstoned registry row of %s", params.collection_dataset)
    return "registry row tombstoned"


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
