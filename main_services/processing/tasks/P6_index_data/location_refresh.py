"""Select documents whose indexed folder closure does not match current locations.

A content hash that gains another path does not create a processing plan. The
page writer still has to refresh that document's folder attributes, or a folder
filter keeps answering from the previous locations. This module names those
documents and rewrites their page rows. It does not extract, OCR, or embed.
"""

from __future__ import annotations

import logging
from typing import Iterable

from .string_term_encodings import hash_string_to_uint63
from .vfs_nodes import ancestor_node_keys

log = logging.getLogger(__name__)

#: Sentinel `plan_hash` for location-only page rewrites. It is a log label only.
#: These rewrites do not create plans and do not record `index_state`.
LOCATION_REFRESH_PLAN_HASH = "location-refresh"

#: Same chunk size `IndexDatasetPlan` uses for `index_text_pages`.
INDEXING_CHUNK_SIZE = 100

#: Rows per Manticore keyset page when reading indexed `file_paths`.
PATHS_SCAN_PAGE = 1000

MECHANISM_AFFECTED = "affected-documents"
MECHANISM_NONE = "none"


def parse_mva_ids(value) -> frozenset[int]:
    """Parse a Manticore MVA attribute into a set of term ids."""
    if value is None or value == "" or value == "()":
        return frozenset()
    if isinstance(value, (list, tuple, set, frozenset)):
        return frozenset(int(x) for x in value)
    text = str(value).strip()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1]
    if not text:
        return frozenset()
    ids = []
    for part in text.split(","):
        piece = part.strip()
        if piece:
            ids.append(int(piece))
    return frozenset(ids)


def expected_vfs_node_ids(
    collection_dataset: str,
    locations: list[tuple[str, str]],
    container_parents: dict[str, list[tuple[str, str]]],
) -> frozenset[int]:
    """The `vfs_node` term ids `document_metadata` would write for these locations."""
    keys, _truncated = ancestor_node_keys(
        collection_dataset, locations, container_parents
    )
    return frozenset(hash_string_to_uint63(key) for key in keys)


def hashes_with_stale_locations(
    expected_by_hash: dict[str, frozenset[int]],
    indexed_by_hash: dict[str, frozenset[int]],
) -> list[str]:
    """Hashes that have an indexed closure and whose current closure differs.

    A hash with no indexed row is not selected. It has never been indexed and
    needs a processing plan, not a location refresh.
    """
    stale = []
    for file_hash, expected in expected_by_hash.items():
        indexed = indexed_by_hash.get(file_hash)
        if indexed is None:
            continue
        if indexed != expected:
            stale.append(file_hash)
    return sorted(stale)


def refresh_scope(
    affected: Iterable[str], indexed_count: int
) -> tuple[list[str], str]:
    """Choose which documents to rewrite.

    Affected-document refresh rewrites page rows for `len(affected)` hashes.
    A collection-wide rebuild drops every shard table and rewrites pages and
    vectors for `indexed_count` hashes. Location-only change is a closure
    mismatch, so the affected set is the mechanism. An empty affected set
    selects nothing.
    """
    selected = list(affected)
    if not selected:
        return [], MECHANISM_NONE
    if indexed_count > 0 and len(selected) > indexed_count:
        raise ValueError(
            "affected set is larger than the indexed document count: "
            f"{len(selected)} > {indexed_count}"
        )
    log.info(
        "location refresh scope: %s hashes out of %d indexed documents; "
        "collection-wide rebuild not selected",
        len(selected), indexed_count,
    )
    return selected, MECHANISM_AFFECTED


def load_expected_path_ids(
    collectionname: str, collection_dataset: str
) -> dict[str, frozenset[int]]:
    """Current ancestor-closure term ids per hash, from ClickHouse VFS tables."""
    from database.clickhouse import get_collection_client

    from .vfs_nodes import container_parents_from_nodes

    with get_collection_client(collectionname) as client:
        vfs_rows = client.query_arrow("""
            SELECT hash, container_hash, path
            FROM vfs_files FINAL
            WHERE collection_dataset = {cd:String}
        """, {"cd": collection_dataset}).to_pylist()
        node_rows = client.query_arrow("""
            SELECT container_hash, path, kind, file_hash
            FROM vfs_nodes FINAL
            WHERE collection_dataset = {cd:String}
        """, {"cd": collection_dataset}).to_pylist()

    parents = container_parents_from_nodes(node_rows)
    locations_by_hash: dict[str, list[tuple[str, str]]] = {}
    for row in vfs_rows:
        locations_by_hash.setdefault(row["hash"], []).append(
            (row["container_hash"] or "", row["path"])
        )
    return {
        file_hash: expected_vfs_node_ids(
            collection_dataset, locations, parents
        )
        for file_hash, locations in locations_by_hash.items()
    }


def load_shard_assignments(
    collectionname: str, collection_dataset: str
) -> dict[str, str]:
    """`file_hash` to shard name for documents that already have an index row."""
    from database.clickhouse import get_collection_client

    with get_collection_client(collectionname) as client:
        rows = client.query(
            "SELECT file_hash, shard_name FROM manticore_shard_assignments FINAL "
            "WHERE collection_dataset = {cd:String}",
            parameters={"cd": collection_dataset},
        ).result_rows
    return {file_hash: shard_name for file_hash, shard_name in rows}


def load_indexed_path_ids(
    collectionname: str, collection_dataset: str, assignments: dict[str, str]
) -> dict[str, frozenset[int]]:
    """Indexed `file_paths` per hash, read from each assigned pages table.

    Reads the `filename_index` row. That row is identified by `extracted_by`,
    because a bound `page_id = -1` does not match the unsigned value Manticore
    stores for that sentinel.
    """
    from database.manticore import get_manticore_client, shard_table_from_name

    from .activities import FILENAME_EXTRACTED_BY

    by_shard: dict[str, list[str]] = {}
    for file_hash, shard_name in assignments.items():
        by_shard.setdefault(shard_name, []).append(file_hash)

    indexed: dict[str, frozenset[int]] = {}
    with get_manticore_client() as cnx:
        cur = cnx.cursor()
        for shard_name, hashes in by_shard.items():
            table = shard_table_from_name(shard_name)
            for i in range(0, len(hashes), PATHS_SCAN_PAGE):
                chunk = hashes[i:i + PATHS_SCAN_PAGE]
                placeholders = ",".join(["%s"] * len(chunk))
                # Filter by extractor, not `page_id = -1`. The filename row
                # stores `page_id` as unsigned 4294967295, and a bound `-1`
                # matches no row through this client.
                cur.execute(
                    f"SELECT file_hash, file_paths FROM {table} "
                    "WHERE collection_dataset = %s AND extracted_by = %s "
                    f"AND file_hash IN ({placeholders}) "
                    f"LIMIT {len(chunk)} OPTION max_matches={len(chunk)}",
                    (collection_dataset, FILENAME_EXTRACTED_BY, *chunk),
                )
                for file_hash, file_paths in cur.fetchall() or []:
                    indexed[file_hash] = parse_mva_ids(file_paths)
    return indexed


def list_stale_location_hashes(
    collectionname: str, collection_dataset: str, item_hashes: list[str] | None = None
) -> tuple[list[str], int, str]:
    """Hashes whose indexed folder closure is behind `vfs_files`.

    Returns the selected hashes, the indexed document count, and the mechanism
    name. A supplied `item_hashes` list is intersected with that stale set when
    it is non-empty; an empty list means "select the stale set".
    """
    expected = load_expected_path_ids(collectionname, collection_dataset)
    assignments = load_shard_assignments(collectionname, collection_dataset)
    indexed = load_indexed_path_ids(collectionname, collection_dataset, assignments)
    stale = hashes_with_stale_locations(expected, indexed)
    if item_hashes:
        wanted = set(item_hashes)
        stale = [h for h in stale if h in wanted]
    selected, mechanism = refresh_scope(stale, len(assignments))
    return selected, len(assignments), mechanism


def _heartbeat(message: str) -> None:
    """Heartbeat when running as an activity. No-op in an in-process test."""
    from temporalio import activity

    try:
        activity.info()
    except RuntimeError:
        return
    activity.heartbeat(message)


def rewrite_page_locations(
    collectionname: str, collection_dataset: str, hashes: list[str],
    assignments: dict[str, str],
) -> list[str]:
    """Run `index_text_pages` for the assigned hashes. Does not rewrite vectors."""
    from .activities import index_text_pages
    from .params import IndexShardParams

    by_shard: dict[str, list[str]] = {}
    for file_hash in hashes:
        shard_name = assignments.get(file_hash)
        if not shard_name:
            continue
        by_shard.setdefault(shard_name, []).append(file_hash)

    written: list[str] = []
    for shard_name, shard_hashes in by_shard.items():
        for i in range(0, len(shard_hashes), INDEXING_CHUNK_SIZE):
            chunk = shard_hashes[i:i + INDEXING_CHUNK_SIZE]
            _heartbeat(f"location refresh {collection_dataset} {shard_name} {i}")
            written.extend(index_text_pages(IndexShardParams(
                collectionname=collectionname,
                collection_dataset=collection_dataset,
                plan_hash=LOCATION_REFRESH_PLAN_HASH,
                shard_name=shard_name,
                hashes=chunk,
            )))
    return sorted(set(written))
