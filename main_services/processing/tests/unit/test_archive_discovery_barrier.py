"""Archive cleanup waits for the final processing and discovery round."""

import asyncio

import pytest

from tasks.P2_execute_plan import workflows


@pytest.mark.parametrize("new_blobs", [0, 1])
def test_archive_cleanup_runs_only_at_the_discovery_fixed_point(monkeypatch, new_blobs):
    calls = []

    async def activity(name, arg=None, **kwargs):
        name = name if isinstance(name, str) else name.__name__
        calls.append(name)
        if name == "list_pending_plans":
            return []
        if name == "count_new_blobs":
            return new_blobs
        return None

    async def step(name, *args):
        calls.append(name.__name__)
        return 0

    async def child(name, arg, **kwargs):
        calls.append(name if isinstance(name, str) else name.__qualname__.split(".")[0])
        return {"plans_run": 0, "invocations": 1, "failed_plans": 0, "failed_dataset_steps": 0}

    monkeypatch.setattr(workflows.workflow, "execute_activity", activity)
    monkeypatch.setattr(workflows.workflow, "execute_child_workflow", child)
    monkeypatch.setattr(workflows.workflow, "patched", lambda _name: True)
    monkeypatch.setattr(workflows, "execute_dataset_step", step)
    asyncio.run(workflows.ExecutePlans().run(workflows.ExecutePlansParams(
        "collection", "dataset", "/tmp", op_id="operation")))
    assert ("reconcile_archive_descendants" in calls) == (new_blobs == 0)
    if not new_blobs:
        assert calls.index("count_new_blobs") < calls.index("reconcile_archive_descendants")
    else:
        assert "ComputePlans" in calls and "ExecutePlans" in calls
