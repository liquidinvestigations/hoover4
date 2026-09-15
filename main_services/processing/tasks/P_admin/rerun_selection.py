"""Select historical Error rows for one operation and reconcile its outcome."""

import logging

from temporalio import activity

from .rerun_params import ReconcileErrorsParams, SelectErrorsParams, SelectionResult
from tasks.heartbeat import with_heartbeat


log = logging.getLogger(__name__)


def classify_pairs(pairs, plan_hashes_by_hash, stage_is_off) -> dict[str, list]:
    """Classify historical Error pairs before the selector changes stored state."""
    classes = {
        "removed_stage_off": [],
        "without_plan": [],
        "selected": [],
    }
    for hash, task_name in pairs:
        pair = (str(hash), str(task_name))
        if stage_is_off(pair[1]):
            classes["removed_stage_off"].append(pair)
        elif not pair[0] or not plan_hashes_by_hash.get(pair[0]):
            classes["without_plan"].append(pair)
        else:
            classes["selected"].append(pair)
    return classes


def _candidate_pairs(params: SelectErrorsParams) -> list[tuple[str, str]]:
    from database.clickhouse import get_collection_client

    filters = [
        "collection_dataset = {ds:String}",
        "op_id != {op:String}",
    ]
    query_params = {"ds": params.collection_dataset, "op": params.op_id}
    if params.task_name:
        filters.append("task_name = {task:String}")
        query_params["task"] = params.task_name
    if params.hash:
        filters.append("hash = {hash:String}")
        query_params["hash"] = params.hash
    with get_collection_client(params.collectionname) as client:
        rows = client.query(
            "SELECT DISTINCT hash, task_name FROM processing_errors WHERE "
            + " AND ".join(filters)
            + " ORDER BY hash, task_name",
            parameters=query_params,
        ).result_rows
    return [(str(hash), str(task_name)) for hash, task_name in rows]


def _historical_error_count(params: SelectErrorsParams) -> int:
    from database.clickhouse import get_collection_client

    with get_collection_client(params.collectionname) as client:
        row = client.query(
            "SELECT count() FROM (SELECT DISTINCT hash, task_name "
            "FROM processing_errors WHERE collection_dataset = {ds:String} "
            "AND op_id != {op:String})",
            parameters={"ds": params.collection_dataset, "op": params.op_id},
        ).result_rows[0]
    return int(row[0])


def _plan_hashes_by_hash(
    collectionname: str, collection_dataset: str, hashes
) -> dict[str, list[str]]:
    from database.clickhouse import get_collection_client
    from tasks.P_admin.failed_file_retry import chunked

    plans: dict[str, list[str]] = {}
    with get_collection_client(collectionname) as client:
        for values in chunked(hashes):
            rows = client.query(
                "SELECT DISTINCT item_hash, plan_hash FROM processing_plan_hits "
                "WHERE collection_dataset = {ds:String} "
                "AND item_hash IN {hashes:Array(String)}",
                parameters={"ds": collection_dataset, "hashes": values},
            ).result_rows
            for hash, plan_hash in rows:
                plans.setdefault(str(hash), []).append(str(plan_hash))
            activity.heartbeat()
    return plans


@activity.defn
@with_heartbeat
def select_historical_errors(params: SelectErrorsParams) -> SelectionResult:
    """Select historical Error rows, clear their stage state and reopen their plans."""
    from database.operation_ledger import (
        delete_error_pairs,
        event_rows,
        insert_error_events,
    )
    from database.operations import merge_detail
    from tasks.P_admin.failed_file_retry import (
        chunked,
        clear_nlp_state,
        clear_regex_state,
        plans_for_hashes,
        reopen_plans,
    )
    from tasks.P_admin.stage_eligibility import stage_is_off

    pairs = _candidate_pairs(params)
    merge_detail(params.op_id, errors_before_run=_historical_error_count(params))

    candidate_hashes = sorted(
        {
            hash
            for hash, task_name in pairs
            if hash and not stage_is_off(task_name, params.collection_dataset)
        }
    )
    plan_hashes_by_hash = _plan_hashes_by_hash(
        params.collectionname, params.collection_dataset, candidate_hashes
    )
    classes = classify_pairs(
        pairs,
        plan_hashes_by_hash,
        lambda task_name: stage_is_off(task_name, params.collection_dataset),
    )

    for event, event_pairs in classes.items():
        insert_error_events(
            params.collectionname,
            event_rows(params.op_id, params.collection_dataset, event_pairs, event),
        )

    for values in chunked(classes["removed_stage_off"]):
        delete_error_pairs(
            params.collectionname, params.collection_dataset, params.op_id, values
        )
        activity.heartbeat()

    selected_hashes = sorted({hash for hash, _ in classes["selected"]})
    for values in chunked(selected_hashes):
        clear_nlp_state(params.collectionname, params.collection_dataset, values)
        clear_regex_state(params.collectionname, params.collection_dataset, values)
        activity.heartbeat()

    plan_hashes = plans_for_hashes(
        params.collectionname, params.collection_dataset, selected_hashes
    )
    for values in chunked(plan_hashes):
        reopen_plans(params.collectionname, params.collection_dataset, values)
        activity.heartbeat()

    merge_detail(
        params.op_id,
        selected_errors=len(classes["selected"]),
        removed_stage_off_errors=len(classes["removed_stage_off"]),
        without_plan_errors=len(classes["without_plan"]),
        recovered_errors=0,
        still_failing_errors=0,
    )
    log.info("[rerun] selected %d Error pairs for %s", len(classes["selected"]), params.op_id)
    return SelectionResult(
        selected_errors=len(classes["selected"]), plan_hashes=plan_hashes
    )


@activity.defn
@with_heartbeat
def reconcile_selected_errors(params: ReconcileErrorsParams) -> str:
    """Replace selected historical Error rows with the result of this operation."""
    from database.clickhouse import get_collection_client
    from database.operation_ledger import (
        delete_error_pairs,
        event_rows,
        insert_error_events,
        pairs_with_event,
    )
    from database.operations import merge_detail
    from tasks.P_admin.failed_file_retry import chunked

    selected = pairs_with_event(
        params.collectionname, params.op_id, params.collection_dataset, "selected"
    )
    with get_collection_client(params.collectionname) as client:
        rows = client.query(
            "SELECT DISTINCT hash, task_name FROM processing_errors "
            "WHERE collection_dataset = {ds:String} AND op_id = {op:String}",
            parameters={"ds": params.collection_dataset, "op": params.op_id},
        ).result_rows
    current = {(str(hash), str(task_name)) for hash, task_name in rows}
    still_failing = [pair for pair in selected if pair in current]
    recovered = [pair for pair in selected if pair not in current]

    for values in chunked(selected):
        delete_error_pairs(
            params.collectionname, params.collection_dataset, params.op_id, values
        )
        activity.heartbeat()
    insert_error_events(
        params.collectionname,
        event_rows(params.op_id, params.collection_dataset, recovered, "recovered"),
    )
    insert_error_events(
        params.collectionname,
        event_rows(
            params.op_id, params.collection_dataset, still_failing, "still_failing"
        ),
    )
    merge_detail(
        params.op_id,
        recovered_errors=len(recovered),
        still_failing_errors=len(still_failing),
    )
    return f"reconciled {len(selected)} Error pairs"
