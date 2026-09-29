"""The plan layer of `AgentRun` with no database: the frozen execution settings, the section
outcomes, the section assignments, the controller dispatch and the section-outcome message.
"""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from temporalio.testing import ActivityEnvironment

from database import agent_plans as ap
from database import agent_runs
from tasks.P_agent import activities, plan_runs, steps

PRID = "7a3f9c1e-2b4d-4e6f-8a0b-1c2d3e4f5a6b"
PLAN = plan_runs.plan_id_for(PRID)
ORGANIZER = "4d2c1b0a-9f8e-4d7c-8b6a-5f4e3d2c1b0a"


def _node(text, *children):
    return {"text": text, "children": list(children)}


def _approved():
    """Version 2: section A with a nested subtree, and section B with no child."""
    base = ap.initial_snapshot(PLAN, "Who owns the lease?")
    return ap.build_tree(base, [_node("A", _node("A1", _node("A1a"))), _node("B")], "k")


def _row(run_id, **changes):
    base = dict(run_id=run_id, username="u", session_id="s", turn_seq=3, thread_id=run_id,
                depth=1, kind="subagent", plan_run_id=PRID, state="completed",
                queue="research-queue", started_at=datetime(2026, 1, 1))
    base.update(changes)
    return agent_runs.RunRow(**base)


@pytest.fixture
def plan(monkeypatch):
    """A plan run at approved version 2 with its execution settings, and lists in place of
    every plan and run store read and write."""
    snap = _approved()
    state = {"snapshot": snap, "documents": [], "reports": {}, "rows": [],
             "messages": {}, "written_rows": [], "settings": {
                 "version": 1, "plan_contract": ap.PLAN_CONTRACT, "model": "model-a",
                 "model_source": "request", "internet_tools": False},
             "plan_run": ap.PlanRunRow(PRID, PLAN, "u", "s", state=ap.EXECUTING,
                                       approved_version=snap.version)}
    monkeypatch.setattr(ap, "read_plan_run", lambda *a: state["plan_run"])
    monkeypatch.setattr(ap, "read_snapshot", lambda *a: state["snapshot"])
    monkeypatch.setattr(ap, "read_documents", lambda *a: list(state["documents"]))
    monkeypatch.setattr(ap, "read_report_data",
                        lambda u, s, p, first: state["reports"].get(first))
    monkeypatch.setattr(ap, "read_execution_settings", lambda *a: state["settings"])
    monkeypatch.setattr(ap, "write_document",
                        lambda *a, **k: state["documents"].append(ap.PlanDocument(
                            ap.document_id(a[3], a[6]), a[4], a[5], a[6], 0, a[7])))
    monkeypatch.setattr(plan_runs, "_plan_rows", lambda *a: list(state["rows"]))
    monkeypatch.setattr(agent_runs, "read_messages",
                        lambda u, s, thread: list(state["messages"].get(thread, [])))
    return state


# ------------------------------------------------------------------ execution settings


def test_the_first_planner_freezes_the_model_and_a_later_run_reads_it(monkeypatch):
    from tasks.P_agent import stream_writer

    written = []
    stored = {}
    monkeypatch.setattr(ap, "read_execution_settings", lambda *a: stored.get("s"))
    monkeypatch.setattr(ap, "write_execution_settings",
                        lambda u, s, p, root, settings: (written.append((p, root, settings)),
                                                         stored.update(s=settings)))
    monkeypatch.setattr(stream_writer, "_chat_model", lambda: "default-model")
    inp = SimpleNamespace(username="u", session_id="s", plan_run_id=PRID, llm_model="model-a",
                          internet_tools=True, model_source="")
    first = plan_runs.freeze_settings(inp)
    assert first == {"version": 1, "plan_contract": 2, "model": "model-a",
                     "model_source": "request", "internet_tools": True}
    assert written == [(PRID, ap.root_node_id(PLAN), first)]
    later = SimpleNamespace(**{**vars(inp), "llm_model": "", "internet_tools": False})
    assert plan_runs.freeze_settings(later) == first
    assert len(written) == 1


def test_a_plan_from_before_the_settings_freezes_the_legacy_or_default_model(monkeypatch):
    from tasks.P_agent import stream_writer

    written = []
    monkeypatch.setattr(ap, "read_execution_settings", lambda *a: None)
    monkeypatch.setattr(ap, "write_execution_settings",
                        lambda u, s, p, root, settings: written.append(settings))
    monkeypatch.setattr(stream_writer, "_chat_model", lambda: "default-model")
    legacy = SimpleNamespace(username="u", session_id="s", plan_run_id=PRID,
                             llm_model="planner-model", internet_tools=False,
                             model_source="legacy_planner")
    assert plan_runs.freeze_settings(legacy)["model_source"] == "legacy_planner"
    empty = SimpleNamespace(**{**vars(legacy), "llm_model": "", "model_source": ""})
    settings = plan_runs.freeze_settings(empty)
    assert (settings["model"], settings["model_source"]) == (
        "default-model", "configured_default")


def test_an_opened_run_of_a_plan_carries_the_frozen_model_and_the_dispatch(monkeypatch, plan):
    from tasks.P_agent import stream_writer

    monkeypatch.setattr(stream_writer, "prepare_thread", lambda messages: messages)
    organizer = _row(ORGANIZER, depth=0, kind="organizer", state="running")
    opened = activities._opened(organizer)
    assert (opened.llm_model, opened.internet_tools, opened.dispatch) == ("model-a", False, True)
    continued = _row("c", depth=0, kind="organizer", state="running",
                     continues_run_id=ORGANIZER)
    assert activities._opened(continued).dispatch is False
    chat = _row("chat", depth=0, kind="chat", plan_run_id=None, state="running")
    plan["settings"] = None
    assert (activities._opened(chat).llm_model, activities._opened(chat).dispatch) == ("", False)


def test_a_step_request_carries_no_delegation_field():
    params = SimpleNamespace(allowed_collections=[], llm_model="m")
    body = steps._step_run(_row("x", plan_node_id="n", purpose="correct"), params)
    assert "can_delegate" not in body and "purpose" not in body
    assert body["llm_model"] == "m"


# ------------------------------------------------------------------ section outcomes


def test_the_sections_come_from_the_thread_and_its_report(plan):
    snap = plan["snapshot"]
    a, b = (n.node_id for n, _ in ap.sections(snap))
    plan["rows"] = [
        _row("ra", plan_node_id=a, purpose="execute"),
        _row("rb", plan_node_id=b, purpose="execute", end_reason="step_budget"),
    ]
    plan["reports"] = {"ra": {"execution": {"state": "completed", "incomplete": False}},
                       "rb": {"execution": {"state": "completed", "incomplete": True}}}
    entries = plan_runs.section_entries("u", "s", PRID)
    assert [(e["title"], e["tasks"], e["state"], e["failed"], e["cause"]) for e in entries] == [
        ("A", 1, "completed", False, ""),
        ("B", 1, "completed", True, "the run stopped before an answer (step_budget)")]
    plan["reports"].pop("ra")
    assert plan_runs.section_entries("u", "s", PRID)[0]["cause"] == "no report"
    plan["documents"].append(ap.PlanDocument(ap.document_id("ra", "report"), a, "executor",
                                             "report", 0, "text"))
    assert plan_runs.section_entries("u", "s", PRID)[0]["failed"] is False


def test_a_continuation_row_is_the_state_of_its_thread(plan):
    a = ap.sections(plan["snapshot"])[0][0].node_id
    first = _row("ra", plan_node_id=a, purpose="execute", state="waiting_for_children")
    later = _row("ra2", plan_node_id=a, purpose="execute", thread_id="ra",
                 continues_run_id="ra", state="failed", error="model down",
                 started_at=datetime(2026, 1, 1) + timedelta(minutes=5))
    plan["rows"] = [first, later]
    plan["reports"] = {"ra": {"execution": {"incomplete": False}}}
    entry = plan_runs.section_entries("u", "s", PRID)[0]
    assert (entry["state"], entry["cause"]) == ("failed", "the run ended failed: model down")


def test_a_plan_from_before_the_settings_keeps_its_stored_sections(plan):
    stored = [{"node_id": "old", "title": "Old section", "corrections": 1, "failed": False,
               "off_tree_reports": [{"run_id": "x", "state": "completed", "report": True}]}]
    plan["settings"] = None
    plan["plan_run"] = ap.PlanRunRow(PRID, PLAN, "u", "s", state=ap.COMPLETED,
                                     approved_version=2, sections_json=json.dumps(stored))
    assert plan_runs.section_entries("u", "s", PRID) == stored


def test_the_organizer_answer_names_each_failed_section(monkeypatch, plan):
    written = []
    monkeypatch.setattr(ap, "write_plan_run", lambda *a, **k: written.append(k))
    a = ap.sections(plan["snapshot"])[0][0].node_id
    plan["rows"] = [_row("ra", plan_node_id=a, purpose="execute", state="failed")]
    answer = plan_runs.final_answer(_row(ORGANIZER, depth=0, kind="organizer"), "Combined.")
    assert answer.startswith("Combined.\n\n## Failed sections")
    assert "| A | the run ended failed |" in answer and "| B | no run |" in answer
    assert json.loads(written[-1]["sections_json"])[0]["failed"] is True


# ------------------------------------------------------------------ assignments and dispatch


def _planning_messages(plan):
    planner0 = _row("p0", depth=0, kind="planner", plan_node_id=None,
                    result="Which year: 2019 or 2020?")
    planner1 = _row("p1", depth=0, kind="planner", plan_node_id=None,
                    result="Orientation: the lease files are in testdata.",
                    started_at=datetime(2026, 1, 1) + timedelta(minutes=5))
    plan["rows"] = [planner0, planner1]
    plan["messages"] = {
        "p0": [agent_runs.RunMessageRow(idx=0, role="human", content="Who owns the lease?"),
               agent_runs.RunMessageRow(idx=1, role="tool", tool_name="ask_user",
                                        usage_json='{"status":"ok"}')],
        "p1": [agent_runs.RunMessageRow(idx=0, role="human",
                                        content="The person answered your question: 2019"),
               agent_runs.RunMessageRow(
                   idx=2, role="tool", tool_name="read_documents", content="{}",
                   usage_json=json.dumps({"status": "ok", "evidence": [{
                       "kind": "document_read", "status": "ok", "reference": {
                           "collectionname": "testdata", "file_hash": "a" * 64,
                           "path": "/lease.txt"}}]}))],
    }


def test_each_section_briefing_holds_the_context_and_the_whole_subtree(plan):
    _planning_messages(plan)
    briefings = plan_runs.section_briefings("u", "s", PRID, ["testdata"], plan["settings"])
    assert [b["section"] for _, b, _ in briefings] == ["1", "2"]
    node, briefing, text = briefings[0]
    assert node == ap.sections(plan["snapshot"])[0][0].node_id
    assert (briefing["controller"], briefing["purpose"], briefing["model"],
            briefing["approved_version"], briefing["collections"]) == (
        True, "execute", "model-a", 2, ["testdata"])
    assert "  1. A\n    1.1. A1\n      1.1.1. A1a" in text
    assert "The person's request:\nWho owns the lease?" in text
    assert "The planner asked: Which year: 2019 or 2020?" in text
    assert "The person answered your question: 2019" in text
    assert "Orientation: the lease files are in testdata." in text
    assert f"- testdata /lease.txt file_hash {'a' * 64}" in text
    assert "Permitted collections: testdata. Web tools: not available." in text
    assert "  2. B" in briefings[1][2] and "1.1. A1" not in briefings[1][2]


class _Writer:
    def __init__(self, row, log):
        self.row, self.log = row, log

    def read(self):
        return self.row

    def write(self, **changes):
        self.log.append(changes)
        for key, value in changes.items():
            setattr(self.row, key, value)


def test_the_dispatch_writes_one_child_a_section_once(monkeypatch, plan):
    _planning_messages(plan)
    children = {}
    messages = []
    monkeypatch.setattr(agent_runs, "read_run",
                        lambda u, s, run_id: children.get(run_id))
    monkeypatch.setattr(agent_runs, "create_run", lambda row: children.update({row.run_id: row}))
    monkeypatch.setattr(agent_runs, "write_message", lambda *a: messages.append(a))
    monkeypatch.setattr(activities, "_batch_children",
                        lambda row, batch: list(children.values()))
    organizer = _row(ORGANIZER, depth=0, kind="organizer", state="running", next_seq=9)
    log = []
    summary = activities._dispatch_sections(organizer, ["testdata"], _Writer(organizer, log))
    batch = agent_runs.batch_id_for(ORGANIZER)
    assert summary.outcome == "delegated" and summary.batch_id == batch
    assert summary.children == [agent_runs.child_run_id(batch, i) for i in range(2)]
    sections = [n.node_id for n, _ in ap.sections(plan["snapshot"])]
    rows = [children[c] for c in summary.children]
    assert [(r.plan_node_id, r.purpose, r.depth, r.kind, r.tool_call_id, r.parent_run_id)
            for r in rows] == [(s, "execute", 1, "subagent", "", ORGANIZER) for s in sections]
    assert [json.loads(r.briefing)["section"] for r in rows] == ["1", "2"]
    assert log == [{"state": "waiting_for_children", "delegated_batch_id": batch,
                    "delegate_seq": 9, "refused_json": "[]"}]
    prompts = [d for d in plan["documents"] if d.kind == "prompt"]
    assert [d.node_id for d in prompts] == sections
    assert len(messages) == 2
    # A retry after the waiting state returns the same children and writes nothing.
    again = activities._dispatch_sections(organizer, ["testdata"], _Writer(organizer, log))
    assert (again.children, len(log), len(messages)) == (summary.children, 1, 2)


def test_a_dispatch_retry_before_the_waiting_state_writes_only_the_missing_child(
        monkeypatch, plan):
    batch = agent_runs.batch_id_for(ORGANIZER)
    first = agent_runs.child_run_id(batch, 0)
    children = {first: _row(first, state="running")}
    created = []
    monkeypatch.setattr(agent_runs, "read_run", lambda u, s, run_id: children.get(run_id))
    monkeypatch.setattr(agent_runs, "create_run", created.append)
    monkeypatch.setattr(agent_runs, "write_message", lambda *a: None)
    organizer = _row(ORGANIZER, depth=0, kind="organizer", state="running")
    summary = activities._dispatch_sections(organizer, [], _Writer(organizer, []))
    assert [r.run_id for r in created] == [agent_runs.child_run_id(batch, 1)]
    assert len(summary.children) == 2


def test_a_stopped_turn_ends_the_organizer_and_starts_no_section(monkeypatch, plan):
    organizer = _row(ORGANIZER, depth=0, kind="organizer", state="running")
    endings = []
    monkeypatch.setattr(agent_runs, "read_run", lambda *a: organizer)
    monkeypatch.setattr(agent_runs, "turn_is_stopped", lambda *a: True)
    monkeypatch.setattr(activities, "_write_ending", endings.append)
    monkeypatch.setattr(activities, "_dispatch_sections",
                        lambda *a: pytest.fail("a stopped turn starts no section"))
    summary = ActivityEnvironment().run(activities.dispatch_sections, activities.DispatchParams(
        run_id=ORGANIZER, username="u", session_id="s"))
    assert summary.outcome == "closed"
    assert [(e.run_id, e.state) for e in endings] == [(ORGANIZER, "cancelled")]


def test_the_continued_organizer_gets_one_message_with_every_section_outcome(
        monkeypatch, plan):
    a, b = (n.node_id for n, _ in ap.sections(plan["snapshot"]))
    batch = agent_runs.batch_id_for(ORGANIZER)
    ca, cb = (agent_runs.child_run_id(batch, i) for i in range(2))
    kids = [_row(ca, plan_node_id=a, purpose="execute", result="A is owned by X [D1]."),
            _row(cb, plan_node_id=b, purpose="execute", state="failed", error="model down")]
    plan["rows"] = kids
    plan["reports"] = {ca: {"execution": {"incomplete": False}, "diagnostics": {},
                            "documents_read": [{"status": "ok"}],
                            "citations": [{"status": "ok"}], "notes": []},
                       cb: {"execution": {"incomplete": True}, "recent_text": [
                           {"text": "B looked at the deed."}]}}
    organizer = _row(ORGANIZER, depth=0, kind="organizer", state="waiting_for_children",
                     delegated_batch_id=batch)
    continuation = _row("cont", depth=0, kind="organizer", thread_id=ORGANIZER,
                        continues_run_id=ORGANIZER)
    written = []
    monkeypatch.setattr(agent_runs, "read_run", lambda u, s, run_id: organizer)
    monkeypatch.setattr(activities, "_batch_children", lambda row, b_id: kids)
    monkeypatch.setattr(agent_runs, "write_message", lambda *a: written.append(a[4]))
    opening = [agent_runs.RunMessageRow(idx=0, role="human", content="Run the approved plan.")]
    thread = activities._add_section_reports(continuation, opening)
    [message] = written
    assert thread[-1] is message and (message.idx, message.role) == (1, "human")
    assert message.content.startswith(plan_runs.SECTIONS_ENDED_TEXT)
    outcomes = json.loads(message.content.split("\n\n", 1)[1])["sections"]
    assert [(o["node"], o["state"], o["failed"]) for o in outcomes] == [
        ("1", "completed", False), ("2", "failed", True)]
    assert outcomes[0]["report"] == "A is owned by X [D1]."
    assert outcomes[0]["evidence"] == {"documents_read": 1, "failed_items": 0,
                                       "citations": 1, "notes": 0}
    assert outcomes[1]["cause"] == "the run ended failed: model down"
    assert outcomes[1]["latest_text"] == "B looked at the deed."
    # A retry finds the message by its marker and writes nothing.
    assert activities._add_section_reports(continuation, thread) == thread
    assert len(written) == 1


def test_the_planner_detects_a_question_in_the_previous_round(monkeypatch):
    prior = _row("prior", depth=0, kind="planner", plan_node_id=None)
    monkeypatch.setattr(plan_runs, "_plan_rows", lambda *args: [prior])
    monkeypatch.setattr(agent_runs, "read_messages", lambda *args: [
        agent_runs.RunMessageRow(idx=2, role="tool", content='{"asked":true}',
                                 tool_name="ask_user", usage_json='{"status":"ok"}')])
    assert plan_runs._last_planner_asked("u", "s", PRID, "next") is True


def test_an_organizer_needs_an_approval_decision(monkeypatch, plan):
    monkeypatch.setattr(ap, "read_decision", lambda *a: ap.PlanDecision("d", "reject", 2, "no"))
    monkeypatch.setattr(plan_runs, "freeze_settings", lambda inp: {})
    inp = SimpleNamespace(username="u", session_id="s", plan_run_id=PRID, kind="organizer",
                          decision_id="d", run_id="o")
    with pytest.raises(RuntimeError, match="not an approval"):
        plan_runs.open_plan_run(inp, "Approved plan version 2.")
