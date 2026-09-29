"""Tests for the historical collection reindex activity input."""

import contextlib
import asyncio
import inspect

from temporalio.client import Client
from temporalio.converter import DataConverter

import database.clickhouse as clickhouse
import database.manticore as manticore
from tasks.P_ops.activities import reindex_collection_activity


class _Result:
    result_rows = [("testdata_dataset", "plan-a"), ("testdata_dataset", "plan-b")]


class _CollectionClient:
    def command(self, _command):
        pass

    def query(self, _query):
        return _Result()


class _Handle:
    def __init__(self):
        self.completed = False

    async def result(self):
        self.completed = True


class _TemporalClient:
    def __init__(self):
        self.handles = []

    async def start_workflow(self, *_args, **_kwargs):
        handle = _Handle()
        self.handles.append(handle)
        return handle


def test_historical_reindex_decodes_string_and_waits_for_plans(monkeypatch):
    temporal = _TemporalClient()

    @contextlib.contextmanager
    def collection_client(_collectionname):
        yield _CollectionClient()

    async def connect(_target):
        return temporal

    monkeypatch.setattr(clickhouse, "get_collection_client", collection_client)
    monkeypatch.setattr(manticore, "drop_collection_tables", lambda _collection: [])
    monkeypatch.setattr(Client, "connect", connect)

    converter = DataConverter()
    payload = asyncio.run(converter.encode(["testdata"]))
    annotation = inspect.signature(reindex_collection_activity).parameters["collectionname"].annotation
    assert annotation is str
    decoded = asyncio.run(converter.decode(payload, [annotation]))
    assert decoded == ["testdata"]
    result = reindex_collection_activity(*decoded)

    assert result == 2
    assert [handle.completed for handle in temporal.handles] == [True, True]
