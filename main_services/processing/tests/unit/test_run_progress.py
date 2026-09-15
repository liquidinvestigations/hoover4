from datetime import datetime, timezone
from types import SimpleNamespace

import pyarrow as pa

from tasks.P2_execute_plan.activities import ListPendingPlansParams, list_pending_plans
from tasks.P_ops.activities import sample_dataset_progress
from tasks.P_ops.params import DatasetProgressParams


class _Client:
    def __init__(self):
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def query_arrow(self, _query):
        return pa.table({"plan_hash": ["plan-a", "plan-b"]})

    def query(self, query, parameters):
        self.queries.append((query, parameters))
        return SimpleNamespace(result_rows=[(1, 2)])


def test_list_pending_plans_records_each_listed_plan(monkeypatch):
    import database.clickhouse as clickhouse
    import database.operation_ledger as ledger

    recorded = []
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: _Client())
    monkeypatch.setattr(
        ledger,
        "insert_operation_plans",
        lambda *args: recorded.append(args),
    )

    result = list_pending_plans(
        ListPendingPlansParams("collection", "dataset", op_id="operation")
    )

    assert result == ["plan-a", "plan-b"]
    assert recorded == [
        ("collection", "operation", "dataset", ["plan-a", "plan-b"], "listed")
    ]


def test_progress_uses_recorded_plans_and_operation_errors(monkeypatch):
    import database.clickhouse as clickhouse
    import database.operation_ledger as ledger
    import database.operations as operations

    client = _Client()
    details = []
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: client)
    monkeypatch.setattr(ledger, "run_plan_counts", lambda *_args: (3, 7))
    monkeypatch.setattr(
        operations,
        "get_operation",
        lambda _op_id: {"started_at": datetime.now(timezone.utc)},
    )
    monkeypatch.setattr(operations, "update_operation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        operations,
        "merge_detail",
        lambda _op_id, **fields: details.append(fields),
    )

    result = sample_dataset_progress(
        DatasetProgressParams("operation", "collection", "dataset")
    )

    assert result == [3, 7]
    assert "op_id = {op:String}" in client.queries[0][0]
    assert client.queries[0][1] == {"ds": "dataset", "op": "operation"}
    assert details == [{"failed_documents": 1, "failed_tasks": 2}]
