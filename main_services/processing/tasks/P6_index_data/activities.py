"""Indexing activities for text content and metadata.

Pure I/O against ClickHouse and Manticore: the NER/entity extraction lives in
the P4_extract_entities stage, which runs strictly before this one. This stage
reads the ``entity_hit`` rows and ``nlp_processed`` watermarks P4 wrote.

Both writers target the shard tables assigned by the shard planner
(``shard_planner.plan_shards``) and use ``REPLACE INTO`` with deterministic row
ids, so re-indexing a document overwrites its rows in place instead of
duplicating them:

* pages id: ``hash_string_to_uint63(f"{collection_dataset}|{file_hash}|{extracted_by}|{page_id}")``
* metadata id: ``hash_string_to_uint63(f"{collection_dataset}|{file_hash}")``
"""

from typing import List
from temporalio import activity
import logging
import os
from .string_term_encodings import get_string_term_ids, hash_string_to_uint63
from tasks.plan_utils import clean_text
from database.clickhouse import get_collection_client
from database.manticore import shard_tables_from_name
from .params import IndexShardParams
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

    The four facet MVA values are interpolated as Manticore tuples (they cannot be
    bound parameters); everything else is a bound parameter. ``meta_table`` comes
    from ``shard_tables_from_name`` (validated).
    """
    return f"""REPLACE INTO {meta_table} (
                        id,
                        collection_dataset,
                        file_hash,
                        filenames,
                        metadata_values,
                        file_types,
                        file_mime_types,
                        file_extensions,
                        file_paths
                    ) VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        {row['file_types']},
                        {row['file_mime_types']},
                        {row['file_extensions']},
                        {row['file_paths']}
                    )"""


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
        text_content = client.query_arrow("""
            SELECT collection_dataset, file_hash, extracted_by, page_id, text
            FROM text_content
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
        cursor = client.cursor()
        for chunk in chunks(text_content, INDEX_ROW_CHUNK_SIZE):
            for row in chunk:
                cursor.execute(
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


@activity.defn
@with_heartbeat
def index_metadata(params: IndexShardParams) -> list[str]:
    """Index the chunk's metadata rows into the shard's meta table.

    Returns the file_hashes actually written (committed), for ``index_state``
    (see ``index_text_pages``).
    """
    collection_dataset: str = params.collection_dataset
    plan_hash: str = params.plan_hash
    item_hashes: list[str] = params.hashes
    _, meta_table = shard_tables_from_name(params.shard_name)
    from database.manticore import get_manticore_client
    with get_collection_client(params.collectionname) as client:
        raw_metadatas = client.query_arrow("""
            SELECT hash,
                    arrayDistinct(arrayFlatten(groupArray(t.file_type))) as file_types,
                    arrayDistinct(arrayFlatten(groupArray(t.mime_type))) as mime_types,
                    arrayDistinct(arrayFlatten(groupArray(t.extensions))) as extensions,
                    arrayDistinct(groupArray(v.path)) as file_paths
            FROM file_types t
            JOIN vfs_files v ON v.hash = t.hash AND v.collection_dataset = t.collection_dataset
            WHERE t.collection_dataset = {collection_dataset:String}
            AND t.hash IN {item_hashes:Array(String)}
            GROUP BY hash
        """, {
            "collection_dataset": collection_dataset,
            "item_hashes": item_hashes
        }).to_pylist()

    # Parent-path closure (every ancestor directory) computed ONCE per item; the
    # union feeds the term-id batch below and the per-item set feeds the row.
    items_with_parents = []
    all_filetypes = set()
    all_mime_types = set()
    all_extensions = set()
    all_parent_paths = set()
    for item in raw_metadatas:
        item_parent_paths = set()
        for path in item['file_paths']:
            parent_path = os.path.dirname(path)
            item_parent_paths.add(parent_path)
            while parent_path != '/':
                parent_path = os.path.dirname(parent_path)
                item_parent_paths.add(parent_path)
        items_with_parents.append((item, item_parent_paths))
        all_filetypes.update(item['file_types'])
        all_mime_types.update(item['mime_types'])
        all_extensions.update(item['extensions'])
        all_parent_paths.update(item_parent_paths)
    filetype_ids = get_string_term_ids(params.collectionname, collection_dataset, 'filetype', all_filetypes)
    mime_type_ids = get_string_term_ids(params.collectionname, collection_dataset, 'mime_type', all_mime_types)
    extension_ids = get_string_term_ids(params.collectionname, collection_dataset, 'extension', all_extensions)
    parent_path_ids = get_string_term_ids(params.collectionname, collection_dataset, 'parent_paths', all_parent_paths)
    search_rows = []
    for item, item_parent_paths in items_with_parents:
        new_row = {
            "collection_dataset": collection_dataset,
            "file_hash": item['hash'],
            "file_types": repr_manticore_tuple([filetype_ids[ft] for ft in item['file_types']]),
            "file_mime_types": repr_manticore_tuple([mime_type_ids[mt] for mt in item['mime_types']]),
            "file_extensions": repr_manticore_tuple([extension_ids[ext] for ext in item['extensions']]),
            "file_paths": repr_manticore_tuple([parent_path_ids[pp] for pp in item_parent_paths]),
            "filenames": "\n".join([os.path.basename(p) for p in item['file_paths']]),
            "metadata_values": "",
        }
        search_rows.append(new_row)
    with get_manticore_client() as client:
        cursor = client.cursor()
        for chunk in chunks(search_rows, INDEX_ROW_CHUNK_SIZE):
            for row in chunk:
                cursor.execute(
                    meta_replace_sql(meta_table, row),
                    (metadata_row_id(collection_dataset, row['file_hash']), row['collection_dataset'], row['file_hash'],  row['filenames'], row['metadata_values'])
                )
            log.info(f"{collection_dataset} (plan {plan_hash[:8]}): Indexed {len(chunk)} metadata into {meta_table}")
            client.commit()
        client.commit()
    return sorted({row['file_hash'] for row in search_rows})


def repr_manticore_tuple(values: List[int]) -> str:
    return "(" + ",".join(str(v) for v in values) + ")"
