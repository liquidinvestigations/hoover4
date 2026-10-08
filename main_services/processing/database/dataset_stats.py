"""Cached statistics and processing state for each dataset.

The website reads ``dataset_stats`` for the storage landing pages and the admin
collection and dataset lists. This module computes one collection at a time and writes
one row for each registered dataset of that collection.

The numbers use the storage card definitions. ``document_count`` counts distinct blob
hashes, extracted files included. ``total_size_bytes`` adds one size for each distinct
blob hash, because ``blobs`` is a ReplacingMergeTree and an unmerged duplicate row would
count twice. ``indexed_count`` counts distinct file hashes in ``index_state``.

A dataset is ``processing`` while a live operation holds it under the lock rule of
``operations.lock_clause``: a dataset operation on the dataset, or a collection
operation on its collection. ``export_collection`` only reads the collection, so it
does not count. Every other dataset is ``done``, including a dataset whose last
operation failed.
"""

import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

PROCESSING = "processing"
DONE = "done"

#: Live kinds that do not change the collection.
READ_ONLY_KINDS = frozenset({"export_collection"})

COLUMNS = [
    "collectionname",
    "collection_dataset",
    "document_count",
    "total_size_bytes",
    "indexed_count",
    "error_count",
    "state",
    "computed_at",
]


def dataset_state(collection_dataset: str, live_operations: list[dict]) -> str:
    """``processing`` when one of ``live_operations`` holds the dataset, else ``done``.

    ``live_operations`` are the live rows of the dataset's collection.
    """
    for op in live_operations:
        if op["kind"] in READ_ONLY_KINDS:
            continue
        if op["target_kind"] == "collection" or op["collection_dataset"] == collection_dataset:
            return PROCESSING
    return DONE


#: Seconds one statistics query may run. ``finish_operation`` runs the refresh inside
#: activities with a two-minute limit, and three queries must fit in it. A refresh that
#: stops at this limit leaves the dataset row in ``processing``, and the next collector
#: pass writes it again (see ``collections_to_refresh``).
QUERY_TIME_LIMIT_S = 30


def _grouped(client, sql: str) -> dict[str, tuple]:
    result = client.query(sql, settings={"max_execution_time": QUERY_TIME_LIMIT_S})
    return {row[0]: tuple(row[1:]) for row in result.result_rows}


def compute_collection_stats(collectionname: str) -> list[dict]:
    """One statistics row for each registered dataset of ``collectionname``."""
    from .clickhouse import get_collection_client, get_global_client
    from .operations import open_operations_for_collection

    with get_global_client() as client:
        datasets = [
            row[0]
            for row in client.query(
                "SELECT collection_dataset FROM dataset FINAL "
                "WHERE collectionname = {c:String} AND is_deleted = 0",
                parameters={"c": collectionname},
            ).result_rows
        ]
    if not datasets:
        return []
    live = open_operations_for_collection(collectionname)

    with get_collection_client(collectionname) as client:
        sizes = _grouped(
            client,
            "SELECT collection_dataset, count(), sum(sz) FROM ("
            " SELECT collection_dataset, blob_hash, any(blob_size_bytes) AS sz"
            " FROM blobs GROUP BY collection_dataset, blob_hash"
            ") GROUP BY collection_dataset",
        )
        indexed = _grouped(
            client,
            "SELECT collection_dataset, uniqExact(file_hash) FROM index_state "
            "GROUP BY collection_dataset",
        )
        errors = _grouped(
            client,
            "SELECT collection_dataset, count() FROM processing_errors FINAL "
            "GROUP BY collection_dataset",
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = []
    for ds in datasets:
        documents, size = sizes.get(ds, (0, 0))
        rows.append({
            "collectionname": collectionname,
            "collection_dataset": ds,
            "document_count": int(documents or 0),
            "total_size_bytes": int(size or 0),
            "indexed_count": int(indexed.get(ds, (0,))[0] or 0),
            "error_count": int(errors.get(ds, (0,))[0] or 0),
            "state": dataset_state(ds, live),
            "computed_at": now,
        })
    return rows


def refresh_dataset_stats(collectionname: str) -> int:
    """Compute and store the statistics of every dataset in ``collectionname``.

    Returns the number of rows written.
    """
    from .clickhouse import get_global_client, insert_durable

    rows = compute_collection_stats(collectionname)
    if not rows:
        return 0
    with get_global_client() as client:
        insert_durable(
            client,
            "dataset_stats",
            [[row[c] for c in COLUMNS] for row in rows],
            column_names=COLUMNS,
        )
    return len(rows)


def refresh_dataset_states(collectionname: str) -> int:
    """Store the current state of each dataset with its stored numbers.

    It reads only the global database, so the single-slot admission activity can call
    it. A dataset with no statistics row is left for the next full refresh.
    Returns the number of rows written.
    """
    from .clickhouse import get_global_client, insert_durable
    from .operations import open_operations_for_collection

    with get_global_client() as client:
        result = client.query(
            "SELECT s.collectionname, s.collection_dataset, s.document_count, "
            "s.total_size_bytes, s.indexed_count, s.error_count "
            "FROM dataset_stats AS s FINAL "
            "WHERE s.collectionname = {c:String} AND s.collection_dataset IN "
            "(SELECT collection_dataset FROM dataset FINAL "
            " WHERE collectionname = {c:String} AND is_deleted = 0)",
            parameters={"c": collectionname},
        )
        stored = result.result_rows
    if not stored:
        return 0
    live = open_operations_for_collection(collectionname)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    data = [
        [*row, dataset_state(row[1], live), now]
        for row in stored
    ]
    with get_global_client() as client:
        insert_durable(client, "dataset_stats", data, column_names=COLUMNS)
    return len(data)


def refresh_dataset_states_logged(collectionname: str) -> None:
    """``refresh_dataset_states`` for a caller that must not fail on it."""
    if not collectionname:
        return
    try:
        refresh_dataset_states(collectionname)
    except Exception as exc:  # noqa: BLE001 - statistics must not block an operation
        log.warning("dataset state refresh failed for %s: %s", collectionname, exc)


def refresh_dataset_stats_logged(collectionname: str) -> None:
    """``refresh_dataset_stats`` for a caller that must not fail on it.

    An operation transition calls this. A failed refresh leaves the previous row, and
    the next ETA collector pass or operation transition writes a new one.
    """
    if not collectionname:
        return
    try:
        refresh_dataset_stats(collectionname)
    except Exception as exc:  # noqa: BLE001 - statistics must not block an operation
        log.warning("dataset statistics refresh failed for %s: %s", collectionname, exc)


def collections_to_refresh() -> list[str]:
    """Collections whose stored statistics a collector pass must write again.

    A collection qualifies when a registered dataset has no statistics row, which covers
    a new deployment and a new dataset. It also qualifies when a stored row says
    `processing`: a live operation then refreshes it anyway, and without one the row is
    left over from a refresh that failed when the operation ended.
    """
    from .clickhouse import get_global_client

    with get_global_client() as client:
        rows = client.query(
            "SELECT DISTINCT d.collectionname FROM dataset AS d FINAL "
            "WHERE d.is_deleted = 0 AND (d.collection_dataset NOT IN "
            "(SELECT collection_dataset FROM dataset_stats) "
            "OR d.collection_dataset IN "
            "(SELECT collection_dataset FROM dataset_stats FINAL WHERE state = 'processing')) "
            "ORDER BY d.collectionname"
        ).result_rows
    return [row[0] for row in rows if row[0]]
