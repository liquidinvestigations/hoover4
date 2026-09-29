"""Tests for the vector memory budget before a Manticore write."""

import contextlib

import pytest
from temporalio.exceptions import ApplicationError

import database.clickhouse as clickhouse
import database.manticore as manticore
from tasks.P6_index_data import activities
from tasks.P6_index_data.params import IndexShardParams


class _QueryResult:
    def __init__(self, rows):
        self.rows = rows

    def to_pylist(self):
        return self.rows


class _CollectionClient:
    def __init__(self, rows):
        self.rows = rows

    def query_arrow(self, _query, _parameters):
        return _QueryResult(self.rows)


class _Cursor:
    def __init__(self):
        self.statement = ""

    def execute(self, statement):
        self.statement = statement

    def fetchall(self):
        if self.statement == "SHOW TABLES":
            return [("testdata_1_vectors",)]
        return [("indexed_documents", "10000000")]


class _ManticoreClient:
    def __init__(self):
        self.writes = []

    def cursor(self):
        return _Cursor()

    def cmd_query(self, statement):
        self.writes.append(statement)

    def commit(self):
        pass


def _rows():
    return [
        {
            "file_hash": f"hash-{number}",
            "extracted_by": "tika",
            "page_id": 0,
            "chunk_index": 0,
            "embedding_model": "model",
            "dims": 384,
            "embedding": [0.0] * 384,
        }
        for number in range(1000)
    ]


def _params():
    return IndexShardParams("testdata", "testdata_dataset", "plan", "testdata_1",
                            [f"hash-{number}" for number in range(1000)])


def _install_budget_stubs(monkeypatch):
    collection = _CollectionClient(_rows())
    vectors = _ManticoreClient()

    @contextlib.contextmanager
    def collection_client(_collectionname):
        yield collection

    @contextlib.contextmanager
    def vectors_client(_endpoint):
        yield vectors

    monkeypatch.setattr(activities, "get_collection_client", collection_client)
    monkeypatch.setattr(clickhouse, "get_server_setting", lambda _key: "model")
    monkeypatch.setattr(manticore, "get_manticore_client", vectors_client)
    monkeypatch.setattr(manticore, "shard_knn_dims", lambda _table: 384)
    monkeypatch.setattr(manticore, "shard_knn_quantization", lambda _table: "1bit")
    monkeypatch.setattr(
        activities,
        "manticore_execute",
        lambda client, statement, _params: client.writes.append(statement),
    )
    monkeypatch.setenv("HOOVER4_INDEXING_WORKERS", "8")
    monkeypatch.setenv("HOOVER4_INDEXING_CONCURRENCY", "1")
    return vectors


def test_vector_memory_budget_allows_the_32_gib_configuration(monkeypatch):
    vectors = _install_budget_stubs(monkeypatch)
    monkeypatch.setenv("MANTICORE_VECTORS_MEM_LIMIT_BYTES", str(32 * 1024 ** 3))

    result = activities.index_vectors(_params())

    assert set(result) == {f"hash-{number}" for number in range(1000)}
    assert len(vectors.writes) == 1000


def test_vector_memory_budget_uses_defaults_for_empty_worker_settings(monkeypatch):
    vectors = _install_budget_stubs(monkeypatch)
    monkeypatch.setenv("MANTICORE_VECTORS_MEM_LIMIT_BYTES", str(32 * 1024 ** 3))
    monkeypatch.setenv("HOOVER4_INDEXING_WORKERS", "")
    monkeypatch.setenv("HOOVER4_INDEXING_CONCURRENCY", "")

    activities.index_vectors(_params())

    assert len(vectors.writes) == 1000


def test_vector_memory_budget_refuses_the_4_gib_configuration(monkeypatch):
    vectors = _install_budget_stubs(monkeypatch)
    monkeypatch.setenv("MANTICORE_VECTORS_MEM_LIMIT_BYTES", str(4 * 1024 ** 3))

    with pytest.raises(ApplicationError) as raised:
        activities.index_vectors(_params())

    assert raised.value.type == "VectorMemoryBudget"
    assert raised.value.non_retryable is True
    assert "manticore_vectors_mem_limit" in str(raised.value)
    assert not vectors.writes


def test_vector_memory_budget_charges_the_target_after_the_batch(monkeypatch):
    vectors = _install_budget_stubs(monkeypatch)
    per_vector = manticore.hnsw_bytes_per_vector(384, "1bit")
    resident = 10_000_000 * per_vector
    incoming = 1_000 * per_vector
    base = resident * 2 + incoming * 8 + 128 * 1024 * 1024
    limit = (base * 10 + 8) // 9
    assert base + limit // 10 <= limit
    assert base + incoming + limit // 10 > limit
    monkeypatch.setenv("MANTICORE_VECTORS_MEM_LIMIT_BYTES", str(limit))

    with pytest.raises(ApplicationError) as raised:
        activities.index_vectors(_params())

    assert raised.value.type == "VectorMemoryBudget"
    assert not vectors.writes


def test_vector_memory_budget_refuses_a_missing_limit(monkeypatch):
    vectors = _install_budget_stubs(monkeypatch)
    monkeypatch.delenv("MANTICORE_VECTORS_MEM_LIMIT_BYTES", raising=False)

    with pytest.raises(ApplicationError) as raised:
        activities.index_vectors(_params())

    assert raised.value.type == "VectorMemoryBudget"
    assert raised.value.non_retryable is True
    assert "MANTICORE_VECTORS_MEM_LIMIT_BYTES" in str(raised.value)
    assert not vectors.writes
