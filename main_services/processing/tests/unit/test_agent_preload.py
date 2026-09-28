"""The run-start reads: when a run gets them, and the rows that `preload_reads` writes.

The database writers are the lists of `test_agent_run.store`, and the agent service is a
function that answers `/preload`, so no service or Temporal server runs.
"""

import json
from dataclasses import fields

import pytest
import requests
from temporalio.testing import ActivityEnvironment

from database import agent_plans, agent_runs, chat_todos
from tasks.P_agent import activities, preload
from tasks.P_agent.preload import PreloadParams, PreloadResult

from test_agent_run import RUN_ID, _row, step_events, store  # noqa: F401 - fixtures


def _read(name, tool="read_skill", status="ok"):
    return {"id": "", "name": tool, "args": {"name": name},
            "content": f"Skill `{name}`.\n\nText." if tool == "read_skill"
            else json.dumps({"tool": name}),
            "status": status, "error_class": ""}


PICKS = {
    "request_classes": ["topic", "person"],
    "class_scores": {"topic": 0.93, "person": 0.61},
    "picks": {"technique": [], "stumble": []},
    "reads": [_read("search")],
    "classifier": {"state": "ok", "error": "", "ms": 412},
}


@pytest.fixture
def service(store, monkeypatch):
    """The agent service. Returns the requests by path."""
    sent = {"preload": []}
    state = {"picks": PICKS, "fail": None}

    def post(url, body, read_seconds):
        path = url.rsplit("/", 1)[1]
        sent[path].append(body)
        if state["fail"] == path:
            raise requests.HTTPError("500 Server Error")
        if path == "preload":
            return state["picks"]
        raise AssertionError(path)

    def write_messages(username, session_id, thread_id, run_id, rows):
        store["inserts"] = store.get("inserts", 0) + 1
        for message in rows:
            agent_runs.write_message(username, session_id, thread_id, run_id, message)

    monkeypatch.setattr(preload, "_post_json", post)
    monkeypatch.setattr(agent_runs, "write_messages", write_messages)
    monkeypatch.setattr(preload, "_earlier_turns", lambda row: state.get("earlier", []))
    sent["state"] = state
    return sent


def _preload(classify="all"):
    return ActivityEnvironment().run(preload.preload_reads, PreloadParams(
        run_id=RUN_ID, username="u", session_id="s", classify=classify))


# ---------------------------------------------------------------- when it runs


@pytest.mark.parametrize("kind, depth, messages, earlier_users, continues, expected", [
    ("chat", 0, ["human"], 0, None, (True, "all")),           # a chat's first turn
    ("chat", 0, ["human"], 1, None, (True, "none")),          # a later turn
    ("planner", 0, ["human"], 0, None, (True, "types")),      # a planner run
    ("organizer", 0, ["human"], 0, None, (True, "none")),
    ("chat", 1, ["human"], 0, None, (True, "none")),          # a sub-agent
    ("chat", 0, ["human", "ai"], 0, None, (False, "none")),   # a resumed thread
    ("chat", 1, ["human"], 0, RUN_ID, (False, "none")),       # a continuation
])
def test_a_run_that_starts_a_thread_gets_a_preload(monkeypatch, kind, depth, messages,
                                                   earlier_users, continues, expected):
    rows = [agent_runs.RunMessageRow(idx=i, role=r, run_id=RUN_ID)
            for i, r in enumerate(messages)]
    monkeypatch.setattr(agent_runs, "read_messages", lambda *a: rows)
    monkeypatch.setattr(activities, "_earlier_user_rows", lambda *a: earlier_users)
    opened = activities._opened(_row(kind=kind, depth=depth, continues_run_id=continues))
    assert (opened.preload, opened.preload_classify) == expected


def test_the_preload_payloads_hold_no_text():
    for params in (PreloadParams, PreloadResult):
        names = {f.name for f in fields(params)}
        assert not names & {"query", "answer", "content", "result", "report", "text"}, params


# ---------------------------------------------------------------- the rows


def test_a_first_turn_writes_the_reads_in_one_insert(service, store, step_events):
    result = _preload()
    assert result == PreloadResult("written", reads=1, request_classes=["topic", "person"])
    assert store["inserts"] == 1
    rows = [(m.idx, m.role, m.tool_call_id) for m in store["messages"]]
    assert rows == [(0, "human", ""), (1, "ai", ""), (2, "tool", "preload-1-0")]
    read_ai = store["messages"][1]
    assert read_ai.content == "" and read_ai.reasoning == ""
    assert [(c["id"], c["name"], c["seq"], c["kind"]) for c in read_ai.tool_calls] == [
        ("preload-1-0", "read_skill", 5, "parallel")]
    assert read_ai.usage["mode"] == "preload" and read_ai.usage["synthetic"] is True
    assert read_ai.usage["step_no"] == 0 and "bound_names" not in read_ai.usage
    assert read_ai.usage["request_classes"] == ["topic", "person"]
    assert read_ai.usage["classifier"]["state"] == "ok"
    assert store["messages"][2].usage == {"chat_seq": 5, "status": "ok", "measure": None,
                                          "error_class": ""}
    assert [(c["seq"], c["tool_name"]) for c in store["chat"]] == [(5, "read_skill")]
    assert store["run"] == [{"next_seq": 6}]
    body = service["preload"][0]
    assert (body["classify"], body["already_read"], body["request_text"]) == ("all", [], "q")
    assert [(e.step, e.name, e.ok, e.mode) for e in step_events] == [
        ("preload", "systemone", True, "ok")]


def test_a_thread_with_a_preload_writes_nothing_again(service, store):
    _preload()
    assert _preload() == PreloadResult("written")
    assert len(service["preload"]) == 1 and store["inserts"] == 1


def test_a_later_turn_sends_the_skills_that_earlier_turns_read(service, store):
    service["state"]["earlier"] = [
        {"role": "ai", "thread_id": "t1", "tool_calls": [
            {"id": "a", "name": "read_skill", "args": {"name": "search"}},
            {"id": "b", "name": "read_skill", "args": {"name": "citation"}}]},
        {"role": "tool", "thread_id": "t1", "tool_call_id": "a", "status": "ok"},
        {"role": "tool", "thread_id": "t1", "tool_call_id": "b", "status": "error"},
    ]
    service["state"]["picks"] = {**PICKS, "reads": [], "request_classes": []}
    result = _preload(classify="none")
    assert service["preload"][0]["already_read"] == ["search"]
    assert result.outcome == "nothing" and "inserts" not in store
    assert store["run"] == []


def test_a_subagent_writes_no_transcript_row_and_sends_no_earlier_read(service, store):
    store["row"] = _row(depth=1)
    service["state"]["earlier"] = [{"role": "tool", "status": "ok"}]
    _preload(classify="none")
    assert service["preload"][0]["already_read"] == []
    assert store["chat"] == []
    assert [m.role for m in store["messages"]] == ["human", "ai", "tool"]


def test_a_failed_preload_request_writes_nothing_and_one_failed_event(service, store,
                                                                      step_events):
    service["state"]["fail"] = "preload"
    with pytest.raises(requests.HTTPError):
        _preload()
    assert [m.role for m in store["messages"]] == ["human"]
    assert store["chat"] == [] and store["run"] == []
    assert [(e.step, e.ok) for e in step_events] == [("preload", False)]


def test_a_closed_run_reads_nothing(service, store):
    store["row"] = _row(state=agent_runs.CANCELLED)
    assert _preload() == PreloadResult("closed")
    assert service["preload"] == []


def test_a_rejected_planner_run_sends_the_question_of_the_plan(monkeypatch):
    from tasks.P_agent import plan_runs

    plan_run = "0b5e3c1a-3333-4222-8333-944455556666"
    plan_id = plan_runs.plan_id_for(plan_run)
    root = agent_plans.PlanNode(agent_plans.root_node_id(plan_id), None, 0, "Who owns the port?")
    snapshot = agent_plans.PlanSnapshot(plan_id, 3, (root,))
    monkeypatch.setattr(agent_plans, "read_snapshot", lambda *a, **k: snapshot)
    row = _row(kind="planner", plan_run_id=plan_run)
    rejected = [agent_runs.RunMessageRow(
        idx=0, role="human", content=plan_runs.REJECTED_TEXT.format(version=2) + "\n\nMore.")]
    assert preload.request_text(row, rejected) == "Who owns the port?"
    opening = [agent_runs.RunMessageRow(idx=0, role="human", content="Research the port.")]
    assert preload.request_text(row, opening) == "Research the port."
