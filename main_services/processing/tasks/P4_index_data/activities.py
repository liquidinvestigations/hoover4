from typing import List
from temporalio import activity
from dataclasses import dataclass
import logging
import os
from .string_term_encodings import get_string_term_ids
from .extract_ner_from_text import extract_ner_from_texts
from database.clickhouse import get_clickhouse_client
import pyarrow as pa
from .params import IndexDatasetPlanParams, IndexTextContentParams
log = logging.getLogger(__name__)

# def hash_to_int64(row):
    # return int.from_bytes(hashlib.sha1(str(row).encode('utf-8')).digest(), 'little') % 2**64


INDEX_ROW_CHUNK_SIZE = 512
def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

@activity.defn
def fetch_plan_hashes(params: IndexDatasetPlanParams) -> list[str]:
    collection_dataset: str = params.collection_dataset
    plan_hash: str = params.plan_hash
    from database.clickhouse import get_clickhouse_client
    with get_clickhouse_client() as client:
        hashes = client.query_arrow("""
            SELECT item_hashes
            FROM processing_plans
            WHERE collection_dataset = {collection_dataset:String} AND plan_hash = {plan_hash:String}
        """, {
            "collection_dataset": collection_dataset,
            "plan_hash": plan_hash
        }).to_pylist()[0]['item_hashes']
    return sorted(set(hashes))


@activity.defn
def index_text_content(params: IndexTextContentParams):
    collection_dataset: str = params.collection_dataset
    item_hashes: list[str] = params.hashes
    plan_hash: str = params.plan_hash
    from database.clickhouse import get_clickhouse_client
    from database.manticore import get_manticore_client
    with get_clickhouse_client() as client:
        text_content = client.query_arrow("""
            SELECT collection_dataset, file_hash, extracted_by, page_id, text
            FROM text_content
            WHERE collection_dataset = {collection_dataset:String}
            AND file_hash IN {item_hashes:Array(String)}
        """, {
            "collection_dataset": collection_dataset,
            "item_hashes": item_hashes
        }).to_pylist()

    text_content = _extract_and_save_ner(collection_dataset, text_content)


    with get_manticore_client() as client:
        cursor = client.cursor()
        for chunk in chunks(text_content, INDEX_ROW_CHUNK_SIZE):
            for row in chunk:
                cursor.execute(
                    f"""INSERT INTO doc_text_pages (
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
                        {row.get('ner_per') or '()'},
                        {row.get('ner_org') or '()'},
                        {row.get('ner_loc') or '()'},
                        {row.get('ner_misc') or '()'}
                    )""",
                    (
                        row['collection_dataset'],
                        row['file_hash'],
                        row['extracted_by'],
                        row['page_id'],
                        _clean_text(row['text'])
                    )
                )
            log.info(f"{collection_dataset} (plan {plan_hash[:8]}): Indexed {len(chunk)} text content")
            client.commit()
        client.commit()
    return "ok"


def _clean_text(text: str) -> str:
    if not text:
        return ''
    # TODO: try different encoding on utf-8 errors
    return text.encode('utf-8', errors='replace').decode('utf-8').strip()


def _extract_and_save_ner(collection_dataset: str, text_content: list[dict]) -> list[dict]:
    try:
        text_ner_extracted = extract_ner_from_texts([_clean_text(t['text']) for t in text_content])
    except Exception as e:
        log.error(f"Error extracting NER from text content: {e}")
        text_ner_extracted = [{"PER": [], "ORG": [], "LOC": [], "MISC": []} for _ in text_content]

    clickhouse_ner_rows = []
    ner_values = set()
    for text_row, ner_result in zip(text_content, text_ner_extracted):
        for entity_type, entity_values in ner_result.items():
            clickhouse_ner_rows.append({
                "collection_dataset": text_row['collection_dataset'],
                "file_hash": text_row['file_hash'],
                "extracted_by": text_row['extracted_by'],
                "page_id": text_row['page_id'],
                "entity_type": entity_type,
                "entity_values": entity_values,
            })
            for value in entity_values:
                ner_values.add(value)
    ner_ids = get_string_term_ids(collection_dataset, 'ner', ner_values)
    for text_row, ner_result in zip(text_content, text_ner_extracted):
        for entity_type, entity_values in ner_result.items():
            field_name = f"ner_{entity_type.lower()}"
            field_values = [ner_ids[value] for value in entity_values]
            text_row[field_name] = repr_manticore_tuple(field_values)


    with get_clickhouse_client() as client:
        tbl_ner = pa.table({
            "collection_dataset": pa.array([row['collection_dataset'] for row in clickhouse_ner_rows], type=pa.string()),
            "file_hash": pa.array([row['file_hash'] for row in clickhouse_ner_rows], type=pa.string()),
            "extracted_by": pa.array([row['extracted_by'] for row in clickhouse_ner_rows], type=pa.string()),
            "page_id": pa.array([row['page_id'] for row in clickhouse_ner_rows], type=pa.uint32()),
            "entity_type": pa.array([row['entity_type'] for row in clickhouse_ner_rows], type=pa.string()),
            "entity_values": pa.array([row['entity_values'] for row in clickhouse_ner_rows], type=pa.list_(pa.string())),
        })
        client.insert_arrow("entity_hit", tbl_ner)
    log.info(f"Extracted {len(clickhouse_ner_rows)} entity groups from text content")
    return text_content


@activity.defn
def index_metadatas(params: IndexTextContentParams) -> str:
    collection_dataset: str = params.collection_dataset
    plan_hash: str = params.plan_hash
    item_hashes: list[str] = params.hashes
    from database.clickhouse import get_clickhouse_client
    from database.manticore import get_manticore_client
    with get_clickhouse_client() as client:
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

    all_filetypes = set()
    all_mime_types = set()
    all_extensions = set()
    all_parent_paths = set()
    for item in raw_metadatas:
        all_filetypes.update(item['file_types'])
        all_mime_types.update(item['mime_types'])
        all_extensions.update(item['extensions'])
        for path in item['file_paths']:
            parent_path = os.path.dirname(path)
            all_parent_paths.add(parent_path)
            while parent_path != '/':
                parent_path = os.path.dirname(parent_path)
                all_parent_paths.add(parent_path)
    filetype_ids = get_string_term_ids(collection_dataset, 'filetype', all_filetypes)
    mime_type_ids = get_string_term_ids(collection_dataset, 'mime_type', all_mime_types)
    extension_ids = get_string_term_ids(collection_dataset, 'extension', all_extensions)
    parent_path_ids = get_string_term_ids(collection_dataset, 'parent_paths', all_parent_paths)
    search_rows = []
    for item in raw_metadatas:
        item_parent_paths = set()
        for pp in item['file_paths']:
            parent_path = os.path.dirname(pp)
            item_parent_paths.add(parent_path)
            while parent_path != '/':
                parent_path = os.path.dirname(parent_path)
                item_parent_paths.add(parent_path)
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
                sql =f"""INSERT INTO doc_metadata (
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
                        {row['file_types']},
                        {row['file_mime_types']},
                        {row['file_extensions']},
                        {row['file_paths']}
                    )"""
                # print(sql)
                cursor.execute(
                    sql,
                    (row['collection_dataset'], row['file_hash'],  row['filenames'], row['metadata_values'])
                )
            log.info(f"{collection_dataset} (plan {plan_hash[:8]}): Indexed {len(chunk)} metadata")
            client.commit()
        client.commit()
    # new_file_rows = []
    # for orig_row in file_types:
    #     for (entry_id, type_name) in enumerate(orig_row['file_types']):
    #         new_file_rows.append({
    #             "collection_dataset": collection_dataset,
    #             "file_hash": orig_row['hash'],
    #             "entry_id": entry_id,
    #             "file_type": type_name
    #         })
    # with get_manticore_client() as client:
    #     cursor = client.cursor()
    #     for chunk in chunks(new_file_rows, INDEX_ROW_CHUNK_SIZE):
    #         for row in chunk:
    #             cursor.execute(
    #                 "INSERT INTO doc_file_type (collection_dataset, file_hash, entry_id, file_type) VALUES (%s, %s, %s, %s)",
    #                 (row['collection_dataset'], row['file_hash'], row['entry_id'], row['file_type'])
    #             )
    #         log.info(f"{collection_dataset} (plan {plan_hash[:8]}): Indexed {len(chunk)} file types")
    #         client.commit()

def repr_manticore_tuple(values: List[int]) -> str:
    return "(" + ",".join(str(v) for v in values) + ")"