"""The vector update selects incomplete or stale vectors, and the embedding cleans them up.

It needs a ClickHouse server. `HOOVER4_TEST_CLICKHOUSE_HOST` points the test at a server
other than the stack's, with the `default` user and no password.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.integration

MODEL = "e5-test"
CD = "vec_ds"


@pytest.fixture
def collection(monkeypatch):
    from database import clickhouse

    host = os.environ.get("HOOVER4_TEST_CLICKHOUSE_HOST")
    if host:
        monkeypatch.setattr(clickhouse, "CLICKHOUSE_HOST", host)
        monkeypatch.setattr(clickhouse, "CLICKHOUSE_USER", "default")
        monkeypatch.setattr(clickhouse, "CLICKHOUSE_PASS", "")
    name = "p97vec" + uuid.uuid4().hex[:8]
    clickhouse.migrate_collection(name)
    yield name
    with clickhouse.get_collection_client(name) as client:
        client.command(f"DROP DATABASE IF EXISTS `{clickhouse.collection_db_name(name)}`")


def _now_ns() -> int:
    return int(datetime.now(timezone.utc).timestamp()) * 1_000_000_000


def _text(client, file_hash, page, version, text="a passage of ordinary words"):
    client.insert("text_content", [[CD, file_hash, "tika", page, text, len(text), version]],
                  column_names=["collection_dataset", "file_hash", "extracted_by", "page_id",
                                "text", "text_bytes", "version"])


def _vfs(client, file_hash, deleted=0):
    # The path is the sort key of `vfs_files`, so each file needs its own.
    client.insert("vfs_files", [[CD, file_hash, f"/{file_hash}", deleted]],
                  column_names=["collection_dataset", "hash", "path", "is_deleted"])


def _vector(client, file_hash, page, chunk, written):
    client.insert("text_chunk_vectors", [[CD, file_hash, "tika", page, chunk, MODEL, 2, [0.1, 0.2], written, written]],
                  column_names=["collection_dataset", "file_hash", "extracted_by", "page_id", "chunk_index",
                                "embedding_model", "dims", "embedding", "created_at", "updated_at"])


def _chunk(client, file_hash, page, chunk, written):
    client.insert("text_chunks", [[CD, file_hash, "tika", page, chunk, 0, 5, "words", 5, written, written]],
                  column_names=["collection_dataset", "file_hash", "extracted_by", "page_id", "chunk_index",
                                "index_start", "index_end", "text", "text_bytes", "created_at", "updated_at"])


def _selected(client):
    from tasks.P_admin.updates.selectors import vector_pending_sql

    rows = client.query(f"SELECT hash FROM ({vector_pending_sql()}) ORDER BY hash",
                        parameters={"cd": CD, "model": MODEL}).result_rows
    return [row[0] for row in rows]


def test_the_selector_finds_incomplete_stale_and_removed_vectors(collection):
    from database.clickhouse import get_collection_client
    from tasks.P5_chunk_embed.activities import EMPTY_PAGE_RECEIPT

    now = _now_ns()
    later = datetime.now(timezone.utc) + timedelta(seconds=5)
    earlier = later - timedelta(hours=1)
    with get_collection_client(collection) as client:
        for file_hash in "abcdefg":
            _vfs(client, file_hash, deleted=1 if file_hash == "g" else 0)
        # a: current text and current vectors.
        _text(client, "a", 1, now)
        _chunk(client, "a", 1, 0, later)
        _vector(client, "a", 1, 0, later)
        # b: no vector and no empty-page receipt.
        _text(client, "b", 1, now)
        # c: vectors older than the text.
        _text(client, "c", 1, now)
        _vector(client, "c", 1, 0, earlier)
        # d: three current chunk rows and two vectors.
        _text(client, "d", 1, now)
        for chunk in range(3):
            _chunk(client, "d", 1, chunk, later)
        for chunk in range(2):
            _vector(client, "d", 1, chunk, later)
        # e: a vector of a page that the text no longer has.
        _text(client, "e", 1, now)
        _vector(client, "e", 1, 0, later)
        _vector(client, "e", 2, 0, later)
        # f: text of an earlier migration, version 0, with vectors.
        _text(client, "f", 1, 0)
        _vector(client, "f", 1, 0, earlier)
        # g: a deleted file.
        _text(client, "g", 1, now)
        assert _selected(client) == ["b", "c", "d", "e"]
        client.insert("processing_output_receipts",
                      [[CD, "b", EMPTY_PAGE_RECEIPT, "tika:1", f"{MODEL}:{now}", "embed", "op"]],
                      column_names=["collection_dataset", "file_hash", "output_kind", "output_identity",
                                    "fingerprint", "stage", "op_id"])
        assert _selected(client) == ["c", "d", "e"]
        # A new text version needs a new receipt.
        _text(client, "b", 1, now + 2_000_000_000)
        assert _selected(client) == ["b", "c", "d", "e"]


def test_the_embedding_deletes_obsolete_chunks_and_removed_pages(collection):
    from database.clickhouse import get_collection_client
    from tasks.P5_chunk_embed import activities as p5
    from tasks.P5_chunk_embed.params import ChunkEmbedParams

    now = _now_ns()
    later = datetime.now(timezone.utc) + timedelta(seconds=5)
    with get_collection_client(collection) as client:
        _vfs(client, "e")
        _text(client, "e", 1, now)
        for chunk in range(3):
            _chunk(client, "e", 1, chunk, later)
            _vector(client, "e", 1, chunk, later)
        _chunk(client, "e", 2, 0, later)
        _vector(client, "e", 2, 0, later)
        # The current text of page 1 has two chunks, and page 2 is gone.
        p5._delete_chunk_keys(client, CD, MODEL, {("e", "tika", 1, 2)})
        assert p5._delete_removed_pages(client, CD, MODEL, ["e"]) == 1
        vectors = client.query("SELECT page_id, chunk_index FROM text_chunk_vectors FINAL ORDER BY 1, 2").result_rows
        chunks = client.query("SELECT page_id, chunk_index FROM text_chunks FINAL ORDER BY 1, 2").result_rows
        assert vectors == [(1, 0), (1, 1)]
        assert chunks == [(1, 0), (1, 1)]
        p5._write_empty_page_receipts(client, ChunkEmbedParams(collection, CD, "plan", ["e"], "op"),
                                      MODEL, {("e", "tika", 3, now)})
        rows = client.query("SELECT output_kind, output_identity, fingerprint FROM processing_output_receipts").result_rows
        assert rows == [(p5.EMPTY_PAGE_RECEIPT, "tika:3", f"{MODEL}:{now}")]


def test_the_dependency_revision_is_the_newest_ended_text_writer(monkeypatch):
    """Only an ended update operation with a text writer step changes the revision."""
    from database import clickhouse, operations
    from database.processing_updates import input_revisions

    host = os.environ.get("HOOVER4_TEST_CLICKHOUSE_HOST")
    if host:
        monkeypatch.setattr(clickhouse, "CLICKHOUSE_HOST", host)
        monkeypatch.setattr(clickhouse, "CLICKHOUSE_USER", "default")
        monkeypatch.setattr(clickhouse, "CLICKHOUSE_PASS", "")
        # A throwaway server holds only this test's global database.
        monkeypatch.setattr(clickhouse, "GLOBAL_DB", "p97_global_" + uuid.uuid4().hex[:8])
    else:
        pytest.skip("the test writes operation rows, so it needs a throwaway server")
    clickhouse._cluster().migrate(clickhouse.GLOBAL_DB, clickhouse.GLOBAL_MIGRATIONS_PATH, cluster_name=None,
                                  create_db_if_no_exists=True, multi_statement=True)
    try:
        def op(op_id, steps, state_name, minute):
            row = operations.create_operation("update_dataset", "c", "c_d", detail={"steps": steps},
                                              op_id=op_id, check_lock=False)
            if state_name != "pending":
                operations.update_operation(op_id, base_row=row, state=state_name,
                                            finished_at=datetime(2026, 11, 19, 10, minute))

        op("ocr-1", ["ocr"], "errored", 1)
        assert input_revisions()["dependencies"] == {"c_d": "ocr-1"}
        op("ner-1", ["entities"], "finished", 2)
        op("main-live", ["unfinished"], "running", 3)
        assert input_revisions()["dependencies"] == {"c_d": "ocr-1"}
        op("main-1", ["failed_files", "search_terms"], "cancelled", 4)
        assert input_revisions()["dependencies"] == {"c_d": "main-1"}
    finally:
        with clickhouse.get_global_client() as client:
            client.command(f"DROP DATABASE IF EXISTS `{clickhouse.GLOBAL_DB}`")
