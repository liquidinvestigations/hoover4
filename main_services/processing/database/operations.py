"""The operations log, and the lock that is built on it.

One row of the global `operations` table per dispatched long operation. The row is the
only durable answer to "was this ever asked for, and how did it end": Temporal's
namespace retention here is a day, and the process that dispatched the work is mortal,
so neither the workflow history nor the caller's terminal survives long enough to be
the record.

Two rules run through everything below and neither is negotiable:

* **`op_id` is the Temporal workflow id.** Every dispatch mints a fresh one with a
  timestamp in it, so two dispatches can never collapse into one execution and every
  attempt keeps its own row.
* **A non-terminal row holds the lock.** A dataset operation holds its dataset and a
  collection operation holds its collection. A row that has stopped reporting is NOT
  treated as free: a run that stopped updating may still have activities in flight, and
  releasing the lock on a clock would start a second writer beside a live one. There is
  deliberately no staleness timeout here. Cancelling the operation is how a lock is
  released early.

The table is a `ReplacingMergeTree(row_version)` ordered by `(started_at, op_id)`, so an
update is an insert of the whole row with a higher `row_version` **and the original
`started_at`**. Changing `started_at` writes a second row rather than replacing the
first, which is why every update path here reads the current row before writing.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

import pyarrow as pa

log = logging.getLogger(__name__)

#: States a row can be in. The first two are live; the last three are terminal.
LIVE_STATES = ("pending", "running")
TERMINAL_STATES = ("finished", "errored", "cancelled")

#: Every operation kind, what it acts on, and whether it destroys data.
#:
#: `destructive` is what the admin UI reads to demand a typed confirmation naming the
#: target before it will schedule one. It is a property of the kind, not of the caller,
#: so the CLI and the web UI cannot disagree about which operations are dangerous.
KINDS: dict[str, dict] = {
    "add_dataset": {"target_kind": "dataset", "destructive": False},
    "rescan_dataset": {"target_kind": "dataset", "destructive": False},
    "compute_plans": {"target_kind": "dataset", "destructive": False},
    "execute_plans": {"target_kind": "dataset", "destructive": False},
    "purge_dataset": {"target_kind": "dataset", "destructive": True},
    "delete_dataset": {"target_kind": "dataset", "destructive": True},
    "change_ocr_languages": {"target_kind": "dataset", "destructive": False},
    "reindex_collection": {"target_kind": "collection", "destructive": False},
    "refresh_document_locations": {"target_kind": "dataset", "destructive": False},
    "retry_failed_files": {"target_kind": "dataset", "destructive": False},
    "ensure_collection": {"target_kind": "collection", "destructive": False},
    "drop_collection_database": {"target_kind": "collection", "destructive": True},
    "export_collection": {"target_kind": "collection", "destructive": False},
    "import_collection": {"target_kind": "collection", "destructive": True},
    "purge_unattributed_entities": {"target_kind": "collection", "destructive": True},
    "backfill_vectors": {"target_kind": "collection", "destructive": False},
}

DRIVEN_KINDS = (
    "add_dataset",
    "rescan_dataset",
    "compute_plans",
    "execute_plans",
    "purge_dataset",
    "delete_dataset",
    "change_ocr_languages",
    "reindex_collection",
    "refresh_document_locations",
    "retry_failed_files",
    "ensure_collection",
    "drop_collection_database",
    "export_collection",
    "import_collection",
    "purge_unattributed_entities",
    "backfill_vectors",
)

#: The columns of `operations`, in table order. One list, because a `ReplacingMergeTree`
#: update rewrites the whole row and a column missed here would be silently reset to its
#: default on every update.
COLUMNS = (
    "op_id", "kind", "target_kind", "collectionname", "collection_dataset",
    "state", "started_at", "finished_at", "updated_at",
    "progress_done", "progress_total", "eta_seconds",
    "detail", "error", "user_id", "rerun_of", "row_version",
)

VERSION_BITS = 62
VERSION_MASK = (1 << VERSION_BITS) - 1
STATE_RANK = {"finished": 1, "errored": 1, "cancelled": 2}


def next_row_version(state: str, prior: int = 0) -> int:
    """Give terminal states priority over late progress inserts."""
    rank = STATE_RANK.get(state, 0)
    now_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
    lower = max(now_us, (int(prior) & VERSION_MASK) + 1)
    return (rank << VERSION_BITS) | lower


class OperationLocked(Exception):
    """A dispatch was refused because a non-terminal operation holds the target.

    Carries the blocking rows so the caller can name what is in the way rather than
    saying only that something is.
    """

    def __init__(self, kind: str, target: str, blockers: list[dict]):
        self.kind = kind
        self.target = target
        self.blockers = blockers
        names = ", ".join(
            f"{blocker['op_id']} ({blocker['kind']}, {blocker['state']})"
            for blocker in blockers
        )
        super().__init__(
            f"{target} is held by {names}. Wait for it, or cancel it with "
            f"`main.py operations cancel <op_id>`, then dispatch again."
        )


def is_destructive(kind: str) -> bool:
    """Whether this kind needs a typed confirmation before it is scheduled."""
    return bool(KINDS.get(kind, {}).get("destructive"))


def target_of(kind: str, collectionname: str, collection_dataset: str) -> str:
    """The single string a kind acts on: the dataset, the collection, or nothing.

    Which identifier is the target is a property of the kind. The value is also part of
    the operation id, so it keeps repeated dispatches distinct.
    """
    target_kind = KINDS[kind]["target_kind"]
    if target_kind == "dataset":
        return collection_dataset
    if target_kind == "collection":
        return collectionname
    raise ValueError(f"Unknown operation target kind: {target_kind}")


def _now() -> datetime:
    """UTC, with the tzinfo dropped: ClickHouse `DateTime` columns are naive UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_op_id(kind: str, collectionname: str, collection_dataset: str) -> str:
    """Mint an operation id: kind, target and a timestamp, and also the workflow id.

    A microsecond timestamp and random suffix distinguish immediate dispatches.
    """
    target = target_of(kind, collectionname, collection_dataset) or "global"
    stamp = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
    return f"{kind}-{target}-{stamp}-{uuid.uuid4().hex[:12]}"


def _row_dicts(result) -> list[dict]:
    """Rows as dicts keyed by the names the query asked for.

    Built from `column_names` rather than from a remembered order: a query that selects
    a subset, or reorders, otherwise silently pairs values with the wrong keys.
    """
    names = list(result.column_names)
    return [dict(zip(names, row)) for row in result.result_rows]


def _select(where: str, parameters: dict, limit: int | None = None) -> list[dict]:
    from .clickhouse import get_global_client

    cols = ", ".join(COLUMNS)
    sql = f"SELECT {cols} FROM operations FINAL"
    if where:
        sql += f" WHERE {where}"
    sql += " ORDER BY started_at DESC, op_id DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    with get_global_client() as client:
        return _row_dicts(client.query(sql, parameters=parameters))


def _insert_row(row: dict) -> None:
    from .clickhouse import get_global_client, insert_arrow_durable

    table = pa.table({
        "op_id": pa.array([row["op_id"]], type=pa.string()),
        "kind": pa.array([row["kind"]], type=pa.string()),
        "target_kind": pa.array([row["target_kind"]], type=pa.string()),
        "collectionname": pa.array([row["collectionname"]], type=pa.string()),
        "collection_dataset": pa.array([row["collection_dataset"]], type=pa.string()),
        "state": pa.array([row["state"]], type=pa.string()),
        "started_at": pa.array([row["started_at"]], type=pa.timestamp("s")),
        "finished_at": pa.array([row["finished_at"]], type=pa.timestamp("s")),
        "updated_at": pa.array([row["updated_at"]], type=pa.timestamp("s")),
        "progress_done": pa.array([int(row["progress_done"])], type=pa.uint64()),
        "progress_total": pa.array([int(row["progress_total"])], type=pa.uint64()),
        "eta_seconds": pa.array([int(row["eta_seconds"])], type=pa.uint32()),
        "detail": pa.array([row["detail"]], type=pa.string()),
        "error": pa.array([row["error"]], type=pa.string()),
        "user_id": pa.array([row["user_id"]], type=pa.string()),
        "rerun_of": pa.array([row["rerun_of"]], type=pa.string()),
        "row_version": pa.array([int(row["row_version"])], type=pa.uint64()),
    })
    with get_global_client() as client:
        insert_arrow_durable(client, "operations", table)


def lock_clause(kind: str, collectionname: str,
                collection_dataset: str) -> tuple[str, dict]:
    """Return the live-row lock clause and its bound parameters."""
    target_kind = KINDS[kind]["target_kind"]
    if target_kind == "dataset":
        return (
            "state IN ('pending', 'running') AND "
            "(collection_dataset = {collection_dataset:String} OR "
            "(target_kind = 'collection' AND collectionname = {collectionname:String}))",
            {
                "collection_dataset": collection_dataset,
                "collectionname": collectionname,
            },
        )
    if target_kind == "collection":
        return (
            "state IN ('pending', 'running') AND collectionname = {collectionname:String}",
            {"collectionname": collectionname},
        )
    raise ValueError(f"Unknown operation target kind: {target_kind}")


def blocking_operations(kind: str, collectionname: str,
                        collection_dataset: str) -> list[dict]:
    """Live operations that conflict with this dispatch, newest first.

    Empty means the lock is free. A stale row is returned like any other, on purpose.
    """
    where, parameters = lock_clause(kind, collectionname, collection_dataset)
    return _select(where, parameters)


def assert_lock_free(kind: str, collectionname: str, collection_dataset: str) -> None:
    """Refuse a dispatch while a non-terminal operation holds its target."""
    blockers = blocking_operations(kind, collectionname, collection_dataset)
    if blockers:
        raise OperationLocked(
            kind, target_of(kind, collectionname, collection_dataset) or "global",
            blockers,
        )


def open_operations_for_collection(collectionname: str) -> list[dict]:
    """Every non-terminal operation touching a collection, whatever its kind.

    What `reindex-collection` reads: it truncates the shard ledger, so it must not run
    beside anything that writes to the collection at all, not merely beside another
    re-index.
    """
    return _select(
        "collectionname = {name:String} AND state IN ('pending', 'running')",
        {"name": collectionname},
    )


def create_operation(kind: str, collectionname: str = "", collection_dataset: str = "",
                     detail: dict | None = None, user_id: str = "system",
                     rerun_of: str = "", op_id: str | None = None) -> dict:
    """Take the lock and write the `pending` row. Returns the row.

    Raises `OperationLocked` if the target is already held. The lock check and row
    insert are separate statements. Concurrent callers can both pass the check.
    """
    if kind not in KINDS:
        raise ValueError(f"Unknown operation kind: {kind}")
    assert_lock_free(kind, collectionname, collection_dataset)
    now = _now()
    row = {
        "op_id": op_id or new_op_id(kind, collectionname, collection_dataset),
        "kind": kind,
        "target_kind": KINDS[kind]["target_kind"],
        "collectionname": collectionname,
        "collection_dataset": collection_dataset,
        "state": "pending",
        "started_at": now,
        # Epoch 0 is the table's own "not finished" sentinel, and a naive datetime
        # because the column is naive UTC.
        "finished_at": datetime(1970, 1, 1),
        "updated_at": now,
        "progress_done": 0,
        "progress_total": 0,
        "eta_seconds": 0,
        "detail": json.dumps(detail or {}, sort_keys=True),
        "error": "",
        "user_id": user_id,
        "rerun_of": rerun_of,
        "row_version": next_row_version("pending"),
    }
    _insert_row(row)
    log.info("operation %s created (%s)", row["op_id"], kind)
    return row


def get_operation(op_id: str) -> dict | None:
    """One row by id, or None. `None` and "still pending" are different answers."""
    rows = _select("op_id = {op_id:String}", {"op_id": op_id}, limit=1)
    return rows[0] if rows else None


def list_operations(state: str = "", collectionname: str = "", kind: str = "",
                    limit: int = 50) -> list[dict]:
    """The newest operations, filtered. Newest first, which is how the log is read."""
    clauses, parameters = [], {}
    if state:
        clauses.append("state = {state:String}")
        parameters["state"] = state
    if collectionname:
        clauses.append("collectionname = {name:String}")
        parameters["name"] = collectionname
    if kind:
        clauses.append("kind = {kind:String}")
        parameters["kind"] = kind
    return _select(" AND ".join(clauses), parameters, limit=limit)


def update_operation(op_id: str, *, base_row: dict | None = None, **changes) -> dict | None:
    """Rewrite a row with the given fields changed. Returns the new row, or None.

    `started_at` is in the sort key and is carried through untouched: writing a
    different one inserts a second row instead of replacing the first, and the log then
    shows one operation twice.
    """
    current = base_row if base_row is not None else get_operation(op_id)
    if current is None:
        log.warning("operation %s not found; nothing updated", op_id)
        return None
    if current["state"] in TERMINAL_STATES:
        return current
    row = dict(current)
    for key, value in changes.items():
        if key not in COLUMNS or key in ("op_id", "started_at", "row_version"):
            raise ValueError(f"Not an updatable operations column: {key}")
        row[key] = value
    if isinstance(row.get("detail"), dict):
        row["detail"] = json.dumps(row["detail"], sort_keys=True)
    row["updated_at"] = _now()
    row["row_version"] = next_row_version(row["state"], current["row_version"])
    _insert_row(row)
    return row


def finish_operation(op_id: str, state: str, error: str = "") -> dict | None:
    """Land a row in a terminal state, stamping `finished_at`. This releases the lock."""
    if state not in TERMINAL_STATES:
        raise ValueError(f"Not a terminal state: {state}")
    return update_operation(op_id, state=state, error=error[:4000],
                            finished_at=_now())


def merge_detail(op_id: str, **fields) -> dict | None:
    """Merge keys into a row's `detail` JSON without losing what is already there.

    `detail` is where per-stage counters live, including the per-document failure
    counts a plan that finished green would otherwise hide. Callers merge rather than
    overwrite so two writers of different counters do not erase each other.
    """
    current = get_operation(op_id)
    if current is None:
        return None
    try:
        detail = json.loads(current.get("detail") or "{}")
    except ValueError:
        detail = {}
    if not isinstance(detail, dict):
        detail = {}
    detail.update(fields)
    return update_operation(op_id, detail=json.dumps(detail, sort_keys=True))
