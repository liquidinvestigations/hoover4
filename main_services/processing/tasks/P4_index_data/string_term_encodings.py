import logging
log = logging.getLogger(__name__)

from typing import Set, Dict

def hash_string_to_uint63(string_value: str) -> int:
    import zlib
    bytes_value = string_value.encode('utf-8', errors='surrogateescape')
    crc32 = zlib.crc32(bytes_value)
    adler32 = zlib.adler32(bytes_value)
    return ((crc32 & 0xFFFFFFFF) | ((adler32 & 0xFFFFFFFF) << 31)) % 2**63


def fetch_string_term_ids(collection_dataset: str, term_field: str, term_values: Set[str]) -> Dict[str, int]:
    if not term_values:
        return {}
    term_values = sorted(term_values)
    from database.clickhouse import get_clickhouse_client
    with get_clickhouse_client() as client:
        term_ids = client.query_arrow("""
            SELECT term_value, term_id
            FROM string_term_text_to_id
            WHERE collection_dataset = {collection_dataset:String}
            AND term_field = {term_field:String}
            AND term_value IN {term_values:Array(String)}
        """, {
            "collection_dataset": collection_dataset,
            "term_field": term_field,
            "term_values": term_values
        }).to_pylist()
    return {row['term_value']: row['term_id'] for row in term_ids}

def create_string_term_ids(collection_dataset: str, term_field: str, term_values: Set[str]) -> Dict[str, int]:
    import pyarrow as pa
    text_to_id = {}
    id_to_text = {}
    for text in term_values:
        text_id = hash_string_to_uint63(text)
        text_to_id[text] = text_id
        id_to_text[text_id] = text

    from database.clickhouse import get_clickhouse_client
    with get_clickhouse_client() as client:
        # Upsert into string_term_text_to_id table
        tbl_text_to_id = pa.table({
            "collection_dataset": pa.array([collection_dataset] * len(text_to_id), type=pa.string()),
            "term_field": pa.array([term_field] * len(text_to_id), type=pa.string()),
            "term_value": pa.array(list(text_to_id.keys()), type=pa.string()),
            "term_id": pa.array(list(text_to_id.values()), type=pa.uint64()),
        })
        client.insert_arrow("string_term_text_to_id", tbl_text_to_id)

        tbl_id_to_text = pa.table({
            "collection_dataset": pa.array([collection_dataset] * len(id_to_text), type=pa.string()),
            "term_field": pa.array([term_field] * len(id_to_text), type=pa.string()),
            "term_id": pa.array(list(id_to_text.keys()), type=pa.uint64()),
            "term_value": pa.array(list(id_to_text.values()), type=pa.string()),
        })
        client.insert_arrow("string_term_id_to_text", tbl_id_to_text)

    return text_to_id


def get_string_term_ids(collection_dataset: str, term_field: str, term_values: Set[str]) -> Dict[str, int]:
    existing_term_ids = fetch_string_term_ids(collection_dataset, term_field, term_values)
    remaining_term_values = term_values - set(existing_term_ids.keys())
    if not remaining_term_values:
        return existing_term_ids
    new_term_ids = create_string_term_ids(collection_dataset, term_field, remaining_term_values)
    log.info(f"Created {len(new_term_ids)} new string term IDs for {term_field} in {collection_dataset}")
    return {**existing_term_ids, **new_term_ids}