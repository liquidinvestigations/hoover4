"""A filename row cannot establish complete document attribute publication."""

from contextlib import nullcontext

import pytest
from database import manticore
from tasks.P6_index_data import location_refresh


@pytest.mark.parametrize("rows, stale", [
    ([(1, "file", "filename_index", -1, "1", "2", "3", "4"),
      (2, "file", "text", 1, "1", "2", "3", "9")], True),
    ([(1, "file", "text", 1, "1", "2", "3", "4")], True),
    ([], True),
    ([(1, "file", "filename_index", -1, "1", "2", "3", "4"),
      (2, "file", "text", 1, "1", "2", "3", "4")], False),
])
def test_every_page_and_the_filename_row_must_match(monkeypatch, rows, stale):
    class Cursor:
        def execute(self, sql, parameters):
            assert "extracted_by =" not in sql
            assert "ORDER BY id ASC" in sql

        def fetchall(self):
            return rows

    class Connection:
        def cursor(self):
            return Cursor()

    monkeypatch.setattr(manticore, "get_manticore_client", lambda: nullcontext(Connection()))
    monkeypatch.setattr(manticore, "table_has_column", lambda _table, column: column != "has_ocr_output")
    monkeypatch.setattr(location_refresh, "load_expected_page_keys", lambda *_args: {"file": {("text", 1)}})
    actual = location_refresh.load_indexed_ids("collection", "dataset", {"file": "collection_1"})
    assert (actual[3]["file"] != frozenset({4})) == stale


def test_a_missing_text_page_cannot_settle_current_attributes(monkeypatch):
    class Cursor:
        def execute(self, sql, parameters):
            pass
        def fetchall(self):
            return [(1, "file", "filename_index", -1, "1", "2", "3", "4"),
                    (2, "file", "text", 1, "1", "2", "3", "4")]
    class Connection:
        def cursor(self):
            return Cursor()
    monkeypatch.setattr(manticore, "get_manticore_client", lambda: nullcontext(Connection()))
    monkeypatch.setattr(manticore, "table_has_column", lambda _table, column: column != "has_ocr_output")
    monkeypatch.setattr(location_refresh, "load_expected_page_keys",
                        lambda *_args: {"file": {("text", 1), ("text", 2)}})
    actual = location_refresh.load_indexed_ids("collection", "dataset", {"file": "collection_1"})
    assert actual[3]["file"] != frozenset({4})


def test_presence_queries_use_bounded_hash_batches(monkeypatch):
    from database import clickhouse
    from tasks.P6_index_data import activities

    hashes = [f"{index:064x}" for index in range(2001)]
    batches = []

    class Cursor:
        def execute(self, sql, parameters):
            pass

        def fetchall(self):
            return []

    class Connection:
        def cursor(self):
            return Cursor()

    def presence(_client, dataset, selected):
        assert dataset == "dataset"
        assert len(selected) <= 1000
        batches.extend(selected)
        return {}

    monkeypatch.setattr(manticore, "get_manticore_client", lambda: nullcontext(Connection()))
    monkeypatch.setattr(manticore, "table_has_column", lambda *_args: True)
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda *_args: nullcontext(object()))
    monkeypatch.setattr(activities, "document_ocr_presence", presence)
    monkeypatch.setattr(location_refresh, "load_expected_page_keys", lambda *_args: {})
    location_refresh.load_indexed_ids("collection", "dataset", dict.fromkeys(hashes, "collection_1"))
    assert batches == hashes
