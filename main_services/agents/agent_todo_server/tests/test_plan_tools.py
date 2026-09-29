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
        keys={},
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

    def write_snapshot(username, session_id, snapshot, idempotency_key=None):
        time.sleep(0.05)
        state.snapshots[snapshot.version] = snapshot
        if idempotency_key is not None:
            state.keys[idempotency_key] = snapshot.version

    def snapshot_by_key(username, session_id, plan_id, idempotency_key):
        version = state.keys.get(idempotency_key)
        return state.snapshots.get(version) if version else None

    monkeypatch.setattr(agent_runs, "read_run", read_run)
    monkeypatch.setattr(agent_plans, "read_plan_run", read_plan_run)
    monkeypatch.setattr(agent_plans, "read_snapshot", read_snapshot)
    monkeypatch.setattr(agent_plans, "write_snapshot", write_snapshot)
    monkeypatch.setattr(agent_plans, "snapshot_by_key", snapshot_by_key)
    monkeypatch.setattr(agent_plans, "read_documents", lambda u, s, r: [
        agent_plans.PlanDocument("doc-1", agent_plans.root_node_id(PLAN_ID), "executor",
                                 "report", 0, "x" * 20_000)])
    return state


def test_two_parallel_mutations_land_as_consecutive_versions(headers, store):
    async def both():
        return await asyncio.gather(plan_tools.append_node.fn(version=1, text="A"),
                                    plan_tools.append_node.fn(version=1, text="B"))

    first, second = asyncio.run(both())
    assert first.success and second.success
    assert sorted([first.version, second.version]) == [2, 3]
    newest = store.snapshots[3]
    assert sorted(n.text for n in newest.nodes if n.parent_id) == ["A", "B"]


def test_stale_number_is_refused_after_renumbering(headers, store):
    call(plan_tools.append_node, version=1, text="A")
    call(plan_tools.append_node, version=2, text="B")
    call(plan_tools.remove_node, version=3, node_id="1")
    refused = call(plan_tools.edit_node, version=3, node_id="1", text="Changed")
    assert (refused.success, refused.code, refused.version) == (False, "stale_version", 4)
    assert "B" in refused.tree


def test_plan_result_exposes_outline_tree_only(headers, store):
    result = call(plan_tools.append_node, version=1, text="A")
    assert result.model_dump() == {"plan_state": "planning", "version": 2,
                                   "tree": "root. What happened?\n  1. A"}


def test_a_sub_agent_of_the_planner_changes_the_plan_with_no_role_check(headers, store):
    headers["X-Hoover4-Agent-Run"] = "helper-run"
    result = call(plan_tools.append_node, version=1, text="From a helper")
    assert result.success and result.version == 2
    assert [s.tasks for s in result.sections] == [["From a helper"]]


def test_frozen_plan_refuses_every_mutation_and_reads_the_approved_version(headers, store):
    assert call(plan_tools.append_node, version=1, text="A").version == 2
    assert call(plan_tools.append_node, version=2, text="B").version == 3
    store.plan_run.state = agent_plans.EXECUTING
    store.plan_run.approved_version = 2
    root = agent_plans.root_node_id(PLAN_ID)
    for tool, args in [(plan_tools.append_node, {"text": "C"}),
                       (plan_tools.edit_node, {"node_id": root, "text": "x"}),
                       (plan_tools.remove_node, {"node_id": root})]:
        result = call(tool, version=3, **args)
        assert (result.success, result.code, result.version) == (False, "plan_frozen", 2)
    assert max(store.snapshots) == 3
    read = call(plan_tools.read_plan)
    assert (read.success, read.version, read.plan_state) == (True, 2, "executing")
    assert "B" not in read.tree


def test_an_invalid_change_is_refused_with_the_tree(headers, store):
    result = call(plan_tools.remove_node, version=1, node_id=agent_plans.root_node_id(PLAN_ID))
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
    assert call(plan_tools.append_node, version=1, text="A").code == "run_closed"


def test_a_document_is_read_one_page_at_a_time(headers, store):
    first = call(plan_tools.read_plan_document, document_id="doc-1")
    assert (first.total_chars, len(first.text), first.next_offset) == (20_000, 16_000, 16_000)
    second = call(plan_tools.read_plan_document, document_id="doc-1", offset="16000")
    assert (len(second.text), second.next_offset) == (4_000, None)
    listing = call(plan_tools.read_plan_document)
    assert listing.text.startswith("doc-1 report")


def test_a_mutation_repeated_with_one_key_writes_one_version(headers, store):
    headers["X-Hoover4-Idempotency-Key"] = "0b7c6f2e-3a4d-5e6f-8a9b-1c2d3e4f5a6b"
    first = call(plan_tools.append_node, version=1, text="A")
    second = call(plan_tools.append_node, version=1, text="A")
    assert first.version == 2
    assert second.model_dump() == first.model_dump()
    assert sorted(store.snapshots) == [1, 2]


def test_a_mutation_with_no_key_writes_a_version_each_time(headers, store):
    assert call(plan_tools.append_node, version=1, text="A").version == 2
    assert call(plan_tools.append_node, version=1, text="A").version == 3


def test_a_malformed_key_is_read_as_no_key(headers, store):
    headers["X-Hoover4-Idempotency-Key"] = "not-a-uuid"
    assert call(plan_tools.append_node, version=1, text="A").version == 2
    assert call(plan_tools.append_node, version=1, text="A").version == 3
    assert store.keys == {}


def test_a_number_path_names_the_parent_and_an_unknown_one_lists_the_nodes(headers, store):
    # The calls of one planner reply that used numbers as parent ids.
    assert call(plan_tools.append_node, version=1, text="Survey").success
    child = call(plan_tools.append_child, version=2, parent_id="1", text="Search every collection")
    assert child.success
    assert [(s.title, s.tasks) for s in child.sections] == [("Survey", ["Search every collection"])]
    assert "  1. Survey" in child.tree and "    1.1. Search every collection" in child.tree
    assert "[" not in child.tree
    refused = call(plan_tools.append_child, version=3, parent_id="3", text="Count per collection")
    assert (refused.success, refused.code, refused.version) == (False, "invalid_plan_change", 3)
    assert "no node has the id or number path '3'" in refused.error
    assert "1 " in refused.error and "(Survey)" in refused.error


# ------------------------------------------------------------------ read_plan_report


def _report(entries=40, final="The lease is from 2019. " * 400):
    """A typed report with a long final answer and `entries` read entries."""
    return {
        "version": 1, "thread_id": "t", "first_run_id": "first-run",
        "execution": {"state": "completed", "end_reason": "", "incomplete": False, "error": ""},
        "final_answer": {"source": {"thread_id": "t", "message_idx": 9}, "text": final},
        "recent_text": [{"source": {"thread_id": "t", "message_idx": 9}, "text": "Short."}],
        "documents_read": [
            {"version": 1, "source": {"thread_id": "t", "message_idx": i, "item_key": f"read:{i}"},
             "kind": "document_read", "status": "ok",
             "reference": {"collectionname": "c", "file_hash": f"{i:064d}", "path": f"/doc{i}.txt"},
             "range": {"page": 1}} for i in range(entries)],
        "citations": [], "notes": [], "artifacts": [], "documents_found": [],
        "diagnostics": {"failed_items": 0},
    }


@pytest.fixture
def reports_store(store, monkeypatch):
    """The plan is executing, one sub-agent thread served the root section, and its report
    documents are in `state.report_docs`."""
    root = agent_plans.root_node_id(PLAN_ID)
    store.plan_run.state = agent_plans.EXECUTING
    store.plan_run.approved_version = 1
    store.report = _report()
    thread = SimpleNamespace(run_id="first-run", plan_node_id=root)
    monkeypatch.setattr(agent_runs, "read_plan_threads", lambda u, s, p: [thread])
    monkeypatch.setattr(agent_plans, "read_report_data",
                        lambda u, s, p, first: store.report if first == "first-run" else None)
    return store


def test_a_report_is_read_in_bounded_pages_to_its_end(headers, reports_store):
    items, cursor, pages = [], "", 0
    while True:
        page = call(plan_tools.read_plan_report, node_id="root", cursor=cursor)
        assert page.success, page.error
        assert len(plan_tools.canonical_json(page.model_dump()).encode()) <= plan_tools.REPORT_PAGE_BYTES
        items += page.items
        pages += 1
        if not page.more:
            break
        cursor = page.more
    assert pages > 1
    assert [i["part"] for i in items[:2]] == ["execution", "final_answer"]
    assert "".join(i["text"] for i in items if i["part"] == "final_answer") == (
        reports_store.report["final_answer"]["text"])
    assert [i["reference"]["path"] for i in items if i["part"] == "documents_read"] == [
        f"/doc{i}.txt" for i in range(40)]
    assert len(items) == page.total


def test_a_page_share_header_makes_the_pages_smaller(headers, reports_store):
    headers["X-Hoover4-Page-Share"] = "4000"
    page = call(plan_tools.read_plan_report, node_id="root")
    assert len(plan_tools.canonical_json(page.model_dump()).encode()) <= 4000 + plan_tools.REPORT_TEXT_CHARS


def test_a_changed_report_refuses_the_old_cursor(headers, reports_store):
    first = call(plan_tools.read_plan_report, node_id="root")
    reports_store.report = _report(entries=41)
    refused = call(plan_tools.read_plan_report, node_id="root", cursor=first.more)
    assert (refused.success, refused.code) == (False, "report_changed")
    assert call(plan_tools.read_plan_report, node_id="root").success


@pytest.mark.parametrize("cursor", ["nonsense", "0000000000000000:3"])
def test_a_cursor_of_another_report_is_refused(headers, reports_store, cursor):
    refused = call(plan_tools.read_plan_report, node_id="root", cursor=cursor)
    assert not refused.success and refused.code in ("report_changed", "invalid_cursor")


def test_a_report_with_no_typed_document_reads_as_legacy_text(headers, reports_store, monkeypatch):
    reports_store.report = None
    monkeypatch.setattr(agent_plans, "document_body", lambda u, s, doc: doc.body)
    monkeypatch.setattr(agent_plans, "read_documents", lambda u, s, r: [
        agent_plans.PlanDocument(agent_plans.document_id("first-run", "report"),
                                 agent_plans.root_node_id(PLAN_ID), "executor", "report", 0,
                                 "The old report.")])
    page = call(plan_tools.read_plan_report, node_id="root")
    assert page.items == [{"part": "legacy_text", "text": "The old report."}]


def test_a_node_with_no_sub_agent_or_an_unknown_node_is_refused(headers, reports_store,
                                                                   monkeypatch):
    assert call(plan_tools.read_plan_report, node_id="9").code == "node_unknown"
    monkeypatch.setattr(agent_runs, "read_plan_threads", lambda u, s, p: [])
    assert call(plan_tools.read_plan_report, node_id="root").code == "no_report"


def test_a_report_read_keeps_the_caller_check(headers, reports_store):
    headers["X-Hoover4-Agent-Run"] = "chat-run"
    assert call(plan_tools.read_plan_report, node_id="root").code == "no_plan"


def test_a_long_report_pages_in_linear_time_and_fits_each_page():
    """A report of 2,000 read entries. The page is built forward and serialized once, so
    all its pages take far less than a second on the test machine."""
    units = plan_tools.report_units(_report(entries=2_000, final="short"))
    started = time.monotonic()
    start, seen, pages = 0, 0, 0
    while True:
        page = plan_tools.report_page("root", units, start, plan_tools.REPORT_PAGE_BYTES)
        assert len(plan_tools.canonical_json(page.model_dump()).encode()) <= plan_tools.REPORT_PAGE_BYTES
        assert page.items == units[start:start + len(page.items)]
        seen += len(page.items)
        pages += 1
        if not page.more:
            break
        start = int(page.more.split(":")[1])
    elapsed = time.monotonic() - started
    assert seen == len(units) and pages > 10
    assert elapsed < 1.0, elapsed


def test_an_unreadable_legacy_report_is_refused(headers, reports_store, monkeypatch):
    reports_store.report = None

    def broken(u, s, doc):
        raise agent_plans.DocumentBodyError("the object store did not answer")

    monkeypatch.setattr(agent_plans, "document_body", broken)
    monkeypatch.setattr(agent_plans, "read_documents", lambda u, s, r: [
        agent_plans.PlanDocument(agent_plans.document_id("first-run", "report"),
                                 agent_plans.root_node_id(PLAN_ID), "executor", "report", 0,
                                 "", artifact_id="a1")])
    page = call(plan_tools.read_plan_report, node_id="root")
    assert (page.success, page.code) == (False, "report_unreadable")
