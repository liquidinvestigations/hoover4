"""Failure-selection helpers used by Error re-runs.

The selector clears stage watermarks, reopens affected plans, and records selected
Error pairs. Reconciliation replaces those pairs after plan execution.
"""

import logging
from typing import NamedTuple

log = logging.getLogger(__name__)

# Hashes per ClickHouse query. A hash list goes into ONE query parameter, and the
# server rejects a parameter over 128 KiB. 4 392 Failed hashes of 40 characters is
# already past it. Sized by bytes, not by "that looks like a lot".
HASH_CHUNK = 500


class FailureGroup(NamedTuple):
    """One (dataset, task) group of ``processing_errors`` rows.

    A tuple rather than a dataclass on purpose: it is a *report* row built straight
    from a query result, never a workflow or activity parameter, and every params
    dataclass carrying a ``collection_dataset`` must also carry a ``collectionname``
    (``tests/unit/test_params_carry_collection.py`` enforces exactly that).
    """

    collection_dataset: str
    task_name: str
    errors: int
    documents: int
    first_seen: str
    last_seen: str

def chunked(values, size: int = HASH_CHUNK):
    """Yield `values` in lists of at most `size`. Empty input yields nothing."""
    values = list(values)
    for start in range(0, len(values), size):
        yield values[start:start + size]


def list_failures(collectionname: str, collection_dataset: str = "") -> list[FailureGroup]:
    """Every (dataset, task) group in ``processing_errors``, newest failure first."""
    from database.clickhouse import get_collection_client

    where = "WHERE collection_dataset = {ds:String}" if collection_dataset else ""
    with get_collection_client(collectionname) as client:
        rows = client.query(f"""
            SELECT collection_dataset,
                   task_name,
                   count() AS errors,
                   uniqExact(hash) AS documents,
                   toString(min(timestamp)) AS first_seen,
                   toString(max(timestamp)) AS last_seen
            FROM processing_errors
            {where}
            GROUP BY collection_dataset, task_name
            ORDER BY last_seen DESC, task_name ASC
        """, parameters={"ds": collection_dataset}).result_rows
    return [FailureGroup(*row) for row in rows]


def failed_hashes(collectionname: str, collection_dataset: str, task_name: str) -> list[str]:
    """The file hashes `task_name` failed on, sorted. Dataset-level rows (empty hash)
    are excluded: they name no file and nothing per-file can be retried for them."""
    from database.clickhouse import get_collection_client

    with get_collection_client(collectionname) as client:
        rows = client.query(
            "SELECT DISTINCT hash FROM processing_errors "
            "WHERE collection_dataset = {ds:String} AND task_name = {task:String} "
            "AND hash != '' ORDER BY hash",
            parameters={"ds": collection_dataset, "task": task_name},
        ).result_rows
    return [row[0] for row in rows]


def plans_for_hashes(collectionname: str, collection_dataset: str, hashes) -> list[str]:
    """The plans those hashes belong to, sorted and de-duplicated."""
    from database.clickhouse import get_collection_client

    found: set[str] = set()
    with get_collection_client(collectionname) as client:
        for chunk in chunked(hashes):
            rows = client.query(
                "SELECT DISTINCT plan_hash FROM processing_plan_hits "
                "WHERE collection_dataset = {ds:String} AND item_hash IN {hashes:Array(String)}",
                parameters={"ds": collection_dataset, "hashes": chunk},
            ).result_rows
            found.update(row[0] for row in rows)
    return sorted(found)


def clear_nlp_state(collectionname: str, collection_dataset: str, hashes) -> tuple[int, int]:
    """Delete the NER watermarks and entity rows of `hashes`. Returns (watermarks, hits).

    Watermarks first, then the hits. See the module docstring. `mutations_sync=2`
    because the re-run that follows depends on the deletes having landed, and an
    `ALTER TABLE ... DELETE` is asynchronous by default.
    """
    from database.clickhouse import get_collection_client

    settings = {"mutations_sync": 2}
    watermarks = hits = 0
    with get_collection_client(collectionname) as client:
        for chunk in chunked(hashes):
            watermarks += int(client.query(
                "SELECT count() FROM nlp_processed WHERE collection_dataset = {ds:String} "
                "AND file_hash IN {hashes:Array(String)}",
                parameters={"ds": collection_dataset, "hashes": chunk},
            ).result_rows[0][0])
            hits += int(client.query(
                "SELECT count() FROM entity_hit WHERE collection_dataset = {ds:String} "
                "AND file_hash IN {hashes:Array(String)}",
                parameters={"ds": collection_dataset, "hashes": chunk},
            ).result_rows[0][0])
            client.command(
                "ALTER TABLE nlp_processed DELETE WHERE collection_dataset = {ds:String} "
                "AND file_hash IN {hashes:Array(String)}",
                parameters={"ds": collection_dataset, "hashes": chunk},
                settings=settings,
            )
            client.command(
                "ALTER TABLE entity_hit DELETE WHERE collection_dataset = {ds:String} "
                "AND file_hash IN {hashes:Array(String)}",
                parameters={"ds": collection_dataset, "hashes": chunk},
                settings=settings,
            )
    log.info(
        "[retry] cleared %d nlp_processed and %d entity_hit rows for %s",
        watermarks, hits, collection_dataset,
    )
    return watermarks, hits


def clear_regex_state(collectionname: str, collection_dataset: str, hashes) -> tuple[int, int]:
    """Delete regex scan watermarks and hits for `hashes` in that order.

    A scan watermark prevents the same rule set from reading a segment again. Deleting
    it before the hits leaves a segment eligible after an interrupted recovery.
    """
    from database.clickhouse import get_collection_client

    settings = {"mutations_sync": 2}
    watermarks = hits = 0
    with get_collection_client(collectionname) as client:
        for chunk in chunked(hashes):
            watermarks += int(client.query(
                "SELECT count() FROM regex_scanned WHERE collection_dataset = {ds:String} "
                "AND file_hash IN {hashes:Array(String)}",
                parameters={"ds": collection_dataset, "hashes": chunk},
            ).result_rows[0][0])
            hits += int(client.query(
                "SELECT count() FROM regex_entity_hit WHERE collection_dataset = {ds:String} "
                "AND file_hash IN {hashes:Array(String)}",
                parameters={"ds": collection_dataset, "hashes": chunk},
            ).result_rows[0][0])
            client.command(
                "ALTER TABLE regex_scanned DELETE WHERE collection_dataset = {ds:String} "
                "AND file_hash IN {hashes:Array(String)}",
                parameters={"ds": collection_dataset, "hashes": chunk},
                settings=settings,
            )
            client.command(
                "ALTER TABLE regex_entity_hit DELETE WHERE collection_dataset = {ds:String} "
                "AND file_hash IN {hashes:Array(String)}",
                parameters={"ds": collection_dataset, "hashes": chunk},
                settings=settings,
            )
    log.info(
        "[retry] cleared %d regex_scanned and %d regex_entity_hit rows for %s",
        watermarks, hits, collection_dataset,
    )
    return watermarks, hits


def reopen_plans(collectionname: str, collection_dataset: str, plan_hashes) -> int:
    """Delete the finished markers of `plan_hashes` so ``ExecutePlans`` runs them again."""
    from database.clickhouse import get_collection_client

    reopened = 0
    with get_collection_client(collectionname) as client:
        for chunk in chunked(plan_hashes):
            client.command(
                "ALTER TABLE processing_plan_finished DELETE "
                "WHERE collection_dataset = {ds:String} AND plan_hash IN {plans:Array(String)}",
                parameters={"ds": collection_dataset, "plans": chunk},
                settings={"mutations_sync": 2},
            )
            reopened += len(chunk)
    return reopened
