"""Activities that write the operations row and drive the store-specific work.

Everything here runs on the operations queues, in the operations container, so a long
backup or a slow ClickHouse poll cannot take an activity slot away from ingestion.

The pipeline modules an activity needs are imported **inside the function**, never at
module scope: this module is loaded by a workflow file that the sandbox re-imports, and
dragging the pipeline's C extensions through that importer fails with a bare
`SystemError` naming nothing in this repository.
"""

import logging
import time

from temporalio import activity

from ..heartbeat import with_heartbeat
from .params import (
    DatasetProgressParams, DatasetRegistryParams, FinishRetryParams,
    OperationStateParams, RetryFailedFilesParams, RetryPlanResult,
)

log = logging.getLogger(__name__)


@activity.defn
@with_heartbeat
def record_operation_state(params: OperationStateParams) -> str:
    """Move an operations row to a new state, or update its counters in place.

    Separate from the workflow's own progress because a workflow cannot touch a
    database: the row is the only thing outside Temporal that knows this run exists,
    and it has to be written by something that can fail and be retried.

    **A row that has already landed terminal is never moved again.** Cancelling an
    operation lands its row from the outside, because a cancelled workflow cannot
    schedule the activity that would land it from the inside; the workflow then unwinds
    and its own failure path arrives here a moment later. Without this guard that late
    write relabels every cancellation as an error, which is the row reporting the
    opposite of what happened.
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

    It also counts the dataset's failed documents onto the row's `detail`, and that is
    not a bonus: an operation whose stages all ran finishes `finished` whether or not
    every document survived, so without a recorded failure count a plan that lost
    documents is indistinguishable from one that did not. The count is of the dataset,
    not of this run. A re-run over an already-damaged dataset should say so rather
    than report a clean sheet because its own attempt added nothing new.

    Returns `[done, total]`. A dataset whose scan has not produced plans yet is
    `[0, 0]`, which the row records as "no estimate can be made" rather than as zero
    progress out of zero work.
    """
    from database.clickhouse import get_collection_client
    from database.operations import get_operation, merge_detail, update_operation

    done = total = 0
    failed_documents = failed_tasks = 0
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
        # Documents rather than error rows: one document that failed six tasks is one
        # failed document, and both numbers are recorded because they answer different
        # questions. A dataset-level failure carries an empty hash and is excluded from
        # the document count rather than counted as a document.
        rows = client.query(
            "SELECT uniqExactIf(hash, hash != ''), count() FROM processing_errors "
            "WHERE collection_dataset = {cd:String}",
            parameters={"cd": params.collection_dataset},
        ).result_rows
        if rows:
            failed_documents = int(rows[0][0])
            failed_tasks = int(rows[0][1])

    eta = 0
    row = get_operation(params.op_id)
    if row and total and done:
        elapsed = max(1.0, time.time() - row["started_at"].timestamp())
        eta = max(0, int(elapsed / done * (total - done)))
    update_operation(params.op_id, progress_done=done, progress_total=total,
                     eta_seconds=eta)
    # Merged, not written over the whole field: `detail` also carries the parameters the
    # operation was dispatched with, and another writer's counters.
    merge_detail(params.op_id, failed_documents=failed_documents,
                 failed_tasks=failed_tasks)
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
def begin_failed_file_retry(params: RetryFailedFilesParams) -> RetryPlanResult:
    """Decide what a retry re-runs, and clear the state that would make it a no-op.

    The stage that failed decides the shape: an NER failure needs its watermarks gone
    before P4 will look at the page again, a parse failure needs the plan's finished
    marker gone before `ExecutePlans` will pick it up, and an index or embed failure
    needs nothing cleared because both stages are idempotent and skip what is done.

    Returns an empty plan rather than raising when there is nothing to retry: a dataset
    with no recorded failures for that task is a finished operation, not a failed one.
    """
    from database.clickhouse import get_collection_client
    from tasks.P_admin.failed_file_retry import (
        RETRY_NLP, RETRY_PLAN, clear_nlp_state, failed_hashes, plans_for_hashes,
        reopen_plans, retry_kind_for_task,
    )

    if not params.task_name:
        raise ValueError(
            "retry_failed_files needs a task_name in its detail: one dispatch retries "
            "one stage of one dataset"
        )
    kind = retry_kind_for_task(params.task_name)
    hashes = failed_hashes(params.collectionname, params.collection_dataset,
                           params.task_name)
    plan_hashes = plans_for_hashes(params.collectionname, params.collection_dataset,
                                   hashes) if hashes else []

    # The server's clock, not this worker's: the "did it fail again" check compares
    # against `processing_errors.timestamp`, written by activities on other hosts.
    with get_collection_client(params.collectionname) as client:
        started_at = str(client.query("SELECT toString(now())").result_rows[0][0])

    if not plan_hashes:
        log.info("[P_ops] %s has nothing to retry for %s",
                 params.collection_dataset, params.task_name)
        return RetryPlanResult(task_name=params.task_name, retry_kind=kind,
                         started_at=started_at)

    if kind == RETRY_NLP:
        clear_nlp_state(params.collectionname, params.collection_dataset, hashes)
    elif kind == RETRY_PLAN:
        reopen_plans(params.collectionname, params.collection_dataset, plan_hashes)

    return RetryPlanResult(task_name=params.task_name, retry_kind=kind,
                     plan_hashes=plan_hashes, hashes=hashes, started_at=started_at)


@activity.defn
@with_heartbeat
def finish_failed_file_retry(params: FinishRetryParams) -> str:
    """Clear only the error rows of the documents the re-run demonstrably fixed.

    A document that failed again keeps exactly one row -- the one this run wrote,
    replacing the one it started from. Appending instead would double the failure count
    the file browser and the admin processing page show, and again on every further
    retry.
    """
    from tasks.P_admin.failed_file_retry import (
        RETRY_NLP, clear_error_rows, drop_superseded_error_rows,
        hashes_without_entities, partition_retry_result, refreshed_hashes,
    )
    from database.operations import merge_detail

    if not params.hashes:
        return "nothing to retry"

    refreshed = refreshed_hashes(params.collectionname, params.collection_dataset,
                                 params.task_name, params.started_at)
    still_broken = (
        hashes_without_entities(params.collectionname, params.collection_dataset,
                                params.hashes)
        if params.retry_kind == RETRY_NLP else []
    )
    outcome = partition_retry_result(params.hashes, refreshed, still_broken)
    if outcome.recovered:
        clear_error_rows(params.collectionname, params.collection_dataset,
                         params.task_name, outcome.recovered)
    if outcome.superseded:
        drop_superseded_error_rows(params.collectionname, params.collection_dataset,
                                   params.task_name, outcome.superseded,
                                   params.started_at)
    still_failing = len(outcome.superseded) + len(outcome.unchanged)
    # On the row rather than only in the return value: an operation whose stages all ran
    # finishes `finished` whether or not the documents recovered, so the counts are the
    # only thing that tells a reader which of the two happened.
    merge_detail(params.op_id, retried_documents=len(params.hashes),
                 recovered_documents=len(outcome.recovered),
                 still_failing_documents=still_failing)
    return (f"retried {len(params.hashes)} document(s): {len(outcome.recovered)} "
            f"recovered, {still_failing} still failing")


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
