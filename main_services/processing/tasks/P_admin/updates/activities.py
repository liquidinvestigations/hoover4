"""Activities of the processing updates: calculation, snapshot, settlement and dispatch.

`check_processing_updates` is the coordinator pass. It reads the input revisions, the
settings and the stored state with a few global queries. A scope whose fingerprints did
not change costs no collection query. A scope with a changed fingerprint, or one that a
person asked to calculate, runs every selector of the scope and writes new check rows. A
step with no automatic work records its fingerprint as applied, so it starts no
operation. The pass returns the scopes with automatic work, collections first.

`snapshot_processing_update` is the first activity of an update operation. It
recalculates the requested steps and compares them with the preview that the person saw.
A changed fingerprint refuses the request with the refreshed counts and starts no work.
"""

import json
import logging
import os
import time
from typing import Dict, List, Tuple

from temporalio import activity
from temporalio.exceptions import ApplicationError

from tasks.heartbeat import HeartbeatClock, with_heartbeat
from tasks.P_admin.updates.params import (
    CheckUpdatesParams,
    CheckUpdatesResult,
    RunUpdateParams,
    StepOutcomeResult,
    StepParams,
    StepSnapshotParams,
    SubmitUpdateParams,
    UpdateCandidateParams,
    UpdateProgressParams,
    UpdateSnapshotResult,
    TablePlanParams,
    TablePlansParams,
    VirusPlansParams,
    VectorPlansParams,
)
from tasks.P_admin.updates.registry import (
    AUTOMATIC_USER,
    SCOPE_COLLECTION,
    SCOPE_DATASET,
    STEPS_BY_ID,
    Desired,
    desired,
    steps_of,
)
from tasks.P_admin.updates import selectors

log = logging.getLogger(__name__)

#: The error type of a manual request whose preview no longer matches the stored state.
PREVIEW_STALE = "ProcessingUpdatePreviewStale"
#: The error type of a dataset request whose collection prerequisite is not up to date.
PREREQUISITE_PENDING = "ProcessingUpdatePrerequisitePending"
#: The error type of a request that names no step or an unknown step.
INVALID_REQUEST = "ProcessingUpdateInvalidRequest"


def automatic_enabled() -> bool:
    """`[processing_updates] automatic` of `hoover4.ini`, rendered into the worker."""
    return (os.getenv("HOOVER4_PROCESSING_UPDATES_AUTOMATIC") or "true").strip().lower() != "false"


# ---- scopes and their desired state ---------------------------------------------------------


def _scopes() -> Tuple[List[str], List[Tuple[str, str]]]:
    """The collections with a live dataset, and each live dataset with its collection."""
    from database.clickhouse import get_global_client

    with get_global_client() as client:
        rows = client.query(
            "SELECT d.collection_dataset, d.collectionname FROM dataset AS d FINAL "
            "WHERE d.is_deleted = 0 AND d.collectionname IN "
            "(SELECT collectionname FROM collections FINAL WHERE is_deleted = 0) "
            "ORDER BY d.collectionname, d.collection_dataset").result_rows
    datasets = [(str(cd), str(c)) for cd, c in rows]
    return sorted({c for _, c in datasets}), datasets


def _context(scope_kind: str, scope_id: str, collectionname: str, revisions: dict,
             applied: Dict[Tuple[str, str], dict]) -> selectors.ScopeContext:
    if scope_kind == SCOPE_DATASET:
        revision = "|".join([revisions["datasets"].get(scope_id, ""),
                             revisions["collections"].get(collectionname, "")])
    else:
        revision = revisions["collections"].get(collectionname, "")
    return selectors.ScopeContext(
        scope_kind, scope_id, collectionname, revision,
        {step_id: row for (sid, step_id), row in applied.items() if sid == scope_id})


def _desired(ctx: selectors.ScopeContext) -> Tuple[Dict[str, Desired], Dict[str, dict]]:
    wanted, targets = {}, {}
    for step in steps_of(ctx.scope_kind):
        key, target = selectors.target_key(step, ctx)
        wanted[step.step_id] = desired(step, key, ctx.input_revision)
        targets[step.step_id] = target
    return wanted, targets


def _calculate(ctx: selectors.ScopeContext, wanted: Dict[str, Desired],
               targets: Dict[str, dict]) -> Dict[str, dict]:
    """Run every selector of a scope and write its check rows. Returns them by step id."""
    from database.clickhouse import get_collection_client
    from database.processing_updates import write_checks

    started = time.monotonic()
    rows, selections = {}, []
    with get_collection_client(ctx.collectionname) as client:
        for step in steps_of(ctx.scope_kind):
            step_started = time.monotonic()
            selection = selectors.select(step, ctx, client, targets.get(step.step_id) or None)
            selections.append(selection)
            want = wanted[step.step_id]
            rows[step.step_id] = {
                "scope_kind": ctx.scope_kind, "scope_id": ctx.scope_id,
                "collectionname": ctx.collectionname, "step_id": step.step_id,
                "desired_fingerprint": want.fingerprint,
                "pending_files": selection.count, "pending_bytes": selection.bytes,
                "automatic_files": min(selection.automatic, selection.count),
                "executions": 1 if selection.count else 0,
                "detail": json.dumps({
                    **want.detail(), **selection.detail, "unit": step.unit,
                    "order": [s.step_id for s in steps_of(ctx.scope_kind)].index(step.step_id),
                    "automatic_step": step.automatic,
                    "title": step.title, "runs": step.runs,
                    "explanation": step.explanation.format(files=f"{selection.count:,}")},
                    sort_keys=True, default=str),
                "check_ms": int((time.monotonic() - step_started) * 1000),
            }
        files, size = (selectors.unique_files(client, selections, ctx.scope_id)
                       if ctx.scope_kind == SCOPE_DATASET else (0, 0))
    rows[""] = {
        "scope_kind": ctx.scope_kind, "scope_id": ctx.scope_id,
        "collectionname": ctx.collectionname, "step_id": "",
        "desired_fingerprint": "", "pending_files": files, "pending_bytes": size,
        "executions": sum(row["executions"] for row in rows.values()),
        "detail": json.dumps({"input_revision": ctx.input_revision}),
        "check_ms": int((time.monotonic() - started) * 1000),
    }
    write_checks(list(rows.values()))
    return rows


def _record_zero_work(ctx: selectors.ScopeContext, rows: Dict[str, dict],
                      applied: Dict[Tuple[str, str], dict]) -> None:
    """Record a fingerprint as applied when its step has no automatic work."""
    from database.processing_updates import write_applied

    for step_id, row in rows.items():
        if not step_id or row["automatic_files"] > 0:
            continue
        current = applied.get((ctx.scope_id, step_id))
        if current and current["applied_fingerprint"] == row["desired_fingerprint"]:
            continue
        write_applied(ctx.scope_kind, ctx.scope_id, ctx.collectionname, step_id,
                      row["desired_fingerprint"], "", json.loads(row["detail"]))
        applied[(ctx.scope_id, step_id)] = {"applied_fingerprint": row["desired_fingerprint"]}


def _automatic_steps(ctx: selectors.ScopeContext, wanted: Dict[str, Desired],
                     checks: Dict[Tuple[str, str], dict], applied: Dict[Tuple[str, str], dict],
                     attempts: dict) -> List[str]:
    """The steps of a scope that the coordinator may start now, in run order."""
    chosen = []
    for step in steps_of(ctx.scope_kind):
        want = wanted[step.step_id]
        check = checks.get((ctx.scope_id, step.step_id))
        row = applied.get((ctx.scope_id, step.step_id))
        if not step.automatic or not check or check["desired_fingerprint"] != want.fingerprint:
            continue
        if int(check["automatic_files"]) <= 0:
            continue
        if row and row["applied_fingerprint"] == want.fingerprint:
            continue
        # A failed or cancelled newest attempt at this fingerprint ends the automatic run
        # of the step until the fingerprint changes. The button stays. A succeeded attempt
        # whose fingerprint is no longer applied left output that a later change replaced,
        # for example after a setting went from A to B and back to A, so the step runs.
        earlier = attempts.get((ctx.scope_id, step.step_id, want.fingerprint)) or []
        if earlier and earlier[0].get("effective_state") in ("failed", "cancelled"):
            continue
        chosen.append(step.step_id)
    return chosen


@activity.defn
@with_heartbeat
def check_processing_updates(params: CheckUpdatesParams) -> CheckUpdatesResult:
    """One coordinator pass: compare, calculate what changed, and return candidates."""
    from database.operations import live_operations
    from database.processing_updates import (
        attempts_at, input_revisions, stored_applied, stored_checks,
    )

    started = time.monotonic()
    heartbeat = HeartbeatClock()
    forced = set(params.forced)
    collections, datasets = _scopes()
    revisions = input_revisions()
    checks = stored_checks()
    applied = stored_applied()
    attempts = attempts_at()
    live = live_operations()
    held_datasets = {row["collection_dataset"] for row in live if row["target_kind"] == "dataset"}
    held_collections = {row["collectionname"] for row in live if row["target_kind"] == "collection"}

    scopes = [(SCOPE_COLLECTION, c, c) for c in collections] + \
             [(SCOPE_DATASET, cd, c) for cd, c in datasets]
    collection_ready: Dict[str, bool] = {}
    candidates: List[UpdateCandidateParams] = []
    calculated = 0
    for scope_kind, scope_id, collectionname in scopes:
        heartbeat.beat(f"checking {scope_id}")
        try:
            ctx = _context(scope_kind, scope_id, collectionname, revisions, applied)
            wanted, targets = _desired(ctx)
            changed = ("*" in forced or scope_id in forced or any(
                (checks.get((scope_id, step_id)) or {}).get("desired_fingerprint") != want.fingerprint
                for step_id, want in wanted.items()))
            if changed:
                rows = _calculate(ctx, wanted, targets)
                calculated += 1
                for step_id, row in rows.items():
                    checks[(scope_id, step_id)] = row
                _record_zero_work(ctx, rows, applied)
        except Exception:
            # One scope that cannot be read must not stop the others.
            log.warning("[updates] could not check %s", scope_id, exc_info=True)
            if scope_kind == SCOPE_COLLECTION:
                collection_ready[scope_id] = False
            continue
        steps = _automatic_steps(ctx, wanted, checks, applied, attempts)
        if scope_kind == SCOPE_COLLECTION:
            # A collection is ready for its dataset writers when its steps are applied.
            collection_ready[scope_id] = all(
                (applied.get((scope_id, step_id)) or {}).get("applied_fingerprint") == want.fingerprint
                for step_id, want in wanted.items())
        if scope_kind == SCOPE_DATASET:
            held = scope_id in held_datasets or collectionname in held_collections
        else:
            held = any(row["collectionname"] == collectionname for row in live)
        if scope_kind == SCOPE_DATASET and not collection_ready.get(collectionname, False):
            # A writer waits for its collection prerequisite, which runs as its own
            # operation first.
            steps = [s for s in steps if not STEPS_BY_ID[s].prerequisites]
        if steps and not held:
            candidates.append(UpdateCandidateParams(
                scope_kind, scope_id, collectionname,
                scope_id if scope_kind == SCOPE_DATASET else "",
                steps, {s: wanted[s].fingerprint for s in steps}))
    return CheckUpdatesResult(candidates, calculated, int((time.monotonic() - started) * 1000),
                              automatic_enabled())


@activity.defn
@with_heartbeat
def submit_automatic_update(params: SubmitUpdateParams) -> str:
    """Write the row of an automatic update operation, or name the one that runs.

    Returns `started:<op_id>` for a new row, `running:<op_id>` when an automatic update
    operation is live, and `held:` when another operation holds the target.
    """
    from database.operations import OperationLocked, create_operation
    from database.processing_updates import live_update_operations

    for row in live_update_operations():
        if row["user_id"] == AUTOMATIC_USER:
            return f"running:{row['op_id']}"
    candidate = params.candidate
    kind = "update_dataset" if candidate.scope_kind == SCOPE_DATASET else "update_collection"
    try:
        create_operation(kind, candidate.collectionname, candidate.collection_dataset,
                         detail={"steps": candidate.steps, "fingerprints": candidate.fingerprints,
                                 "automatic": True},
                         user_id=AUTOMATIC_USER, op_id=params.op_id)
    except OperationLocked:
        return "held:"
    return f"started:{params.op_id}"


@activity.defn
@with_heartbeat
def update_operation_state(op_id: str) -> str:
    """The state of an operations row, or `missing`."""
    from database.operations import get_operation

    row = get_operation(op_id)
    return row["state"] if row else "missing"


# ---- one update operation -------------------------------------------------------------------


def _scope_of(params) -> Tuple[str, str]:
    return ((params.collection_dataset, SCOPE_DATASET) if params.scope_kind == SCOPE_DATASET
            else (params.collectionname, SCOPE_COLLECTION))


@activity.defn
@with_heartbeat
def snapshot_processing_update(params: RunUpdateParams) -> UpdateSnapshotResult:
    """Validate the request, compare it with the current state, and snapshot its steps."""
    from database.processing_updates import input_revisions, stored_applied

    scope_id, scope_kind = _scope_of(params)
    known = [step.step_id for step in steps_of(scope_kind)]
    if not params.steps:
        raise ApplicationError("The request selects no update step, so nothing runs.",
                               type=INVALID_REQUEST, non_retryable=True)
    unknown = [s for s in params.steps if s not in known]
    if unknown:
        raise ApplicationError(f"Unknown update steps for a {scope_kind}: {unknown}",
                               type=INVALID_REQUEST, non_retryable=True)
    applied = stored_applied([scope_id, params.collectionname])
    revisions = input_revisions()
    ctx = _context(scope_kind, scope_id, params.collectionname, revisions, applied)
    wanted, targets = _desired(ctx)

    stale = [s for s in params.steps
             if params.fingerprints.get(s) and params.fingerprints[s] != wanted[s].fingerprint]
    rows = _calculate(ctx, wanted, targets)
    if stale:
        counts = ", ".join(f"{STEPS_BY_ID[s].title}: {rows[s]['pending_files']:,}" for s in stale)
        raise ApplicationError(
            f"The preview changed before the update started ({counts}). Review the new counts "
            "and start the update again. Nothing ran.", type=PREVIEW_STALE, non_retryable=True)

    if scope_kind == SCOPE_DATASET:
        collection_ctx = _context(SCOPE_COLLECTION, params.collectionname, params.collectionname,
                                  revisions, applied)
        collection_wanted, _ = _desired(collection_ctx)
        needed = sorted({p for s in params.steps for p in STEPS_BY_ID[s].prerequisites})
        waiting = [p for p in needed
                   if (applied.get((params.collectionname, p)) or {}).get("applied_fingerprint")
                   != collection_wanted[p].fingerprint]
        if waiting:
            names = ", ".join(STEPS_BY_ID[p].title for p in waiting)
            raise ApplicationError(
                f"The collection {params.collectionname} needs an update first: {names}. Start "
                "it on the collection page, then start this update again. Nothing ran.",
                type=PREREQUISITE_PENDING, non_retryable=True)

    snapshot = []
    for step in steps_of(scope_kind):
        if step.step_id not in params.steps:
            continue
        row = rows[step.step_id]
        snapshot.append(StepSnapshotParams(step.step_id, wanted[step.step_id].fingerprint,
                                           row["detail"], int(row["pending_files"])))
    return UpdateSnapshotResult(snapshot)


def _detail(step: StepSnapshotParams) -> dict:
    try:
        return json.loads(step.detail or "{}")
    except ValueError:
        return {}


def failed_tasks_of(params: StepParams) -> List[str]:
    """The error names that a failed files step retries."""
    detail = _detail(params.step)
    return list(detail.get("automatic_tasks" if params.automatic else "manual_tasks") or [])


@activity.defn
@with_heartbeat
def begin_update_step(params: StepParams) -> str:
    """Record the running attempt. A failed files step claims its retry entitlement here."""
    from database.processing_updates import claim_retries, write_attempt
    from tasks.stage_versions import STAGE_VERSIONS, canonical_stage

    scope_id, scope_kind = _scope_of(params)
    write_attempt(scope_kind, scope_id, params.collectionname, params.step.step_id, params.op_id,
                  params.step.fingerprint, params.automatic, "running", _detail(params.step))
    if params.step.step_id == "failed_files":
        stages = {canonical_stage(task) for task in failed_tasks_of(params)}
        claim_retries(params.collection_dataset, params.collectionname, params.op_id,
                      {stage: STAGE_VERSIONS[stage] for stage in stages if stage})
    return "running"


def _settle(params: StepParams) -> Tuple[bool, str]:
    """The settlement rule of each step, see `selectors.py`."""
    from database.clickhouse import get_collection_client
    from database.processing_updates import stored_applied

    step_id = params.step.step_id
    if step_id == "search_schema":
        differences = selectors.schema_differences(params.collectionname)
        return not differences, f"{len(differences)} search tables still differ from the schema."
    scope_id, scope_kind = _scope_of(params)
    ctx = selectors.ScopeContext(scope_kind, scope_id, params.collectionname, "",
                                 {k[1]: v for k, v in stored_applied([scope_id]).items()})
    with get_collection_client(params.collectionname) as client:
        if step_id == "unfinished":
            selection = selectors.select_unfinished(client, ctx)
            return (selection.count == 0,
                    f"{selection.detail.get('plans', 0)} plans and {selection.count} files are still unfinished.")
        if step_id == "ocr":
            if "languages" not in _detail(params.step):
                selection = selectors.select_ocr(client, ctx)
                return selection.count == 0, f"{selection.count} automatic OCR publications remain incomplete."
            from tasks.dataset_config import effective_ocr_settings

            current = {e: s.value for e, s in effective_ocr_settings(scope_id, params.collectionname).items()}
            keep = [_detail(params.step).get("languages") or current, current]
            variants, pairs = selectors.obsolete_ocr_outputs(client, scope_id, keep)
            return (not variants and not pairs,
                    f"OCR text of removed languages remains: {variants + [' '.join(p) for p in pairs]}")
        if step_id == "ocr_detection":
            selection = selectors.select_ocr_detection(client, ctx)
            return selection.count == 0, f"{selection.count} files have no OCR detection result."
        if step_id == "virus_scan":
            selection = selectors.select_virus_scan(client, ctx)
            stale = infected_without_attribute(params.collectionname, scope_id)
            return (selection.count == 0 and not stale,
                    f"{selection.count} files have no antivirus verdict, and {len(stale)} infected files "
                    "have search rows without their search attribute.")
        if step_id == "archive_members":
            selection = selectors.select_archive_members(client, ctx)
            return selection.count == 0, f"{selection.count} archives still have no complete member receipt."
        if step_id == "image_previews":
            selection = selectors.select_image_previews(client, ctx)
            return selection.count == 0, f"{selection.count} files still have no image preview."
        if step_id == "entities":
            selection = selectors.select(selectors.STEPS_BY_ID["entities"], ctx, client)
            if selection.count:
                return False, f"{selection.count} files need complete named entity output."
            from .entities import EntityUpdateParams, verify_index
            after = ""
            while True:
                rows = client.query("SELECT DISTINCT file_hash FROM processing_output_receipts "
                    "WHERE collection_dataset={cd:String} AND output_kind='entities' AND op_id={op:String} "
                    "AND file_hash>{after:String} ORDER BY file_hash LIMIT 100",
                    parameters={"cd":scope_id,"op":params.op_id,"after":after}).result_rows
                if not rows:
                    break
                hashes = [row[0] for row in rows]
                verify_index(EntityUpdateParams(params.collectionname,scope_id,params.op_id,hashes))
                after = hashes[-1]
            return True, "Named entities and searchable output are current."
        if step_id == "tables":
            selection = selectors.select_tables(client, ctx)
            return selection.count == 0, f"{selection.count} files still have an earlier table reading."
        if step_id == "pdf_text":
            from tasks.P_admin.updates.pdf_text_layer import layer_target, unbuilt_tombstones

            target = layer_target(scope_id, params.collectionname)
            selection = selectors.select_pdf_text(client, ctx, target)
            unbuilt = unbuilt_tombstones(client, scope_id, target)
            return (selection.count == 0 and unbuilt == 0,
                    f"{selection.count} files still have an earlier PDF text layer, and {unbuilt} "
                    "removed PDF parts have no new part.")
        if step_id == "search_terms":
            missing = selectors.missing_search_terms(client, ctx)
            return missing == 0, f"{missing} filter terms remain absent or incorrect."
        if step_id == "text_rows":
            selection = selectors.select_text_rows(client, ctx)
            return selection.count == 0, f"{selection.count} files still have text rows from an earlier split."
        if step_id == "page_text":
            selection = selectors.select_page_text(client, ctx)
            return selection.count == 0, f"{selection.count} files still have incomplete indexed text."
        if step_id == "folder_counts":
            selection = selectors.select_folder_counts(
                client, selectors.ScopeContext(scope_kind, scope_id, params.collectionname))
            return selection.count == 0, f"{selection.count} folders still have no counts."
    # Failed files and vectors settle by their work: the reconciliation recorded the
    # outcome of every selected pair, and every selected plan ran embedding and indexing.
    return True, ""


@activity.defn
@with_heartbeat
def settle_update_step(params: StepParams) -> StepOutcomeResult:
    """Verify the output of a step. Record the applied fingerprint only when it settles.

    The applied fingerprint is the snapshot's, so a desired fingerprint that changed
    while the step ran stays waiting.
    """
    from database.processing_updates import write_applied, write_attempt

    scope_id, scope_kind = _scope_of(params)
    settled, message = _settle(params)
    detail = {**_detail(params.step), "summary": params.state}
    if settled:
        write_applied(scope_kind, scope_id, params.collectionname, params.step.step_id,
                      params.step.fingerprint, params.op_id, detail)
        write_attempt(scope_kind, scope_id, params.collectionname, params.step.step_id,
                      params.op_id, params.step.fingerprint, params.automatic, "succeeded", detail)
        return StepOutcomeResult(True, params.state)
    write_attempt(scope_kind, scope_id, params.collectionname, params.step.step_id, params.op_id,
                  params.step.fingerprint, params.automatic, "failed", detail, message)
    return StepOutcomeResult(False, message)


@activity.defn
@with_heartbeat
def finish_update_step(params: StepParams) -> str:
    """Record a step that ended without settlement: failed or skipped."""
    from database.processing_updates import write_attempt

    scope_id, scope_kind = _scope_of(params)
    write_attempt(scope_kind, scope_id, params.collectionname, params.step.step_id, params.op_id,
                  params.step.fingerprint, params.automatic, params.state or "failed",
                  _detail(params.step), params.error)
    return params.state or "failed"


@activity.defn
@with_heartbeat
def report_update_progress(params: UpdateProgressParams) -> str:
    """Write the state of one step and the step counters onto the operations row."""
    from database.operations import get_operation, update_operation

    row = get_operation(params.op_id)
    if row is None:
        return "missing"
    try:
        detail = json.loads(row.get("detail") or "{}")
    except ValueError:
        detail = {}
    steps = detail.setdefault("step_progress", {})
    steps[params.step_id] = {"state": params.state, "message": params.message[:2000]}
    update_operation(params.op_id, detail=json.dumps(detail, sort_keys=True),
                     progress_done=params.done, progress_total=params.total)
    return params.state


@activity.defn
@with_heartbeat
def refresh_update_checks(params: RunUpdateParams) -> int:
    """Calculate the scope again after an operation, so the page shows what remains."""
    from database.processing_updates import input_revisions, stored_applied

    scope_id, scope_kind = _scope_of(params)
    applied = stored_applied([scope_id])
    ctx = _context(scope_kind, scope_id, params.collectionname, input_revisions(), applied)
    wanted, targets = _desired(ctx)
    rows = _calculate(ctx, wanted, targets)
    return sum(int(row["pending_files"]) for step_id, row in rows.items() if step_id)


# ---- step work ------------------------------------------------------------------------------


@activity.defn
@with_heartbeat
def obsolete_ocr_variants(params: StepParams) -> dict:
    """The stored OCR variants outside the snapshot languages and the current languages.

    Both values are kept, so a settings change during the run never deletes text that
    the newer settings use.
    """
    from database.clickhouse import get_collection_client
    from tasks.dataset_config import effective_ocr_settings

    current = {e: s.value for e, s in effective_ocr_settings(
        params.collection_dataset, params.collectionname).items()}
    keep = [_detail(params.step).get("languages") or current, current]
    with get_collection_client(params.collectionname) as client:
        variants, pairs = selectors.obsolete_ocr_outputs(client, params.collection_dataset, keep)
    return {"variants": variants, "pairs": [list(p) for p in pairs]}


@activity.defn
@with_heartbeat
def apply_search_schema(params: StepParams) -> dict:
    """Add the missing columns to each shard pages table. Report a needed rebuild.

    A column with another type cannot be changed in place, so the workflow then rebuilds
    the collection index. A new scalar attribute reads 0 on existing rows, so a writer
    that fills it must refresh the documents it changes.
    """
    from database.manticore import client_for_table

    differences = selectors.schema_differences(params.collectionname)
    altered = 0
    for table, difference in sorted(differences.items()):
        if difference["retyped"]:
            continue
        for name, kind in difference["missing"]:
            with client_for_table(table) as cnx:
                cursor = cnx.cursor()
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
                cnx.commit()
            altered += 1
    rebuild = any(d["retyped"] for d in differences.values())
    return {"altered_columns": altered, "rebuild": rebuild}


@activity.defn
@with_heartbeat
def list_update_vector_plans(params: VectorPlansParams) -> List[str]:
    """At most 100 finished plans after `after` that hold a file without a current vector."""
    from database.clickhouse import get_collection_client

    with get_collection_client(params.collectionname) as client:
        rows = client.query(
            "SELECT DISTINCT plan_hash FROM processing_plan_hits WHERE collection_dataset = {cd:String} "
            "AND plan_hash > {after:String} "
            "AND plan_hash IN (SELECT plan_hash FROM processing_plan_finished WHERE collection_dataset = {cd:String}) "
            "AND item_hash IN (SELECT DISTINCT file_hash FROM text_content WHERE collection_dataset = {cd:String} "
            "AND file_hash NOT IN (SELECT file_hash FROM text_chunk_vectors WHERE collection_dataset = {cd:String} "
            "AND embedding_model = {model:String})) ORDER BY plan_hash LIMIT 100",
            parameters={"cd": params.collection_dataset, "after": params.after,
                        "model": params.model}).result_rows
    return [row[0] for row in rows]


@activity.defn
@with_heartbeat
def list_update_text_row_plans(params: TablePlansParams) -> List[str]:
    """At most 100 plans after `after` that hold a file that the `text_rows` step selects."""
    from database.clickhouse import get_collection_client

    hash_sql, extra = selectors.text_rows_hash_sql()
    with get_collection_client(params.collectionname) as client:
        rows = client.query(
            "SELECT DISTINCT plan_hash FROM processing_plan_hits WHERE collection_dataset = {cd:String} "
            f"AND plan_hash > {{after:String}} AND item_hash IN ({hash_sql}) ORDER BY plan_hash LIMIT 100",
            parameters={"cd": params.collection_dataset, "after": params.after, **extra}).result_rows
    return [row[0] for row in rows]


@activity.defn
@with_heartbeat
def list_update_table_plans(params: TablePlansParams) -> List[str]:
    """At most 100 plans after `after` that hold a file that the `tables` step selects."""
    from database.clickhouse import get_collection_client

    hash_sql, extra = selectors.tables_hash_sql()
    with get_collection_client(params.collectionname) as client:
        rows = client.query(
            "SELECT DISTINCT plan_hash FROM processing_plan_hits WHERE collection_dataset = {cd:String} "
            f"AND plan_hash > {{after:String}} AND item_hash IN ({hash_sql}) ORDER BY plan_hash LIMIT 100",
            parameters={"cd": params.collection_dataset, "after": params.after, **extra}).result_rows
    return [row[0] for row in rows]


@activity.defn
@with_heartbeat
def reparse_update_tables(params: TablePlanParams) -> List[str]:
    """Read the selected files of one plan again with the current table reader.

    The reader is chosen from the stored detection and a structural check of the bytes,
    so detection does not run again. Returns the hashes that were read.
    """
    import shutil

    from database.clickhouse import get_collection_client
    from tasks.P2_execute_plan.activities import write_blob_files
    from tasks.P3_parse_files.batch_runner import try_budget_seconds
    from tasks.P3_parse_files.file_names import bounded_file_names
    from tasks.P3_parse_files.parse_table import ParseTableParams, parse_table_and_store
    from tasks.P3_parse_files.table_formats import MARKUP_TABLE_READERS, READER_VERSION
    from tasks.P_admin.updates.table_receipts import TableReceiptParams, prepare_table_text

    hash_sql, extra = selectors.tables_hash_sql()
    with get_collection_client(params.collectionname) as client:
        rows = client.query(
            "SELECT h.item_hash, b.size, b.s3_path, n.names, t.mimes, t.encodings, t.sniff, t.file_mime "
            "FROM (SELECT DISTINCT item_hash FROM processing_plan_hits WHERE collection_dataset = {cd:String} "
            f"AND plan_hash = {{plan:String}} AND item_hash IN ({hash_sql})) AS h "
            "INNER JOIN (SELECT blob_hash, any(blob_size_bytes) AS size, any(s3_path) AS s3_path FROM blobs "
            "WHERE collection_dataset = {cd:String} GROUP BY blob_hash) AS b ON b.blob_hash = h.item_hash "
            "LEFT JOIN (SELECT hash, groupUniqArray(splitByChar('/', path)[-1]) AS names FROM vfs_files FINAL "
            "WHERE collection_dataset = {cd:String} AND is_deleted = 0 GROUP BY hash) AS n ON n.hash = h.item_hash "
            "LEFT JOIN (SELECT hash, groupUniqArrayArray(mime_type) AS mimes, "
            "groupUniqArrayArray(mime_encoding) AS encodings, "
            "groupUniqArrayArrayIf(mime_type, extracted_by = 'content_sniff') AS sniff, "
            "anyIf(mime_type[1], extracted_by = 'file') AS file_mime "
            "FROM file_types WHERE collection_dataset = {cd:String} GROUP BY hash) AS t ON t.hash = h.item_hash",
            parameters={"cd": params.collection_dataset, "plan": params.plan_hash, **extra}).result_rows
    if not rows:
        return []
    out_dir = os.path.join("/tmp/hoover4", params.collection_dataset, f"update-tables-{params.plan_hash}")
    os.makedirs(out_dir, exist_ok=True)
    clock = HeartbeatClock()
    read: List[str] = []
    try:
        write_blob_files(params.collectionname, params.collection_dataset, [
            {"item_hash": row[0], "file_size_bytes": int(row[1] or 0), "s3_url": row[2] or "",
             "path": os.path.join(out_dir, row[0])} for row in rows],
            context=f"{params.collection_dataset}/{params.plan_hash}")
        for file_hash, size, _, names, mimes, encodings, sniff, file_mime in rows:
            clock.beat(f"table {file_hash}")
            authoritative = next((m for m in (sniff or []) if m in MARKUP_TABLE_READERS), "")
            with get_collection_client(params.collectionname) as client:
                published = client.query(
                    "SELECT status, generation FROM table_documents FINAL WHERE collection_dataset = {cd:String} "
                    "AND hash = {hash:String} AND reader_version = {version:UInt16} "
                    "AND status IN ('ok', 'empty') LIMIT 1",
                    parameters={"cd": params.collection_dataset, "hash": file_hash,
                                "version": READER_VERSION}).result_rows
            from tasks.P3_parse_files.table_generations import complete_column_coverage
            with get_collection_client(params.collectionname) as client:
                complete = bool(published) and (published[0][0] == "empty" or complete_column_coverage(
                    client, params.collection_dataset, file_hash, int(published[0][1])))
                if complete:
                    from tasks.P3_parse_files.table_text import complete_table_text
                    complete = complete_table_text(client, params.collection_dataset, file_hash, int(published[0][1]))
            if complete:
                read.append(file_hash)
                continue
            outcome = parse_table_and_store(ParseTableParams(
                collectionname=params.collectionname, collection_dataset=params.collection_dataset,
                file_hash=file_hash, file_path=os.path.join(out_dir, file_hash),
                timeout_seconds=try_budget_seconds("parse_table_batch", int(size or 0)),
                mime_types=list(mimes or []), mime_encodings=list(encodings or []),
                op_id=params.op_id, file_names=bounded_file_names(list(names or [])),
                sniff_mime_type=authoritative, file_mime_type=file_mime or ""))
            value = getattr(outcome, "value", outcome)
            if isinstance(value, dict) and value.get("status") in ("failed", "unreadable"):
                # An unreadable file has no table output. The other files of the plan continue.
                log.warning("[updates] Table parsing failed for %s: %s", file_hash, value.get("error", ""))
                continue
            read.append(file_hash)
        with get_collection_client(params.collectionname) as client:
            prepare_table_text(client, TableReceiptParams(params.collectionname, params.collection_dataset,
                                                         params.op_id, read))
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
    return read


@activity.defn
@with_heartbeat
def prepare_table_update(params: TablePlanParams) -> Dict[str, int]:
    """Read tables and return the exact published generation for each selected file."""
    from database.clickhouse import get_collection_client
    hashes = reparse_update_tables(params)
    if not hashes:
        return {}
    with get_collection_client(params.collectionname) as client:
        rows = client.query(
            "SELECT hash, generation FROM table_documents FINAL WHERE collection_dataset = {cd:String} "
            "AND hash IN {hashes:Array(String)} AND status IN ('ok', 'empty')",
            parameters={"cd": params.collection_dataset, "hashes": hashes}).result_rows
    generations = {file_hash: int(generation) for file_hash, generation in rows}
    if set(generations) != set(hashes):
        raise RuntimeError("A table update has no published generation")
    return generations


@activity.defn
@with_heartbeat
def list_update_virus_plans(params: VirusPlansParams) -> List[str]:
    """At most 100 plans after `after` that hold a file that the `virus_scan` step selects."""
    from database.clickhouse import get_collection_client

    hash_sql, extra = selectors.virus_hash_sql()
    with get_collection_client(params.collectionname) as client:
        rows = client.query(
            "SELECT DISTINCT plan_hash FROM processing_plan_hits WHERE collection_dataset = {cd:String} "
            f"AND plan_hash > {{after:String}} AND item_hash IN ({hash_sql}) ORDER BY plan_hash LIMIT 100",
            parameters={"cd": params.collection_dataset, "after": params.after, **extra}).result_rows
    return [row[0] for row in rows]


@activity.defn
@with_heartbeat
def scan_update_files(params: TablePlanParams) -> int:
    """Scan the selected files of one plan, one at a time, and store their attempts."""
    import shutil

    from database.clickhouse import get_collection_client
    from tasks.P2_execute_plan.activities import write_blob_files
    from tasks.P3_parse_files.scan_virus import scan_file, store_attempts

    hash_sql, extra = selectors.virus_hash_sql()
    with get_collection_client(params.collectionname) as client:
        rows = client.query(
            "SELECT h.item_hash, b.size, b.s3_path FROM (SELECT DISTINCT item_hash FROM processing_plan_hits "
            "WHERE collection_dataset = {cd:String} AND plan_hash = {plan:String} "
            f"AND item_hash IN ({hash_sql})) AS h "
            "INNER JOIN (SELECT blob_hash, any(blob_size_bytes) AS size, any(s3_path) AS s3_path FROM blobs "
            "WHERE collection_dataset = {cd:String} GROUP BY blob_hash) AS b ON b.blob_hash = h.item_hash",
            parameters={"cd": params.collection_dataset, "plan": params.plan_hash, **extra}).result_rows
    out_dir = os.path.join("/tmp/hoover4", params.collection_dataset, f"update-virus-{params.plan_hash}")
    os.makedirs(out_dir, exist_ok=True)
    clock = HeartbeatClock()
    try:
        for file_hash, size, s3_path in rows:
            clock.beat(f"scan {file_hash}")
            path = os.path.join(out_dir, file_hash)
            write_blob_files(params.collectionname, params.collection_dataset, [
                {"item_hash": file_hash, "file_size_bytes": int(size or 0), "s3_url": s3_path or "", "path": path}],
                context=f"{params.collection_dataset}/{params.plan_hash}")
            try:
                store_attempts(params.collectionname,
                               [scan_file(params.collection_dataset, file_hash, path, int(size or 0))])
            finally:
                os.remove(path)
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
    return len(rows)


@activity.defn
@with_heartbeat
def list_update_detection_plans(params: VirusPlansParams) -> List[str]:
    """At most 100 plans after `after` that hold a file that the `ocr_detection` step selects."""
    from database.clickhouse import get_collection_client

    hash_sql, extra = selectors.detection_hash_sql()
    with get_collection_client(params.collectionname) as client:
        rows = client.query(
            "SELECT DISTINCT plan_hash FROM processing_plan_hits WHERE collection_dataset = {cd:String} "
            f"AND plan_hash > {{after:String}} AND item_hash IN ({hash_sql}) ORDER BY plan_hash LIMIT 100",
            parameters={"cd": params.collection_dataset, "after": params.after, **extra}).result_rows
    return [row[0] for row in rows]


@activity.defn
@with_heartbeat
def detect_update_files(params: TablePlanParams) -> int:
    """Examine the selected files of one plan, one at a time, and store their rows.

    An image that the service cannot decode stores an `undecodable` row and leaves the
    selection. A PDF that does not render stays selected, and settlement reports it.
    The other files of the plan continue.
    """
    import shutil

    from database.clickhouse import get_collection_client
    from tasks.P2_execute_plan.activities import write_blob_files
    from tasks.P3_parse_files import ocr_detection
    from tasks.P3_parse_files.batch_runner import BatchFile, StageBatchParams
    from tasks.P3_parse_files.pdf_parts import source_file

    hash_sql, extra = selectors.detection_hash_sql()
    cd = params.collection_dataset
    out_dir = os.path.join("/tmp/hoover4", cd, f"update-detection-{params.plan_hash}")
    os.makedirs(out_dir, exist_ok=True)
    clock = HeartbeatClock()
    with get_collection_client(params.collectionname) as client:
        rows = client.query(
            "SELECT h.item_hash, b.size, b.s3_path FROM (SELECT DISTINCT item_hash FROM processing_plan_hits "
            "WHERE collection_dataset = {cd:String} AND plan_hash = {plan:String} "
            f"AND item_hash IN ({hash_sql})) AS h "
            "LEFT JOIN (SELECT blob_hash, any(blob_size_bytes) AS size, any(s3_path) AS s3_path FROM blobs "
            "WHERE collection_dataset = {cd:String} GROUP BY blob_hash) AS b ON b.blob_hash = h.item_hash",
            parameters={"cd": cd, "plan": params.plan_hash, **extra}).result_rows
        scope = StageBatchParams(collectionname=params.collectionname, collection_dataset=cd,
                                 plan_hash=params.plan_hash, files=[], op_id=params.op_id)
        try:
            for file_hash, size, s3_path in rows:
                clock.beat(f"detect {file_hash}")
                path = os.path.join(out_dir, file_hash)
                write_blob_files(params.collectionname, cd, [
                    {"item_hash": file_hash, "file_size_bytes": int(size or 0), "s3_url": s3_path or "", "path": path}],
                    context=f"{cd}/{params.plan_hash}")
                try:
                    kind = next((kind for kind in ("original", "preview")
                                 if ocr_detection.stored_pdf_pages(client, cd, file_hash, kind)), "image")
                    file = BatchFile(item_hash=file_hash, file_path=path, source_kind=kind,
                                     routes=["image"] if kind == "image" else [])
                    ocr_detection._detect_file(scope, file)
                except ocr_detection.NotDetectable as error:
                    log.warning("[updates] %s has no OCR detection: %s", file_hash, error)
                finally:
                    os.remove(path)
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
    return len(rows)


def _shard_page_tables(collectionname: str) -> List[str]:
    from database.manticore import list_shard_tables

    return [t for t in list_shard_tables(collectionname) if t.endswith("_pages")]


def _dataset_verdicts(collectionname: str, collection_dataset: str) -> Dict[str, str]:
    """The effective verdict of each live file of the dataset that has one."""
    from database.clickhouse import get_collection_client

    with get_collection_client(collectionname) as client:
        rows = client.query(
            "SELECT hash, argMax(verdict, result_seq) FROM virus_scan_results WHERE attempt_status = 'completed' "
            "AND hash IN (SELECT hash FROM vfs_files FINAL WHERE collection_dataset = {cd:String} AND is_deleted = 0) "
            "GROUP BY hash", parameters={"cd": collection_dataset}).result_rows
    return {r[0]: r[1] for r in rows}


def _hashes_with_attribute(collectionname: str, collection_dataset: str, hashes: List[str], value: int) -> set:
    """The hashes among `hashes` with a search row whose `virus_hit` differs from `value`."""
    from database.manticore import client_for_table, table_has_column

    found: set = set()
    for table in _shard_page_tables(collectionname):
        if not table_has_column(table, "virus_hit"):
            continue
        with client_for_table(table) as cnx:
            cursor = cnx.cursor()
            for start in range(0, len(hashes), 200):
                chunk = hashes[start:start + 200]
                placeholders = ",".join(["%s"] * len(chunk))
                cursor.execute(
                    f"SELECT file_hash FROM {table} WHERE collection_dataset = %s AND file_hash IN ({placeholders}) "
                    f"AND virus_hit != %s GROUP BY file_hash LIMIT 1000 OPTION max_matches=1000",
                    (collection_dataset, *chunk, value))
                found.update(row[0] for row in cursor.fetchall())
    return found


def infected_without_attribute(collectionname: str, collection_dataset: str) -> List[str]:
    """The infected files of the dataset with a search row whose `virus_hit` is not 1."""
    infected = [h for h, v in _dataset_verdicts(collectionname, collection_dataset).items() if v == "infected"]
    if not infected:
        return []
    return sorted(_hashes_with_attribute(collectionname, collection_dataset, infected, 1))


@activity.defn
@with_heartbeat
def stale_virus_attributes(params: TablePlansParams) -> Dict[str, List[str]]:
    """The live files of the dataset whose search rows hold another `virus_hit` than their
    effective verdict, grouped by one plan that holds each file.

    Manticore refuses an UPDATE of a columnar attribute, so the caller indexes these files
    again with `IndexDatasetPlan`. The page writer reads the verdict when it writes a row.
    """
    from database.clickhouse import get_collection_client

    verdicts = _dataset_verdicts(params.collectionname, params.collection_dataset)
    stale: set = set()
    for value, hashes in ((1, [h for h, v in verdicts.items() if v == "infected"]),
                          (0, [h for h, v in verdicts.items() if v == "clean"])):
        if hashes:
            stale.update(_hashes_with_attribute(params.collectionname, params.collection_dataset, hashes, value))
    if not stale:
        return {}
    with get_collection_client(params.collectionname) as client:
        rows = client.query(
            "SELECT item_hash, max(plan_hash) FROM processing_plan_hits WHERE collection_dataset = {cd:String} "
            "AND item_hash IN {h:Array(String)} GROUP BY item_hash",
            parameters={"cd": params.collection_dataset, "h": sorted(stale)}).result_rows
    plans: Dict[str, List[str]] = {}
    for file_hash, plan_hash in rows:
        plans.setdefault(plan_hash, []).append(file_hash)
    return plans


@activity.defn
@with_heartbeat
def retire_cached_searches(params: TablePlansParams) -> None:
    """Change `server_settings.cache_epoch`, so no cached search answers with old attributes."""
    import time as _time

    from tasks.llm_catalog import set_server_setting

    set_server_setting("cache_epoch", f"virus-{params.collection_dataset}-{_time.time_ns()}")


@activity.defn
@with_heartbeat
def restore_missing_image_previews(params: TablePlansParams) -> int:
    """Publish and read at most 100 missing uncommon-image previews."""
    import tempfile
    from database.clickhouse import get_collection_client
    from tasks.P2_execute_plan.activities import write_blob_files
    from tasks.P3_parse_files.batch_runner import try_budget_seconds
    from tasks.P3_parse_files.image_preview import (
        PREVIEW_UNDECODABLE, ImagePreviewParams, make_image_preview, read_preview_bytes)

    hash_sql, extra = selectors.image_preview_hash_sql()
    with get_collection_client(params.collectionname) as client:
        rows = client.query(
            "SELECT h.hash, any(b.blob_size_bytes), any(b.s3_path), groupUniqArrayArray(t.mime_type) "
            f"FROM (SELECT hash FROM ({hash_sql}) LIMIT 100) AS h "
            "INNER JOIN blobs AS b ON b.blob_hash = h.hash AND b.collection_dataset = {cd:String} "
            "LEFT JOIN file_types AS t ON t.hash = h.hash AND t.collection_dataset = {cd:String} "
            "GROUP BY h.hash",
            parameters={"cd": params.collection_dataset, **extra}).result_rows
        clock = HeartbeatClock()
        with tempfile.TemporaryDirectory(prefix="hoover4-preview-update-") as folder:
            for file_hash, size, s3_path, mimes in rows:
                clock.beat(f"preview {file_hash}")
                path = os.path.join(folder, file_hash)
                write_blob_files(params.collectionname, params.collection_dataset, [
                    {"item_hash": file_hash, "file_size_bytes": int(size or 0), "s3_url": s3_path or "", "path": path}],
                    context=f"{params.collection_dataset} missing image preview")
                outcome = make_image_preview(ImagePreviewParams(
                    params.collectionname, params.collection_dataset, file_hash, path,
                    list(mimes or []), ["image"],
                    try_budget_seconds("make_image_preview_batch", int(size or 0))))
                undecodable = str(getattr(outcome, "value", "")).startswith(PREVIEW_UNDECODABLE)
                if not undecodable and not read_preview_bytes(client, params.collection_dataset, file_hash):
                    raise RuntimeError(f"The image preview remains unavailable for {file_hash}")
                os.remove(path)
    return len(rows)
