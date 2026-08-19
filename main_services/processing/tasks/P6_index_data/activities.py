"""Indexing activities for text content, metadata and chunk vectors.

Pure I/O against ClickHouse and Manticore: the NER/entity extraction lives in
the P4_extract_entities stage, which runs strictly before this one. This stage
reads the ``entity_hit`` rows and ``nlp_processed`` watermarks P4 wrote, and the
``text_chunk_vectors`` rows P5 wrote.

Both writers target the shard tables assigned by the shard planner
(``shard_planner.plan_shards``) and use ``REPLACE INTO`` with deterministic row
ids, so re-indexing a document overwrites its rows in place instead of
duplicating them:

* pages id: ``hash_string_to_uint63(f"{collection_dataset}|{file_hash}|{extracted_by}|{page_id}")``
* vectors id: ``hash_string_to_uint63(f"{collection_dataset}|{file_hash}|{extracted_by}|{page_id}|{chunk_index}|{embedding_model}")``

**One writer owns the pages table, because every row of a document has to carry the
same metadata.** The document's attributes are denormalized onto each of its rows
(``manticore.pages_table_ddl``), and the result list reads them from whichever row of a
``GROUP BY file_hash`` Manticore returns - so a page written with different values than
its siblings is a document with a non-deterministic date and size. Splitting text rows
and filename rows across two activities would also mean computing the same metadata
twice per chunk.
"""

from typing import List
from temporalio import activity
import logging
import os
from .string_term_encodings import get_string_term_ids, hash_string_to_uint63
from tasks.plan_utils import clean_text
from database.clickhouse import get_collection_client
from database.manticore import DOCUMENT_COLUMNS, manticore_execute, shard_table_from_name
from .params import BuildEmailGraphParams, BuildVfsNodesParams, IndexShardParams, OptimizeShardsParams
from tasks.heartbeat import with_heartbeat
from tasks.P0_scan_disk.mime_type_mapper import coarse_file_type
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


#: The MVA columns of a pages row, in the order :func:`pages_replace_sql` writes them.
#: Manticore cannot bind an MVA, so each one is interpolated as a literal tuple built by
#: :func:`repr_manticore_tuple` — which is why they are listed apart from the scalars.
_MVA_COLUMNS = (
    'ner_per', 'ner_org', 'ner_loc', 'ner_misc',
    'file_types', 'file_mime_types', 'file_extensions', 'file_paths', 'dates',
    'email_from', 'email_to',
)

#: The bound (non-MVA) columns of a pages row, in the same order.
_SCALAR_COLUMNS = (
    'collection_dataset', 'file_hash', 'extracted_by', 'page_id', 'page_text',
    'date_min', 'date_max', 'file_size_bytes', 'struct_flags', 'primary_filename',
)


def pages_replace_sql(pages_table: str, row: dict) -> str:
    """REPLACE INTO statement for one pages row.

    MVA values are interpolated as Manticore tuples (they cannot be bound parameters);
    a missing one renders as the empty MVA ``()`` rather than as ``None``. Every scalar
    is a bound parameter, in the order :func:`pages_replace_params` returns them.
    ``pages_table`` comes from ``shard_table_from_name`` (validated).
    """
    columns = ', '.join(('id',) + _SCALAR_COLUMNS + _MVA_COLUMNS)
    placeholders = ', '.join(['%s'] * (1 + len(_SCALAR_COLUMNS)))
    mvas = ', '.join(row.get(name) or '()' for name in _MVA_COLUMNS)
    return f"""REPLACE INTO {pages_table} ({columns}) VALUES ({placeholders}, {mvas})"""


def pages_replace_params(collection_dataset: str, row: dict) -> tuple:
    """Bound parameters for :func:`pages_replace_sql`, in its column order.

    The placeholder list and the parameters are two halves of one statement written in
    two places; getting them out of step swaps ``file_size_bytes`` and ``struct_flags``,
    which is the same type, no error, and wrong data.
    """
    return (
        pages_row_id(collection_dataset, row['file_hash'], row['extracted_by'], row['page_id']),
    ) + tuple(row[name] for name in _SCALAR_COLUMNS)


def pages_row_id(collection_dataset: str, file_hash: str, extracted_by: str, page_id: int) -> int:
    """Deterministic Manticore row id for one pages row. Enables REPLACE INTO."""
    return hash_string_to_uint63(f"{collection_dataset}|{file_hash}|{extracted_by}|{page_id}")


@activity.defn
@with_heartbeat
def index_text_pages(params: IndexShardParams) -> list[str]:
    """Index the chunk's documents into the shard's table: text rows and filename rows.

    Every row carries its document's metadata (:func:`document_metadata`), so the
    metadata is read once per chunk and both row kinds are written by one writer — see
    the module docstring.

    Rows are inserted grouped by ``(collection_dataset, file_hash, page_id)``. That
    ordering is what makes the duplicated metadata nearly free: the columnar engine picks
    a storage scheme per block, and a block whose rows all belong to one document holds
    one repeated value per metadata column. Inserted in arrival order the same data costs
    several times as much on disk.

    Returns the file_hashes actually written (committed). ``IndexDatasetPlan``
    records exactly these in ``index_state`` — a document whose writer failed
    must never be counted by the shard ledger.
    """
    collection_dataset: str = params.collection_dataset
    item_hashes: list[str] = params.hashes
    plan_hash: str = params.plan_hash
    pages_table = shard_table_from_name(params.shard_name)
    from database.manticore import get_manticore_client

    metadata = document_metadata(params)

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

    rows = []
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
        page = dict(metadata.get(row['file_hash']) or empty_document_metadata())
        page.update({
            'collection_dataset': row['collection_dataset'],
            'file_hash': row['file_hash'],
            'extracted_by': row['extracted_by'],
            'page_id': row['page_id'],
            'page_text': clean_text(row['text']),
        })
        for entity_type in ("PER", "ORG", "LOC", "MISC"):
            field_name = f"ner_{entity_type.lower()}"
            field_values = [ner_ids[value] for value in segment_entities.get(entity_type, [])]
            page[field_name] = repr_manticore_tuple(field_values)
        rows.append(page)

    for file_hash, document in metadata.items():
        if not document['basenames']:
            continue
        filename_row = dict(document)
        filename_row.update({
            'collection_dataset': collection_dataset,
            'file_hash': file_hash,
            'extracted_by': FILENAME_EXTRACTED_BY,
            'page_id': FILENAME_PAGE_ID,
            'page_text': "\n".join(document['basenames']),
        })
        rows.append(filename_row)

    # Grouped by document, filename row first (page_id -1). See the docstring.
    rows.sort(key=lambda row: (row['collection_dataset'], row['file_hash'],
                               row['page_id'], row['extracted_by']))

    with get_manticore_client() as client:
        for chunk in chunks(rows, INDEX_ROW_CHUNK_SIZE):
            for row in chunk:
                manticore_execute(
                    client,
                    pages_replace_sql(pages_table, row),
                    pages_replace_params(collection_dataset, row),
                )
            log.info(f"{collection_dataset} (plan {plan_hash[:8]}): Indexed {len(chunk)} rows into {pages_table}")
            client.commit()
        client.commit()
    return sorted({row['file_hash'] for row in rows})


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


def empty_document_metadata() -> dict:
    """The metadata of a document nothing is known about.

    Every column is non-nullable in Manticore, so "nothing known" needs values rather
    than omitted columns: empty MVAs, the two unknown sentinels, and an empty title. A
    text segment whose document has no `file_types` row still has to be searchable, and
    it must not carry a date or a size it does not have.
    """
    from database.manticore import DATE_UNKNOWN, SIZE_UNKNOWN

    row = {name: repr_manticore_tuple([]) for name in DOCUMENT_COLUMNS
           if name not in ('date_min', 'date_max', 'file_size_bytes', 'struct_flags',
                           'primary_filename')}
    row.update({
        'date_min': DATE_UNKNOWN,
        'date_max': DATE_UNKNOWN,
        'file_size_bytes': SIZE_UNKNOWN,
        'struct_flags': 0,
        'primary_filename': "",
        'basenames': [],
    })
    return row


def document_metadata(params: IndexShardParams) -> dict[str, dict]:
    """The chunk's per-document metadata, keyed by ``file_hash``.

    One ClickHouse read per source, all FINAL, joined in Python rather than in one
    monster JOIN: the sources have wildly different cardinalities (one `file_types` row
    per document, N `vfs_files` rows, M `document_dates` rows, K `email_addresses` rows)
    and joining them server-side multiplies the rows before it groups them.

    Each value is a ready-to-write row fragment — MVAs already rendered as Manticore
    tuples — plus ``basenames``, which is not a column: it is the text of the document's
    ``filename_index`` row. Documents are keyed by hash and NOT restricted to those with
    a `file_types` row, because a document known only to `vfs_files` still has a
    filename, a size and a folder to be filtered by.
    """
    from database.enum_wire import ROLE_DEFAULT, ROLE_ORDINALS, enum_from_wire

    from .vfs_nodes import (
        STRUCT_FLAG_EMAIL_HAS_ATTACHMENTS,
        STRUCT_FLAG_TRUNCATED_ANCESTRY,
        ancestor_node_keys,
        container_parents_from_nodes,
    )

    collection_dataset: str = params.collection_dataset
    plan_hash: str = params.plan_hash
    item_hashes: list[str] = params.hashes

    with get_collection_client(params.collectionname) as client:
        # The coarse type and the MIME come from `file_type_canonical`, one value each,
        # which is what makes the file-type facet single-valued per document: a .docx
        # used to appear under `doc` AND `archive` because the union of five disagreeing
        # detectors went straight into the index. The losing detections are not lost --
        # they are on `file_type_canonical.losers` and in `file_types`, both of which the
        # raw metadata tab still shows.
        #
        # Extensions stay a union: a document reachable under several names has all of
        # them, and none of them is wrong.
        raw_metadatas = client.query_arrow("""
            SELECT c.hash AS hash,
                    [c.file_type] AS file_types,
                    if(c.mime_type = '', [], [c.mime_type]) AS mime_types,
                    e.extensions AS extensions
            FROM (
                SELECT hash, file_type, mime_type FROM file_type_canonical FINAL
                WHERE collection_dataset = {collection_dataset:String}
                AND hash IN {item_hashes:Array(String)}
            ) AS c
            LEFT JOIN (
                SELECT hash, arrayDistinct(arrayFlatten(groupArray(extensions))) AS extensions
                FROM file_types FINAL
                WHERE collection_dataset = {collection_dataset:String}
                AND hash IN {item_hashes:Array(String)}
                GROUP BY hash
            ) AS e ON e.hash = c.hash
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
            SELECT email_hash, toString(role) AS role, address
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
        # `role` is an Enum8 and arrives as an ORDINAL through arrow unless the query
        # says `toString`. Both belts are done up here: the SELECT above asks for the
        # name, and this normalises whatever arrives. Comparing the raw value to `'from'`
        # is always false for an ordinal, does not raise, and files every sender as a
        # recipient — which is how the whole corpus ended up with an empty sender field.
        role = enum_from_wire(row['role'], ROLE_ORDINALS, ROLE_DEFAULT)
        bucket = from_by_hash if role == 'from' else to_by_hash
        bucket.setdefault(row['email_hash'], set()).add(row['address'])

    file_types_by_hash = {item['hash']: item for item in raw_metadatas}
    items = []
    all_filetypes: set[str] = set()
    all_mime_types: set[str] = set()
    all_extensions: set[str] = set()
    all_node_keys: set[str] = set()
    all_addresses: set[str] = set()
    for file_hash in sorted(set(file_types_by_hash) | set(vfs_by_hash)):
        item = file_types_by_hash.get(
            file_hash, {'hash': file_hash, 'file_types': [], 'mime_types': [], 'extensions': []}
        )
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

    from database.manticore import DATE_UNKNOWN, SIZE_UNKNOWN

    metadata: dict[str, dict] = {}
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
        basenames = sorted({os.path.basename(row['path']) for row in rows if row['path']})
        metadata[file_hash] = {
            "file_types": repr_manticore_tuple([filetype_ids[ft] for ft in item['file_types']]),
            "file_mime_types": repr_manticore_tuple([mime_type_ids[mt] for mt in item['mime_types']]),
            "file_extensions": repr_manticore_tuple([extension_ids[ext] for ext in item['extensions']]),
            "file_paths": repr_manticore_tuple(sorted(node_key_ids[k] for k in node_keys)),
            "dates": repr_manticore_tuple(dates),
            "date_min": dates[0] if dates else DATE_UNKNOWN,
            "date_max": dates[-1] if dates else DATE_UNKNOWN,
            "file_size_bytes": max(sizes) if sizes else SIZE_UNKNOWN,
            "struct_flags": struct_flags,
            "primary_filename": primary_filename(basenames),
            "email_from": repr_manticore_tuple(
                sorted(address_ids[a] for a in from_by_hash.get(file_hash, ()))
            ),
            "email_to": repr_manticore_tuple(
                sorted(address_ids[a] for a in to_by_hash.get(file_hash, ()))
            ),
            # Not a column: the text of the document's `filename_index` row.
            #
            # **Only ever real basenames.** They come from `vfs_files` paths and never
            # from `text_content`, which is what keeps the filename row immune to the
            # base64/XPM junk that contaminated page text. Folder names are deliberately
            # NOT in it: they go through the `<coll>_vfs` structure index, where a folder
            # is one row rather than one row per document under it.
            "basenames": basenames,
        }
    return metadata


#: `extracted_by` of the synthetic pages row that carries a document's filenames, and
#: the `page_id` it uses. NOT a real page: every consumer of the pages table has to
#: exclude it explicitly, and `test_filename_row_excluded` enumerates them.
FILENAME_EXTRACTED_BY = 'filename_index'
FILENAME_PAGE_ID = -1


#: Compaction thresholds, read from ``SHOW TABLE <t> STATUS``. Re-ingesting a document
#: leaves its old rows dead in place, and every write batch adds a chunk; both accumulate
#: silently, and both are what compaction reclaims. Measured on a live corpus: a table at
#: 75 % killed lost 58 % of its disk, one at 26 % lost 32 %.
OPTIMIZE_KILLED_RATE_PERCENT = 20.0
OPTIMIZE_DISK_CHUNKS = 12


def should_optimize(status: dict) -> bool:
    """Whether a shard table is worth compacting, from its ``SHOW TABLE … STATUS``.

    ``killed_rate`` is reported as a percentage STRING (``'34.22%'``), which is why it
    is parsed rather than compared: read as a fraction it is 34, and every table looks
    like it needs compacting forever.
    """
    killed = str(status.get('killed_rate', '0')).strip().rstrip('%')
    try:
        killed_rate = float(killed)
    except ValueError:
        killed_rate = 0.0
    try:
        disk_chunks = int(status.get('disk_chunks', 0))
    except (TypeError, ValueError):
        disk_chunks = 0
    return killed_rate > OPTIMIZE_KILLED_RATE_PERCENT or disk_chunks > OPTIMIZE_DISK_CHUNKS


@activity.defn
@with_heartbeat
def optimize_shard_tables(params: OptimizeShardsParams) -> str:
    """Compact the shards this plan wrote to, when they have accumulated enough waste.

    **A storage win, not a latency win** — say so rather than selling it as a speedup.
    Killed rows are cheap to skip at query time; what compaction buys is the disk back,
    plus a small consistent gain from merging chunks.

    ``OPTION cutoff=1`` is what actually compacts: `optimize_cutoff` defaults to 24, so a
    plain OPTIMIZE barely moves a table sitting at 20 chunks. Never ``sync=1`` from an
    activity — it blocks for the whole merge and Temporal times the activity out on a
    large shard; the statement returns immediately and the daemon merges in the
    background.

    Skipped entirely while another plan of the same collection is still in flight: a
    merge competing with a write batch for I/O is how a 2 GB table takes minutes instead
    of seconds. The plan this activity belongs to is not counted — its own row reaches
    `processing_plan_finished` only after indexing returns.
    """
    from database.manticore import get_manticore_client, shard_table_from_name

    with get_collection_client(params.collectionname) as client:
        in_flight = client.query("""
            SELECT count() FROM (
                SELECT collection_dataset, plan_hash FROM processing_plans FINAL
                WHERE plan_hash != {plan_hash:String}
            ) AS p
            WHERE (p.collection_dataset, p.plan_hash) NOT IN (
                SELECT collection_dataset, plan_hash FROM processing_plan_finished FINAL
            )
        """, parameters={"plan_hash": params.plan_hash}).result_rows[0][0]
    if in_flight:
        log.info(
            "[P6] optimize %s (plan %s): %d other plan(s) still in flight; skipping",
            params.collectionname, params.plan_hash[:8], in_flight,
        )
        return "skipped: ingest in flight"

    compacted = []
    with get_manticore_client() as cnx:
        for shard_name in sorted(set(params.shard_names)):
            table = shard_table_from_name(shard_name)
            cur = cnx.cursor()
            cur.execute(f"SHOW TABLE {table} STATUS")
            status = {row[0]: row[1] for row in cur.fetchall()}
            if not should_optimize(status):
                continue
            log.info(
                "[P6] optimize %s: killed_rate=%s disk_chunks=%s; compacting",
                table, status.get('killed_rate'), status.get('disk_chunks'),
            )
            cur.execute(f"OPTIMIZE TABLE {table} OPTION cutoff=1")
            compacted.append(table)
    return f"compacted {len(compacted)}: {', '.join(compacted)}" if compacted else "nothing to compact"


@activity.defn
@with_heartbeat
def build_vfs_nodes(params: BuildVfsNodesParams) -> str:
    """Materialise one dataset's VFS tree into ClickHouse ``vfs_nodes``.

    Dataset-scoped and idempotent: it rebuilds the whole tree and REPLACEs it, because a
    plan only ever holds a slice of the dataset and a tree assembled slice by slice has
    holes wherever a parent arrived in a later plan than its child. It is cheap — one
    small row per node, no text.

    Runs before the per-shard writers: `document_metadata` reads this table to build
    each document's ancestor closure, and `index_vfs_structure` copies it into Manticore.
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
        # Everything written below carries an `updated_at` of at least this instant, so
        # anything for this dataset still older afterwards is a node the rebuild did not
        # produce. A ReplacingMergeTree replaces rows that came back and keeps rows that
        # did not: without this sweep a node that stopped existing — a file that stopped
        # being a container, the `/` that used to sit inside every archive — would stay
        # in the tree forever, because nothing overwrites a key that is never written
        # again. Read from the server rather than from Python: the comparison is against
        # ClickHouse's own clock.
        cutoff = client.query("SELECT now()").result_rows[0][0]
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
        client.command(
            "DELETE FROM vfs_nodes WHERE collection_dataset = {cd:String} "
            "AND updated_at < {cutoff:DateTime}",
            parameters={"cd": collection_dataset, "cutoff": cutoff},
        )
    log.info("[P6] %s: materialised %d VFS nodes", collection_dataset, len(nodes))
    return f"{len(nodes)} nodes"


@activity.defn
@with_heartbeat
def build_email_graph(params: BuildEmailGraphParams) -> str:
    """Rebuild one dataset's ``email_identity`` rows and the whole collection's
    ``email_edges`` and ``email_clusters``.

    Collection-scoped on purpose. The most common edge is `identity` -- the same message
    present in two custodians' mailboxes -- and an edge builder that could only see one
    dataset would never find one. The identity ROWS are per dataset because that is where
    the source tables are; the graph over them is not.

    Full rebuild plus a stale sweep, the same shape as `build_vfs_nodes`, and for the same
    reason: all three tables are ReplacingMergeTrees, so a row whose key stops being
    produced is never overwritten and would survive every later rebuild. Rows are written
    first, then everything for this scope older than a server-read cutoff is deleted.

    ``email_clusters`` gets a row only for a message that has at least one edge. A row per
    isolated message would be one row per email in the corpus to say "no connections", and
    the viewer already reads a missing row as exactly that.
    """
    import pyarrow as pa

    from database.enum_wire import ROLE_DEFAULT, ROLE_ORDINALS, enum_from_wire
    from tasks.P3_parse_files.parse_email import first_header, header_pairs_from_json
    from .email_graph import (
        EmailIdentity,
        build_all_edges,
        connected_components,
        normalise_message_id,
        normalise_subject,
        subject_prefix_kind,
    )

    collection_dataset: str = params.collection_dataset
    with get_collection_client(params.collectionname) as client:
        header_rows = client.query_arrow("""
            SELECT email_hash, raw_headers_json, subject, toInt64(date_sent) AS date_sent,
                   date_sent_known
            FROM email_headers FINAL
            WHERE collection_dataset = {cd:String}
        """, {"cd": collection_dataset}).to_pylist()
        # `toString(role)`: an Enum8 read through arrow arrives as its ORDINAL, and
        # comparing that to 'from' is false for every row without raising. That is the
        # exact bug that left the whole corpus with an empty sender field.
        address_rows = client.query_arrow("""
            SELECT email_hash, toString(role) AS role, address
            FROM email_addresses FINAL
            WHERE collection_dataset = {cd:String} AND address != ''
        """, {"cd": collection_dataset}).to_pylist()

    participants_by_hash: dict[str, set[str]] = {}
    from_by_hash: dict[str, str] = {}
    for row in address_rows:
        role = enum_from_wire(row['role'], ROLE_ORDINALS, ROLE_DEFAULT)
        participants_by_hash.setdefault(row['email_hash'], set()).add(row['address'])
        if role == 'from' and row['email_hash'] not in from_by_hash:
            from_by_hash[row['email_hash']] = row['address']

    dataset_identities = []
    for row in header_rows:
        pairs = header_pairs_from_json(row['raw_headers_json'])
        subject = row['subject'] or ''
        dataset_identities.append(EmailIdentity(
            collection_dataset=collection_dataset,
            email_hash=row['email_hash'],
            message_id=normalise_message_id(first_header(pairs, 'Message-ID')),
            subject_norm=normalise_subject(subject),
            subject_prefix=subject_prefix_kind(subject),
            date_sent=int(row['date_sent'] or 0),
            date_sent_known=int(row['date_sent_known'] or 0),
            from_address=from_by_hash.get(row['email_hash'], ''),
            participants=tuple(sorted(participants_by_hash.get(row['email_hash'], ()))),
        ))

    with get_collection_client(params.collectionname) as client:
        if dataset_identities:
            cutoff = client.query("SELECT now()").result_rows[0][0]
            client.insert_arrow("email_identity", pa.table({
                "collection_dataset": pa.array([i.collection_dataset for i in dataset_identities], type=pa.string()),
                "email_hash": pa.array([i.email_hash for i in dataset_identities], type=pa.string()),
                "message_id": pa.array([i.message_id for i in dataset_identities], type=pa.string()),
                "subject_norm": pa.array([i.subject_norm for i in dataset_identities], type=pa.string()),
                "date_sent": pa.array([i.date_sent for i in dataset_identities], type=pa.int64()).cast(pa.timestamp("s")),
                "date_sent_known": pa.array([i.date_sent_known for i in dataset_identities], type=pa.uint8()),
                "from_address": pa.array([i.from_address for i in dataset_identities], type=pa.string()),
                "subject_prefix": pa.array([i.subject_prefix for i in dataset_identities], type=pa.string()),
                "participants": pa.array([list(i.participants) for i in dataset_identities], type=pa.list_(pa.string())),
            }))
            client.command(
                "DELETE FROM email_identity WHERE collection_dataset = {cd:String} "
                "AND updated_at < {cutoff:DateTime}",
                parameters={"cd": collection_dataset, "cutoff": cutoff},
            )

        # The whole collection, for the graph. Identity edges cross datasets, so this
        # cannot be narrowed to the one that just finished.
        identity_rows = client.query_arrow("""
            SELECT collection_dataset, email_hash, message_id, subject_norm, subject_prefix,
                   toInt64(date_sent) AS date_sent, date_sent_known, from_address, participants
            FROM email_identity FINAL
        """).to_pylist()
        containment_rows = client.query_arrow("""
            SELECT collection_dataset, container_hash, hash FROM vfs_files FINAL
            WHERE container_hash != ''
        """).to_pylist()

    identities = [EmailIdentity(
        collection_dataset=row['collection_dataset'],
        email_hash=row['email_hash'],
        message_id=row['message_id'],
        subject_norm=row['subject_norm'],
        subject_prefix=row['subject_prefix'],
        date_sent=int(row['date_sent'] or 0),
        date_sent_known=int(row['date_sent_known'] or 0),
        from_address=row['from_address'],
        participants=tuple(row['participants'] or ()),
    ) for row in identity_rows]

    # RFC threading headers are read only for the dataset just rebuilt plus whatever is
    # already known: `raw_headers_json` for the whole collection is the largest column in
    # this stage and 0.06% of these corpora carry `In-Reply-To` at all. The map is keyed
    # by node so a missing entry simply produces no RFC edge.
    header_pairs_by_key = {
        (collection_dataset, row['email_hash']): header_pairs_from_json(row['raw_headers_json'])
        for row in header_rows
    }
    containment = [
        (row['collection_dataset'], row['container_hash'], row['hash'])
        for row in containment_rows
    ]

    edges, stats = build_all_edges(identities, header_pairs_by_key, containment)
    log.info("[P6] %s: email graph over %d messages, %s",
             params.collectionname, len(identities), stats.summary())

    components = connected_components(edges)
    cluster_rows = []
    for node, members in components.items():
        anchor_key = min(members)
        cluster_rows.append((
            node[0], node[1],
            hash_string_to_uint63(f"{anchor_key[0]}|{anchor_key[1]}"),
            len(members),
        ))

    with get_collection_client(params.collectionname) as client:
        cutoff = client.query("SELECT now()").result_rows[0][0]
        if edges:
            client.insert_arrow("email_edges", pa.table({
                "collectionname": pa.array([params.collectionname] * len(edges), type=pa.string()),
                "src_dataset": pa.array([e.src_dataset for e in edges], type=pa.string()),
                "src_hash": pa.array([e.src_hash for e in edges], type=pa.string()),
                "dst_dataset": pa.array([e.dst_dataset for e in edges], type=pa.string()),
                "dst_hash": pa.array([e.dst_hash for e in edges], type=pa.string()),
                "kind": pa.array([e.kind for e in edges], type=pa.string()),
                "confidence": pa.array([e.confidence for e in edges], type=pa.float32()),
                "evidence": pa.array([e.evidence for e in edges], type=pa.string()),
            }))
        if cluster_rows:
            client.insert_arrow("email_clusters", pa.table({
                "collectionname": pa.array([params.collectionname] * len(cluster_rows), type=pa.string()),
                "collection_dataset": pa.array([r[0] for r in cluster_rows], type=pa.string()),
                "email_hash": pa.array([r[1] for r in cluster_rows], type=pa.string()),
                "cluster_id": pa.array([r[2] for r in cluster_rows], type=pa.uint64()),
                "cluster_size": pa.array([r[3] for r in cluster_rows], type=pa.uint32()),
            }))
        for table in ("email_edges", "email_clusters"):
            client.command(
                f"DELETE FROM {table} WHERE collectionname = {{cn:String}} "
                "AND updated_at < {cutoff:DateTime}",
                parameters={"cn": params.collectionname, "cutoff": cutoff},
            )

    log.info("[P6] %s: %d email edges, %d clustered messages",
             params.collectionname, len(edges), len(cluster_rows))
    return f"{len(edges)} edges, {len(cluster_rows)} clustered"


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
        # Clear the dataset's rows first, then write the tree back. A REPLACE only
        # overwrites the keys it is given, so a node that no longer exists would survive
        # every future rebuild and keep answering the tree — and the whole point of this
        # activity is that `vfs_nodes` is the truth. The gap is the duration of one
        # dataset's rebuild, during which the tree is being rewritten anyway.
        manticore_execute(
            client, f"DELETE FROM {vfs_table} WHERE collection_dataset = %s",
            (collection_dataset,),
        )
        client.commit()
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


@activity.defn
@with_heartbeat
def resolve_canonical_file_type(params: BuildVfsNodesParams) -> str:
    """Decide one definitive type per document, after every parser has had its turn.

    This is the "last final pass" the whole parallel-detection design was waiting for.
    Detection is contradictory on purpose and processing is attempted on every detected
    type, which is what gets a .docx its office text out of a file libmagic calls a zip.
    The cost was a file-type facet that listed the same document under three headings.
    Here the contradictions are resolved, once, from what the parsers actually produced.

    Dataset-scoped and idempotent, like `build_vfs_nodes`, and for the same reason: a
    plan holds a slice of the dataset, and a document's evidence can arrive in a
    different plan from its detections. It runs before `document_metadata`, which reads
    the result.

    See `canonical_file_type.py` for the rank table itself.
    """
    import pyarrow as pa

    from .canonical_file_type import resolve_canonical

    collection_dataset: str = params.collection_dataset
    with get_collection_client(params.collectionname) as client:
        detection_rows = client.query_arrow("""
            SELECT hash, extracted_by, mime_type
            FROM file_types FINAL
            WHERE collection_dataset = {cd:String}
        """, {"cd": collection_dataset}).to_pylist()

        # What each parser actually produced rows for. `text_content` is joined by
        # extracted_by rather than taken wholesale: every text extractor writes there,
        # and only the office one is evidence of an office document.
        evidence_rows = client.query_arrow("""
            SELECT email_hash AS hash, 'email' AS kind FROM emails FINAL
                WHERE collection_dataset = {cd:String}
            UNION ALL
            SELECT pdf_hash AS hash, 'pdf' AS kind FROM pdfs FINAL
                WHERE collection_dataset = {cd:String}
            UNION ALL
            SELECT image_hash AS hash, 'image' AS kind FROM image FINAL
                WHERE collection_dataset = {cd:String}
            UNION ALL
            SELECT archive_hash AS hash, 'archive' AS kind FROM archives FINAL
                WHERE collection_dataset = {cd:String}
            UNION ALL
            SELECT hash, 'office' AS kind FROM text_content FINAL
                WHERE collection_dataset = {cd:String} AND extracted_by = 'office_xml'
        """, {"cd": collection_dataset}).to_pylist()

        # How many members each container actually produced. An archive that exploded
        # into nothing is not an archive, and half a million container nodes corpus-wide
        # are exactly that.
        member_rows = client.query_arrow("""
            SELECT container_hash, count() AS members FROM (
                SELECT DISTINCT container_hash, path FROM vfs_files FINAL
                WHERE collection_dataset = {cd:String} AND container_hash != ''
                UNION ALL
                SELECT DISTINCT container_hash, path FROM vfs_directories FINAL
                WHERE collection_dataset = {cd:String} AND container_hash != ''
            )
            GROUP BY container_hash
        """, {"cd": collection_dataset}).to_pylist()

    detections: dict[str, dict[str, list[str]]] = {}
    for row in detection_rows:
        detections.setdefault(row['hash'], {})[row['extracted_by']] = [
            m for m in (row['mime_type'] or []) if m
        ]

    #: Office text is evidence of a document, but not of *which* document: the extractor
    #: is one activity for Word, Excel and PowerPoint alike. The MIME set decides which,
    #: and `doc` is the fallback when it cannot.
    evidence: dict[str, set[str]] = {}
    for row in evidence_rows:
        evidence.setdefault(row['hash'], set()).add(row['kind'])
    members = {row['container_hash']: int(row['members']) for row in member_rows}

    hashes = sorted(set(detections) | set(evidence))
    if not hashes:
        log.info("%s: no detections to canonicalise", collection_dataset)
        return "ok"

    out_hashes: list[str] = []
    out_mimes: list[str] = []
    out_types: list[str] = []
    out_decided: list[str] = []
    out_losers: list[list[str]] = []
    for file_hash in hashes:
        by_detector = detections.get(file_hash, {})
        kinds = set(evidence.get(file_hash, ()))
        if 'office' in kinds:
            kinds.discard('office')
            all_mimes = {m for mimes in by_detector.values() for m in mimes}
            office_coarse = {coarse_file_type(m) for m in all_mimes} & {'doc', 'xls', 'ppt'}
            kinds |= office_coarse or {'doc'}
        canonical = resolve_canonical(
            by_detector, kinds, members.get(file_hash, 0),
        )
        out_hashes.append(file_hash)
        out_mimes.append(canonical.mime_type)
        out_types.append(canonical.file_type)
        out_decided.append(canonical.decided_by)
        out_losers.append(canonical.losers)

    table = pa.table({
        "collection_dataset": pa.array([collection_dataset] * len(out_hashes), type=pa.string()),
        "hash": pa.array(out_hashes, type=pa.string()),
        "mime_type": pa.array(out_mimes, type=pa.string()),
        "file_type": pa.array(out_types, type=pa.string()),
        "decided_by": pa.array(out_decided, type=pa.string()),
        "losers": pa.array(out_losers, type=pa.list_(pa.string())),
    })
    with get_collection_client(params.collectionname) as client:
        client.insert_arrow("file_type_canonical", table)
    log.info("%s: canonical file type resolved for %d documents",
             collection_dataset, len(out_hashes))
    return "ok"
