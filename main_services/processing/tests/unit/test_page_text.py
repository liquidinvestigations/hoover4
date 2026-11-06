"""An indexed copy that ended at a NUL byte is found, replaced, and then settled."""

import pytest

from database.manticore import indexed_text
from tasks.P6_index_data.activities import pages_row_id
from tasks.P_admin.updates import page_text


class Result:
    def __init__(self, rows):
        self.result_rows = rows


class Client:
    def __init__(self, keys):
        self.keys = keys

    def query(self, sql, parameters=None):
        if "text_content" in sql:
            after = (parameters["hash"], parameters["source"], parameters["page"])
            return Result([key for key in self.keys if key > after][:page_text._PAGES])
        return Result([("f", "shard_1")])


class Cursor:
    column_names = ("id", "page_text", "file_size_bytes")

    def __init__(self, rows):
        self.rows = rows
        self.found = []

    def execute(self, sql, params=None):
        self.found = [self.rows[int(sql.rsplit("=", 1)[1])]]

    def fetchall(self):
        return self.found


class Connection:
    def __init__(self, rows):
        self.rows = rows
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return Cursor(self.rows)

    def commit(self):
        self.commits += 1


@pytest.fixture
def stored(monkeypatch):
    bodies = {("f", "raw_text", 1): "head\0tail", ("f", "raw_text", 2): "kept\0copy"}
    row_id = lambda key: pages_row_id("d", *key)
    rows = {row_id(("f", "raw_text", 1)): (row_id(("f", "raw_text", 1)), "head", 7),
            row_id(("f", "raw_text", 2)): (row_id(("f", "raw_text", 2)), "kept copy", 9)}
    connection = Connection(rows)
    written = []

    def execute(_connection, _sql, params):
        written.append(params)

    monkeypatch.setattr("database.manticore.get_manticore_client", lambda: connection)
    monkeypatch.setattr("database.manticore.manticore_execute", execute)
    monkeypatch.setattr("database.manticore.shard_table_from_name", lambda shard: shard + "_pages")
    monkeypatch.setattr("tasks.text_sources.fetch_text_batch", lambda _client, _dataset, keys: [
        dict(file_hash=key[0], extracted_by=key[1], page_id=key[2], text=bodies[key]) for key in keys])
    monkeypatch.setattr("tasks.P6_index_data.activities.pages_replace_sql", lambda table, row: table)
    monkeypatch.setattr("tasks.P6_index_data.activities.pages_replace_params",
                        lambda dataset, row: (row["id"], row["page_text"], row["file_size_bytes"]))
    return Client(sorted(bodies)), rows, written, row_id


def test_a_count_finds_the_row_that_ended_at_a_nul_byte_and_writes_nothing(stored):
    client, _rows, written, _row_id = stored
    assert page_text.stale_page_files(client, "c", "d") == {"f"}
    assert written == []


def test_a_rewrite_replaces_only_the_stale_row_and_keeps_its_attributes(stored):
    client, _rows, written, row_id = stored
    assert page_text.stale_page_files(client, "c", "d", rewrite=True) == {"f"}
    assert written == [(row_id(("f", "raw_text", 1)), "head tail", 7)]


def test_a_rewritten_row_settles(stored):
    client, rows, _written, row_id = stored
    key = row_id(("f", "raw_text", 1))
    rows[key] = (key, "head tail", 7)
    assert page_text.stale_page_files(client, "c", "d") == set()


def test_the_indexed_copy_keeps_the_text_after_a_nul_byte():
    assert indexed_text("before\0after") == "before after"
