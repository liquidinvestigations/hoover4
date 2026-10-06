"""A failed storage read stops dependent processing."""

import pytest

from tasks.P3_parse_files.document_dates import (
    ResolveDocumentDatesParams, resolve_document_dates,
)
from tasks.P6_index_data import shard_planner
from tasks.P6_index_data.params import PlanShardsParams


class FailedFlush:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def command(self, sql):
        pytest.fail("Unexpected async queue flush")

    def query(self, *_args, **_kwargs):
        raise RuntimeError("read failed")

    def query_arrow(self, *_args, **_kwargs):
        raise RuntimeError("read failed")


def test_date_resolution_propagates_read_failure(monkeypatch):
    from database import clickhouse

    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: FailedFlush())
    with pytest.raises(RuntimeError, match="read failed"):
        resolve_document_dates(ResolveDocumentDatesParams("collection", "dataset", "plan"))


def test_index_planner_propagates_read_failure(monkeypatch):
    monkeypatch.setattr(shard_planner, "get_collection_client", lambda _name: FailedFlush())
    with pytest.raises(RuntimeError, match="read failed"):
        shard_planner.plan_shards(
            PlanShardsParams("collection", "dataset", "plan", ["file"])
        )
