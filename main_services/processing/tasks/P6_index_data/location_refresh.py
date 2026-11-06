"""Select documents whose indexed folder, language or OCR attributes are stale.

A content hash that gains another path does not create a processing plan. The
page writer still has to refresh that document's folder attributes, or a folder
filter keeps answering from the previous locations. A change to the document
language rule has the same effect on the language filter, and new OCR detection
rows have the same effect on the OCR filters. This module names those documents
and rewrites their page rows. It does not extract, OCR, or embed.
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
    """Hashes that have an indexed term-id set and whose current set differs.

    The sets are folder closures or languages. A hash with no indexed row is not
    selected. It has never been indexed and needs a processing plan, not a refresh.
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
            "WHERE collection_dataset = {cd:String} AND file_hash IN ("
            "SELECT hash FROM vfs_files FINAL WHERE collection_dataset = {cd:String} AND is_deleted = 0)",
            parameters={"cd": collection_dataset},
        ).result_rows
    return {file_hash: shard_name for file_hash, shard_name in rows}


def load_expected_language_ids(
    collectionname: str, collection_dataset: str
) -> dict[str, frozenset[int]]:
    """Current `language` term ids per hash, by the rule the page writer applies."""
    from database.clickhouse import get_collection_client

    from .activities import document_languages
    from .string_term_encodings import get_string_term_ids_by_field

    with get_collection_client(collectionname) as client:
        languages = document_languages(client, collection_dataset)
    codes = {code for values in languages.values() for code in values}
    ids = get_string_term_ids_by_field(
        collectionname, collection_dataset, {"language": codes}
    )["language"] if codes else {}
    return {
        file_hash: frozenset(ids[code] for code in values)
        for file_hash, values in languages.items()
    }


def load_expected_ocr_ids(
    collectionname: str, collection_dataset: str
) -> tuple[dict[str, frozenset[int]], dict[str, frozenset[int]]]:
    """Current `ocr_script` and `ocr_language` term ids per hash."""
    from database.clickhouse import get_collection_client

    from .activities import document_ocr_attributes
    from .string_term_encodings import get_string_term_ids_by_field

    with get_collection_client(collectionname) as client:
        scripts, languages = document_ocr_attributes(client, collection_dataset)
    fields = {"ocr_script": {name for names in scripts.values() for name in names},
              "ocr_language": {code for codes in languages.values() for code in codes}}
    ids = get_string_term_ids_by_field(collectionname, collection_dataset, fields)
    return ({h: frozenset(ids["ocr_script"][name] for name in names) for h, names in scripts.items()},
            {h: frozenset(ids["ocr_language"][code] for code in codes) for h, codes in languages.items()})


def load_indexed_ids(
    collectionname: str, collection_dataset: str, assignments: dict[str, str]
) -> tuple[dict[str, frozenset[int]], ...]:
    """Read every indexed row and mark inconsistent or missing document attributes."""
    from database.manticore import get_manticore_client, shard_table_from_name, table_has_column

    from .activities import FILENAME_EXTRACTED_BY, document_ocr_presence

    by_shard: dict[str, list[str]] = {}
    for file_hash, shard_name in assignments.items():
        by_shard.setdefault(shard_name, []).append(file_hash)

    paths: dict[str, frozenset[int]] = {}
    languages: dict[str, frozenset[int]] = {}
    ocr_scripts: dict[str, frozenset[int]] = {}
    ocr_languages: dict[str, frozenset[int]] = {}
    with get_manticore_client() as cnx:
        cur = cnx.cursor()
        for shard_name, hashes in by_shard.items():
            table = shard_table_from_name(shard_name)
            has_ocr = table_has_column(table, "ocr_script")
            has_presence = table_has_column(table, "has_ocr_output")
            columns = "id, file_hash, extracted_by, page_id, file_paths, language" + (", ocr_script, ocr_language" if has_ocr else "")
            columns += ", has_ocr_output" if has_presence else ""
            filenames, incomplete = set(), set()
            for i in range(0, len(hashes), PATHS_SCAN_PAGE):
                chunk = hashes[i:i + PATHS_SCAN_PAGE]
                presence = {}
                if has_presence:
                    from database.clickhouse import get_collection_client
                    with get_collection_client(collectionname) as client:
                        presence = document_ocr_presence(client, collection_dataset, chunk)
                placeholders = ",".join(["%s"] * len(chunk))
                expected_pages = load_expected_page_keys(collectionname, collection_dataset, chunk)
                observed_pages = {}
                after = 0
                while True:
                    _heartbeat("Reading indexed document attributes")
                    cur.execute(
                        f"SELECT {columns} FROM {table} WHERE collection_dataset = %s "
                        f"AND file_hash IN ({placeholders}) AND id > %s ORDER BY id ASC "
                        f"LIMIT {PATHS_SCAN_PAGE} OPTION max_matches={PATHS_SCAN_PAGE}",
                        (collection_dataset, *chunk, after))
                    rows = cur.fetchall() or []
                    if not rows:
                        break
                    for row in rows:
                        after = int(row[0])
                        file_hash = row[1]
                        if has_presence and int(row[-1]) != presence.get(file_hash, 0):
                            incomplete.add(file_hash)
                        if row[2] == FILENAME_EXTRACTED_BY:
                            filenames.add(file_hash)
                        else:
                            observed_pages.setdefault(file_hash, set()).add((row[2], int(row[3])))
                        targets = [(paths, row[4]), (languages, row[5])]
                        if has_ocr:
                            targets.extend([(ocr_scripts, row[6]), (ocr_languages, row[7])])
                        for target, value in targets:
                            value = parse_mva_ids(value)
                            if file_hash in target and target[file_hash] != value:
                                target[file_hash] = frozenset({-1})
                            else:
                                target[file_hash] = value
                    if len(rows) < PATHS_SCAN_PAGE:
                        break
                incomplete.update(file_hash for file_hash in chunk
                                  if observed_pages.get(file_hash, set()) != expected_pages.get(file_hash, set()))
            for file_hash in hashes:
                if file_hash not in filenames or file_hash in incomplete:
                    for target in (paths, languages, ocr_scripts, ocr_languages):
                        target[file_hash] = frozenset({-1})
    return paths, languages, ocr_scripts, ocr_languages


def load_expected_page_keys(collectionname: str, collection_dataset: str, hashes: list[str]) -> dict:
    """Read every current text-page identity that the page writer must publish."""
    from database.clickhouse import get_collection_client
    with get_collection_client(collectionname) as client:
        rows = client.query(
            "SELECT DISTINCT file_hash, extracted_by, page_id FROM text_content "
            "WHERE collection_dataset = {cd:String} AND file_hash IN {hashes:Array(String)}",
            parameters={"cd": collection_dataset, "hashes": hashes}).result_rows
    expected = {}
    for file_hash, source, page in rows:
        expected.setdefault(file_hash, set()).add((source, int(page)))
    return expected


def list_stale_location_hashes(
    collectionname: str, collection_dataset: str, item_hashes: list[str] | None = None
) -> tuple[list[str], int, str]:
    """Hashes whose indexed folder closure, languages or OCR values differ from current values.

    Returns the selected hashes, the indexed document count, and the mechanism
    name. A supplied `item_hashes` list is intersected with that stale set when
    it is non-empty; an empty list means "select the stale set".
    """
    expected_paths = load_expected_path_ids(collectionname, collection_dataset)
    assignments = load_shard_assignments(collectionname, collection_dataset)
    indexed_paths, indexed_languages, indexed_scripts, indexed_ocr_languages = load_indexed_ids(
        collectionname, collection_dataset, assignments
    )
    expected_languages = {
        file_hash: frozenset() for file_hash in indexed_languages
    } | load_expected_language_ids(collectionname, collection_dataset)
    scripts, ocr_languages = load_expected_ocr_ids(collectionname, collection_dataset)
    expected_scripts = {file_hash: frozenset() for file_hash in indexed_scripts} | scripts
    expected_ocr_languages = {file_hash: frozenset() for file_hash in indexed_ocr_languages} | ocr_languages
    stale = sorted(
        set(hashes_with_stale_locations(expected_paths, indexed_paths))
        | set(hashes_with_stale_locations(expected_languages, indexed_languages))
        | set(hashes_with_stale_locations(expected_scripts, indexed_scripts))
        | set(hashes_with_stale_locations(expected_ocr_languages, indexed_ocr_languages))
    )
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
