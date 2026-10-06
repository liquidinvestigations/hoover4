"""Tests for the collection reindex operation's activity input."""

import asyncio

from tasks.P_ops import workflows
from tasks.P_ops.params import OperationParams


def test_reindex_passes_one_activity_input_in_args(monkeypatch):
    calls = []

    async def execute_activity(activity, *positional, **options):
        calls.append((activity, positional, options))
        return 2

    monkeypatch.setattr(workflows.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(workflows.workflow, "patched", lambda _name: False)

    result = asyncio.run(workflows.Operation()._dispatch(OperationParams(
        op_id="operation", kind="reindex_collection", collectionname="testdata",
        detail={"vectors_only": True},
    )))

    assert result == "queued 2 plan(s) for re-indexing"
    activity, positional, options = calls[0]
    assert activity is workflows.reindex_collection_activity
    assert positional == ("testdata",)
    assert "args" not in options


def test_reindex_waits_for_rebuild_child(monkeypatch):
    waiting = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def execute_activity(activity, *_args, **_options):
        calls.append(activity)

    async def execute_child_workflow(_run, _params, **_options):
        waiting.set()
        await release.wait()
        return 3

    monkeypatch.setattr(workflows.workflow, "patched", lambda _name: True)
    monkeypatch.setattr(workflows.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(workflows.workflow, "execute_child_workflow", execute_child_workflow)

    async def check():
        task = asyncio.create_task(workflows.Operation()._dispatch(OperationParams(
            op_id="operation", kind="reindex_collection", collectionname="testdata",
            detail={"vectors_only": True},
        )))
        await waiting.wait()
        assert not task.done()
        release.set()
        assert await task == "re-indexed 3 plan(s)"

    asyncio.run(check())
    assert calls == [workflows.prepare_reindex_collection]


def test_rebuild_waits_for_every_child_and_reports_a_failure(monkeypatch):
    release = asyncio.Event()
    first_failed = asyncio.Event()

    async def execute_activity(_activity, _params, **_options):
        return [("dataset", "hash-1"), ("dataset", "hash-2")]

    async def execute_child_workflow(_run, params, **_options):
        if params.plan_hash == "hash-1":
            first_failed.set()
            raise RuntimeError("vector child failed")
        await release.wait()
        return None

    monkeypatch.setattr(workflows.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(workflows.workflow, "execute_child_workflow", execute_child_workflow)

    async def check():
        task = asyncio.create_task(workflows.RebuildCollectionPlans().run(
            workflows.RebuildPlansParams("operation", "testdata", True)))
        await first_failed.wait()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        try:
            await task
        except workflows.ApplicationError as exc:
            assert "1 index plans failed" in str(exc)
        else:
            raise AssertionError("failed vector child did not fail the rebuild")

    asyncio.run(check())


def test_rebuild_continues_after_one_bounded_plan_page(monkeypatch):
    planned = [("dataset", f"hash-{index:03d}") for index in range(100)]
    continued = []

    async def execute_activity(_activity, _params, **_options):
        return planned

    async def execute_child_workflow(_run, _params, **_options):
        return None

    monkeypatch.setattr(workflows.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(workflows.workflow, "execute_child_workflow", execute_child_workflow)
    monkeypatch.setattr(workflows.workflow, "continue_as_new", continued.append)

    result = asyncio.run(workflows.RebuildCollectionPlans().run(
        workflows.RebuildPlansParams("operation", "testdata", True, completed=200)))

    assert result == 300
    assert len(continued) == 1
    assert continued[0].cursor_dataset == "dataset"
    assert continued[0].cursor_hash == "hash-099"
    assert continued[0].completed == 300
