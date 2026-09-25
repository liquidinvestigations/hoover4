"""The plan tools: the run lookup, the state rule, no role check, and the lock.

Storage is replaced with dicts, so no ClickHouse is needed. The tree rules that run are the
real ones in `database.agent_plans`. Each store call sleeps briefly, so two mutations that
did not take the lock would read the same version and one change would be lost.

Cases: `frozen-plan` (no mutation after approval, and `read_plan` shows the approved
version), two parallel mutations that land as consecutive versions, a sub-agent of the
planner that changes the plan (no role check), and the refusals for a missing header, a
run with no plan, and a terminal plan run.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from agent_todo_server import plan_tools
from database import agent_plans, agent_runs

SECRET = "test-secret"
PLAN_ID = "5f0a9b8e-1c2d-4e3f-8a9b-0c1d2e3f4a5b"
PLAN_RUN = "9a8b7c6d-5e4f-4a3b-9c2d-1e0f9a8b7c6d"
HEADERS = {
    "Authorization": f"Bearer {SECRET}",
    "X-Hoover4-User": "ann",
    "X-Hoover4-Chat-Session": "s1",
    "X-Hoover4-Agent-Run": "planner-run",
}


def call(tool, **kwargs):
    return asyncio.run(getattr(tool, "fn", tool)(**kwargs))


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("MCP_SHARED_SECRET", SECRET)
    monkeypatch.delenv("MCP_SHARED_SECRET_FILE", raising=False)


@pytest.fixture
def headers(monkeypatch):
    current = dict(HEADERS)
    monkeypatch.setattr(plan_tools, "get_http_headers", lambda: dict(current))
    return current


@pytest.fixture
def store(monkeypatch):
    """The run rows, the plan run row and the snapshots, keyed as the tables are."""
    state = SimpleNamespace(
        runs={
            "planner-run": SimpleNamespace(run_id="planner-run", kind="planner",
                                           plan_run_id=PLAN_RUN),
            "helper-run": SimpleNamespace(run_id="helper-run", kind="subagent",
                                          plan_run_id=PLAN_RUN),
            "chat-run": SimpleNamespace(run_id="chat-run", kind="chat", plan_run_id=None),
        },
        plan_run=agent_plans.PlanRunRow(run_id=PLAN_RUN, plan_id=PLAN_ID, username="ann",
                                        session_id="s1", state=agent_plans.PLANNING),
        snapshots={1: agent_plans.initial_snapshot(PLAN_ID, "What happened?")},
    )

    def read_run(username, session_id, run_id):
        assert (username, session_id) == ("ann", "s1")
        return state.runs.get(run_id)

    def read_plan_run(username, session_id, plan_run_id):
        return state.plan_run if plan_run_id == PLAN_RUN else None

    def read_snapshot(username, session_id, plan_id, version=None):
        time.sleep(0.05)
        version = version or max(state.snapshots)
        return state.snapshots.get(version)

    def write_snapshot(username, session_id, snapshot):
        time.sleep(0.05)
        state.snapshots[snapshot.version] = snapshot

    monkeypatch.setattr(agent_runs, "read_run", read_run)
    monkeypatch.setattr(agent_plans, "read_plan_run", read_plan_run)
    monkeypatch.setattr(agent_plans, "read_snapshot", read_snapshot)
    monkeypatch.setattr(agent_plans, "write_snapshot", write_snapshot)
    monkeypatch.setattr(agent_plans, "read_documents", lambda u, s, r: [
        agent_plans.PlanDocument("doc-1", agent_plans.root_node_id(PLAN_ID), "executor",
                                 "report", 0, "x" * 20_000)])
    return state


def test_two_parallel_mutations_land_as_consecutive_versions(headers, store):
    async def both():
        return await asyncio.gather(plan_tools.append_node.fn(text="A"),
                                    plan_tools.append_node.fn(text="B"))

    first, second = asyncio.run(both())
    assert first.success and second.success
    assert sorted([first.version, second.version]) == [2, 3]
    newest = store.snapshots[3]
    assert sorted(n.text for n in newest.nodes if n.parent_id) == ["A", "B"]


def test_a_sub_agent_of_the_planner_changes_the_plan_with_no_role_check(headers, store):
    headers["X-Hoover4-Agent-Run"] = "helper-run"
    result = call(plan_tools.append_node, text="From a helper")
    assert result.success and result.version == 2
    assert [s.tasks for s in result.sections] == [["From a helper"]]


def test_frozen_plan_refuses_every_mutation_and_reads_the_approved_version(headers, store):
    assert call(plan_tools.append_node, text="A").version == 2
    assert call(plan_tools.append_node, text="B").version == 3
    store.plan_run.state = agent_plans.EXECUTING
    store.plan_run.approved_version = 2
    root = agent_plans.root_node_id(PLAN_ID)
    for tool, args in [(plan_tools.append_node, {"text": "C"}),
                       (plan_tools.edit_node, {"node_id": root, "text": "x"}),
                       (plan_tools.remove_node, {"node_id": root})]:
        result = call(tool, **args)
        assert (result.success, result.code, result.version) == (False, "plan_frozen", 2)
    assert max(store.snapshots) == 3
    read = call(plan_tools.read_plan)
    assert (read.success, read.version, read.plan_state) == (True, 2, "executing")
    assert "B" not in read.tree


def test_an_invalid_change_is_refused_with_the_tree(headers, store):
    result = call(plan_tools.remove_node, node_id=agent_plans.root_node_id(PLAN_ID))
    assert (result.success, result.code, result.version) == (False, "invalid_plan_change", 1)
    assert "cannot be removed" in result.error


@pytest.mark.parametrize("change, code", [
    ({"X-Hoover4-Agent-Run": ""}, "caller_unknown"),
    ({"X-Hoover4-Agent-Run": "chat-run"}, "no_plan"),
    ({"X-Hoover4-Agent-Run": "unknown-run"}, "run_unknown"),
])
def test_a_call_without_a_plan_run_is_refused(headers, store, change, code):
    headers.update(change)
    result = call(plan_tools.read_plan)
    assert (result.success, result.code) == (False, code)


def test_a_terminal_plan_run_is_closed(headers, store):
    store.plan_run.state = agent_plans.CANCELLED
    assert call(plan_tools.append_node, text="A").code == "run_closed"


def test_a_document_is_read_one_page_at_a_time(headers, store):
    first = call(plan_tools.read_plan_document, document_id="doc-1")
    assert (first.total_chars, len(first.text), first.next_offset) == (20_000, 16_000, 16_000)
    second = call(plan_tools.read_plan_document, document_id="doc-1", offset="16000")
    assert (len(second.text), second.next_offset) == (4_000, None)
    listing = call(plan_tools.read_plan_document)
    assert listing.text.startswith("doc-1 report")
