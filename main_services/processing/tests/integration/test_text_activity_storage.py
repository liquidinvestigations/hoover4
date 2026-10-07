"""Verify buffered text storage and replacement against ClickHouse."""

import pytest

from database.clickhouse import get_collection_client
from tasks.P3_parse_files.batch_runner import run_batch
from tasks.P3_parse_files.parse_common import insert_text_pages


pytestmark = pytest.mark.integration


def test_hundred_text_files_share_one_waited_insert(temp_collection, monkeypatch):
    with get_collection_client(temp_collection) as client:
        calls = []
        original = client.insert_arrow

        def insert(table, rows, **kwargs):
            calls.append((table, rows.num_rows, kwargs["settings"]))
            return original(table, rows, **kwargs)

        monkeypatch.setattr(client, "insert_arrow", insert)

        def parse(index):
            result = insert_text_pages(temp_collection, "batch", str(index), "raw_text", [(1, "source text")])
            assert client.query("SELECT count() FROM text_content").result_rows == [(0,)]
            return result

        result = run_batch("text", list(range(100)), key=str, size=lambda _: 1,
                           step=parse, task_name="parse", budget=lambda _: 900)
        assert all(row.status == "ok" for row in result.results)
        assert calls == [("text_content", 100, {"async_insert": 1, "wait_for_async_insert": 1})]
        assert client.query("SELECT count(), uniqExact(file_hash) FROM text_content").result_rows == [(100, 100)]


def test_buffered_replacements_preserve_pages_until_storage(temp_collection):
    for file_hash in ("shortened", "empty"):
        insert_text_pages(temp_collection, "batch", file_hash, "raw_text", [(1, "old first"), (2, "old last")])
    with get_collection_client(temp_collection) as client:
        def parse(file_hash):
            pages = [(1, "replacement")] if file_hash == "shortened" else []
            result = insert_text_pages(temp_collection, "batch", file_hash, "raw_text", pages)
            assert client.query("SELECT count() FROM text_content FINAL").result_rows == [(4,)]
            return result

        result = run_batch("text", ["shortened", "empty"], key=str, size=lambda _: 1,
                           step=parse, task_name="parse", budget=lambda _: 900)
        assert all(row.status == "ok" for row in result.results)
        assert client.query("SELECT file_hash,page_id,text FROM text_content FINAL").result_rows == [
            ("shortened", 1, "replacement")]
