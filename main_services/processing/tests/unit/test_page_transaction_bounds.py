"""Keep page transactions bounded and roll back a failed statement."""

import asyncio
import pytest

from tasks.P6_index_data import activities as pages


class Connection:
    def __init__(self, failure=None):
        self.commands = []
        self.failure = failure

    def cmd_query(self, statement):
        self.commands.append(statement)
        if self.failure and statement.startswith(b"REPLACE"):
            raise self.failure("write failed")


def prepare(monkeypatch):
    monkeypatch.setattr(pages, "pages_replace_sql", lambda _table, _row: "unused")
    monkeypatch.setattr(pages, "pages_replace_params", lambda _dataset, row: row)
    monkeypatch.setattr(
        pages, "bind_manticore_sql",
        lambda _client, _sql, row: b"REPLACE INTO pages VALUES (" + row["text"] + b")",
    )


def test_row_and_byte_bounds_keep_full_text(monkeypatch):
    prepare(monkeypatch)
    monkeypatch.setattr(pages, "INDEX_STATEMENT_MAX_ROWS", 2)
    monkeypatch.setattr(pages, "INDEX_STATEMENT_MAX_BYTES", 50)
    client = Connection()
    rows = [{"text": bytes([letter]) * 8} for letter in b"abc"]

    pages.write_page_batches(client, "pages", "dataset", rows)

    statements = [c for c in client.commands if c.startswith(b"REPLACE")]
    assert len(statements) == 2
    assert all(len(statement) <= 50 for statement in statements)
    assert b"a" * 8 in statements[0] and b"b" * 8 in statements[0]
    assert b"c" * 8 in statements[1]
    assert client.commands.count(b"BEGIN") == client.commands.count(b"COMMIT") == 2


def test_large_row_gets_own_transaction_without_truncation(monkeypatch):
    prepare(monkeypatch)
    monkeypatch.setattr(pages, "INDEX_STATEMENT_MAX_BYTES", 44)
    monkeypatch.setattr(pages, "INDEX_ROW_MAX_BYTES", 100)
    client = Connection()
    page = b"x" * 60

    pages.write_page_batches(client, "pages", "dataset", [{"text": b"a"}, {"text": page}])

    statements = [c for c in client.commands if c.startswith(b"REPLACE")]
    assert len(statements) == 2
    assert page in statements[1]

    with pytest.raises(ValueError, match="row limit"):
        pages.write_page_batches(client, "pages", "dataset", [{"text": b"y" * 101}])


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
def test_failed_replace_rolls_back(monkeypatch, failure):
    prepare(monkeypatch)
    client = Connection(failure=failure)

    with pytest.raises(failure, match="write failed"):
        pages.write_page_batches(client, "pages", "dataset", [{"text": b"a"}])

    assert client.commands[0] == b"BEGIN"
    assert client.commands[-1] == b"ROLLBACK"
    assert b"COMMIT" not in client.commands
