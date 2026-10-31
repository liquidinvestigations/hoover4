"""Reads and writes of the processing update state.

Migration `00051_processing_updates.sql` defines the tables. Three facts stay apart:

* a **check** (`processing_update_checks`) is the newest calculation of a step: what it
  should produce now (the desired fingerprint) and which files it selects;
* an **attempt** (`processing_update_attempts`) is one run of a step under one operation,
  with the snapshot that it ran for;
* the **applied** state (`processing_update_applied`) is the fingerprint that a step last
  produced and verified.

A step is up to date when its applied fingerprint equals its desired fingerprint. An
attempt row keeps the operations rule for its version: a terminal row outranks a running
row. A running attempt whose operation row is terminal reads as the end of that
operation, so a worker stop or a cancellation cannot leave a step running for ever.

The **input revision** of a dataset is the newest terminal operation that can change its
input: every kind except the processing updates themselves, on the dataset or on its
collection. New ingestion, an interrupted operation or a retry therefore change it, and
the steps that select unfinished work calculate again without a code change.
"""

import json
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from .operations import TERMINAL_STATES, UPDATE_KINDS, VERSION_BITS, VERSION_MASK

ATTEMPT_TERMINAL = ("succeeded", "failed", "cancelled", "skipped")
_UPDATE_KINDS_SQL = ", ".join(f"'{kind}'" for kind in UPDATE_KINDS)
_TERMINAL_SQL = ", ".join(f"'{state}'" for state in TERMINAL_STATES)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def attempt_row_version(state: str, prior: int = 0) -> int:
    """The version of an attempt row: rank 1 for a terminal state, above `prior`."""
    rank = 1 if state in ATTEMPT_TERMINAL else 0
    now_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
    return (rank << VERSION_BITS) | max(now_us, (int(prior) & VERSION_MASK) + 1)


def effective_attempt_state(state: str, operation_state: str) -> str:
    """The state of an attempt, with a running row closed by its terminal operation."""
    if state != "running" or operation_state not in TERMINAL_STATES:
        return state
    return {"cancelled": "cancelled"}.get(operation_state, "failed")


# ---- reads -------------------------------------------------------------------------------


def input_revisions() -> Dict[str, str]:
    """The input revision of each dataset scope and each collection scope.

    Keys are `collection_dataset` and `collectionname`. A dataset revision joins its own
    newest terminal operation with that of its collection. One query over the global
    operations table.
    """
    from .clickhouse import get_global_client

    with get_global_client() as client:
        rows = client.query(
            "SELECT target_kind, collectionname, collection_dataset, "
            "argMax(op_id, (finished_at, op_id)) FROM operations FINAL "
            f"WHERE state IN ({_TERMINAL_SQL}) AND kind NOT IN ({_UPDATE_KINDS_SQL}) "
            "GROUP BY target_kind, collectionname, collection_dataset"
        ).result_rows
    collections: Dict[str, str] = {}
    datasets: Dict[str, str] = {}
    for target_kind, collectionname, collection_dataset, op_id in rows:
        if target_kind == "collection":
            collections[collectionname] = op_id
        elif collection_dataset:
            datasets[collection_dataset] = op_id
    return {"datasets": datasets, "collections": collections}


def stored_checks(scope_ids: Iterable[str] = ()) -> Dict[Tuple[str, str], dict]:
    """The newest check of each `(scope_id, step_id)`, optionally for some scopes."""
    return _keyed(
        "SELECT scope_kind, scope_id, collectionname, step_id, desired_fingerprint, "
        "pending_files, pending_bytes, automatic_files, executions, detail, check_ms, "
        "checked_at FROM processing_update_checks FINAL", scope_ids)


def stored_applied(scope_ids: Iterable[str] = ()) -> Dict[Tuple[str, str], dict]:
    """The applied state of each `(scope_id, step_id)`."""
    return _keyed(
        "SELECT scope_kind, scope_id, collectionname, step_id, applied_fingerprint, op_id, "
        "detail, applied_at FROM processing_update_applied FINAL", scope_ids)


def attempts_at(scope_ids: Iterable[str] = ()) -> Dict[Tuple[str, str, str], List[dict]]:
    """Attempts keyed by `(scope_id, step_id, desired_fingerprint)`, newest first.

    Each row carries `effective_state`, which closes a running row whose operation ended.
    """
    from .clickhouse import get_global_client

    scope_ids = list(scope_ids)
    where = "WHERE a.scope_id IN {s:Array(String)} " if scope_ids else ""
    with get_global_client() as client:
        result = client.query(
            "SELECT a.scope_id, a.step_id, a.op_id, a.desired_fingerprint, a.automatic, "
            "a.state, a.error, a.started_at, a.ended_at, o.state AS operation_state "
            "FROM processing_update_attempts AS a FINAL "
            "LEFT JOIN (SELECT op_id, state FROM operations FINAL "
            f"WHERE kind IN ({_UPDATE_KINDS_SQL})) AS o ON o.op_id = a.op_id "
            + where + "ORDER BY a.started_at DESC",
            parameters={"s": scope_ids})
        names = list(result.column_names)
        rows = [dict(zip(names, row)) for row in result.result_rows]
    keyed: Dict[Tuple[str, str, str], List[dict]] = {}
    for row in rows:
        row["effective_state"] = effective_attempt_state(row["state"], row["operation_state"] or "")
        keyed.setdefault((row["scope_id"], row["step_id"], row["desired_fingerprint"]), []).append(row)
    return keyed


def _keyed(sql: str, scope_ids: Iterable[str]) -> Dict[Tuple[str, str], dict]:
    from .clickhouse import get_global_client

    scope_ids = list(scope_ids)
    if scope_ids:
        sql += " WHERE scope_id IN {s:Array(String)}"
    with get_global_client() as client:
        result = client.query(sql, parameters={"s": scope_ids})
        names = list(result.column_names)
        rows = [dict(zip(names, row)) for row in result.result_rows]
    return {(row["scope_id"], row["step_id"]): row for row in rows}


def entitled_stage_versions() -> Dict[str, int]:
    """Stages whose current version is not their baseline, with that version.

    Errors of these stage versions may get one automatic retry.
    """
    from tasks.stage_versions import STAGE_VERSIONS

    from .clickhouse import get_global_client

    with get_global_client() as client:
        rows = client.query(
            "SELECT stage, version, baseline FROM stage_versions FINAL").result_rows
    recorded = {(stage, int(version)): int(baseline) for stage, version, baseline in rows}
    return {stage: version for stage, version in STAGE_VERSIONS.items()
            if recorded.get((stage, version)) == 0}


def claimed_stage_versions(collection_dataset: str) -> set:
    """The `(stage, version)` pairs that a retry already claimed for a dataset."""
    from .clickhouse import get_global_client

    with get_global_client() as client:
        rows = client.query(
            "SELECT stage, stage_version FROM processing_retry_claims FINAL "
            "WHERE collection_dataset = {cd:String}",
            parameters={"cd": collection_dataset}).result_rows
    return {(stage, int(version)) for stage, version in rows}


def live_update_operations() -> List[dict]:
    """Live operations of the update kinds."""
    from .operations import _select, LIVE_STATES

    live = ", ".join(f"'{state}'" for state in LIVE_STATES)
    return _select(f"kind IN ({_UPDATE_KINDS_SQL}) AND state IN ({live})", {})


# ---- writes ------------------------------------------------------------------------------


def write_checks(rows: List[dict]) -> None:
    """Insert check rows. Each dict has the columns of `processing_update_checks`."""
    if not rows:
        return
    from .clickhouse import get_global_client, insert_durable

    columns = ["scope_kind", "scope_id", "collectionname", "step_id", "desired_fingerprint",
               "pending_files", "pending_bytes", "automatic_files", "executions", "detail",
               "check_ms", "checked_at"]
    now = _now()
    data = [[row.get("checked_at", now) if c == "checked_at" else row.get(c, 0 if c in (
        "pending_files", "pending_bytes", "automatic_files", "executions", "check_ms") else "")
             for c in columns] for row in rows]
    with get_global_client() as client:
        insert_durable(client, "processing_update_checks", data, column_names=columns)


def write_applied(scope_kind: str, scope_id: str, collectionname: str, step_id: str,
                  fingerprint: str, op_id: str = "", detail: Optional[dict] = None) -> None:
    """Record that a step produced and verified `fingerprint`."""
    from .clickhouse import get_global_client, insert_durable

    with get_global_client() as client:
        insert_durable(client, "processing_update_applied", [[
            scope_kind, scope_id, collectionname, step_id, fingerprint, op_id,
            json.dumps(detail or {}, sort_keys=True), _now()]],
            column_names=["scope_kind", "scope_id", "collectionname", "step_id",
                          "applied_fingerprint", "op_id", "detail", "applied_at"])


def write_attempt(scope_kind: str, scope_id: str, collectionname: str, step_id: str,
                  op_id: str, fingerprint: str, automatic: bool, state: str,
                  snapshot: dict, error: str = "") -> None:
    """Write an attempt row. A terminal state keeps the start time of the running row."""
    from .clickhouse import get_global_client, insert_durable

    with get_global_client() as client:
        prior = client.query(
            "SELECT started_at, row_version, state FROM processing_update_attempts FINAL "
            "WHERE scope_id = {s:String} AND step_id = {st:String} AND op_id = {op:String}",
            parameters={"s": scope_id, "st": step_id, "op": op_id}).result_rows
        started_at, prior_version, prior_state = prior[0] if prior else (_now(), 0, "")
        if prior_state in ATTEMPT_TERMINAL:
            return
        ended = _now() if state in ATTEMPT_TERMINAL else datetime(1970, 1, 1)
        insert_durable(client, "processing_update_attempts", [[
            scope_kind, scope_id, collectionname, step_id, op_id, fingerprint,
            1 if automatic else 0, state, error[:4000], json.dumps(snapshot, sort_keys=True),
            started_at, ended, attempt_row_version(state, prior_version)]],
            column_names=["scope_kind", "scope_id", "collectionname", "step_id", "op_id",
                          "desired_fingerprint", "automatic", "state", "error", "snapshot",
                          "started_at", "ended_at", "row_version"])


def claim_retries(collection_dataset: str, collectionname: str, op_id: str,
                  stage_versions: Dict[str, int]) -> None:
    """Claim the retry of each stage version for a dataset. A repeated claim is harmless."""
    if not stage_versions:
        return
    from .clickhouse import get_global_client, insert_durable

    with get_global_client() as client:
        existing = {(stage, int(version)) for stage, version in client.query(
            "SELECT stage, stage_version FROM processing_retry_claims FINAL "
            "WHERE collection_dataset = {cd:String}",
            parameters={"cd": collection_dataset}).result_rows}
        now = _now()
        rows = [[collection_dataset, collectionname, stage, version, op_id, now]
                for stage, version in sorted(stage_versions.items())
                if (stage, version) not in existing]
        if rows:
            insert_durable(client, "processing_retry_claims", rows,
                           column_names=["collection_dataset", "collectionname", "stage",
                                         "stage_version", "op_id", "claimed_at"])
