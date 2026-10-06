"""Verify current text and planner sizes against unmerged storage versions."""

import ast
from pathlib import Path

import pytest

from tasks.P3_parse_files.parse_common import insert_text_sources
from tasks.text_sources import fetch_text_batch
from .test_text_storage_migration import storage, migrate

pytestmark = pytest.mark.integration


def test_every_pipeline_reader_selects_latest_unmerged_text_and_size(storage):
    _, client, cluster, folder = storage
    migrate(client, cluster, folder)
    client.command('SYSTEM STOP MERGES text_content')
    columns = ['collection_dataset', 'file_hash', 'extracted_by', 'page_id', 'text', 'text_bytes', 'version']
    client.insert('text_content', [
        ['dataset', 'file', 'raw_text', 1, 'old long content', 16, 1],
        ['dataset', 'file', 'raw_text', 1, 'new', 3, 2],
        ['dataset', 'file', 'raw_text', 2, 'second page', 11, 2],
        ['other', 'file', 'raw_text', 1, 'other dataset', 13, 9],
    ], column_names=columns)
    keys = [('file', 'raw_text', 1), ('file', 'raw_text', 2)]
    texts = fetch_text_batch(client, 'dataset', keys)
    assert [row['text'] for row in texts] == ['new', 'second page']
    sizes = {row['page_id']: len(row['text'].encode()) for row in texts}
    params = {'collection_dataset': 'dataset', 'cd': 'dataset', 'item_hashes': ['file'],
              'hashes': ['file'], 'nlp_model': 'test', 'rule_set_version': 1,
              'after_hash': '', 'after_by': '', 'after_page': 0, 'page_rows': 100}
    tasks = Path(__file__).resolve().parents[2] / 'tasks'
    queries = []
    for relative in ('P4_extract_entities/activities.py', 'P4_extract_entities/scan_regex_entities.py',
                     'P5_chunk_embed/activities.py', 'P6_index_data/activities.py',
                     'P6_index_data/shard_planner.py'):
        tree = ast.parse((tasks / relative).read_text())
        selected = []
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call) or not call.args or not isinstance(call.args[0], ast.Constant):
                continue
            sql = call.args[0].value
            if not isinstance(sql, str) or 'FROM text_content' not in sql:
                continue
            if 'argMax(text' in sql:
                selected.append(sql)
        assert selected, relative
        for sql in selected:
            rows = client.query_arrow(sql, parameters=params).to_pylist()
            assert rows, (relative, sql)
            for row in rows:
                if 'page_id' in row:
                    assert len(rows) == 2
                    if 'text_bytes' in row:
                        assert row['text_bytes'] == sizes[row['page_id']]
                    if 'text' in row:
                        assert len(row['text'].encode()) == sizes[row['page_id']]
                elif 'text_bytes' in row:
                    assert row['text_bytes'] == sum(sizes.values())
                elif 'segments' in row:
                    assert row['segments'] == 2
            queries.append((relative, sql))
    assert len(queries) == 6


def test_email_sources_share_read_and_insert_and_clear_obsolete_pages(storage, monkeypatch):
    collection, client, cluster, folder = storage
    migrate(client, cluster, folder)
    from database import clickhouse
    from contextlib import contextmanager

    calls = []

    class Recorder:
        def query(self, *args, **kwargs):
            calls.append('query')
            return client.query(*args, **kwargs)

        def insert_arrow(self, *args, **kwargs):
            calls.append('insert')
            return client.insert_arrow(*args, **kwargs)

        def command(self, *args, **kwargs):
            calls.append('delete')
            return client.command(*args, **kwargs)

    @contextmanager
    def recording(_collection):
        yield Recorder()

    monkeypatch.setattr(clickhouse, 'get_collection_client', recording)
    sources = {source: [(1, source), (2, 'old page')]
               for source in ('email_parser', 'email_html', 'email_rtf', 'email_richtext')}
    assert insert_text_sources(collection, 'dataset', 'file', sources, min_chars=1) == 8
    assert calls == ['query', 'insert']
    calls.clear()
    sources = {source: [(1, source)] for source in sources}
    assert insert_text_sources(collection, 'dataset', 'file', sources, min_chars=1) == 4
    assert calls == ['query', 'insert', 'delete', 'delete', 'delete', 'delete']
    assert client.query('SELECT count() FROM text_content FINAL').result_rows == [(4,)]


def test_ocr_versions_and_tombstones_keep_one_complete_row(storage):
    import shutil
    from database import clickhouse as db
    from tasks.P3_parse_files.parse_ocr_pdf import RunOcrPdfParams, _already_done
    from tasks.P_admin import ocr_languages

    _, client, cluster, folder = storage
    migrate(client, cluster, folder)
    client.command("INSERT INTO pdf_ocr_results "
                   "(collection_dataset,pdf_hash,engine,languages,blob_key,blob_hash,is_deleted) VALUES "
                   "('dataset','existing','tesseract','eng','legacy','legacy-hash',0),"
                   "('dataset','deleted','easyocr','en','deleted-legacy','deleted-hash',1)")
    shutil.copy(Path(db.COLLECTION_MIGRATIONS_PATH) / '00053_pdf_ocr_version.sql', folder)
    cluster.migrate(client.database, folder, cluster_name=None, create_db_if_no_exists=True, multi_statement=True)
    assert 'DateTime64(9)' in client.query('SHOW CREATE TABLE pdf_ocr_results').result_rows[0][0]
    assert client.query("SELECT count() FROM pdf_ocr_results WHERE pdf_hash IN ('existing','deleted')").result_rows == [(2,)]
    client.command('SYSTEM STOP MERGES pdf_ocr_results')
    columns = ['collection_dataset', 'pdf_hash', 'engine', 'languages', 'blob_key', 'blob_hash',
               'page_count', 'size_bytes', 'run_time_ms', 'is_deleted', 'updated_at']
    client.command("INSERT INTO pdf_ocr_results (" + ','.join(columns) + ") VALUES "
                   "('dataset','pdf','tesseract','eng','old','hash-old',1,10,20,0,'2026-01-01 00:00:00.001'),"
                   "('dataset','pdf','tesseract','eng','new','hash-new',2,30,40,0,'2026-01-01 00:00:00.002')")
    params = RunOcrPdfParams('collection', 'dataset', 'pdf', 'unused', 'tesseract', 900)
    assert _already_done(client, params, 'eng')
    tree = ast.parse(Path(ocr_languages.__file__).read_text())
    statements = [call.args[0].value for call in ast.walk(tree) if isinstance(call, ast.Call)
                  and call.args and isinstance(call.args[0], ast.Constant)
                  and isinstance(call.args[0].value, str)]
    tombstone = next(sql for sql in statements if sql.startswith('INSERT INTO pdf_ocr_results'))
    client.command(tombstone, parameters={'cd': 'dataset', 'en': 'tesseract', 'la': 'eng'})
    assert not _already_done(client, params, 'eng')
    result = client.query('SELECT argMax((blob_key, blob_hash, page_count, size_bytes, run_time_ms, is_deleted), updated_at) '
                          "FROM pdf_ocr_results WHERE pdf_hash = 'pdf' GROUP BY pdf_hash").result_rows
    result = [row[0] for row in result]
    assert result == [('new', 'hash-new', 2, 30, 40, 1)]
    deletion = next(sql for sql in statements if sql.startswith('SELECT pdf_hash, latest.1'))
    assert sorted(client.query(deletion, parameters={'cd': 'dataset', 'en': 'tesseract', 'la': 'eng'}).result_rows) == [('existing', 'legacy'), ('pdf', 'new')]


def test_clickhouse_check_failure_isolates_one_file(storage):
    import pyarrow as pa
    from database.clickhouse import insert_parser_arrow
    from tasks.P3_parse_files.batch_runner import run_batch

    _, client, _, _ = storage
    client.command('CREATE TABLE parser_batch_probe (value UInt16, CONSTRAINT accepted CHECK value != 37) '
                   'ENGINE = MergeTree ORDER BY value')

    def parse(value):
        insert_parser_arrow(client, 'parser_batch_probe',
                            pa.table({'value': pa.array([value], type=pa.uint16())}))
        return value

    result = run_batch('detect_mime_batch', range(100), key=str, size=lambda _: 1,
                       step=parse, task_name='parse')
    assert result.results[37].status == 'failed'
    assert sum(row.status == 'ok' for row in result.results) == 99
    assert client.query('SELECT count(), uniqExact(value) FROM parser_batch_probe').result_rows == [(99, 99)]


def test_term_fields_share_a_read_and_two_waited_writes(storage, monkeypatch):
    from contextlib import contextmanager
    from database import clickhouse as db
    from tasks.P6_index_data.string_term_encodings import get_string_term_ids_by_field, hash_string_to_uint63

    collection, client, _, _ = storage
    events = []

    class Recorder:
        def query_arrow(self, *args, **kwargs):
            events.append('read')
            return client.query_arrow(*args, **kwargs)

        def insert_arrow(self, table, data, **kwargs):
            events.append(table)
            assert kwargs['settings'] == {'async_insert': 1, 'wait_for_async_insert': 1}
            return client.insert_arrow(table, data, **kwargs)

    @contextmanager
    def recording(_collection):
        yield Recorder()

    monkeypatch.setattr(db, 'get_collection_client', recording)
    fields = {'ner': {'shared', 'a' * 140000}, 'email_address': {'shared', 'quote"\\\n'}, 'empty': set()}
    ids = get_string_term_ids_by_field(collection, 'dataset', fields)
    assert ids == {field: {value: hash_string_to_uint63(value) for value in values}
                   for field, values in fields.items()}
    assert events == ['read', 'string_term_text_to_id', 'string_term_id_to_text']
    events.clear()
    assert get_string_term_ids_by_field(collection, 'dataset', fields) == ids
    assert events == ['read']


def test_production_migration_applies_the_readiness_marker(storage):
    from database import clickhouse as db
    collection, client, _, _ = storage
    assert db.migrate_collection(collection) == client.database
    assert client.query('EXISTS TABLE ocr_pdf_version_ready').result_rows == [(1,)]


def test_regex_values_and_json_come_from_one_rule_version(storage):
    from tasks.P6_index_data import activities
    _, client, _, _ = storage
    columns = ['collection_dataset', 'file_hash', 'extracted_by', 'page_id', 'rule_set_version',
               'entity_type', 'entity_values', 'entity_value_json']
    client.insert('regex_entity_hit', [
        ['dataset', 'file', 'raw_text', 1, 1, 'email', ['old'], ['old-json']],
        ['dataset', 'file', 'raw_text', 1, 2, 'email', ['new'], ['new-json']],
    ], column_names=columns)
    tree = ast.parse(Path(activities.__file__).read_text())
    sql = next(call.args[0].value for call in ast.walk(tree) if isinstance(call, ast.Call)
               and call.args and isinstance(call.args[0], ast.Constant)
               and isinstance(call.args[0].value, str)
               and 'argMax((entity_values, entity_value_json)' in call.args[0].value)
    rows = client.query_arrow(sql, parameters={'collection_dataset': 'dataset', 'item_hashes': ['file']}).to_pylist()
    assert len(rows) == 1
    assert rows[0]['entity_values'] == ['new']
    assert rows[0]['entity_value_json'] == ['new-json']
