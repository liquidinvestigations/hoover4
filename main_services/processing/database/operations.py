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
* **A non-terminal row holds the lock.** A second dispatch of the same kind against the
  same target is refused while one exists, and a row that has stopped reporting is NOT
  treated as free: a run that stopped updating may still have activities in flight, and
  releasing the lock on a clock would start a second writer beside a live one. There is
  deliberately no staleness timeout here. Cancelling the operation is how a lock is
  released early.

The table is a `ReplacingMergeTree(updated_at)` ordered by `(started_at, op_id)`, so an
update is an insert of the whole row with a newer `updated_at` **and the original
`started_at`**. Changing `started_at` writes a second row rather than replacing the
first, which is why every update path here reads the current row before writing.
"""

import json
import logging
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
    "retry_failed_files": {"target_kind": "dataset", "destructive": False},
    "ensure_collection": {"target_kind": "collection", "destructive": False},
    "drop_collection_database": {"target_kind": "collection", "destructive": True},
    "export_collection": {"target_kind": "collection", "destructive": False},
    "import_collection": {"target_kind": "collection", "destructive": True},
}

#: The columns of `operations`, in table order. One list, because a `ReplacingMergeTree`
#: update rewrites the whole row and a column missed here would be silently reset to its
#: default on every update.
COLUMNS = (
    "op_id", "kind", "target_kind", "collectionname", "collection_dataset",
    "state", "started_at", "finished_at", "updated_at",
    "progress_done", "progress_total", "eta_seconds",
    "detail", "error", "user_id", "rerun_of",
)


class OperationLocked(Exception):
    """A dispatch was refused because a non-terminal operation holds the target.

    Carries the blocking rows so the caller can name what is in the way rather than
    saying only that something is.
    """

    def __init__(self, kind: str, target: str, blockers: list[dict]):
        self.kind = kind
        self.target = target
        self.blockers = blockers
        names = ", ".join(f"{b['op_id']} ({b['state']})" for b in blockers[:5])
        super().__init__(
            f"{kind} is already running for {target}: {names}. Wait for it, or cancel "
            f"it with `main.py operations cancel <op_id>`, then dispatch again."
        )


def is_destructive(kind: str) -> bool:
    """Whether this kind needs a typed confirmation before it is scheduled."""
    return bool(KINDS.get(kind, {}).get("destructive"))


def target_of(kind: str, collectionname: str, collection_dataset: str) -> str:
    """The single string a kind locks on: the dataset, the collection, or nothing.

    The lock is over `(kind, target)`, and which of the two identifiers is the target
    is a property of the kind. Reading both would let a dataset-scoped operation block
    on a collection-scoped one that is not touching it.
    """
    target_kind = KINDS.get(kind, {}).get("target_kind", "global")
    if target_kind == "dataset":
        return collection_dataset
    if target_kind == "collection":
        return collectionname
    return ""


def _now() -> datetime:
    """UTC, with the tzinfo dropped: ClickHouse `DateTime` columns are naive UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_op_id(kind: str, collectionname: str, collection_dataset: str) -> str:
    """Mint an operation id: kind, target and a timestamp, and also the workflow id.

    The timestamp is what makes it unique per dispatch, so the reuse policy on the
    workflow stops deciding anything and a re-run is always a new execution with a
    history of its own.
    """
    target = target_of(kind, collectionname, collection_dataset) or "global"
    stamp = int(datetime.now(timezone.utc).timestamp())
    return f"{kind}-{target}-{stamp}"


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
    })
    with get_global_client() as client:
        insert_arrow_durable(client, "operations", table)


def blocking_operations(kind: str, collectionname: str,
                        collection_dataset: str) -> list[dict]:
    """Non-terminal rows of this kind against this target, newest first.

    Empty means the lock is free. A stale row is returned like any other, on purpose.
    """
    target = target_of(kind, collectionname, collection_dataset)
    column = {
        "dataset": "collection_dataset",
        "collection": "collectionname",
    }.get(KINDS.get(kind, {}).get("target_kind", "global"))
    where = "kind = {kind:String} AND state IN ('pending', 'running')"
    parameters: dict = {"kind": kind}
    if column:
        where += f" AND {column} = {{target:String}}"
        parameters["target"] = target
    return _select(where, parameters)


def assert_lock_free(kind: str, collectionname: str, collection_dataset: str) -> None:
    """Refuse a dispatch while a non-terminal operation of this kind holds the target."""
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

    Raises `OperationLocked` if the target is already held. The check and the insert are
    not atomic — ClickHouse offers no way to make them so — and that is acceptable
    because the workflow id is the second guard: two dispatches that pass the check in
    the same second still mint different ids, and the underlying pipeline stages are
    idempotent.
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


def update_operation(op_id: str, **changes) -> dict | None:
    """Rewrite a row with the given fields changed. Returns the new row, or None.

    `started_at` is in the sort key and is carried through untouched: writing a
    different one inserts a second row instead of replacing the first, and the log then
    shows one operation twice.
    """
    current = get_operation(op_id)
    if current is None:
        log.warning("operation %s not found; nothing updated", op_id)
        return None
    row = dict(current)
    for key, value in changes.items():
        if key not in COLUMNS or key in ("op_id", "started_at"):
            raise ValueError(f"Not an updatable operations column: {key}")
        row[key] = value
    if isinstance(row.get("detail"), dict):
        row["detail"] = json.dumps(row["detail"], sort_keys=True)
    row["updated_at"] = _now()
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
