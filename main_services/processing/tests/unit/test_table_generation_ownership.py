"""Generation commands retain writing generations and reject retired publication."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from temporalio.exceptions import ApplicationError

from database import clickhouse
from tasks.P3_parse_files import table_generations as owners


class Store:
    def __init__(self):
        self.owners = {}
        self.named = set()
        self.deleted = []

    def query(self, sql, parameters=None):
        if "SELECT generation, attempt_token" in sql:
            rows = [(generation, *row) for generation, row in self.owners.items()]
        elif "max(generation)" in sql:
            rows = [(0,)]
        elif "SELECT state" in sql:
            rows = [(self.owners[parameters["generation"]][2],)]
        elif "SELECT count()" in sql:
            rows = [(int(parameters["generation"] in self.named),)]
        else:
            raise AssertionError(sql)
        return SimpleNamespace(result_rows=rows)

    def command(self, sql, parameters):
        self.deleted.append((sql, parameters))


@pytest.fixture
def store(monkeypatch):
    db = Store()
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: nullcontext(db))

    def insert(client, table, rows, **kwargs):
        if table == "processing_output_receipts":
            return
        assert table == "table_generation_owners"
        for file_hash, generation, token, operation, state in rows:
            db.owners[generation] = token, operation, state

    monkeypatch.setattr(clickhouse, "insert_durable", insert)
    return db


def test_concurrent_allocations_have_distinct_generations_and_retry_identity(store):
    first = owners.GenerationCommand("collection", "hash", "allocate", "attempt-a")
    second = owners.GenerationCommand("collection", "hash", "allocate", "attempt-b")
    assert owners.apply_table_generation_command(first) == 1
    assert owners.apply_table_generation_command(second) == 2
    assert owners.apply_table_generation_command(first) == 1
    assert store.owners[1][2] == store.owners[2][2] == "writing"


def test_retirement_requires_writer_completion_and_no_published_reference(store):
    command = owners.GenerationCommand("collection", "hash", "retire", generation=1)
    store.owners[1] = "attempt", "operation", "writing"
    with pytest.raises(ApplicationError, match="termination"):
        owners.apply_table_generation_command(command)
    assert not store.deleted
    store.owners[1] = "attempt", "operation", "published"
    store.named.add(1)
    owners.apply_table_generation_command(command)
    assert not store.deleted
    store.named.clear()
    owners.apply_table_generation_command(command)
    assert store.owners[1][2] == "retired"
    assert not store.deleted
    owners.delete_retired_generation(store, "hash", 1)
    assert len(store.deleted) == 3


def test_retired_attempt_cannot_allocate_again(store):
    store.owners[1] = "attempt", "operation", "retired"
    with pytest.raises(ApplicationError, match="retired"):
        owners.apply_table_generation_command(owners.GenerationCommand(
            "collection", "hash", "allocate", "attempt"))
