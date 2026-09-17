"""Collection operations keep one clear and bounded plan pages across continuation."""

import asyncio

import pytest

from tasks.P_admin.collection_backfill import FinishedPlanPage
from tasks.P_admin import collection_backfill
from tasks.P_ops import workflows
from tasks.P_ops.params import OperationParams


def test_finished_plan_activity_limits_result_and_records_page(monkeypatch):
    from database import clickhouse, operation_ledger
    from types import SimpleNamespace

    plans = [["dataset", f"plan-{index:04d}"] for index in range(100)]
    queries = []
    recorded = []

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def query(self, sql, **_kwargs):
            queries.append(sql)
            return SimpleNamespace(result_rows=[[501]] if "count()" in sql else plans)

    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: Client())
    monkeypatch.setattr(operation_ledger, "insert_operation_plans",
                        lambda *args: recorded.append(args))

    page = collection_backfill._record_finished_plans(
        collection_backfill.CollectionBackfillParams("operation", "collection")
    )

    assert len(page.plans) == 100
    assert page.cursor == plans[-1]
    assert page.total == 501
    assert "LIMIT 100" in queries[-1]
    assert len(recorded) == 1
    assert recorded[0][3] == [pair[1] for pair in plans]


def test_empty_purge_apply_does_not_dispatch(monkeypatch, capsys):
    from database import clickhouse
    from tasks.P_ops import cli
    from types import SimpleNamespace
    import main

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def query(self, *_args):
            return SimpleNamespace(result_rows=[[0]])

    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: Client())
    monkeypatch.setattr(cli, "submit_operation", lambda *_args, **_kwargs:
                        pytest.fail("empty purge dispatched"))
    main.purge_unattributed_entities.callback("collection", True)
    assert "no unattributed entity_hit rows" in capsys.readouterr().out


class Continued(BaseException):
    pass


@pytest.mark.parametrize("kind,clear_expected", [
    ("purge_unattributed_entities", 1),
    ("backfill_vectors", 0),
])
def test_501_plans_continue_after_500_without_reclear(monkeypatch, kind, clear_expected):
    plans = [["dataset", f"plan-{index:04d}"] for index in range(501)]
    params = OperationParams("operation", kind, "collection")
    entities = {"orphan"}
    clear_calls = []
    page_sizes = []
    child_calls = []
    continuations = []

    async def execute_activity(name, argument, **_kwargs):
        if name == "clear_unattributed_entities":
            clear_calls.append(argument)
            entities.clear()
            return None
        assert name == "list_finished_plans"
        start = int(argument.cursor[1].split("-")[1]) + 1 if argument.cursor else 0
        page = plans[start:start + 100]
        page_sizes.append(len(page))
        return FinishedPlanPage(page, page[-1] if page else argument.cursor, len(plans))

    async def execute_child_workflow(name, child_params, **_kwargs):
        child_calls.append((name, child_params["plan_hash"]))
        if name in ("ExtractEntitiesForPlan", "ChunkEmbedForPlan"):
            entities.add("attributed")
        if clear_expected:
            assert "orphan" not in entities

    def continue_as_new(next_params):
        continuations.append((next_params.plan_done, list(next_params.plan_cursor),
                              next_params.clear_complete))
        raise Continued()

    async def record(_self, _op_id, done, total):
        assert total == 501
        assert done <= total

    monkeypatch.setattr(workflows.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(workflows.workflow, "execute_child_workflow", execute_child_workflow)
    monkeypatch.setattr(workflows.workflow, "continue_as_new", continue_as_new)
    monkeypatch.setattr(workflows.Operation, "_record", record)

    operation = workflows.Operation()
    with pytest.raises(Continued):
        asyncio.run(operation._dispatch(params))
    assert continuations == [(500, ["dataset", "plan-0499"], bool(clear_expected))]
    assert entities == {"attributed"} if clear_expected else {"orphan", "attributed"}

    result = asyncio.run(operation._dispatch(params))
    assert "501 plan(s)" in result
    assert params.plan_done == 501
    assert len(clear_calls) == clear_expected
    assert page_sizes == [100, 100, 100, 100, 100, 1]
    assert len(child_calls) == 1002
    assert "attributed" in entities
