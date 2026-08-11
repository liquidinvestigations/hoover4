"""Helpers for mapping string terms to stable numeric identifiers."""

import hashlib
import logging
log = logging.getLogger(__name__)

from typing import Set, Dict

def hash_string_to_uint63(string_value: str) -> int:
    """63-bit content-derived id for a string.

    blake2b truncated to 63 bits. This decides Manticore REPLACE INTO row identity
    (pages/metadata row ids) and string-term ids, so a collision silently
    overwrites a different document's row — the previous crc32|adler32
    construction was far too weak for that job (Adler-32 especially so on short
    inputs).

    NOTE: changed for the collections bugfix round (2026-07). Every id minted
    before that change is stale: run `main.py reindex-collection <name>` per
    collection (rebuilds the Manticore rows with the new ids) and re-mint
    string_term_* by re-running the NLP/index stages (the reindex does).
    """
    digest = hashlib.blake2b(
        string_value.encode('utf-8', errors='surrogateescape'), digest_size=8
    ).digest()
    return int.from_bytes(digest, 'big') % 2**63


#: Byte budget for one lookup's worth of term values.
#:
#: Query PARAMETERS travel in the HTTP request's form fields, not its body, and
#: ClickHouse caps a single field at `http_max_field_value_size` (128 KiB by default).
#: Over that it answers `Code: 1000 … HTML Form Exception: Field value too long`, which
#: names neither the parameter nor the query and reads like a malformed request.
#:
#: This is a pure scale bug: a fixture corpus has a few hundred distinct entity values per
#: batch and never comes close, while one 200-document batch of entity-dense text produces
#: megabytes of them and fails every time. Chunking removes the ceiling instead of raising
#: it, so no server setting has to agree with this code.
_TERM_LOOKUP_BYTE_BUDGET = 64 * 1024


def _chunk_by_bytes(values, budget=_TERM_LOOKUP_BYTE_BUDGET):
    """Split `values` into lists whose encoded size stays under `budget`.

    Sized by BYTES rather than by count: term values are arbitrary text, so a fixed
    count is only ever right for one corpus. A single value larger than the budget still
    goes out on its own — nothing here can make that one fit, and splitting it would
    change what is being looked up.
    """
    chunk, size = [], 0
    for value in values:
        # +3 for the quotes and comma the array literal adds around each element.
        cost = len(value.encode('utf-8', errors='surrogateescape')) + 3
        if chunk and size + cost > budget:
            yield chunk
            chunk, size = [], 0
        chunk.append(value)
        size += cost
    if chunk:
        yield chunk


def fetch_string_term_ids(collectionname: str, collection_dataset: str, term_field: str, term_values: Set[str]) -> Dict[str, int]:
    if not term_values:
        return {}
    from database.clickhouse import get_collection_client
    found: Dict[str, int] = {}
    with get_collection_client(collectionname) as client:
        for chunk in _chunk_by_bytes(sorted(term_values)):
            term_ids = client.query_arrow("""
                SELECT term_value, term_id
                FROM string_term_text_to_id
                WHERE collection_dataset = {collection_dataset:String}
                AND term_field = {term_field:String}
                AND term_value IN {term_values:Array(String)}
            """, {
                "collection_dataset": collection_dataset,
                "term_field": term_field,
                "term_values": chunk
            }).to_pylist()
            found.update({row['term_value']: row['term_id'] for row in term_ids})
    return found

def create_string_term_ids(collectionname: str, collection_dataset: str, term_field: str, term_values: Set[str]) -> Dict[str, int]:
    import pyarrow as pa
    text_to_id = {}
    id_to_text = {}
    for text in term_values:
        text_id = hash_string_to_uint63(text)
        text_to_id[text] = text_id
        id_to_text[text_id] = text

    from database.clickhouse import get_collection_client
    with get_collection_client(collectionname) as client:
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


def get_string_term_ids(collectionname: str, collection_dataset: str, term_field: str, term_values: Set[str]) -> Dict[str, int]:
    existing_term_ids = fetch_string_term_ids(collectionname, collection_dataset, term_field, term_values)
    remaining_term_values = term_values - set(existing_term_ids.keys())
    if not remaining_term_values:
        return existing_term_ids
    new_term_ids = create_string_term_ids(collectionname, collection_dataset, term_field, remaining_term_values)
    log.info(f"Created {len(new_term_ids)} new string term IDs for {term_field} in {collection_dataset}")
    return {**existing_term_ids, **new_term_ids}