"""Verify text replacement through the activity insert buffer."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from temporalio.exceptions import ApplicationError

from database import clickhouse
from tasks.P3_parse_files.batch_runner import _State, run_batch
from tasks.P3_parse_files.insert_batch import parser_insert_batch
from tasks.P3_parse_files.parse_common import insert_text_pages, insert_text_sources


class TextClient:
    def __init__(self, refused=None, cleanup_failure=None):
        self.refused = refused
        self.cleanup_failure = cleanup_failure
        self.inserts = []
        self.stored = []
        self.deleted = []

    def query(self, _sql, parameters):
        if "sources" in parameters:
            rows = [(source, page, 100) for source in parameters["sources"] for page in (1, 2)]
        else:
            rows = [(1, 100), (2, 100)]
        return SimpleNamespace(result_rows=rows)

    def insert_arrow(self, table, rows, *, settings):
        assert table == "text_content"
        assert settings == {"async_insert": 1, "wait_for_async_insert": 1}
        values = rows.to_pylist()
        self.inserts.append(values)
        if any(row["file_hash"] == self.refused for row in values):
            raise ApplicationError("Refused text row", type="BadRow", non_retryable=True)
        self.stored.extend(values)

    def command(self, sql, parameters):
        assert "mutations_sync = 2" in sql
        if parameters["ids"] == [2]:
            assert any(row["file_hash"] == parameters["fh"] for row in self.stored)
        if parameters["fh"] == self.cleanup_failure:
            raise RuntimeError("Cleanup failed")
        self.deleted.append(parameters)


@pytest.fixture
def text_client(monkeypatch):
    client = TextClient()
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: nullcontext(client))
    return client


def run_text_files(client, count=100):
    def parse(index):
        return insert_text_sources("collection", "dataset", str(index), {
            "raw_text": [(1, "source text")], "email_body": [(1, "email text")],
        })
    return run_batch("text", list(range(count)), key=str, size=lambda _: 1,
                     step=parse, task_name="parse", budget=lambda _: 900)


def test_actual_text_writer_batches_hundred_files_before_completion(text_client, monkeypatch):
    observations = []
    original = _State._publish

    def publish(state):
        original(state)
        observations.append((len(state.done), len(text_client.stored), len(text_client.deleted)))

    monkeypatch.setattr(_State, "_publish", publish)
    result = run_text_files(text_client)
    assert all(row.status == "ok" for row in result.results)
    assert [len(rows) for rows in text_client.inserts] == [200]
    assert len(text_client.deleted) == 200
    assert all(stored == 200 and deleted >= 2 * done
               for done, stored, deleted in observations if done)
    assert all(row["version"] > 100 for row in text_client.stored)


def test_refused_text_keeps_prior_pages_and_isolates_one_file(text_client):
    text_client.refused = "37"
    result = run_text_files(text_client)
    assert result.results[37].status == "failed"
    assert result.results[37].error_type == "BadRow"
    assert sum(row.status == "ok" for row in result.results) == 99
    assert len(text_client.stored) == len(text_client.deleted) == 198
    assert all(row["fh"] != "37" for row in text_client.deleted)


def test_empty_replacement_waits_for_completion_without_an_insert(text_client):
    with parser_insert_batch() as batch:
        batch.index = 0
        assert insert_text_pages("collection", "dataset", "file", "raw_text", []) == 0
        assert 0 in batch.seen
        assert not text_client.inserts and not text_client.deleted
        batch.flush()
        batch.finish_file(0)
    assert not text_client.inserts
    assert text_client.deleted[0]["ids"] == [1, 2]


def test_size_flush_stores_text_before_replacement_cleanup(text_client, monkeypatch):
    from tasks.P3_parse_files import insert_batch

    monkeypatch.setattr(insert_batch, "BUFFER_BYTES", 1)
    with parser_insert_batch() as batch:
        batch.index = 0
        insert_text_pages("collection", "dataset", "file", "raw_text", [(1, "new text")])
        assert len(text_client.stored) == 1
        assert not text_client.deleted
        batch.finish_file(0)
    assert text_client.deleted[0]["ids"] == [2]


def test_cleanup_failure_fails_only_its_file_after_storage(text_client):
    text_client.cleanup_failure = "0"
    result = run_text_files(text_client, count=2)
    assert [row.status for row in result.results] == ["failed", "ok"]
    assert len(text_client.stored) == 4
    assert len(text_client.deleted) == 2
    assert all(row["fh"] == "1" for row in text_client.deleted)


def test_direct_replacement_waits_and_removes_obsolete_pages(text_client):
    assert insert_text_pages("collection", "dataset", "file", "raw_text", [(1, "new text")]) == 1
    assert len(text_client.stored) == 1
    assert text_client.deleted[0]["ids"] == [2]
