"""Verify parser storage batches, file isolation and heartbeat completion."""

import pyarrow as pa
import pytest
from temporalio.exceptions import ApplicationError

from database.clickhouse import insert_parser_arrow
from tasks.P3_parse_files.batch_runner import run_batch
from tasks.P3_parse_files.insert_batch import parser_insert_batch


class Client:
    def __init__(self, bad=None):
        self.calls = []
        self.rows = []
        self.bad = bad

    def insert_arrow(self, table, rows, *, settings):
        self.calls.append((table, rows.num_rows, settings))
        values = rows.column('value').to_pylist()
        if self.bad in values:
            raise ApplicationError('Refused row', type='BadRow', non_retryable=True)
        self.rows.extend((table, value) for value in values)


def test_hundred_files_write_once_per_table_after_parsing(monkeypatch):
    from tasks.P3_parse_files.batch_runner import _State

    client = Client()
    details = []
    original = _State._publish

    def publish(state):
        original(state)
        details.append((len(state.done), len(client.rows)))

    monkeypatch.setattr(_State, '_publish', publish)

    def parse(value):
        insert_parser_arrow(client, 'file_types', pa.table({'value': [value]}))
        insert_parser_arrow(client, 'emails', pa.table({'value': [value]}))
        assert not client.rows
        return value

    result = run_batch('test', list(range(100)), key=str, size=lambda _: 1,
                       step=parse, task_name='parse', budget=lambda _: 900)
    assert all(row.status == 'ok' for row in result.results)
    assert [(table, count) for table, count, _ in client.calls] == [('file_types', 100), ('emails', 100)]
    assert all(settings == {'async_insert': 1, 'wait_for_async_insert': 1}
               for _, _, settings in client.calls)
    assert all(stored == 200 for done, stored in details if done)


def test_failed_batch_isolates_one_file_and_writes_the_other_ninety_nine():
    client = Client(bad=37)

    def parse(value):
        insert_parser_arrow(client, 'file_types', pa.table({'value': [value]}))
        return value

    result = run_batch('test', list(range(100)), key=str, size=lambda _: 1,
                       step=parse, task_name='parse', budget=lambda _: 900)
    assert result.results[37].status == 'failed'
    assert result.results[37].error_type == 'BadRow'
    assert sum(row.status == 'ok' for row in result.results) == 99
    assert sorted(value for _, value in client.rows) == [value for value in range(100) if value != 37]


def test_buffer_flushes_at_its_size_limit_and_preserves_cleanup_order(monkeypatch):
    import tasks.P3_parse_files.insert_batch as module

    monkeypatch.setattr(module, 'BUFFER_BYTES', 100)
    client = Client()
    cleanup = []
    with parser_insert_batch() as batch:
        batch.index = 0
        batch.after_storage(lambda: cleanup.append(len(client.rows)))
        insert_parser_arrow(client, 'cells', pa.table({'value': ['x' * 101]}))
        assert len(client.rows) == 1
        assert cleanup == []
        batch.finish_file(0)
    assert cleanup == [1]


def test_failed_file_keeps_its_member_folder():
    client = Client(bad='bad')
    cleanup = []
    with parser_insert_batch() as batch:
        batch.index = 0
        batch.after_storage(lambda: cleanup.append('removed'))
        insert_parser_arrow(client, 'blobs', pa.table({'value': ['bad']}))
        batch.flush()
        batch.finish_file(0)
    assert cleanup == []
    assert 0 in batch.errors


@pytest.mark.parametrize('mime', ['text/rtf', 'application/rtf', 'text/html', 'application/xhtml+xml',
                                  'image/x-xbitmap', 'image/x-xpixmap', 'image/svg+xml',
                                  'text/xml', 'application/xml', 'application/vnd.ms-word+xml'])
def test_structured_documents_exclude_raw_text(mime):
    from tasks.P3_parse_files.workflows import route_stages

    assert 'text' not in route_stages({'coarse_types': ['text'], 'mime_types': [mime]})


@pytest.mark.parametrize('mime', ['text/plain', 'text/x-pgp', 'text/calendar', 'text/vcard'])
def test_plain_and_property_text_keeps_raw_route(mime):
    from tasks.P3_parse_files.workflows import route_stages

    assert 'text' in route_stages({'coarse_types': ['text'], 'mime_types': [mime]})


def test_final_table_manifest_follows_cells_even_when_queued_first():
    client = Client()
    with parser_insert_batch() as batch:
        batch.index = 0
        insert_parser_arrow(client, 'table_documents', pa.table({'value': [0]}))
        batch.index = 1
        insert_parser_arrow(client, 'table_cells', pa.table({'value': [1]}))
        batch.flush()
    assert [table for table, _, _ in client.calls] == ['table_cells', 'table_documents']
