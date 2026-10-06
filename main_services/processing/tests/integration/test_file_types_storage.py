"""Verify filename inputs and SQLite text in a migrated collection."""

from pathlib import Path
import sqlite3
import pytest
from .test_text_storage_migration import storage, migrate
from tasks.P2_execute_plan.activities import get_plan_items_metadata, GetPlanItemsMetadataParams
from tasks.P3_parse_files.parse_table import parse_table_and_store, ParseTableParams

pytestmark = pytest.mark.integration


@pytest.fixture
def collection(storage):
    name, client, cluster, folder = storage
    migrate(client, cluster, folder)
    return name, client


def flush(client):
    pass


def test_plan_metadata_keeps_bounded_names(collection):
    name, client = collection
    client.command("INSERT INTO processing_plan_hits (collection_dataset, plan_hash, item_hash) VALUES ('ds', 'plan', 'hash')")
    client.command("INSERT INTO blobs (collection_dataset, blob_hash, blob_size_bytes) VALUES ('ds', 'hash', 42)")
    client.command("INSERT INTO vfs_files (collection_dataset, path, hash) VALUES "
                   "('ds', '/one.txt', 'hash'), ('ds', '/two.txt', 'hash'), ('ds', '/three.csv', 'hash')")
    items = get_plan_items_metadata(GetPlanItemsMetadataParams(name, 'ds', 'plan'))
    assert len(items) == 1 and items[0]['file_size_bytes'] == 42
    assert {Path(n).suffix for n in items[0]['file_names']} == {'.txt', '.csv'}


def test_sqlite_text_and_shared_claim(collection, tmp_path):
    name, client = collection
    path = tmp_path / 'hash'
    database = sqlite3.connect(path)
    database.execute('CREATE TABLE contacts (name TEXT, email TEXT, attachment BLOB)')
    database.execute('INSERT INTO contacts VALUES (?, ?, ?)', ('stapler', 'person@example.org', b'private binary'))
    database.commit()
    database.close()
    params = ParseTableParams(name, 'first', 'hash', str(path), 900,
                             mime_types=['application/vnd.sqlite3'], sniff_mime_type='application/vnd.sqlite3')
    assert parse_table_and_store(params)['status'] == 'ok'
    flush(client)
    text = client.query("SELECT text FROM text_content FINAL WHERE collection_dataset = 'first' AND extracted_by = 'table_text'").result_rows
    joined = ''.join(row[0] for row in text)
    assert '[contacts]' in joined and 'stapler' in joined and 'person@example.org' in joined
    assert 'BLOB' not in joined and 'private binary' not in joined
    assert client.query("SELECT cell_text FROM table_cells FINAL WHERE column_id = 3 AND source_row = 2").result_rows == [('[BLOB 14 bytes]',)]
    params.collection_dataset = 'second'
    assert parse_table_and_store(params)['deduped']
    flush(client)
    assert client.query("SELECT text FROM text_content FINAL WHERE collection_dataset = 'second' AND extracted_by = 'table_text'").result_rows == text


def test_failed_stream_preserves_another_dataset_grid(collection, tmp_path, monkeypatch):
    from tasks.P3_parse_files import parse_table, table_readers
    name, client = collection
    client.command("INSERT INTO table_documents (collection_dataset, hash, status, reader, reader_version) "
                   "VALUES ('second', 'shared', 'ok', 'calamine', 1)")
    client.command("INSERT INTO table_cells (file_hash, sheet_id, column_id, row_id, source_row, cell_kind, cell_text) "
                   "VALUES ('shared', 0, 1, 1, 1, 'text', 'existing cell')")
    before = client.query("SELECT cell_text FROM table_cells FINAL WHERE file_hash = 'shared'").result_rows
    monkeypatch.setattr(parse_table, '_existing_parse', lambda *a: None)
    monkeypatch.setattr(parse_table, '_record_skip', lambda *a: None)
    monkeypatch.setattr(parse_table, 'INSERT_BATCH_CELLS', 3)
    def read(*args, **kwargs):
        if args[1] == 'xlsx_stream':
            for column in range(1, 4):
                yield 0, 'Sheet', table_readers.RawCell(1, column, 'text', 'discarded')
            raise ValueError('stream failed after a flush')
        raise ValueError('fallback failed')
    monkeypatch.setattr(table_readers, 'read_cells', read)
    params = ParseTableParams(name, 'first', 'shared', str(tmp_path / 'input.xlsx'), 900,
                             mime_types=['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'])
    assert parse_table_and_store(params)['status'] == 'failed'
    flush(client)
    assert client.query("SELECT cell_text FROM table_cells FINAL WHERE file_hash = 'shared'").result_rows == before
    assert client.query("SELECT status FROM table_documents FINAL WHERE collection_dataset = 'second'").result_rows == [('ok',)]
