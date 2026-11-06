"""Verify table generation publication and exact receipts against ClickHouse."""

import uuid
from pathlib import Path

import pytest
from temporalio.exceptions import ApplicationError

from database import clickhouse
from tasks.P3_parse_files import parse_table, table_generations
from tasks.P_admin.activities import CollectionDatabaseParams, sweep_orphan_table_cells
from tasks.P_admin.updates import table_receipts

pytestmark = pytest.mark.integration


@pytest.fixture
def collection(monkeypatch):
    name = "publication_" + uuid.uuid4().hex[:12] + "a"
    clickhouse.migrate_collection(name)
    monkeypatch.setattr(table_generations, "send_command", table_generations.apply_table_generation_command)
    try:
        yield name
    finally:
        client = clickhouse._client("default")
        client.command(f"DROP DATABASE {clickhouse.collection_db_name(name)}")
        client.close()


def parse(collection, tmp_path, dataset, monkeypatch):
    path = tmp_path / "source.csv"
    path.write_text("Name,Count\nalpha,10\nbeta,20\n")
    monkeypatch.setattr(parse_table, "_existing_parse", lambda *_args: None)
    result = parse_table.parse_table_and_store(parse_table.ParseTableParams(
        collection, dataset, "source", str(path), 900, mime_types=["text/csv"], file_names=["source.csv"]))
    assert result["status"] == "ok"


def test_active_generation_survives_other_publication_and_dataset_removal(collection, tmp_path, monkeypatch):
    first = table_generations.GenerationCommand(collection, "source", "allocate", "paused-writer")
    active = table_generations.apply_table_generation_command(first)
    parse(collection, tmp_path, "dataset_a", monkeypatch)
    with clickhouse.get_collection_client(collection) as client:
        client.insert("table_cells", [["source", 0, 1, 1, "paused", active]],
                      column_names=["file_hash", "sheet_id", "column_id", "row_id", "cell_text", "generation"])
        published = client.query("SELECT generation FROM table_documents FINAL").result_rows[0][0]
        assert published > active
        sweep_orphan_table_cells(CollectionDatabaseParams(collection))
        state = client.query("SELECT state FROM table_generation_owners FINAL WHERE generation = {g:UInt32}",
                             parameters={"g": active}).result_rows
        assert state == [("writing",)]
        assert client.query("SELECT count() FROM table_cells FINAL WHERE generation = {g:UInt32}",
                            parameters={"g": active}).result_rows[0][0] == 1
        from tasks.P_admin.activities import PurgeDatasetParams, purge_dataset_from_clickhouse
        purge_dataset_from_clickhouse(PurgeDatasetParams(collection, "unrelated"))
        sweep_orphan_table_cells(CollectionDatabaseParams(collection))
        assert client.query("SELECT count() FROM table_cells FINAL WHERE generation = {g:UInt32}",
                            parameters={"g": published}).result_rows[0][0] > 0


def test_stale_publication_and_retired_publication_fail(collection, tmp_path, monkeypatch):
    parse(collection, tmp_path, "dataset_a", monkeypatch)
    with clickhouse.get_collection_client(collection) as client:
        table = client.query_arrow("SELECT * EXCEPT updated_at FROM table_documents FINAL")
        old_generation = int(table.to_pylist()[0]["generation"])
    parse(collection, tmp_path, "dataset_a", monkeypatch)
    import pyarrow as pa
    buffer = pa.BufferOutputStream()
    with pa.ipc.new_stream(buffer, table.schema) as stream:
        stream.write_table(table)
    command = table_generations.GenerationCommand(collection, "source", "publish",
        generation=old_generation, manifest=buffer.getvalue().to_pybytes())
    with pytest.raises(ApplicationError, match="newer"):
        table_generations.apply_table_generation_command(command)
    table_generations.apply_table_generation_command(table_generations.GenerationCommand(
        collection, "source", "retire", generation=old_generation))
    with pytest.raises(ApplicationError, match="cannot publish"):
        table_generations.apply_table_generation_command(command)


def test_exact_page_receipts_and_pinned_table_identity(collection, tmp_path, monkeypatch):
    parse(collection, tmp_path, "dataset_a", monkeypatch)
    with clickhouse.get_collection_client(collection) as client:
        generation = int(client.query("SELECT generation FROM table_documents FINAL").result_rows[0][0])
        client.insert("text_content", [["dataset_a", "source", "table_text", 1, "first", 5, 100],
                                       ["dataset_a", "source", "table_text", 2, "second", 6, 101]],
                      column_names=["collection_dataset", "file_hash", "extracted_by", "page_id", "text", "text_bytes", "version"])
        params = table_receipts.TableReceiptParams(collection, "dataset_a", "operation", ["source"],
                                                   ["index_text"], {"source": generation})
        client.insert("ocr_indexed_text", [["dataset_a", "source", "table_text", 1, 100]],
                      column_names=["collection_dataset", "file_hash", "extracted_by", "page_id", "text_version"])
        with pytest.raises(RuntimeError, match="incomplete stored output"):
            table_receipts.write_receipts(client, params)
        client.insert("ocr_indexed_text", [["dataset_a", "source", "table_text", 2, 101]],
                      column_names=["collection_dataset", "file_hash", "extracted_by", "page_id", "text_version"])
        table_receipts.write_receipts(client, params)
        assert client.query("SELECT count() FROM processing_output_receipts FINAL").result_rows[0][0] == 1
        params.generations["source"] += 1
        with pytest.raises(RuntimeError, match="changed during"):
            table_receipts.write_receipts(client, params)


def test_missing_columns_cannot_replace_a_published_table(collection, tmp_path, monkeypatch):
    parse(collection, tmp_path, "dataset_a", monkeypatch)
    with clickhouse.get_collection_client(collection) as client:
        previous = int(client.query("SELECT generation FROM table_documents FINAL").result_rows[0][0])
    original = table_generations.apply_table_generation_command

    def lose_columns(command):
        if command.action == "publish" and command.generation > previous:
            assert command.expected_columns > 0
            with clickhouse.get_collection_client(collection) as client:
                client.command("DELETE FROM table_columns WHERE hash = {hash:String} "
                               "AND generation = {generation:UInt32} SETTINGS mutations_sync = 2",
                               parameters={"hash": command.file_hash, "generation": command.generation})
        return original(command)

    monkeypatch.setattr(table_generations, "send_command", lose_columns)
    with pytest.raises(RuntimeError, match="incomplete stored columns"):
        parse(collection, tmp_path, "dataset_a", monkeypatch)
    with clickhouse.get_collection_client(collection) as client:
        assert client.query("SELECT generation FROM table_documents FINAL").result_rows == [(previous,)]
        assert client.query("SELECT count() FROM table_columns FINAL WHERE generation = {generation:UInt32}",
                            parameters={"generation": previous}).result_rows[0][0] > 0
        assert client.query("SELECT state FROM table_generation_owners FINAL WHERE generation > {generation:UInt32}",
                            parameters={"generation": previous}).result_rows == [("writing",)]


def test_dedup_reparses_a_legacy_source_with_incomplete_column_metadata(collection, tmp_path, monkeypatch):
    existing_lookup = parse_table._existing_parse
    parse(collection, tmp_path, "dataset_a", monkeypatch)
    with clickhouse.get_collection_client(collection) as client:
        previous = int(client.query("SELECT generation FROM table_documents FINAL").result_rows[0][0])
        client.command("DELETE FROM table_columns WHERE column_id = 2 SETTINGS mutations_sync = 2")
        assert not table_generations.complete_column_coverage(client, "dataset_a", "source", previous)
    monkeypatch.setattr(parse_table, "_existing_parse", existing_lookup)
    result = parse_table.parse_table_and_store(parse_table.ParseTableParams(
        collection, "dataset_b", "source", str(tmp_path / "source.csv"), 900,
        mime_types=["text/csv"], file_names=["source.csv"]))
    assert result["status"] == "ok" and not result.get("deduped")
    with clickhouse.get_collection_client(collection) as client:
        generation = int(client.query("SELECT generation FROM table_documents FINAL WHERE collection_dataset = 'dataset_b'").result_rows[0][0])
        assert generation > previous
        assert table_generations.complete_column_coverage(client, "dataset_b", "source", generation)


def test_interrupted_physical_deletion_resumes_after_retirement(collection, tmp_path, monkeypatch):
    parse(collection, tmp_path, "dataset_a", monkeypatch)
    with clickhouse.get_collection_client(collection) as client:
        retired = int(client.query("SELECT generation FROM table_documents FINAL").result_rows[0][0])
    parse(collection, tmp_path, "dataset_a", monkeypatch)
    assert table_generations.apply_table_generation_command(table_generations.GenerationCommand(
        collection, "source", "retire", generation=retired)) == retired
    with clickhouse.get_collection_client(collection) as client:
        assert client.query("SELECT count() FROM table_cells FINAL WHERE generation = {g:UInt32}",
                            parameters={"g": retired}).result_rows[0][0] > 0
        command = client.command

        def interrupt(sql, *args, **kwargs):
            if sql.startswith("DELETE FROM table_sheets"):
                raise RuntimeError("injected physical deletion failure")
            return command(sql, *args, **kwargs)

        monkeypatch.setattr(client, "command", interrupt)
        with pytest.raises(RuntimeError, match="injected physical"):
            table_generations.delete_retired_generation(client, "source", retired)
        assert client.query("SELECT count() FROM processing_output_receipts WHERE stage = 'deleted'").result_rows[0][0] == 0
        monkeypatch.setattr(client, "command", command)
        table_generations.delete_retired_generation(client, "source", retired)
        assert client.query("SELECT count() FROM processing_output_receipts WHERE stage = 'deleted'").result_rows[0][0] == 1
        assert client.query("SELECT count() FROM table_columns FINAL WHERE generation = {g:UInt32}",
                            parameters={"g": retired}).result_rows[0][0] == 0
        assert client.query("SELECT count() FROM table_cells FINAL WHERE generation > {g:UInt32}",
                            parameters={"g": retired}).result_rows[0][0] > 0


def test_sqlite_text_copy_finishes_before_publication_and_recovers_missing_text(collection, tmp_path, monkeypatch):
    import sqlite3
    from tasks.P3_parse_files import parse_common, table_text
    path = tmp_path / "source.sqlite"
    with sqlite3.connect(path) as source:
        source.execute("CREATE TABLE source (" + ",".join(f"c{index} TEXT" for index in range(1, 351)) + ")")
        source.execute("INSERT INTO source VALUES (" + ",".join(["?"] * 350) + ")",
                       [""] * 349 + ["Ada Example at column 350"])
    params = lambda dataset: parse_table.ParseTableParams(collection, dataset, "sqlite_source", str(path), 900,
        mime_types=["application/vnd.sqlite3"], sniff_mime_type="application/vnd.sqlite3", file_names=["source.sqlite"])
    assert parse_table.parse_table_and_store(params("dataset_a"))["status"] == "ok"
    original = parse_common.insert_text_pages

    def interrupt(collection_name, dataset, *args, **kwargs):
        if dataset == "dataset_b":
            raise RuntimeError("injected SQLite text copy failure")
        return original(collection_name, dataset, *args, **kwargs)

    monkeypatch.setattr(parse_common, "insert_text_pages", interrupt)
    with pytest.raises(RuntimeError, match="injected SQLite"):
        parse_table.parse_table_and_store(params("dataset_b"))
    with clickhouse.get_collection_client(collection) as client:
        assert client.query("SELECT count() FROM table_documents FINAL WHERE collection_dataset = 'dataset_b'").result_rows[0][0] == 0
    monkeypatch.setattr(parse_common, "insert_text_pages", original)
    assert parse_table.parse_table_and_store(params("dataset_b"))["deduped"]
    with clickhouse.get_collection_client(collection) as client:
        generation = int(client.query("SELECT generation FROM table_documents FINAL WHERE collection_dataset = 'dataset_b'").result_rows[0][0])
        assert table_text.complete_table_text(client, "dataset_b", "sqlite_source", generation)
        assert "Ada Example at column 350" in "".join(row[0] for row in client.query(
            "SELECT text FROM text_content FINAL WHERE collection_dataset = 'dataset_b'").result_rows)
        client.command("DELETE FROM text_content WHERE collection_dataset = 'dataset_b' SETTINGS mutations_sync = 2")
        receipt = table_receipts.TableReceiptParams(collection, "dataset_b", "operation", ["sqlite_source"],
                                                   ["parse", "text"], {"sqlite_source": generation})
        with pytest.raises(RuntimeError, match="incomplete required text"):
            table_receipts.write_receipts(client, receipt)
    assert parse_table.parse_table_and_store(params("dataset_b"))["deduped"]
    with clickhouse.get_collection_client(collection) as client:
        table_receipts.write_receipts(client, receipt)


@pytest.mark.parametrize("name,mime", [("ordinary.tsv", "text/plain"), ("download", "text/tab-separated-values")])
def test_short_tsv_download_keeps_logical_delimiter(collection, tmp_path, name, mime):
    from tasks.P3_parse_files.table_formats import READER_VERSION
    path = tmp_path / "downloadedhash"
    path.write_text("Tsvupgradeunique\tOrchid\nGamma\tMaple\nDelta\tCedar\n")
    result = parse_table.parse_table_and_store(parse_table.ParseTableParams(
        collection, "dataset", "tsv", str(path), 900, mime_types=[mime], file_names=[name]))
    assert result["status"] == "ok"
    with clickhouse.get_collection_client(collection) as client:
        assert client.query("SELECT reader_version, row_count, column_count, status FROM table_documents FINAL").result_rows == [(READER_VERSION, 3, 2, "ok")]
        generation = client.query("SELECT generation FROM table_documents FINAL").result_rows[0][0]
        assert client.query("SELECT count() FROM table_cells FINAL WHERE generation = {g:UInt32}",
                            parameters={"g": generation}).result_rows[0][0] == 6
