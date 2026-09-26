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
from tasks.P_agent import activities, steps, stream_writer
from tasks.P_agent.activities import (
    AgentRunInput, AppendNagParams, CallRef, OpenedRun, RunRef, RunSummary, WriteEndingParams,
)
from tasks.P_agent.steps import (
    ModelStepParams, ModelStepResult, StepFailure, StepRef, ToolCallParams,
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
                 "read_chat_todo", "delegate_step", "prepare_continuation",
                 "record_step_failure", "plan_has_sections"):
        assert name in chat_acts, name
    assert workers["CHAT_MODEL_TASK_QUEUE"][1] == ["model_step"]
    assert workers["RESEARCH_TASK_QUEUE"][1] == ["model_step"]
    assert workers["AGENT_TOOL_TASK_QUEUE"][1] == ["tool_call"]


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
                # The model step goes to the queue in the row.
                assert name == "model_step"
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
        "todo_before_nag", "planner_retry_done",
    }
    for params in (StepRef, ModelStepParams, ModelStepResult, ToolCallParams, StepFailure,
                   CallRef, RunRef, RunSummary, OpenedRun, WriteEndingParams):
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


def _row(**changes):
    base = dict(run_id=RUN_ID, username="u", session_id="s", turn_seq=4, thread_id=RUN_ID,
                depth=0, kind="chat", queue="chat-model-queue", start_seq=5, next_seq=5)
    base.update(changes)
    return agent_runs.RunRow(**base)


class _FakeWriter:
    def __init__(self, store):
        self.store = store

    def write(self, **changes):
        self.store["run"].append(changes)

    def read(self):
        return self.store["row"]

    def start_keepalive(self):
        pass

    def stop_keepalive(self):
        pass


@pytest.fixture(autouse=True)
def step_events(monkeypatch):
    """Replace the `agent_step_events` writer with a list, so no test of this file sends a
    row to the timing daemon, which flushes into the stack's table."""
    from database import agent_step_events

    recorded = []
    monkeypatch.setattr(agent_step_events, "record", recorded.append)
    return recorded


@pytest.fixture
def store(monkeypatch):
    """Replace every database read and write of the steps with lists."""
    written = {"messages": [], "chat": [], "stream": [], "run": [], "row": _row(),
               "requests": []}

    def write_message(username, session_id, thread_id, run_id, message):
        written["messages"] = [m for m in written["messages"] if m.idx != message.idx]
        written["messages"].append(message)
        written["messages"].sort(key=lambda m: m.idx)

    monkeypatch.setattr(agent_runs, "write_message", write_message)
    monkeypatch.setattr(agent_runs, "read_messages", lambda *a: list(written["messages"]))
    monkeypatch.setattr(agent_runs, "read_run", lambda *a: written["row"])
    monkeypatch.setattr(agent_runs, "RunRowWriter", lambda *a, **k: _FakeWriter(written))
    monkeypatch.setattr(
        stream_writer.ResearchStreamWriter, "_insert_stream_row",
        lambda self, *a, **k: written["stream"].append((a, k)),
    )
    monkeypatch.setattr(stream_writer, "context_window_for", lambda model: 0)
    monkeypatch.setattr(stream_writer, "_chat_model", lambda: "test-model")
    monkeypatch.setattr(stream_writer, "_chat_history", lambda *a: [])
    monkeypatch.setattr(steps, "_finish_stream_rows_from", lambda *a: None)
    monkeypatch.setattr(activities, "_insert_chat_row",
                        lambda u, s, seq, role, **f: written["chat"].append(
                            {"seq": seq, "role": role, **f}))
    monkeypatch.setattr(steps, "_insert_chat_row", activities._insert_chat_row)
    written["messages"].append(agent_runs.RunMessageRow(idx=0, role="human", content="q",
                                                        run_id=RUN_ID))
    return written


def _entry(call_id, name, args, kind="parallel", retry=True):
    return {"id": call_id, "name": name, "args": args, "kind": kind, "briefings": None,
            "page_share": 24000, "budget_exhausted": False, "retry": retry,
            "args_digest": steps.args_digest(name, args)}


def _frames(text="", entries=(), usage=None):
    turn = {"type": "model_turn", "text": text, "reasoning": "", "tool_calls": list(entries),
            "bound_names": ["search_collections"],
            "usage": usage or {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
            "summarised": False}
    lines = [f"data: {json.dumps({'type': 'response', 'content': text})}"] if text else []
    return lines + [f"data: {json.dumps(turn)}",
                    f"data: {json.dumps({'type': 'end', 'model': 'm', 'usage': {}})}"]


def _serve(monkeypatch, store, lines):
    def fake(url, body, read_seconds):
        store["requests"].append(body)
        yield from lines
    monkeypatch.setattr(steps, "_lines", fake)


def _step(step_no=1, mode="tools", reason=""):
    return ActivityEnvironment().run(steps.model_step, ModelStepParams(
        run_id=RUN_ID, username="u", session_id="s", step_no=step_no, mode=mode,
        final_reason=reason))


# ---------------------------------------------------------------- model_step


def test_a_reply_with_calls_takes_seqs_in_call_order_with_delegations_last(store, monkeypatch):
    entries = [_entry(LONG_ID_A, "search_collections", {"query": "alpha"}),
               _entry("d1", "run_subagent", {"tasks": []}, kind="delegation"),
               _entry(LONG_ID_B, "append_node", {"text": "b"}, kind="ordered")]
    _serve(monkeypatch, store, _frames(entries=entries))
    result = _step()
    assert result.outcome == "calls" and result.repeated is False
    assert [(c.call_id, c.kind, c.seq, c.position) for c in result.calls] == [
        (LONG_ID_A, "parallel", 5, 0), ("d1", "delegation", 7, 1),
        (LONG_ID_B, "ordered", 6, 2)]
    ai = store["messages"][-1]
    assert (ai.idx, ai.role, ai.is_final) == (1, "ai", 1)
    assert json.loads(ai.usage_json)["step_no"] == 1
    assert store["run"][-1] == {"next_seq": 8, "model_steps": 1, "prompt_tokens": 7,
                                "completion_tokens": 3}
    tool_rows = [a for a, k in store["stream"] if a[1] == "tool"]
    assert [r[0] for r in tool_rows] == [5, 7, 6]
    # The request sends the stored call entries as `id`, `name` and `args` only.
    assert store["requests"][0]["messages"] == [{"role": "human", "content": "q"}]
    assert _payload_bytes(result) < agent_workflows.AGENT_RUN_PAYLOAD_BYTES


def test_a_keepalive_comment_line_changes_nothing(store, monkeypatch):
    """The agent sends `: keepalive` while a model call waits. The reader skips it."""
    lines = _frames(text="done")
    _serve(monkeypatch, store, lines)
    plain = _step()
    first = (list(store["chat"]), store["run"][-1])
    store["chat"].clear()
    store["run"].clear()
    store["messages"] = store["messages"][:1]
    _serve(monkeypatch, store, [": keepalive", "", lines[0], ": keepalive", *lines[1:]])
    assert _step() == plain
    assert (list(store["chat"]), store["run"][-1]) == first
    assert plain.outcome == "answered" and first[0][0]["content"] == "done"


def test_a_retry_after_the_write_makes_no_second_model_call(store, monkeypatch):
    _serve(monkeypatch, store, _frames(text="The answer."))
    first = _step()
    store["row"] = _row(next_seq=6, model_steps=1, result="The answer.")

    def refuse(*a, **k):
        raise AssertionError("no model call on a retry after the write")
    monkeypatch.setattr(steps, "_lines", refuse)
    second = _step()
    assert second == first
    assert [r["seq"] for r in store["chat"]] == [5, 5]
    assert store["run"][-1]["next_seq"] == 6 and "prompt_tokens" not in store["run"][-1]


def test_a_repeated_call_is_found_and_a_repeated_read_is_not(store, monkeypatch):
    store["messages"].append(agent_runs.RunMessageRow(
        idx=1, role="ai", run_id=RUN_ID, tool_calls_json=json.dumps([
            _entry("a", "search_collections", {"query": "a"}), _entry("t", "read_todo", {})])))
    store["messages"].append(agent_runs.RunMessageRow(idx=2, role="tool", tool_call_id="a"))
    store["messages"].append(agent_runs.RunMessageRow(idx=3, role="tool", tool_call_id="t"))
    _serve(monkeypatch, store, _frames(entries=[_entry("t2", "read_todo", {})]))
    assert _step(step_no=2).repeated is False
    _serve(monkeypatch, store, _frames(entries=[_entry("b", "search_collections",
                                                       {"query": "a"})]))
    assert _step(step_no=3).repeated is True


def test_a_final_step_stores_not_run_results_and_one_human_message(store, monkeypatch):
    store["messages"].append(agent_runs.RunMessageRow(
        idx=1, role="ai", run_id=RUN_ID, tool_calls_json=json.dumps([
            dict(_entry("a", "search_collections", {"query": "a"}), position=0, seq=5)])))
    _serve(monkeypatch, store, _frames(text="Final."))
    result = _step(step_no=2, mode="final", reason="repeated_call")
    roles = [(m.idx, m.role) for m in store["messages"]]
    assert roles == [(0, "human"), (1, "ai"), (2, "tool"), (3, "human"), (4, "ai")]
    assert json.loads(store["messages"][2].content)["error"] == "not_run"
    assert store["messages"][3].content == steps.FINAL_TEXT["repeated_call"]
    assert store["requests"][0]["mode"] == "final"
    assert result.outcome == "answered"
    assert store["run"][-1]["end_reason"] == "repeated_call"
    # A retry of the step before its reply writes neither a second result nor a second
    # human message.
    del store["messages"][-1]
    _step(step_no=2, mode="final", reason="repeated_call")
    assert [(m.idx, m.role) for m in store["messages"]] == roles


def test_an_error_frame_that_is_not_retryable_raises_the_rejected_type(store, monkeypatch):
    frame = {"type": "error", "error_class": "http_400", "retryable": False,
             "content": "bad request"}
    _serve(monkeypatch, store, [f"data: {json.dumps(frame)}"])
    with pytest.raises(steps.ModelRequestRejected):
        _step()


def test_the_largest_step_result_stays_under_the_payload_guard():
    """A step result carries one `CallRef` for each call. Its size for 1, 12, 16 and 1,600
    calls, against the payload guard limit of 512 KiB, with the ids that the service gives
    (`call-{step_no}-{position}`) and with a joined streaming id of 234 characters."""
    sizes = {}
    for label, call_id in (("short", "call-600-{i}"), ("joined", LONG_ID_A)):
        for count in (1, 12, 16, 1600):
            result = ModelStepResult(outcome="calls", calls=[
                CallRef(ai_idx=10**6, position=i, call_id=call_id.format(i=i),
                        name="search_collections", kind="parallel", seq=10**6 + i)
                for i in range(count)], next_seq=10**6, next_idx=10**6)
            sizes[(label, count)] = _payload_bytes(result)
    print("model_step result bytes by call count:", sizes)
    assert sizes[("joined", 1)] < agent_workflows.AGENT_RUN_PAYLOAD_BYTES
    assert sizes[("short", 1600)] < 512 * 1024


# ---------------------------------------------------------------- tool_call


def _with_calls(store, entries):
    for position, entry in enumerate(entries):
        entry.update(position=position, seq=5 + position)
    store["messages"].append(agent_runs.RunMessageRow(
        idx=1, role="ai", run_id=RUN_ID, tool_calls_json=json.dumps(entries),
        usage_json=json.dumps({"bound_names": ["search_collections"], "step_no": 1})))
    return activities.call_refs(store["messages"][-1])


def _tool(call):
    return ActivityEnvironment().run(steps.tool_call, ToolCallParams(
        run_id=RUN_ID, username="u", session_id="s", call=call))


def test_two_parallel_calls_keep_their_own_arguments_results_and_indexes(store, monkeypatch):
    calls = _with_calls(store, [_entry(LONG_ID_A, "search_collections", {"query": "alpha"}),
                                _entry(LONG_ID_B, "search_collections", {"query": "beta"})])
    bodies = []

    def post(url, body, read_seconds):
        bodies.append(body)
        return {"content": json.dumps({"hits": [body["call"]["args"]["query"]]}),
                "status": "ok", "measure": {"sha256": body["call"]["id"][-4:]}}
    monkeypatch.setattr(steps, "_post_json", post)
    # The second call ends first.
    assert _tool(calls[1]).status == "ok"
    assert _tool(calls[0]).status == "ok"
    rows = {r["seq"]: r for r in store["chat"]}
    assert json.loads(rows[5]["tool_input"]) == {"query": "alpha"}
    assert json.loads(rows[5]["tool_output"]) == {"hits": ["alpha"]}
    assert json.loads(rows[6]["tool_output"]) == {"hits": ["beta"]}
    tools = {m.idx: m for m in store["messages"] if m.role == "tool"}
    assert tools[2].tool_call_id == LONG_ID_A and tools[3].tool_call_id == LONG_ID_B
    assert json.loads(tools[2].usage_json)["chat_seq"] == 5
    assert bodies[0]["bound_names"] == ["search_collections"]
    assert bodies[0]["page_share"] == 24000
    # The key comes from the thread, the reply and the place of the call.
    assert bodies[1]["idempotency_key"] != bodies[0]["idempotency_key"]
    store["messages"] = [m for m in store["messages"] if m.role != "tool"]
    _tool(calls[0])
    assert bodies[2]["idempotency_key"] == bodies[1]["idempotency_key"]


def test_an_answered_call_runs_nothing(store, monkeypatch):
    calls = _with_calls(store, [_entry("a", "search_collections", {"query": "a"})])
    store["messages"].append(agent_runs.RunMessageRow(
        idx=2, role="tool", tool_call_id="a", usage_json=json.dumps({"status": "error"})))
    monkeypatch.setattr(steps, "_post_json", lambda *a: pytest.fail("the call ran again"))
    assert _tool(calls[0]).status == "error"


def test_a_late_result_does_not_replace_a_stored_failure(store, monkeypatch):
    calls = _with_calls(store, [_entry("a", "search_collections", {"query": "a"})])

    def post(url, body, read_seconds):
        # `record_step_failure` stores its result while this attempt still waits.
        ActivityEnvironment().run(steps.record_step_failure, StepFailure(
            run_id=RUN_ID, username="u", session_id="s", step="tool",
            error_class="start_to_close_timeout", call=calls[0]))
        return {"content": "late", "status": "ok"}
    monkeypatch.setattr(steps, "_post_json", post)
    assert _tool(calls[0]).status == "error"
    [tool] = [m for m in store["messages"] if m.role == "tool"]
    assert json.loads(tool.content) == {
        "success": False, "error": "tool_unavailable",
        "message": "The tool call did not finish (start_to_close_timeout). Try it again, "
                   "or use another tool."}


def _step_failure(call, error_class):
    ActivityEnvironment().run(steps.record_step_failure, StepFailure(
        run_id=RUN_ID, username="u", session_id="s", step="tool", name=call.name,
        task_queue="agent-tool-queue", error_class=error_class, call=call))


def test_a_start_to_close_timeout_gets_no_workflow_row(store, step_events):
    # Each attempt wrote its own row, so a second row would count the failure twice.
    calls = _with_calls(store, [_entry("a", "search_collections", {"query": "a"})])
    _step_failure(calls[0], "start_to_close_timeout")
    assert step_events == []
    [tool] = [m for m in store["messages"] if m.role == "tool"]
    assert json.loads(tool.content)["error"] == "tool_unavailable"


@pytest.mark.parametrize("error_class", ["schedule_to_start_timeout", "heartbeat_timeout"])
def test_a_step_no_attempt_could_record_gets_one_workflow_row(store, step_events,
                                                               error_class):
    calls = _with_calls(store, [_entry("a", "search_collections", {"query": "a"})])
    _step_failure(calls[0], error_class)
    [event] = step_events
    assert (event.attempt, event.ok, event.error_class, event.step, event.tool_call_id) == (
        0, False, error_class, "tool", "a")


def test_the_tool_index_puts_delegations_after_the_other_calls():
    ai = agent_runs.RunMessageRow(idx=4, role="ai", tool_calls_json=json.dumps([
        {"kind": "delegation"}, {"kind": "parallel"}, {"kind": "ordered"}]))
    assert [steps.tool_idx(ai, p) for p in range(3)] == [7, 5, 6]


def test_run_message_sends_the_call_fields_and_the_tool_status():
    ai = agent_runs.RunMessageRow(idx=1, role="ai", tool_calls_json=json.dumps([
        dict(_entry("a", "t", {"x": 1}), position=0, seq=5)]))
    tool = agent_runs.RunMessageRow(idx=2, role="tool", tool_call_id="a", tool_name="t",
                                    usage_json=json.dumps({"status": "error"}))
    assert stream_writer.run_message(ai)["tool_calls"] == [
        {"id": "a", "name": "t", "args": {"x": 1}}]
    assert stream_writer.run_message(tool)["status"] == "error"


# ---------------------------------------------------------------- open_run


def test_pending_calls_leave_out_the_delegations_of_a_continued_run():
    ai = agent_runs.RunMessageRow(idx=1, role="ai", run_id="other", tool_calls_json=json.dumps([
        dict(_entry("s", "search_collections", {}), position=0, seq=5),
        dict(_entry("d", "run_subagent", {}, kind="delegation"), position=1, seq=6)]))
    messages = [agent_runs.RunMessageRow(idx=0, role="human"), ai]
    assert [c.call_id for c in activities.pending_calls(_row(), messages)] == ["s"]
    own = agent_runs.RunMessageRow(**{**ai.__dict__, "run_id": RUN_ID})
    assert [c.call_id for c in activities.pending_calls(_row(), [messages[0], own])] == [
        "s", "d"]


# ---------------------------------------------------------------- payloads and writer


def test_a_summary_with_five_children_stays_under_the_bound():
    summary = RunSummary(outcome="delegated", next_seq=4_000_000_000, next_idx=4_000_000_000,
                         children=[RUN_ID] * 5, batch_id=RUN_ID,
                         prompt_tokens=10**15, completion_tokens=10**15,
                         end_reason="step_budget")
    assert _payload_bytes(summary) < agent_workflows.AGENT_RUN_PAYLOAD_BYTES
    inp = AgentRunInput(run_id=RUN_ID, username="u" * 64, session_id="s" * 64,
                        allowed_collections=["c" * 64] * 20, turn_uuid="t" * 64)
    assert _payload_bytes(inp) < agent_workflows.AGENT_RUN_PAYLOAD_BYTES


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


def test_the_run_row_carries_the_step_columns():
    assert {"model_steps", "end_reason"} <= set(agent_runs.RUN_COLUMNS)


def test_append_nag_writes_the_round_and_the_counters(monkeypatch, store):
    row = _row(next_seq=9)
    run_writes = []
    monkeypatch.setattr(agent_runs, "read_run", lambda *a: row)
    monkeypatch.setattr(agent_runs, "write_run", lambda r, **c: run_writes.append(c))
    nxt = ActivityEnvironment().run(activities.append_nag, AppendNagParams(
        run_id=RUN_ID, username="u", session_id="s", seq=9, idx=6, message="nag text",
        starts_round=True, nags_this_turn=1, nags_without_progress=1))
    assert nxt == 10
    assert store["chat"] == [{"seq": 9, "role": "nag", "content": "nag text"}]
    assert [(m.idx, m.role) for m in store["messages"]] == [(0, "human"), (6, "human")]
    assert run_writes == [{"next_seq": 10, "nags_this_turn": 1, "nags_without_progress": 1}]
