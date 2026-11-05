"""Retain table update work until every dependent stage completes."""

from dataclasses import dataclass, field

from temporalio import activity
from tasks.heartbeat import with_heartbeat

STAGES = ("parse", "text", "entities", "regex", "embed", "index_text", "index_vectors")


def contract() -> str:
    from tasks.P_admin.updates.registry import STEPS_BY_ID, fingerprint
    return fingerprint(STEPS_BY_ID["tables"], "")


@dataclass
class TableReceiptParams:
    collectionname: str
    collection_dataset: str
    op_id: str
    hashes: list[str] = field(default_factory=list)
    stages: list[str] = field(default_factory=list)
    generations: dict[str, int] = field(default_factory=dict)


def write_receipts(client, params: TableReceiptParams) -> None:
    from database.clickhouse import insert_durable
    from tasks.P3_parse_files.table_formats import READER_VERSION

    if not set(params.stages) <= set(STAGES):
        raise ValueError("Unknown table update stage")
    rows = client.query(
        "SELECT hash, generation FROM table_documents FINAL WHERE collection_dataset = {cd:String} "
        "AND hash IN {hashes:Array(String)} AND reader_version = {version:UInt16} "
        "AND status IN ('ok', 'empty')",
        parameters={"cd": params.collection_dataset, "hashes": params.hashes,
                    "version": READER_VERSION}).result_rows
    if {row[0] for row in rows} != set(params.hashes):
        raise RuntimeError("A table update has no current published output")
    actual = {file_hash: int(generation) for file_hash, generation in rows}
    if actual != params.generations:
        raise RuntimeError("The published table changed during its update")
    from tasks.P3_parse_files.table_text import complete_table_text
    if any(not complete_table_text(client, params.collection_dataset, file_hash, generation)
           for file_hash, generation in actual.items()):
        raise RuntimeError("A table update has incomplete required text")
    verify_stages(client, params)

    if rows:
        insert_durable(client, "processing_output_receipts", [
            [params.collection_dataset, file_hash, "table", str(generation), contract(), stage, params.op_id]
            for file_hash, generation in rows for stage in params.stages],
            column_names=["collection_dataset", "file_hash", "output_kind", "output_identity",
                          "fingerprint", "stage", "op_id"])


@activity.defn
@with_heartbeat
def record_table_update_receipts(params: TableReceiptParams) -> None:
    from database.clickhouse import get_collection_client
    with get_collection_client(params.collectionname) as client:
        write_receipts(client, params)


def prepare_table_text(client, params: TableReceiptParams) -> None:
    """Remove dependent table text rows before the first receipt for this output."""
    from tasks.text_sources import TABLE_TEXT
    pending = client.query(
        "SELECT hash, generation FROM table_documents FINAL WHERE collection_dataset = {cd:String} "
        "AND hash IN {hashes:Array(String)} AND status IN ('ok', 'empty') "
        "AND (hash, toString(generation)) NOT IN (SELECT file_hash, output_identity "
        "FROM processing_output_receipts WHERE collection_dataset = {cd:String} "
        "AND output_kind = 'table' AND fingerprint = {fingerprint:String} AND stage = 'parse')",
        parameters={"cd": params.collection_dataset, "hashes": params.hashes,
                    "fingerprint": contract()}).result_rows
    hashes = [row[0] for row in pending]
    if not hashes:
        return
    for table in ("entity_hit", "nlp_processed", "regex_entity_hit", "regex_scanned",
                  "signal_hit", "signal_scanned", "signal_cluster", "text_chunks", "text_chunk_vectors"):
        client.command(
            f"DELETE FROM {table} WHERE collection_dataset = {{cd:String}} "
            "AND file_hash IN {hashes:Array(String)} AND extracted_by = {source:String} "
            "SETTINGS mutations_sync = 2",
            parameters={"cd": params.collection_dataset, "hashes": hashes, "source": TABLE_TEXT})
    write_receipts(client, TableReceiptParams(params.collectionname, params.collection_dataset,
                                            params.op_id, hashes, ["parse", "text"],
                                            {row[0]: int(row[1]) for row in pending}))


def verify_stages(client, params: TableReceiptParams) -> None:
    """Verify durable table text dependencies before recording their completion."""
    import os
    from tasks.text_sources import TABLE_TEXT
    values = {"cd": params.collection_dataset, "hashes": params.hashes, "source": TABLE_TEXT}
    text = client.query(
        "SELECT file_hash, page_id, max(version) FROM text_content "
        "WHERE collection_dataset = {cd:String} AND file_hash IN {hashes:Array(String)} "
        "AND extracted_by = {source:String} GROUP BY file_hash, page_id", parameters=values).result_rows
    expected = {(file_hash, int(page)): int(version) for file_hash, page, version in text}
    if "entities" in params.stages and (os.getenv("NER_URL") or "").strip():
        rows = client.query(
            "SELECT file_hash, page_id FROM nlp_processed FINAL "
            "WHERE collection_dataset = {cd:String} AND file_hash IN {hashes:Array(String)} "
            "AND extracted_by = {source:String}", parameters=values).result_rows
        if not set(expected) <= {(file_hash, int(page)) for file_hash, page in rows}:
            raise RuntimeError("Table entity extraction has incomplete stored output")
    if "regex" in params.stages:
        rows = client.query(
            "SELECT file_hash, page_id, argMax(text_version, scan_version) FROM signal_scanned "
            "WHERE collection_dataset = {cd:String} AND file_hash IN {hashes:Array(String)} "
            "AND extracted_by = {source:String} GROUP BY file_hash, page_id", parameters=values).result_rows
        actual = {(file_hash, int(page)): int(version) for file_hash, page, version in rows}
        if any(actual.get(key) != version for key, version in expected.items()):
            raise RuntimeError("Table signal extraction has incomplete stored output")
        rows = client.query(
            "SELECT file_hash, page_id FROM regex_scanned FINAL "
            "WHERE collection_dataset = {cd:String} AND file_hash IN {hashes:Array(String)} "
            "AND extracted_by = {source:String}", parameters=values).result_rows
        if not set(expected) <= {(file_hash, int(page)) for file_hash, page in rows}:
            raise RuntimeError("Table pattern extraction has incomplete stored output")

    if "embed" in params.stages:
        verify_table_embeddings(client, params, expected)
    if "index_text" in params.stages:
        rows = client.query(
            "SELECT file_hash, page_id, argMax(text_version, receipt_version) FROM ocr_indexed_text "
            "WHERE collection_dataset = {cd:String} AND file_hash IN {hashes:Array(String)} "
            "AND extracted_by = {source:String} GROUP BY file_hash, page_id", parameters=values).result_rows
        actual = {(file_hash, int(page)): int(version) for file_hash, page, version in rows}
        if any(actual.get(key) != version for key, version in expected.items()):
            raise RuntimeError("Table text indexing has incomplete stored output")
    if "index_vectors" in params.stages:
        verify_vector_index(client, params)


def verify_vector_index(client, params: TableReceiptParams) -> None:
    from database.clickhouse import get_server_setting
    from database.manticore import VECTORS, get_manticore_client, shard_knn_dims, vectors_table_from_name
    from tasks.P6_index_data.activities import _scan_indexed_page_rows, vectors_row_id
    model = get_server_setting("embeddings_serving_model") or ""
    rows = client.query(
        "SELECT file_hash, extracted_by, page_id, chunk_index FROM text_chunk_vectors FINAL "
        "WHERE collection_dataset = {cd:String} AND file_hash IN {hashes:Array(String)} "
        "AND embedding_model = {model:String}",
        parameters={"cd": params.collection_dataset, "hashes": params.hashes, "model": model}).result_rows
    expected = {vectors_row_id(params.collection_dataset, file_hash, source, int(page), int(chunk), model)
                for file_hash, source, page, chunk in rows}
    shards = client.query(
        "SELECT file_hash, shard_name FROM index_state FINAL WHERE collection_dataset = {cd:String} "
        "AND file_hash IN {hashes:Array(String)}",
        parameters={"cd": params.collection_dataset, "hashes": params.hashes}).result_rows
    actual = set()
    with get_manticore_client(VECTORS) as connection:
        for shard in sorted({row[1] for row in shards}):
            hashes = [row[0] for row in shards if row[1] == shard]
            table = vectors_table_from_name(shard)
            if shard_knn_dims(table) is None:
                continue
            for page in _scan_indexed_page_rows(connection.cursor(), table,
                                              params.collection_dataset, hashes):
                actual.update(row[0] for row in page)
    if actual != expected:
        raise RuntimeError("Table vector indexing has incomplete stored output")


def verify_table_embeddings(client, params, versions) -> None:
    """Verify expected chunk identities and bodies against their durable vectors."""
    from database.clickhouse import get_server_setting
    from tasks.dataset_config import collection_vectors_enabled
    from tasks.P5_chunk_embed.chunking import chunk_page_text
    from tasks.text_quality import non_linguistic_reason
    from tasks.text_sources import TABLE_TEXT, fetch_text_batch, plan_text_batches
    if not collection_vectors_enabled(params.collectionname):
        return
    model = get_server_setting("embeddings_serving_model") or ""
    rows = client.query(
        "SELECT file_hash, page_id, argMax(text_bytes, version) FROM text_content "
        "WHERE collection_dataset = {cd:String} AND file_hash IN {hashes:Array(String)} "
        "AND extracted_by = {source:String} GROUP BY file_hash, page_id",
        parameters={"cd": params.collection_dataset, "hashes": params.hashes, "source": TABLE_TEXT}).result_rows
    keys = [((file_hash, TABLE_TEXT, int(page)), int(size)) for file_hash, page, size in rows]
    for batch in plan_text_batches(keys):
        expected = {}
        for row in fetch_text_batch(client, params.collection_dataset, batch):
            key = row["file_hash"], int(row["page_id"])
            if versions.get(key) != int(row["text_version"]):
                raise RuntimeError("Table text changed during embedding verification")
            for chunk in chunk_page_text(row["text"]):
                if not non_linguistic_reason(chunk.text):
                    expected[row["file_hash"], row["extracted_by"], int(row["page_id"]), chunk.chunk_index] = chunk.text
        values = {"cd": params.collection_dataset, "keys": batch, "model": model}
        chunks = client.query(
            "SELECT file_hash, extracted_by, page_id, chunk_index, text FROM text_chunks FINAL "
            "WHERE collection_dataset = {cd:String} "
            "AND (file_hash, extracted_by, page_id) IN {keys:Array(Tuple(String, String, UInt32))}",
            parameters=values).result_rows
        actual = {(h, source, int(page), int(index)): text for h, source, page, index, text in chunks}
        vectors = client.query(
            "SELECT file_hash, extracted_by, page_id, chunk_index FROM text_chunk_vectors FINAL "
            "WHERE collection_dataset = {cd:String} AND embedding_model = {model:String} "
            "AND (file_hash, extracted_by, page_id) IN {keys:Array(Tuple(String, String, UInt32))}",
            parameters=values).result_rows
        identities = {(h, source, int(page), int(index)) for h, source, page, index in vectors}
        if actual != expected or identities != set(expected):
            raise RuntimeError("Table embedding has incomplete stored output")
