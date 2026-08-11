"""Tests for collection database naming and dataset -> collection resolution.

The validation matrix is NOT written here: both runtimes (this package and the
Rust backend) validate collectionnames independently, so the cases live in one
canonical list, ``database/collectionname_validation_cases.json``, loaded by both
test suites. These are pure functions guarding the one place an identifier is
string-interpolated into SQL (a database name cannot be a bound parameter), so
the rejection matrix is the important half.
"""

import json
from pathlib import Path

import pytest

from database import clickhouse
from database.clickhouse import (
    GLOBAL_DB,
    UnknownDatasetError,
    collection_db_name,
    resolve_collection,
)

_CASES = json.loads(
    (Path(clickhouse.__file__).parent / "collectionname_validation_cases.json").read_text()
)


@pytest.mark.parametrize("name", _CASES["valid"])
def test_accepts_valid_slugs(name):
    assert collection_db_name(name) == f"Hoover4_Collection_{name}"


@pytest.mark.parametrize("name", _CASES["invalid"])
def test_rejects_invalid_slugs(name):
    with pytest.raises(ValueError):
        collection_db_name(name)


def test_global_db_is_not_a_collection_db():
    assert not GLOBAL_DB.startswith(clickhouse.COLLECTION_DB_PREFIX)


class _FakeResult:
    def __init__(self, rows):
        self.result_rows = rows


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows
        self.queries = []

    def query(self, sql, parameters=None):
        self.queries.append((sql, parameters))
        return _FakeResult(self._rows)


@pytest.fixture(autouse=True)
def _clear_resolver_cache():
    clickhouse._COLLECTION_OF_DATASET.clear()
    yield
    clickhouse._COLLECTION_OF_DATASET.clear()


def _patch_global_client(monkeypatch, rows):
    from contextlib import contextmanager

    client = _FakeClient(rows)

    @contextmanager
    def _fake():
        yield client

    monkeypatch.setattr(clickhouse, "get_global_client", _fake)
    return client


def test_resolve_collection_returns_and_caches(monkeypatch):
    client = _patch_global_client(monkeypatch, [["testdata"]])

    assert resolve_collection("testdata_testfiles") == "testdata"
    # The mapping never changes, so the second call must not hit the database again.
    assert resolve_collection("testdata_testfiles") == "testdata"
    assert len(client.queries) == 1


def test_resolve_collection_raises_for_unknown_dataset(monkeypatch):
    _patch_global_client(monkeypatch, [])

    with pytest.raises(UnknownDatasetError) as excinfo:
        resolve_collection("nope_nothing")
    assert "nope_nothing" in str(excinfo.value)


def test_resolve_collection_raises_for_blank_collectionname(monkeypatch):
    """A row with an empty collectionname must not silently route to the global DB."""
    _patch_global_client(monkeypatch, [[""]])

    with pytest.raises(UnknownDatasetError):
        resolve_collection("legacy_dataset")
