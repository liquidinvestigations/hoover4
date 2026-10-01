"""A failed insert flush stops dependent processing before it reads stale rows."""

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
        assert sql == "SYSTEM FLUSH ASYNC INSERT QUEUE"
        raise RuntimeError("flush failed")

    def query(self, *_args, **_kwargs):
        pytest.fail("the stage read after a failed flush")

    def query_arrow(self, *_args, **_kwargs):
        pytest.fail("the stage read after a failed flush")


def test_date_resolution_propagates_flush_failure(monkeypatch):
    from database import clickhouse

    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: FailedFlush())
    with pytest.raises(RuntimeError, match="flush failed"):
        resolve_document_dates(ResolveDocumentDatesParams("collection", "dataset", "plan"))


def test_index_planner_propagates_flush_failure(monkeypatch):
    monkeypatch.setattr(shard_planner, "get_collection_client", lambda _name: FailedFlush())
    with pytest.raises(RuntimeError, match="flush failed"):
        shard_planner.plan_shards(
            PlanShardsParams("collection", "dataset", "plan", ["file"])
        )
