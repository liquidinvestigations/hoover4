"""The `AgentRun` workflow, its activities and its storage, with no service running.

The database writers are replaced by lists, and the agent stream by a list of frames, so
each test reads exactly what the activity would have written.
"""

import ast
import json
from dataclasses import fields
from pathlib import Path

import pytest
from temporalio.converter import DataConverter
from temporalio.testing import ActivityEnvironment

import tasks.P_agent.workflows as agent_workflows
from database import agent_runs
from tasks.P_agent import activities, stream_writer
from tasks.P_agent.activities import (
    AgentRunInput, AppendNagParams, OpenedRun, RunAgentParams, RunRef, RunSummary,
    WriteEndingParams,
)

RUN_WORKER = Path(agent_workflows.__file__).resolve().parent.parent / "run_worker.py"
RUN_ID = "0b5e3c1a-1111-4222-8333-944455556666"

#: A live tool call id under streaming: the served model's id repeated by the chunk join.
LONG_ID_A = "chatcmpl-tool-a5ca7d0e11f2" * 9
LONG_ID_B = "chatcmpl-tool-b71c3e9d04aa" * 9


def _payload_bytes(value) -> int:
    payloads = DataConverter.default.payload_converter.to_payloads([value])
    return sum(p.ByteSize() for p in payloads)


# ---------------------------------------------------------------- registration


def _chat_worker_calls():
    tree = ast.parse(RUN_WORKER.read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_chat_worker")
    workers = {}
    for call in ast.walk(fn):
        if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "Worker":
            kw = {k.arg: k.value for k in call.keywords}
            queue = kw["task_queue"].id
            workflows = [e.id for e in kw["workflows"].elts]
            acts = [e.id for e in kw["activities"].elts]
            workers[queue] = (workflows, acts)
    return workers


def test_agent_run_and_its_activities_are_registered_on_their_queues():
    workers = _chat_worker_calls()
    chat_workflows, chat_acts = workers["CHAT_TASK_QUEUE"]
    assert chat_workflows == ["AgentRun"]
    for name in ("open_run", "append_nag", "write_ending", "summarize_if_first_turn",
                 "read_chat_todo"):
        assert name in chat_acts, name
    assert "run_agent" in workers["CHAT_MODEL_TASK_QUEUE"][1]
    assert "run_agent" in workers["RESEARCH_TASK_QUEUE"][1]


def test_the_agent_run_sweep_is_registered_on_the_operations_queue():
    tree = ast.parse(RUN_WORKER.read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_operations_worker")
    for call in ast.walk(fn):
        if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "Worker":
            kw = {k.arg: k.value for k in call.keywords}
            if getattr(kw["task_queue"], "value", "") == "operations-queue":
                assert "supervise_agent_runs" in [e.id for e in kw["activities"].elts]
                return
    raise AssertionError("no operations-queue worker")


def test_fan_in_and_continue_run_are_registered_on_the_chat_queue():
    _, chat_acts = _chat_worker_calls()["CHAT_TASK_QUEUE"]
    assert {"fan_in", "continue_run"} <= set(chat_acts)


def test_chat_turn_is_removed_and_unregistered():
    assert not hasattr(agent_workflows, "ChatTurn")
    assert "ChatTurn" not in RUN_WORKER.read_text()


def test_every_activity_agent_run_schedules_is_registered_on_its_queue():
    tree = ast.parse(Path(agent_workflows.__file__).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AgentRun")
    workers = _chat_worker_calls()
    for call in ast.walk(cls):
        if isinstance(call, ast.Call) and getattr(call.func, "attr", "") == "execute_activity":
            name = call.args[0].id
            queue = next(k.value for k in call.keywords if k.arg == "task_queue")
            if isinstance(queue, ast.Name):
                assert name in workers[queue.id][1], (name, queue.id)
            else:
                # The agent activity goes to the queue in the row.
                assert name == "run_agent"
                for lead_queue in agent_runs.LEAD_QUEUES.values():
                    constant = {"chat-model-queue": "CHAT_MODEL_TASK_QUEUE",
                                "research-queue": "RESEARCH_TASK_QUEUE"}[lead_queue]
                    assert name in workers[constant][1]


def test_lead_queues_mirror_the_workflow_queue_names():
    assert agent_runs.LEAD_QUEUES["chat"] == agent_workflows.CHAT_MODEL_TASK_QUEUE
    assert agent_runs.LEAD_QUEUES["planner"] == agent_workflows.RESEARCH_TASK_QUEUE


# ---------------------------------------------------------------- workflow input


def test_agent_run_input_holds_ids_and_settings_only():
    assert {f.name for f in fields(AgentRunInput)} == {
        "run_id", "username", "session_id", "kind", "turn_seq", "start_seq", "turn_uuid",
        "allowed_collections", "llm_model", "internet_tools", "plan_run_id", "decision_id",
    }
    for params in (RunAgentParams, RunRef, RunSummary, OpenedRun, WriteEndingParams):
        names = {f.name for f in fields(params)}
        assert not names & {"query", "answer", "content", "result", "briefing", "report"}, params


@pytest.mark.parametrize("stored", [None, []])
def test_agent_run_input_reads_null_collections_as_an_empty_list(stored):
    # The start payload as Temporal's HTTP route stores it for a user with no collection.
    start = {"run_id": RUN_ID, "username": "u", "session_id": "s", "kind": "chat",
             "turn_seq": 1, "start_seq": 2, "turn_uuid": "t", "allowed_collections": stored,
             "llm_model": "", "internet_tools": False}
    converter = DataConverter.default.payload_converter
    payloads = converter.to_payloads([start])
    (inp,) = converter.from_payloads(payloads, [AgentRunInput])
    assert inp.allowed_collections == []


# ---------------------------------------------------------------- the fakes


class _FakeWriter:
    def __init__(self):
        self.writes = []

    def write(self, **changes):
        self.writes.append(changes)

    def start_keepalive(self):
        pass

    def stop_keepalive(self):
        pass


@pytest.fixture
def store(monkeypatch):
    """Replace every database write with a list, and return the lists."""
    written = {"messages": [], "chat": [], "stream": []}

    def write_message(username, session_id, thread_id, run_id, message):
        written["messages"].append(message)

    monkeypatch.setattr(agent_runs, "write_message", write_message)
    monkeypatch.setattr(
        stream_writer.ResearchStreamWriter, "_insert_stream_row",
        lambda self, *a, **k: written["stream"].append((a, k)),
    )
    monkeypatch.setattr(stream_writer, "context_window_for", lambda model: 0)
    monkeypatch.setattr(stream_writer, "_chat_model", lambda: "test-model")
    return written


def _row(**changes):
    base = dict(run_id=RUN_ID, username="u", session_id="s", turn_seq=4, thread_id=RUN_ID,
                depth=0, kind="chat", queue="chat-model-queue", start_seq=5, next_seq=5)
    base.update(changes)
    return agent_runs.RunRow(**base)


def _client(store, row=None, messages=None):
    row = row or _row()
    messages = messages or [agent_runs.RunMessageRow(idx=0, role="human", content="question")]

    def chat_row(seq, role, **fields):
        store["chat"].append({"seq": seq, "role": role, **fields})

    return stream_writer.RunStreamClient(
        row, messages, _FakeWriter(), turn_uuid="turn", history=[],
        allowed_collections=["c"], llm_model="m", internet_tools=False,
        write_chat_row=chat_row,
    )


# ---------------------------------------------------------------- pairing


def test_two_parallel_calls_keep_their_own_arguments_and_results(store):
    client = _client(store)
    calls = [
        {"id": LONG_ID_A, "name": "search", "args": {"query": "alpha"}},
        {"id": LONG_ID_B, "name": "search", "args": {"query": "beta"}},
    ]
    client._handle_run_event("model_turn", {"index": 1, "text": "", "reasoning": "",
                                            "tool_calls": calls, "usage": {}})
    client._handle_run_event("tool_start", {"index": 2, "tool_call_id": LONG_ID_A,
                                            "name": "search", "args": {"query": "alpha"}})
    client._handle_run_event("tool_start", {"index": 3, "tool_call_id": LONG_ID_B,
                                            "name": "search", "args": {"query": "beta"}})
    # The second call ends first.
    client._handle_run_event("tool_result", {"index": 3, "tool_call_id": LONG_ID_B,
                                             "name": "search", "content": '{"hits": ["b"]}',
                                             "measure": {"sha256": "bb"}, "status": "ok"})
    client._handle_run_event("tool_result", {"index": 2, "tool_call_id": LONG_ID_A,
                                             "name": "search", "content": '{"hits": ["a"]}',
                                             "measure": {"sha256": "aa"}, "status": "ok"})

    rows = {r["seq"]: r for r in store["chat"]}
    assert set(rows) == {5, 6}
    assert json.loads(rows[5]["tool_input"]) == {"query": "alpha"}
    assert json.loads(rows[5]["tool_output"]) == {"hits": ["a"]}
    assert json.loads(rows[6]["tool_input"]) == {"query": "beta"}
    assert json.loads(rows[6]["tool_output"]) == {"hits": ["b"]}

    tools = {m.idx: m for m in store["messages"] if m.role == "tool"}
    assert tools[2].tool_call_id == LONG_ID_A and tools[3].tool_call_id == LONG_ID_B
    assert json.loads(tools[2].usage_json)["chat_seq"] == 5
    assert json.loads(tools[2].usage_json)["measure"] == {"sha256": "aa"}
    ai = next(m for m in store["messages"] if m.role == "ai" and m.is_final)
    assert [c["id"] for c in json.loads(ai.tool_calls_json)] == [LONG_ID_A, LONG_ID_B]
    assert client.next_seq == 7
    assert client.tool_turns_used == 1


def test_a_retry_keeps_the_unanswered_call_for_the_agent_to_run_first():
    messages = [
        agent_runs.RunMessageRow(idx=0, role="human", content="q"),
        agent_runs.RunMessageRow(idx=1, role="ai", tool_calls_json=json.dumps([
            {"id": "a", "name": "t", "args": {}}, {"id": "b", "name": "t", "args": {}}])),
        agent_runs.RunMessageRow(idx=2, role="tool", tool_call_id="a", content="x",
                                 usage_json='{"chat_seq": 5}'),
        agent_runs.RunMessageRow(idx=3, role="ai", content="part", is_final=0),
    ]
    complete = stream_writer.prepare_thread(messages)
    # The partial goes, and call "b" stays without a result: the agent runs it first.
    assert [m.idx for m in complete] == [0, 1, 2]
    assert list(agent_runs.iter_thread_tool_seqs(complete)) == [5]


# ---------------------------------------------------------------- payload bound


class _FakeResponse:
    def __init__(self, frames):
        self._lines = [f"data: {json.dumps(f)}" for f in frames]

    def raise_for_status(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self, decode_unicode=True):
        return iter(self._lines)


def test_ten_large_pages_stay_out_of_the_run_agent_result(store, monkeypatch):
    page = "p" * 24_000
    calls = [{"id": f"call-{i}", "name": "search", "args": {"query": str(i)}}
             for i in range(10)]
    frames = [{"type": "model_turn", "content": {"index": 1, "text": "", "reasoning": "",
                                                 "tool_calls": calls, "usage": {}}}]
    for i, call in enumerate(calls):
        frames.append({"type": "tool_start", "content": {
            "index": 2 + i, "tool_call_id": call["id"], "name": "search", "args": call["args"]}})
    for i, call in enumerate(calls):
        frames.append({"type": "tool_result", "content": {
            "index": 2 + i, "tool_call_id": call["id"], "name": "search", "content": page,
            "measure": None, "status": "ok"}})
    frames.append({"type": "model_turn", "content": {"index": 12, "text": "done",
                                                     "reasoning": "", "tool_calls": [],
                                                     "usage": {}}})
    frames.append({"type": "response", "content": "done"})
    frames.append({"type": "end", "content": "done", "model": "m",
                   "usage": {"prompt_tokens": 7, "completion_tokens": 3}})

    row = _row()
    monkeypatch.setattr(agent_runs, "read_run", lambda *a: row)
    monkeypatch.setattr(agent_runs, "read_messages", lambda *a: [
        agent_runs.RunMessageRow(idx=0, role="human", content="question")])
    monkeypatch.setattr(agent_runs, "RunRowWriter", lambda *a, **k: _FakeWriter())
    monkeypatch.setattr(stream_writer, "_chat_history", lambda *a: [])
    monkeypatch.setattr(stream_writer, "release_browser", lambda run_id: None)
    monkeypatch.setattr(stream_writer.requests, "post", lambda *a, **k: _FakeResponse(frames))
    monkeypatch.setattr(stream_writer.ResearchStreamWriter, "_finish_stream_rows",
                        lambda self: None)
    monkeypatch.setattr(activities, "_insert_chat_row",
                        lambda u, s, seq, role, **f: store["chat"].append(
                            {"seq": seq, "role": role, **f}))

    summary = ActivityEnvironment().run(
        activities.run_agent, RunAgentParams(run_id=RUN_ID, username="u", session_id="s"))

    assert summary.outcome == "answered"
    assert summary.next_seq == 16 and summary.next_idx == 13
    assert _payload_bytes(summary) < agent_workflows.AGENT_RUN_PAYLOAD_BYTES
    stored = [m for m in store["messages"] if m.role == "tool"]
    assert len(stored) == 10 and all(m.content == page for m in stored)
    assert [r["role"] for r in store["chat"]] == ["tool"] * 10 + ["assistant"]
    assert store["chat"][-1]["content"] == "done"


def test_a_summary_with_five_children_stays_under_the_bound():
    summary = RunSummary(outcome="delegated", next_seq=4_000_000_000, next_idx=4_000_000_000,
                         children=[RUN_ID] * 5, batch_id=RUN_ID,
                         prompt_tokens=10**15, completion_tokens=10**15)
    assert _payload_bytes(summary) < agent_workflows.AGENT_RUN_PAYLOAD_BYTES
    inp = AgentRunInput(run_id=RUN_ID, username="u" * 64, session_id="s" * 64,
                        allowed_collections=["c" * 64] * 20, turn_uuid="t" * 64)
    assert _payload_bytes(inp) < agent_workflows.AGENT_RUN_PAYLOAD_BYTES


# ---------------------------------------------------------------- properties and writer


def test_named_properties():
    assert agent_runs.writes_transcript(_row(depth=0, kind="planner"))
    assert not agent_runs.writes_transcript(_row(depth=1, kind="subagent"))
    assert agent_runs.is_chat_lead(_row())
    assert not agent_runs.is_chat_lead(_row(kind="organizer"))


def test_the_row_writer_refuses_a_terminal_row_and_adds_one_to_the_version(monkeypatch):
    rows = {"current": _row(state_version=3)}
    inserted = []
    monkeypatch.setattr(agent_runs, "read_run", lambda *a: rows["current"])

    def version(current, changes):
        inserted.append((current.state_version + 1, changes))
        return current

    monkeypatch.setattr(agent_runs, "_write_version", version)
    writer = agent_runs.RunRowWriter(rows["current"])
    writer.write(next_seq=9)
    rows["current"] = _row(state=agent_runs.COMPLETED, state_version=4)
    assert writer.write(next_seq=10) is None
    assert inserted == [(4, {"next_seq": 9})]


def test_append_nag_writes_the_round_and_resets_the_tool_turns(monkeypatch, store):
    row = _row(next_seq=9)
    run_writes = []
    monkeypatch.setattr(agent_runs, "read_run", lambda *a: row)
    monkeypatch.setattr(agent_runs, "write_run", lambda r, **c: run_writes.append(c))
    monkeypatch.setattr(activities, "_insert_chat_row",
                        lambda u, s, seq, role, **f: store["chat"].append(
                            {"seq": seq, "role": role, **f}))
    nxt = ActivityEnvironment().run(activities.append_nag, AppendNagParams(
        run_id=RUN_ID, username="u", session_id="s", seq=9, idx=6, message="nag text",
        starts_round=True, nags_this_turn=1, nags_without_progress=1, extra_tool_turns=6))
    assert nxt == 10
    assert store["chat"] == [{"seq": 9, "role": "nag", "content": "nag text"}]
    assert [(m.idx, m.role) for m in store["messages"]] == [(6, "human")]
    assert run_writes == [{"next_seq": 10, "nags_this_turn": 1, "nags_without_progress": 1,
                           "extra_tool_turns": 6, "tool_turns_used": 0}]


# ---------------------------------------------------------------- the agent keepalive


def _run_frames_with(store, monkeypatch, lines):
    """Run `run_agent` over a stream whose raw lines are `lines`, and return what it wrote."""
    store["messages"].clear()
    store["chat"].clear()
    store["stream"].clear()

    class _RawResponse(_FakeResponse):
        def __init__(self):
            self._lines = list(lines)

    row = _row()
    monkeypatch.setattr(agent_runs, "read_run", lambda *a: row)
    monkeypatch.setattr(agent_runs, "read_messages", lambda *a: [
        agent_runs.RunMessageRow(idx=0, role="human", content="question")])
    monkeypatch.setattr(agent_runs, "RunRowWriter", lambda *a, **k: _FakeWriter())
    monkeypatch.setattr(stream_writer, "_chat_history", lambda *a: [])
    monkeypatch.setattr(stream_writer, "release_browser", lambda run_id: None)
    monkeypatch.setattr(stream_writer.requests, "post", lambda *a, **k: _RawResponse())
    monkeypatch.setattr(stream_writer.ResearchStreamWriter, "_finish_stream_rows",
                        lambda self: None)
    monkeypatch.setattr(activities, "_insert_chat_row",
                        lambda u, s, seq, role, **f: store["chat"].append(
                            {"seq": seq, "role": role, **f}))
    summary = ActivityEnvironment().run(
        activities.run_agent, RunAgentParams(run_id=RUN_ID, username="u", session_id="s"))
    return summary, list(store["messages"]), list(store["chat"])


def test_a_keepalive_comment_line_changes_nothing(store, monkeypatch):
    """The agent sends `: keepalive` while a model call waits. The reader skips it."""
    frames = [
        {"type": "model_turn", "content": {"index": 1, "text": "done", "reasoning": "",
                                           "tool_calls": [], "usage": {}}},
        {"type": "response", "content": "done"},
        {"type": "end", "content": "done", "model": "m",
         "usage": {"prompt_tokens": 7, "completion_tokens": 3}},
    ]
    data = [f"data: {json.dumps(f)}" for f in frames]
    plain = _run_frames_with(store, monkeypatch, data)
    with_keepalive = _run_frames_with(
        store, monkeypatch, [": keepalive", "", data[0], ": keepalive", "", *data[1:]])

    assert plain[0].outcome == "answered"
    assert with_keepalive == plain
