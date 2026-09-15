"""Read and write the Error events and plan records of an operation."""

from collections.abc import Mapping

PAIR_SEPARATOR = "\x1f"
ERROR_EXCERPT_CHARS = 2000
EVENTS = (
    "error",
    "selected",
    "removed_stage_off",
    "without_plan",
    "recovered",
    "still_failing",
)
PLAN_SOURCES = ("listed", "backfill")

_EVENT_COLUMNS = (
    "op_id",
    "collection_dataset",
    "hash",
    "task_name",
    "event",
    "error_logs",
)
_PLAN_COLUMNS = ("op_id", "collection_dataset", "plan_hash", "source")


def pair_key(hash: str, task_name: str) -> str:
    """Return the storage key for one Error pair."""
    return f"{hash}{PAIR_SEPARATOR}{task_name}"


def event_rows(
    op_id: str,
    collection_dataset: str,
    pairs,
    event: str,
    error_logs: Mapping[tuple[str, str], str] | None = None,
) -> list[dict]:
    """Build operation event rows for Error pairs."""
    if event not in EVENTS:
        raise ValueError(f"Unknown operation error event: {event}")
    error_logs = error_logs or {}
    return [
        {
            "op_id": op_id,
            "collection_dataset": collection_dataset,
            "hash": hash,
            "task_name": task_name,
            "event": event,
            "error_logs": str(error_logs.get((hash, task_name), ""))[
                :ERROR_EXCERPT_CHARS
            ],
        }
        for hash, task_name in pairs
    ]


def insert_error_events(collectionname: str, rows: list[dict]) -> int:
    """Insert Error event rows and return the number written."""
    if not rows:
        return 0
    from .clickhouse import get_collection_client, insert_durable

    values = [[row[column] for column in _EVENT_COLUMNS] for row in rows]
    with get_collection_client(collectionname) as client:
        insert_durable(
            client,
            "operation_error_events",
            values,
            column_names=_EVENT_COLUMNS,
        )
    return len(values)


def insert_operation_plans(
    collectionname: str,
    op_id: str,
    collection_dataset: str,
    plan_hashes,
    source: str,
) -> int:
    """Insert plan records and return the number written."""
    if source not in PLAN_SOURCES:
        raise ValueError(f"Unknown operation plan source: {source}")
    plan_hashes = list(plan_hashes)
    if not op_id or not plan_hashes:
        return 0
    from .clickhouse import get_collection_client, insert_durable

    values = [
        [op_id, collection_dataset, plan_hash, source] for plan_hash in plan_hashes
    ]
    with get_collection_client(collectionname) as client:
        insert_durable(
            client,
            "operation_plans",
            values,
            column_names=_PLAN_COLUMNS,
        )
    return len(values)


def pairs_with_event(
    collectionname: str,
    op_id: str,
    collection_dataset: str,
    event: str,
) -> list[tuple[str, str]]:
    """Read the distinct pairs with one operation event."""
    from .clickhouse import get_collection_client

    with get_collection_client(collectionname) as client:
        rows = client.query(
            "SELECT DISTINCT hash, task_name FROM operation_error_events FINAL "
            "WHERE op_id = {op:String} AND collection_dataset = {ds:String} "
            "AND event = {event:String} ORDER BY hash, task_name",
            parameters={"op": op_id, "ds": collection_dataset, "event": event},
        ).result_rows
    return [(str(hash), str(task_name)) for hash, task_name in rows]


def run_plan_counts(
    collectionname: str,
    op_id: str,
    collection_dataset: str,
) -> tuple[int, int]:
    """Return completed and recorded plan counts for one operation."""
    from .clickhouse import get_collection_client

    with get_collection_client(collectionname) as client:
        row = client.query(
            "SELECT uniqExact(p.plan_hash) AS plans_total, "
            "uniqExactIf(p.plan_hash, f.plan_hash != '') AS plans_done "
            "FROM (SELECT DISTINCT plan_hash FROM operation_plans "
            "WHERE op_id = {op:String} AND collection_dataset = {ds:String}) AS p "
            "LEFT JOIN (SELECT plan_hash FROM processing_plan_finished FINAL "
            "WHERE collection_dataset = {ds:String}) AS f "
            "ON f.plan_hash = p.plan_hash",
            parameters={"op": op_id, "ds": collection_dataset},
        ).result_rows[0]
    plans_total, plans_done = row
    return int(plans_done), int(plans_total)


def delete_error_pairs(
    collectionname: str,
    collection_dataset: str,
    keep_op_id: str,
    pairs,
) -> int:
    """Delete older Error rows for pairs and return the number of pairs processed."""
    keys = [pair_key(hash, task_name) for hash, task_name in pairs]
    if not keys:
        return 0
    from .clickhouse import get_collection_client

    with get_collection_client(collectionname) as client:
        for start in range(0, len(keys), 500):
            client.command(
                "ALTER TABLE processing_errors DELETE "
                "WHERE collection_dataset = {ds:String} "
                "AND op_id != {op:String} "
                "AND concat(hash, char(31), task_name) IN {keys:Array(String)}",
                parameters={
                    "ds": collection_dataset,
                    "op": keep_op_id,
                    "keys": keys[start:start + 500],
                },
                settings={"mutations_sync": 2},
            )
    return len(keys)
