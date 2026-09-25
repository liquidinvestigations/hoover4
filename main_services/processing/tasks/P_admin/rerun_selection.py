"""Select historical Error rows for one operation and reconcile its outcome."""

import logging
import json

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


#: Error names that the outcome row of another error name proves recovered.
_OUTCOME_NAME_ALIASES = {"detector_error_tika": ("parse_error_tika",)}


def recovery_activity(task_name: str) -> str | None:
    """Map an Error name to the activity that can prove its recovery."""
    direct = {
        "detector_error_tika": "run_tika_and_store",
        "parse_error_tika": "run_tika_and_store",
        "extract_plaintext_chunks": "extract_plaintext_chunks",
        "parse_office_xml_and_store": "parse_office_xml_and_store",
        "parse_table_and_store": "parse_table_and_store",
        "parse_image_metadata_and_store": "parse_image_metadata_and_store",
        "parse_audio_metadata_and_store": "parse_audio_metadata_and_store",
        "P4_ExtractEntities": "extract_entities_for_hashes",
        "P4_ScanRegexEntities": "scan_regex_entities_for_hashes",
        "P5_ChunkEmbed": "chunk_embed_for_hashes",
        "P6_IndexTextPages": "index_text_pages",
        "P6_IndexVectors": "index_vectors",
    }
    if task_name in direct:
        return direct[task_name]
    for prefix, activity_name in (
        ("run_ocr_and_store[", "run_ocr_and_store"),
        ("run_ocr_pdf_and_store[", "run_ocr_pdf_and_store"),
    ):
        if task_name.startswith(prefix) and task_name.endswith("]") and len(task_name) > len(prefix) + 1:
            return activity_name
    return None


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
            "SELECT DISTINCT hash, task_name FROM processing_errors FINAL WHERE "
            + " AND ".join(filters)
            + " ORDER BY hash, task_name",
            parameters=query_params,
        ).result_rows
    return [(str(hash), str(task_name)) for hash, task_name in rows]


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
        selection_snapshot,
    )
    from tasks.P_admin.failed_file_retry import (
        chunked,
        clear_nlp_state,
        clear_regex_state,
        plans_for_hashes,
        reopen_plans,
    )
    from tasks.P_admin.stage_eligibility import stage_is_off

    snapshot = selection_snapshot(params.collectionname, params.op_id,
                                  params.collection_dataset)
    if snapshot is None:
        pairs = _candidate_pairs(params)
        candidate_hashes = sorted({hash for hash, task_name in pairs
            if hash and not stage_is_off(task_name, params.collection_dataset)})
        plan_hashes_by_hash = _plan_hashes_by_hash(
            params.collectionname, params.collection_dataset, candidate_hashes
        )
        classes = classify_pairs(
            pairs, plan_hashes_by_hash,
            lambda task_name: stage_is_off(task_name, params.collection_dataset),
        )
        for event, event_pairs in classes.items():
            for values in chunked(event_pairs):
                insert_error_events(params.collectionname, event_rows(
                    params.op_id, params.collection_dataset, values, event))
        counts = {
            "errors_before_run": len(pairs),
            "selected": len(classes["selected"]),
            "removed_stage_off": len(classes["removed_stage_off"]),
            "without_plan": len(classes["without_plan"]),
            "task_name": params.task_name,
            "hash": params.hash,
        }
        marker = event_rows(params.op_id, params.collection_dataset,
                            [("", "")], "selection_complete")
        marker[0]["error_logs"] = json.dumps(counts, sort_keys=True)
        insert_error_events(params.collectionname, marker)
    else:
        counts, classes = snapshot
        if counts["task_name"] != params.task_name or counts["hash"] != params.hash:
            raise ValueError("Selection filter differs from its complete snapshot")

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

    log.info("[rerun] selected %d Error pairs for %s", len(classes["selected"]), params.op_id)
    return SelectionResult(
        selected_errors=len(classes["selected"]),
        errors_before_run=counts["errors_before_run"],
        removed_stage_off_errors=len(classes["removed_stage_off"]),
        without_plan_errors=len(classes["without_plan"]),
        plan_hashes=plan_hashes,
    )


@activity.defn
@with_heartbeat
def reconcile_selected_errors(params: ReconcileErrorsParams) -> dict:
    """Reconcile selected Error rows with exact evidence from this operation."""
    from database.clickhouse import get_collection_client
    from database.operation_ledger import (
        delete_error_pairs,
        event_rows,
        insert_error_events,
        pairs_with_event,
    )
    from tasks.P_admin.failed_file_retry import chunked

    selected = pairs_with_event(
        params.collectionname, params.op_id, params.collection_dataset, "selected"
    )
    current = set(pairs_with_event(
        params.collectionname, params.op_id, params.collection_dataset, "error"
    ))
    with get_collection_client(params.collectionname) as client:
        rows = client.query(
            "SELECT DISTINCT o.hash, o.error_task_name, o.activity_name "
            "FROM processing_document_outcomes AS o "
            "INNER JOIN processing_task_runs AS r ON "
            "r.op_id = o.op_id AND r.collection_dataset = o.collection_dataset "
            "AND r.task_name = o.activity_name "
            "AND r.workflow_run_id = o.workflow_run_id "
            "AND r.activity_id = o.activity_id AND r.attempt = o.attempt "
            "AND r.outcome = o.outcome "
            "WHERE o.op_id = {op:String} AND o.collection_dataset = {ds:String} "
            "AND o.outcome IN ('ok', 'skipped')",
            parameters={"op": params.op_id, "ds": params.collection_dataset},
        ).result_rows
    evidence = {(str(hash), str(task_name)) for hash, task_name, activity_name in rows
                if recovery_activity(str(task_name)) == str(activity_name)}
    # A successful `run_tika_and_store` writes its outcome under `detector_error_tika`,
    # and it proves the recovery of a `parse_error_tika` row of the same file too.
    evidence |= {(hash, alias) for hash, task_name in list(evidence)
                 for alias in _OUTCOME_NAME_ALIASES.get(task_name, ())}
    unknown = [pair for pair in selected if recovery_activity(pair[1]) is None]
    recovered = [pair for pair in selected if pair in evidence and pair not in current]
    still_failing = [pair for pair in selected
                     if recovery_activity(pair[1]) is not None and pair not in recovered]

    for values in chunked(sorted(set(selected) | current)):
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
    return {
        "recovered_errors": len(recovered),
        "still_failing_errors": len(still_failing),
        "unknown_task_errors": len(unknown),
    }
