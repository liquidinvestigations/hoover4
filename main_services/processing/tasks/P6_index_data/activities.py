"""Indexing activities for text content, metadata and chunk vectors.

Pure I/O against ClickHouse and Manticore: the NER/entity extraction lives in
the P4_extract_entities stage, which runs strictly before this one. This stage
reads the ``entity_hit`` rows and ``nlp_processed`` watermarks P4 wrote, and the
``text_chunk_vectors`` rows P5 wrote.

All three writers target the shard tables assigned by the shard planner
(``shard_planner.plan_shards``) and use ``REPLACE INTO`` with deterministic row
ids, so re-indexing a document overwrites its rows in place instead of
duplicating them:

* pages id: ``hash_string_to_uint63(f"{collection_dataset}|{file_hash}|{extracted_by}|{page_id}")``
* metadata id: ``hash_string_to_uint63(f"{collection_dataset}|{file_hash}")``
* vectors id: ``hash_string_to_uint63(f"{collection_dataset}|{file_hash}|{extracted_by}|{page_id}|{chunk_index}|{embedding_model}")``
"""

from typing import List
from temporalio import activity
import logging
import os
from .string_term_encodings import get_string_term_ids, hash_string_to_uint63
from tasks.plan_utils import clean_text
from database.clickhouse import get_collection_client
from database.manticore import manticore_execute, shard_tables_from_name
from .params import BuildVfsNodesParams, IndexShardParams
from tasks.heartbeat import with_heartbeat
log = logging.getLogger(__name__)


INDEX_ROW_CHUNK_SIZE = 512


def union_entities_by_segment(entity_rows):
    """Group `entity_hit` rows into `{(hash, extracted_by, page_id): {type: [values]}}`.

    **Union across NER providers, not last-wins.** `entity_hit` is keyed by
    `(…, page_id, nlp_model, entity_type)`, so one segment has one row per provider per
    type. Assigning instead of merging keeps whichever row the query happened to return
    last and silently discards the other provider's entities -- no error, no warning,
    just fewer facets, in a stage whose output nobody diffs.

    Values are deduplicated (order-preserving) because the providers agree on most
    entities, and the same term id twice in a Manticore MVA inflates every facet count.

    Extracted from the activity so it can be tested without a live ClickHouse: this is
    the exact shape of bug that only shows up as "the numbers look a bit low".
    """
    entities_by_segment = {}
    for row in entity_rows:
        key = (row['file_hash'], row['extracted_by'], row['page_id'])
        bucket = entities_by_segment.setdefault(key, {})
        existing = bucket.get(row['entity_type'])
        if existing is None:
            bucket[row['entity_type']] = list(dict.fromkeys(row['entity_values']))
        else:
            seen = set(existing)
            existing.extend(v for v in row['entity_values'] if v not in seen and not seen.add(v))
    return entities_by_segment


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def pages_replace_sql(pages_table: str, row: dict) -> str:
    """REPLACE INTO statement for one pages row.

    The four NER MVA values are interpolated as Manticore tuples (they cannot be
    bound parameters); ``repr_manticore_tuple([])`` renders the empty MVA as ``()``.
    Everything else is a bound parameter. ``pages_table`` comes from
    ``shard_tables_from_name`` (validated).
    """
    return f"""REPLACE INTO {pages_table} (
                        id,
                        collection_dataset,
                        file_hash,
                        extracted_by,
                        page_id,
                        page_text,
                        ner_per,
                        ner_org,
                        ner_loc,
                        ner_misc
                    ) VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        {row.get('ner_per') or '()'},
                        {row.get('ner_org') or '()'},
                        {row.get('ner_loc') or '()'},
                        {row.get('ner_misc') or '()'}
                    )"""


def meta_replace_sql(meta_table: str, row: dict) -> str:
    """REPLACE INTO statement for one metadata row.

    Every MVA is interpolated as a Manticore tuple (they cannot be bound parameters);
    every scalar is a bound parameter, in the order :func:`meta_replace_params` returns
    them. ``meta_table`` comes from ``shard_tables_from_name`` (validated).

    The two old text columns (``filenames``, ``metadata_values``) are gone — see
    ``manticore.meta_table_ddl``.
    """
    return f"""REPLACE INTO {meta_table} (
                        id,
                        collection_dataset,
                        file_hash,
                        date_min,
                        date_max,
                        file_size_bytes,
                        struct_flags,
                        primary_filename,
                        file_types,
                        file_mime_types,
                        file_extensions,
                        file_paths,
                        dates,
                        email_from,
                        email_to
                    ) VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        {row['file_types']},
                        {row['file_mime_types']},
                        {row['file_extensions']},
                        {row['file_paths']},
                        {row['dates']},
                        {row['email_from']},
                        {row['email_to']}
                    )"""


def meta_replace_params(collection_dataset: str, row: dict) -> tuple:
    """Bound parameters for :func:`meta_replace_sql`, in its column order."""
    return (
        metadata_row_id(collection_dataset, row['file_hash']),
        row['collection_dataset'],
        row['file_hash'],
        row['date_min'],
        row['date_max'],
        row['file_size_bytes'],
        row['struct_flags'],
        row['primary_filename'],
    )


def pages_row_id(collection_dataset: str, file_hash: str, extracted_by: str, page_id: int) -> int:
    """Deterministic Manticore row id for one pages row. Enables REPLACE INTO."""
    return hash_string_to_uint63(f"{collection_dataset}|{file_hash}|{extracted_by}|{page_id}")


def metadata_row_id(collection_dataset: str, file_hash: str) -> int:
    """Deterministic Manticore row id for one metadata row. Enables REPLACE INTO."""
    return hash_string_to_uint63(f"{collection_dataset}|{file_hash}")


@activity.defn
@with_heartbeat
def index_text_pages(params: IndexShardParams) -> list[str]:
    """Index the chunk's text segments into the shard's pages table.

    Returns the file_hashes actually written (committed). ``IndexDatasetPlan``
    records exactly these in ``index_state`` — a document whose writer failed
    must never be counted by the shard ledger.
    """
    collection_dataset: str = params.collection_dataset
    item_hashes: list[str] = params.hashes
    plan_hash: str = params.plan_hash
    pages_table, _ = shard_tables_from_name(params.shard_name)
    from database.manticore import get_manticore_client
    with get_collection_client(params.collectionname) as client:
        # FINAL: `text_content` is a ReplacingMergeTree, so a re-parse leaves two rows for
        # the same segment until the background merge runs. The Manticore row id is
        # deterministic, so the duplicate REPLACEs into the same row rather than corrupting
        # the index — but it doubles the work of the whole activity, and the page text is
        # then non-deterministically whichever copy came back last.
        text_content = client.query_arrow("""
            SELECT collection_dataset, file_hash, extracted_by, page_id, text
            FROM text_content FINAL
            WHERE collection_dataset = {collection_dataset:String}
            AND file_hash IN {item_hashes:Array(String)}
        """, {
            "collection_dataset": collection_dataset,
            "item_hashes": item_hashes
        }).to_pylist()
        if not text_content:
            return []
        entity_rows = client.query_arrow("""
            SELECT file_hash, extracted_by, page_id, entity_type, entity_values
            FROM entity_hit
            WHERE collection_dataset = {collection_dataset:String}
            AND file_hash IN {item_hashes:Array(String)}
        """, {
            "collection_dataset": collection_dataset,
            "item_hashes": item_hashes
        }).to_pylist()
        processed_rows = client.query_arrow("""
            SELECT file_hash, extracted_by, page_id
            FROM nlp_processed
            WHERE collection_dataset = {collection_dataset:String}
            AND file_hash IN {item_hashes:Array(String)}
        """, {
            "collection_dataset": collection_dataset,
            "item_hashes": item_hashes
        }).to_pylist()

    processed_keys = {(row['file_hash'], row['extracted_by'], row['page_id']) for row in processed_rows}

    entities_by_segment = union_entities_by_segment(entity_rows)
    ner_values = set()
    for row in entity_rows:
        ner_values.update(row['entity_values'])

    # Cache hits: the NLP stage already populated the 'ner' term dictionary
    # with these values (ids are content-derived via hash_string_to_uint63).
    ner_ids = get_string_term_ids(params.collectionname, collection_dataset, 'ner', ner_values)

    for row in text_content:
        key = (row['file_hash'], row['extracted_by'], row['page_id'])
        if key not in processed_keys:
            # Running out of order: the NLP stage has no watermark for this
            # segment (and will have recorded its own error). A missing entity
            # list must not block search - index with empty entity MVAs.
            log.warning(
                f"{collection_dataset} (plan {plan_hash[:8]}): no nlp_processed watermark for "
                f"{row['file_hash']}/{row['extracted_by']}/{row['page_id']}; indexing with empty entities"
            )
            segment_entities = {}
        else:
            segment_entities = entities_by_segment.get(key, {})
        for entity_type in ("PER", "ORG", "LOC", "MISC"):
            field_name = f"ner_{entity_type.lower()}"
            field_values = [ner_ids[value] for value in segment_entities.get(entity_type, [])]
            row[field_name] = repr_manticore_tuple(field_values)

    with get_manticore_client() as client:
        for chunk in chunks(text_content, INDEX_ROW_CHUNK_SIZE):
            for row in chunk:
                manticore_execute(
                    client,
                    pages_replace_sql(pages_table, row),
                    (
                        pages_row_id(collection_dataset, row['file_hash'], row['extracted_by'], row['page_id']),
                        row['collection_dataset'],
                        row['file_hash'],
                        row['extracted_by'],
                        row['page_id'],
                        clean_text(row['text'])
                    )
                )
            log.info(f"{collection_dataset} (plan {plan_hash[:8]}): Indexed {len(chunk)} text content into {pages_table}")
            client.commit()
        client.commit()
    return sorted({row['file_hash'] for row in text_content})


def primary_filename(basenames) -> str:
    """The result-card title and the "sort by name" key.

    First of the document's distinct basenames under a case-folded ordering: one document
    can sit at several paths, and the title must depend neither on which row the query
    happened to return first nor on how a twin path spells its case. NFKC so that a
    full-width or decomposed filename sorts next to its ASCII twin rather than after every
    other name.

    The name keeps its ORIGINAL CASE, because this string is what the result card and the
    file-browser link display and `/README` is not called `readme`. Nothing downstream
    needs it folded: filename MATCHING goes through the full-text ``filename_index`` pages
    row, which is case-insensitive by tokenisation, and the name SORT is case-insensitive
    because Manticore compares string attributes under ``libc_ci``.
    """
    import unicodedata
    normalised = sorted(
        (unicodedata.normalize("NFKC", name) for name in basenames if name),
        key=lambda name: (name.casefold(), name),
    )
    return normalised[0] if normalised else ""


@activity.defn
@with_heartbeat
def index_metadata(params: IndexShardParams) -> list[str]:
    """Index the chunk's metadata rows into the shard's meta table.

    One ClickHouse read per source, all FINAL, joined in Python rather than in one
    monster JOIN: the sources have wildly different cardinalities (one `file_types` row
    per document, N `vfs_files` rows, M `document_dates` rows, K `email_addresses` rows)
    and joining them server-side multiplies the rows before it groups them.

    Returns the file_hashes actually written (committed), for ``index_state``
    (see ``index_text_pages``).
    """
    from database.manticore import DATE_UNKNOWN, SIZE_UNKNOWN, get_manticore_client
    from .vfs_nodes import (
        STRUCT_FLAG_EMAIL_HAS_ATTACHMENTS,
        STRUCT_FLAG_TRUNCATED_ANCESTRY,
        ancestor_node_keys,
        container_parents_from_nodes,
    )

    collection_dataset: str = params.collection_dataset
    plan_hash: str = params.plan_hash
    item_hashes: list[str] = params.hashes
    _, meta_table = shard_tables_from_name(params.shard_name)

    with get_collection_client(params.collectionname) as client:
        raw_metadatas = client.query_arrow("""
            SELECT hash,
                    arrayDistinct(arrayFlatten(groupArray(file_type))) as file_types,
                    arrayDistinct(arrayFlatten(groupArray(mime_type))) as mime_types,
                    arrayDistinct(arrayFlatten(groupArray(extensions))) as extensions
            FROM file_types FINAL
            WHERE collection_dataset = {collection_dataset:String}
            AND hash IN {item_hashes:Array(String)}
            GROUP BY hash
        """, {
            "collection_dataset": collection_dataset,
            "item_hashes": item_hashes
        }).to_pylist()

        vfs_rows = client.query_arrow("""
            SELECT hash, container_hash, path, file_size_bytes
            FROM vfs_files FINAL
            WHERE collection_dataset = {collection_dataset:String}
            AND hash IN {item_hashes:Array(String)}
        """, {
            "collection_dataset": collection_dataset,
            "item_hashes": item_hashes
        }).to_pylist()

        date_rows = client.query_arrow("""
            SELECT hash, date
            FROM document_dates FINAL
            WHERE collection_dataset = {collection_dataset:String}
            AND hash IN {item_hashes:Array(String)}
        """, {
            "collection_dataset": collection_dataset,
            "item_hashes": item_hashes
        }).to_pylist()

        address_rows = client.query_arrow("""
            SELECT email_hash, role, address
            FROM email_addresses FINAL
            WHERE collection_dataset = {collection_dataset:String}
            AND email_hash IN {item_hashes:Array(String)}
        """, {
            "collection_dataset": collection_dataset,
            "item_hashes": item_hashes
        }).to_pylist()

        # Which of these documents are emails, and which hashes are containers at all.
        # `email_has_attachments` is "is an email AND is a container", so both are needed.
        email_hashes = {
            row['email_hash'] for row in client.query_arrow("""
                SELECT email_hash FROM emails FINAL
                WHERE collection_dataset = {collection_dataset:String}
                AND email_hash IN {item_hashes:Array(String)}
            """, {
                "collection_dataset": collection_dataset,
                "item_hashes": item_hashes
            }).to_pylist()
        }
        container_hashes_in_use = {
            row['container_hash'] for row in client.query_arrow("""
                SELECT DISTINCT container_hash FROM vfs_files FINAL
                WHERE collection_dataset = {collection_dataset:String}
                AND container_hash IN {item_hashes:Array(String)}
            """, {
                "collection_dataset": collection_dataset,
                "item_hashes": item_hashes
            }).to_pylist()
        }

        # The whole dataset's node table, for the multi-parent closure. It is one small
        # row per node and the closure needs the containers this chunk's documents are
        # NOT in, so it cannot be narrowed to the chunk.
        node_rows = client.query_arrow("""
            SELECT container_hash, path, kind, file_hash
            FROM vfs_nodes FINAL
            WHERE collection_dataset = {collection_dataset:String}
        """, {"collection_dataset": collection_dataset}).to_pylist()

    container_parents = container_parents_from_nodes(node_rows)

    vfs_by_hash: dict[str, list[dict]] = {}
    for row in vfs_rows:
        vfs_by_hash.setdefault(row['hash'], []).append(row)
    dates_by_hash: dict[str, set[int]] = {}
    for row in date_rows:
        dates_by_hash.setdefault(row['hash'], set()).add(int(row['date']))
    from_by_hash: dict[str, set[str]] = {}
    to_by_hash: dict[str, set[str]] = {}
    for row in address_rows:
        bucket = from_by_hash if row['role'] == 'from' else to_by_hash
        bucket.setdefault(row['email_hash'], set()).add(row['address'])

    items = []
    all_filetypes: set[str] = set()
    all_mime_types: set[str] = set()
    all_extensions: set[str] = set()
    all_node_keys: set[str] = set()
    all_addresses: set[str] = set()
    for item in raw_metadatas:
        file_hash = item['hash']
        rows = vfs_by_hash.get(file_hash, [])
        node_keys, truncated = ancestor_node_keys(
            collection_dataset,
            [(row['container_hash'] or '', row['path']) for row in rows],
            container_parents,
        )
        if truncated:
            log.warning(
                "%s (plan %s): ancestor closure truncated for %s; struct_flags records it",
                collection_dataset, plan_hash[:8], file_hash,
            )
        addresses = from_by_hash.get(file_hash, set()) | to_by_hash.get(file_hash, set())
        items.append((item, rows, node_keys, truncated))
        all_filetypes.update(item['file_types'])
        all_mime_types.update(item['mime_types'])
        all_extensions.update(item['extensions'])
        all_node_keys.update(node_keys)
        all_addresses.update(addresses)

    filetype_ids = get_string_term_ids(params.collectionname, collection_dataset, 'filetype', all_filetypes)
    mime_type_ids = get_string_term_ids(params.collectionname, collection_dataset, 'mime_type', all_mime_types)
    extension_ids = get_string_term_ids(params.collectionname, collection_dataset, 'extension', all_extensions)
    # `vfs_node`, not the old `parent_paths`: the term VALUE embeds collection_dataset
    # and container_hash, so the id cannot collide across datasets or archives.
    node_key_ids = get_string_term_ids(params.collectionname, collection_dataset, 'vfs_node', all_node_keys)
    address_ids = get_string_term_ids(params.collectionname, collection_dataset, 'email_address', all_addresses)

    search_rows = []
    for item, rows, node_keys, truncated in items:
        file_hash = item['hash']
        dates = sorted(dates_by_hash.get(file_hash, ()))
        # `max` over the paths is defensive: they are the same content so the sizes
        # agree, but a stale row must not shrink the document.
        sizes = [int(row['file_size_bytes']) for row in rows if row['file_size_bytes'] is not None]
        struct_flags = 0
        if truncated:
            struct_flags |= STRUCT_FLAG_TRUNCATED_ANCESTRY
        if file_hash in email_hashes and file_hash in container_hashes_in_use:
            struct_flags |= STRUCT_FLAG_EMAIL_HAS_ATTACHMENTS
        search_rows.append({
            "collection_dataset": collection_dataset,
            "file_hash": file_hash,
            "file_types": repr_manticore_tuple([filetype_ids[ft] for ft in item['file_types']]),
            "file_mime_types": repr_manticore_tuple([mime_type_ids[mt] for mt in item['mime_types']]),
            "file_extensions": repr_manticore_tuple([extension_ids[ext] for ext in item['extensions']]),
            "file_paths": repr_manticore_tuple(sorted(node_key_ids[k] for k in node_keys)),
            "dates": repr_manticore_tuple(dates),
            "date_min": dates[0] if dates else DATE_UNKNOWN,
            "date_max": dates[-1] if dates else DATE_UNKNOWN,
            "file_size_bytes": max(sizes) if sizes else SIZE_UNKNOWN,
            "struct_flags": struct_flags,
            "primary_filename": primary_filename(
                {os.path.basename(row['path']) for row in rows}
            ),
            "email_from": repr_manticore_tuple(
                sorted(address_ids[a] for a in from_by_hash.get(file_hash, ()))
            ),
            "email_to": repr_manticore_tuple(
                sorted(address_ids[a] for a in to_by_hash.get(file_hash, ()))
            ),
        })

    with get_manticore_client() as client:
        for chunk in chunks(search_rows, INDEX_ROW_CHUNK_SIZE):
            for row in chunk:
                manticore_execute(
                    client,
                    meta_replace_sql(meta_table, row),
                    meta_replace_params(collection_dataset, row),
                )
            log.info(f"{collection_dataset} (plan {plan_hash[:8]}): Indexed {len(chunk)} metadata into {meta_table}")
            client.commit()
        client.commit()
    return sorted({row['file_hash'] for row in search_rows})


#: `extracted_by` of the synthetic pages row that carries a document's filenames, and
#: the `page_id` it uses. NOT a real page: every consumer of the pages table has to
#: exclude it explicitly, and `test_filename_row_excluded` enumerates them.
FILENAME_EXTRACTED_BY = 'filename_index'
FILENAME_PAGE_ID = -1


@activity.defn
@with_heartbeat
def index_filenames_row(params: IndexShardParams) -> list[str]:
    """One synthetic pages row per document holding its distinct basenames.

    This is what makes a query for a filename find the document, and it is the source of
    the filename match-highlight. It lives in the pages table rather than as a text field
    on meta because that is where the query already looks — the alternative was a second
    infix-indexed text column carrying the same strings.

    **Only ever real basenames.** It is built from `vfs_files` paths and never from
    `text_content`, which is what keeps it immune to the base64/XPM junk that
    contaminated page text. Folder names are deliberately NOT in it: they go
    through the `<coll>_vfs` structure index, where a folder is one row rather than one
    row per document under it.
    """
    from database.manticore import get_manticore_client

    collection_dataset: str = params.collection_dataset
    plan_hash: str = params.plan_hash
    item_hashes: list[str] = params.hashes
    pages_table, _ = shard_tables_from_name(params.shard_name)

    with get_collection_client(params.collectionname) as client:
        rows = client.query_arrow("""
            SELECT hash, groupUniqArray(path) AS paths
            FROM vfs_files FINAL
            WHERE collection_dataset = {collection_dataset:String}
            AND hash IN {item_hashes:Array(String)}
            GROUP BY hash
        """, {
            "collection_dataset": collection_dataset,
            "item_hashes": item_hashes
        }).to_pylist()

    written = []
    with get_manticore_client() as client:
        for chunk in chunks(rows, INDEX_ROW_CHUNK_SIZE):
            for row in chunk:
                basenames = sorted({os.path.basename(p) for p in row['paths'] if p})
                manticore_execute(
                    client,
                    pages_replace_sql(pages_table, {}),
                    (
                        pages_row_id(collection_dataset, row['hash'], FILENAME_EXTRACTED_BY, FILENAME_PAGE_ID),
                        collection_dataset,
                        row['hash'],
                        FILENAME_EXTRACTED_BY,
                        FILENAME_PAGE_ID,
                        "\n".join(basenames),
                    ),
                )
                written.append(row['hash'])
            client.commit()
        client.commit()
    log.info(
        f"{collection_dataset} (plan {plan_hash[:8]}): Indexed {len(written)} filename rows into {pages_table}"
    )
    return sorted(set(written))


@activity.defn
@with_heartbeat
def build_vfs_nodes(params: BuildVfsNodesParams) -> str:
    """Materialise one dataset's VFS tree into ClickHouse ``vfs_nodes``.

    Dataset-scoped and idempotent: it rebuilds the whole tree and REPLACEs it, because a
    plan only ever holds a slice of the dataset and a tree assembled slice by slice has
    holes wherever a parent arrived in a later plan than its child. It is cheap — one
    small row per node, no text.

    Runs before the per-shard writers: `index_metadata` reads this table to build the
    ancestor closure, and `index_vfs_structure` copies it into Manticore.
    """
    import pyarrow as pa

    from .vfs_nodes import build_node_rows

    collection_dataset: str = params.collection_dataset
    with get_collection_client(params.collectionname) as client:
        # FINAL on every one: all four are ReplacingMergeTrees, and a duplicate row here
        # becomes a duplicate node, which becomes a duplicate child in the tree sidebar.
        dir_rows = client.query_arrow("""
            SELECT container_hash, path FROM vfs_directories FINAL
            WHERE collection_dataset = {cd:String}
        """, {"cd": collection_dataset}).to_pylist()
        file_rows = client.query_arrow("""
            SELECT container_hash, path, hash, file_size_bytes FROM vfs_files FINAL
            WHERE collection_dataset = {cd:String}
        """, {"cd": collection_dataset}).to_pylist()
        archive_hashes = {
            r['archive_hash'] for r in client.query_arrow("""
                SELECT archive_hash FROM archives FINAL WHERE collection_dataset = {cd:String}
            """, {"cd": collection_dataset}).to_pylist()
        }
        email_hashes = {
            r['email_hash'] for r in client.query_arrow("""
                SELECT email_hash FROM emails FINAL WHERE collection_dataset = {cd:String}
            """, {"cd": collection_dataset}).to_pylist()
        }

    nodes = build_node_rows(
        collection_dataset,
        [(r['container_hash'] or '', r['path']) for r in dir_rows],
        [(r['container_hash'] or '', r['path'], r['hash'], int(r['file_size_bytes'] or 0))
         for r in file_rows],
        archive_hashes | email_hashes,
    )
    if not nodes:
        return "0 nodes"

    with get_collection_client(params.collectionname) as client:
        client.insert_arrow("vfs_nodes", pa.table({
            "collection_dataset": pa.array([collection_dataset] * len(nodes), type=pa.string()),
            "container_hash": pa.array([n.container_hash for n in nodes], type=pa.string()),
            "path": pa.array([n.path for n in nodes], type=pa.string()),
            "node_key": pa.array([n.node_key for n in nodes], type=pa.string()),
            "parent_key": pa.array([n.parent_key for n in nodes], type=pa.string()),
            "kind": pa.array([n.kind for n in nodes], type=pa.string()),
            "file_hash": pa.array([n.file_hash for n in nodes], type=pa.string()),
            "file_size_bytes": pa.array([n.file_size_bytes for n in nodes], type=pa.int64()),
            "depth": pa.array([n.depth for n in nodes], type=pa.uint16()),
        }))
    log.info("[P6] %s: materialised %d VFS nodes", collection_dataset, len(nodes))
    return f"{len(nodes)} nodes"


@activity.defn
@with_heartbeat
def index_vfs_structure(params: BuildVfsNodesParams) -> str:
    """Copy one dataset's ``vfs_nodes`` into the collection's ``<coll>_vfs`` table.

    Deterministic row ids from the node key, so a rebuild REPLACEs in place. The
    ``ancestor_keys`` MVA is the FULL multi-parent closure, not the single ``parent_key``
    chain: filtering on a folder must find everything under it even when the container
    in between exists at two paths (`zip-in-multiple-locations`).
    """
    from database.manticore import get_manticore_client, vfs_table_name

    from .vfs_nodes import (
        KIND_TO_INT,
        ancestor_node_keys,
        container_parents_from_nodes,
        kind_from_wire,
    )

    collection_dataset: str = params.collection_dataset
    vfs_table = vfs_table_name(params.collectionname)
    with get_collection_client(params.collectionname) as client:
        nodes = client.query_arrow("""
            SELECT container_hash, path, node_key, parent_key, kind, file_hash,
                   file_size_bytes, depth
            FROM vfs_nodes FINAL
            WHERE collection_dataset = {cd:String}
        """, {"cd": collection_dataset}).to_pylist()
    if not nodes:
        return "0 nodes"

    container_parents = container_parents_from_nodes(nodes)
    all_keys: set[str] = set()
    closures: list[set[str]] = []
    for node in nodes:
        keys, _ = ancestor_node_keys(
            collection_dataset,
            [(node['container_hash'] or '', node['path'])],
            container_parents,
        )
        # A node is not its own ancestor; the closure of its PATH is what "everything
        # above me" means, and the caller filters `ancestor_keys` to find descendants.
        keys.discard(node['node_key'])
        closures.append(keys)
        all_keys.update(keys)

    key_ids = get_string_term_ids(params.collectionname, collection_dataset, 'vfs_node', all_keys)

    with get_manticore_client() as client:
        for start in range(0, len(nodes), INDEX_ROW_CHUNK_SIZE):
            for node, closure in zip(nodes[start:start + INDEX_ROW_CHUNK_SIZE],
                                     closures[start:start + INDEX_ROW_CHUNK_SIZE]):
                ancestors = repr_manticore_tuple(sorted(key_ids[k] for k in closure))
                manticore_execute(
                    client,
                    f"""REPLACE INTO {vfs_table} (
                            id, collection_dataset, container_hash, node_key, parent_key,
                            ancestor_keys, name, path, kind, file_hash, file_size_bytes, depth
                        ) VALUES (%s, %s, %s, %s, %s, {ancestors}, %s, %s, %s, %s, %s, %s)""",
                    (
                        hash_string_to_uint63(node['node_key']),
                        collection_dataset,
                        node['container_hash'] or '',
                        node['node_key'],
                        node['parent_key'] or '',
                        os.path.basename(node['path']) or '/',
                        node['path'],
                        KIND_TO_INT[kind_from_wire(node['kind'])],
                        node['file_hash'] or '',
                        int(node['file_size_bytes']),
                        int(node['depth']),
                    ),
                )
            client.commit()
        client.commit()
    log.info("[P6] %s: indexed %d nodes into %s", collection_dataset, len(nodes), vfs_table)
    return f"{len(nodes)} nodes"


def repr_manticore_tuple(values: List[int]) -> str:
    return "(" + ",".join(str(v) for v in values) + ")"


def repr_manticore_vector(values: List[float]) -> str:
    """A float_vector literal for interpolation into a REPLACE (it cannot be bound).

    ``repr(float(v))`` is the shortest string that round-trips the value — a trimmed
    format would quantise the embedding the probe just verified.
    """
    return "(" + ",".join(repr(float(v)) for v in values) + ")"


def vectors_row_id(collection_dataset: str, file_hash: str, extracted_by: str,
                   page_id: int, chunk_index: int, embedding_model: str) -> int:
    """Deterministic Manticore row id for one vectors row. Enables REPLACE INTO.

    The model is part of the id: two models with the same ``knn_dims`` would otherwise
    overwrite each other's rows under the same key.
    """
    return hash_string_to_uint63(
        f"{collection_dataset}|{file_hash}|{extracted_by}|{page_id}|{chunk_index}|{embedding_model}"
    )


@activity.defn
@with_heartbeat
def index_vectors(params: IndexShardParams) -> list[str]:
    """Copy the chunk's embedded vectors into the shard's HNSW ``_vectors`` table.

    ClickHouse ``text_chunk_vectors`` is the durable store; this table is the
    disposable, RAM-resident query copy. Returns the file_hashes actually written
    (committed), for ``index_state`` (see ``index_text_pages``).

    Loud refusals (non-retryable — retrying cannot fix a config lie):

    * vectors exist but the probe never ran, or the shard's ``_vectors`` table is
      missing (a stale deploy: the planner creates it from the probed dimension);
    * the rows' dimension does not match the table's ``knn_dims``. ``knn_dims`` is
      fixed at creation; writing 384-dim vectors into a 1024-dim table is the failure
      this whole mechanism exists to prevent, and it must be visible (the activity
      fails, the workflow records one processing_errors row per hash) rather than
      silently degrading retrieval.

    Rows embedded by a model other than the probed serving one are SKIPPED (with a
    warning): search embeds its queries with the probed model, so another model's
    vectors would quietly rot retrieval. Re-embed (``main.py backfill-vectors``) after
    a model change.
    """
    from temporalio.exceptions import ApplicationError

    from database.clickhouse import get_server_setting
    from database.manticore import get_manticore_client, shard_knn_dims, vectors_table_from_name

    collection_dataset: str = params.collection_dataset
    item_hashes: list[str] = params.hashes
    plan_hash: str = params.plan_hash
    vectors_table = vectors_table_from_name(params.shard_name)

    with get_collection_client(params.collectionname) as client:
        rows = client.query_arrow("""
            SELECT file_hash, extracted_by, page_id, chunk_index, embedding_model, dims, embedding
            FROM text_chunk_vectors FINAL
            WHERE collection_dataset = {collection_dataset:String}
            AND file_hash IN {item_hashes:Array(String)}
        """, {
            "collection_dataset": collection_dataset,
            "item_hashes": item_hashes,
        }).to_pylist()

    if not rows:
        # Embeddings disabled, or P5 found nothing to chunk: both are normal, and
        # search simply has no vector half for these documents.
        return []

    serving_model = get_server_setting("embeddings_serving_model")
    if not serving_model:
        raise ApplicationError(
            f"{len(rows)} vectors wait to be indexed but embeddings_serving_model is "
            "not in server_settings; run `main.py probe-embeddings`",
            non_retryable=True,
        )

    table_dims = shard_knn_dims(vectors_table)
    if table_dims is None:
        raise ApplicationError(
            f"{vectors_table} does not exist while {len(rows)} vectors wait to be "
            "indexed; the shard planner creates it from the probed dimension — "
            "is this worker running current code?",
            non_retryable=True,
        )

    kept = [r for r in rows if r["embedding_model"] == serving_model]
    skipped = len(rows) - len(kept)
    if skipped:
        log.warning(
            "%s (plan %s): skipping %d vectors embedded by a model other than the "
            "probed serving model %s; re-embed with `main.py backfill-vectors`",
            collection_dataset, plan_hash[:8], skipped, serving_model,
        )
    if not kept:
        return []

    dims_found = {int(r["dims"]) for r in kept}
    if dims_found != {table_dims}:
        raise ApplicationError(
            f"refusing to index {len(kept)} vectors of dims {sorted(dims_found)} into "
            f"{vectors_table} (knn_dims={table_dims}); a table's knn_dims cannot be "
            "altered — drop and rebuild the _vectors tables "
            "(`main.py reindex-collection`) after changing the embedding model",
            non_retryable=True,
        )

    with get_manticore_client() as client:
        for chunk in chunks(kept, INDEX_ROW_CHUNK_SIZE):
            for row in chunk:
                manticore_execute(
                    client,
                    f"""REPLACE INTO {vectors_table} (
                        id,
                        collection_dataset,
                        file_hash,
                        extracted_by,
                        page_id,
                        chunk_index,
                        embedding
                    ) VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        {repr_manticore_vector(row['embedding'])}
                    )""",
                    (
                        vectors_row_id(collection_dataset, row['file_hash'], row['extracted_by'],
                                       int(row['page_id']), int(row['chunk_index']), row['embedding_model']),
                        collection_dataset,
                        row['file_hash'],
                        row['extracted_by'],
                        int(row['page_id']),
                        int(row['chunk_index']),
                    ),
                )
            log.info(
                f"{collection_dataset} (plan {plan_hash[:8]}): Indexed {len(chunk)} vectors into {vectors_table}"
            )
            client.commit()
        client.commit()
    return sorted({row['file_hash'] for row in kept})
