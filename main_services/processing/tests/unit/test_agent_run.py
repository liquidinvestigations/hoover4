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
from tasks.P_agent import activities, citations, steps, stream_writer
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
                 "dispatch_sections", "prepare_continuation",
                 "record_step_failure", "plan_has_sections",
                 "check_citations", "write_empty_note", "write_incomplete"):
        assert name in chat_acts, name
    for removed in ("read_chat_todo", "preload_reads", "write_repeat_note",
                    "write_found_documents", "delegate_step"):
        assert removed not in chat_acts, removed
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
        "planner_retry_done", "model_source",
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
    monkeypatch.setattr(agent_runs, "read_earlier_threads", lambda *a: [])
    monkeypatch.setattr(steps, "_finish_stream_rows_from", lambda *a: None)
    monkeypatch.setattr(steps, "thinking_setting", lambda: True)
    monkeypatch.setattr(activities, "_insert_chat_row",
                        lambda u, s, seq, role, **f: written["chat"].append(
                            {"seq": seq, "role": role, **f}))
    monkeypatch.setattr(steps, "_insert_chat_row", activities._insert_chat_row)
    written["messages"].append(agent_runs.RunMessageRow(idx=0, role="human", content="q",
                                                        run_id=RUN_ID))
    return written


def _entry(call_id, name, args, kind="parallel", retry=True):
    return {"id": call_id, "name": name, "args": args, "kind": kind, "briefings": None,
            "page_share": 24000, "retry": retry}


@pytest.mark.parametrize("kind,reference", [("chat", ""), ("planner", '{"plan_id":"p"}')])
def test_a_successful_question_writes_the_turn_answer(monkeypatch, store, kind, reference):
    from tasks.P_agent import plan_runs
    monkeypatch.setattr(plan_runs, "plan_reference", lambda row: reference)
    question = "Bigger or smaller than 50?"
    call = activities.CallRef(ai_idx=1, position=0, call_id="ask-1", name="ask_user",
                              kind="parallel", seq=5)
    store["row"] = _row(next_seq=6, kind=kind)
    store["messages"].extend([
        agent_runs.RunMessageRow(idx=1, role="ai", content="", run_id=RUN_ID,
                                 tool_calls_json=json.dumps([_entry("ask-1", "ask_user",
                                                                       {"question": question})])),
        agent_runs.RunMessageRow(idx=2, role="tool", content=json.dumps({"asked": True}),
                                 run_id=RUN_ID, tool_call_id="ask-1", tool_name="ask_user",
                                 usage_json=json.dumps({"status": "ok"})),
    ])
    monkeypatch.setattr(agent_runs, "write_run",
                        lambda row, **changes: store["run"].append(changes))
    result = ActivityEnvironment().run(steps.write_asked_answer,
                                       steps.AskedAnswerParams(run_id=RUN_ID, username="u",
                                                              session_id="s", call=call))
    assert result == 7
    assert store["chat"][-1] == {"seq": 6, "role": "assistant", "content": question,
                                  "plan_reference_json": reference}
    assert store["run"][-1] == {"result": question, "next_seq": 7}


def _frames(text="", entries=(), usage=None, reasoning="", model=None):
    turn = {"type": "model_turn", "text": text, "reasoning": reasoning,
            "tool_calls": list(entries),
            "usage": usage or {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
            "summarised": False}
    if model is not None:
        turn["model"] = model
    lines = [f"data: {json.dumps({'type': 'response', 'content': text})}"] if text else []
    return lines + [f"data: {json.dumps(turn)}",
                    f"data: {json.dumps({'type': 'end', 'model': 'm', 'usage': {}})}"]


def _serve(monkeypatch, store, lines):
    def fake(url, body, read_seconds):
        store["requests"].append(body)
        yield from lines
    monkeypatch.setattr(steps, "_lines", fake)


def _step(step_no=1):
    return ActivityEnvironment().run(steps.model_step, ModelStepParams(
        run_id=RUN_ID, username="u", session_id="s", step_no=step_no))


# ---------------------------------------------------------------- model_step


@pytest.mark.parametrize("stored, on", [
    (None, True), ("", True), ("on", True), ("off", False), (" off ", False)])
def test_the_thinking_switch_is_on_unless_the_setting_says_off(monkeypatch, stored, on):
    import database.clickhouse as ch
    monkeypatch.setattr(ch, "get_server_setting", lambda key: stored)
    assert steps.thinking_setting() is on


def test_a_failed_read_of_the_thinking_switch_sends_on(monkeypatch):
    import database.clickhouse as ch

    def fail(key):
        raise ConnectionError("no database")
    monkeypatch.setattr(ch, "get_server_setting", fail)
    assert steps.thinking_setting() is True


def test_each_model_call_sends_the_thinking_switch_it_reads(store, monkeypatch):
    monkeypatch.setattr(steps, "thinking_setting", lambda: False)
    _serve(monkeypatch, store, _frames(text="first"))
    _step(step_no=1)
    assert store["requests"][0]["thinking"] is False


def test_a_reply_with_calls_takes_seqs_in_call_order(store, monkeypatch):
    entries = [_entry(LONG_ID_A, "search_collections", {"query": "alpha"}),
               _entry("t1", "read_todo", {}, kind="ordered"),
               _entry(LONG_ID_B, "write_plan", {"version": 1, "children": []},
                      kind="ordered")]
    _serve(monkeypatch, store, _frames(entries=entries))
    result = _step()
    assert result.outcome == "calls"
    assert [(c.call_id, c.kind, c.seq, c.position) for c in result.calls] == [
        (LONG_ID_A, "parallel", 5, 0), ("t1", "ordered", 6, 1),
        (LONG_ID_B, "ordered", 7, 2)]
    ai = store["messages"][-1]
    assert (ai.idx, ai.role, ai.is_final) == (1, "ai", 1)
    assert json.loads(ai.usage_json)["step_no"] == 1
    assert store["run"][-1] == {"next_seq": 8, "model_steps": 1, "prompt_tokens": 7,
                                "completion_tokens": 3}
    tool_rows = [a for a, k in store["stream"] if a[1] == "tool"]
    assert [r[0] for r in tool_rows] == [5, 6, 7]
    # The request sends the stored call entries as `id`, `name` and `args` only.
    assert store["requests"][0]["messages"] == [
        {"role": "human", "content": "q", "thread_id": RUN_ID, "idx": 0}]
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


def _answered_reply(store, idx, step_no, entries, status="ok"):
    """An earlier `ai` message of the thread at `idx`, with one result for each call."""
    store["messages"].append(agent_runs.RunMessageRow(
        idx=idx, role="ai", run_id=RUN_ID, usage_json=json.dumps({"step_no": step_no}),
        tool_calls_json=json.dumps([dict(e, position=p, seq=5 + p)
                                    for p, e in enumerate(entries)])))
    for p, e in enumerate(entries):
        store["messages"].append(agent_runs.RunMessageRow(
            idx=idx + 1 + p, role="tool", tool_call_id=e["id"], tool_name=e["name"],
            usage_json=json.dumps({"status": status})))


def _runs(store, call_id, entry, count, first_idx=1):
    """`count` earlier replies of the same call, each with its result. Returns the next
    free index."""
    idx = first_idx
    for step_no in range(1, count + 1):
        _answered_reply(store, idx, step_no, [dict(entry, id=f"{call_id}{step_no}")])
        idx += 2
    return idx


def test_an_identical_call_runs_again_with_no_refusal(store, monkeypatch):
    """Three earlier runs of one search, and a reply that sends the same search twice.
    Every call of the reply runs, and no result is written for it in advance."""
    _runs(store, "a", _entry("a", "search_collections", {"query": "a"}), 3)
    _serve(monkeypatch, store, _frames(entries=[
        _entry("r", "search_collections", {"query": "a"}),
        _entry("r2", "search_collections", {"query": "a"}),
        _entry("n", "search_collections", {"query": "new"})]))
    result = _step(step_no=4)
    assert result.outcome == "calls"
    assert [c.call_id for c in result.calls] == ["r", "r2", "n"]
    assert not [m for m in store["messages"]
                if m.role == "tool" and m.tool_call_id in ("r", "r2", "n")]
    assert not hasattr(steps, "repeat_sources") and not hasattr(steps, "REPEAT_STEP_LIMIT")


def test_a_repeated_read_of_the_todo_list_runs_every_time(store, monkeypatch):
    for step_no in (1, 2, 3):
        _answered_reply(store, 2 * step_no - 1, step_no, [_entry(f"t{step_no}", "read_todo", {})])
    _serve(monkeypatch, store, _frames(entries=[_entry("t4", "read_todo", {})]))
    assert [c.call_id for c in _step(step_no=4).calls] == ["t4"]


def test_an_answer_with_open_todo_items_is_final_and_reads_no_todo(store, monkeypatch):
    """The worker never reads the todo list to decide an answer."""
    from database import chat_todos

    monkeypatch.setattr(chat_todos, "read_todo", lambda *a: pytest.fail("no todo read"))
    _answered_reply(store, 1, 1, [_entry("w", "write_todo", {"goal": "g", "steps": ["a"]})])
    _serve(monkeypatch, store, _frames(text="The answer, with step a still open."))
    result = _step(step_no=2)
    assert result.outcome == "answered"
    assert [r["content"] for r in store["chat"] if r["role"] == "assistant"] == [
        "The answer, with step a still open."]
    assert "end_reason" not in store["run"][-1]


def _citation_round(store, marked=False):
    """A turn whose answer named `[D1]` with no citation, and the note of the repair round
    after it: the marked note, or the note text of a thread from before the marker."""
    from tasks.P_agent import citations

    store["messages"].append(agent_runs.RunMessageRow(
        idx=1, role="ai", run_id=RUN_ID, content="The memo sets the budget [D1].",
        usage_json=json.dumps({"step_no": 1})))
    note = (agent_runs.RunMessageRow(idx=2, role="human", content="Cite [D1].",
                                     usage_json=json.dumps({"repair_marker": "citation"}))
            if marked else agent_runs.RunMessageRow(idx=2, role="human",
                                                    content=citations.LEGACY_CITATION_NOTE))
    store["messages"].append(note)
    store["row"] = _row(next_seq=8, model_steps=1, result="The memo sets the budget [D1].")


def test_the_reply_of_the_citation_round_replaces_the_answer(store, monkeypatch):
    _citation_round(store)
    _serve(monkeypatch, store, _frames(text="The memo sets the budget [D2]."))
    _step(step_no=2)
    assert [r["content"] for r in store["chat"] if r["role"] == "assistant"] == [
        "The memo sets the budget [D2]."]
    assert store["run"][-1]["result"] == "The memo sets the budget [D2]."


@pytest.mark.parametrize("marked", [False, True])
def test_a_citation_round_reply_with_no_text_keeps_the_answer(store, monkeypatch, marked):
    _citation_round(store, marked)
    _serve(monkeypatch, store, _frames(reasoning="The citations are done."))
    _step(step_no=2)
    assert [r for r in store["chat"] if r["role"] == "assistant"] == []
    assert "result" not in store["run"][-1]


def _citation_result(idx, handle, file_hash, status="ok", error=""):
    """A stored `cite_documents` result with its typed evidence."""
    from tasks.P_agent import reports

    content = {"citations": [{"file_hash": file_hash[:16], "handle": handle}]}
    if error:
        content = {"success": False, "error": error}
    entries = reports.with_source(reports.normalize(
        "cite_documents", {}, json.dumps(content), status,
        [{"collectionname": "c", "file_hash": file_hash, "handle": handle}] if not error else None),
        RUN_ID, idx)
    return agent_runs.RunMessageRow(
        idx=idx, role="tool", tool_name="cite_documents", tool_call_id=f"cite-{idx}",
        content=json.dumps(content), run_id=RUN_ID,
        usage_json=json.dumps({"status": status, "evidence": entries}))


@pytest.fixture
def citations_store(store, monkeypatch):
    """The session's `cite_documents` results come from `store["session_citations"]`."""
    store["session_citations"] = []
    monkeypatch.setattr(agent_runs, "read_session_tool_messages",
                        lambda u, s, name: {RUN_ID: list(store["session_citations"])})
    monkeypatch.setattr(agent_runs, "write_run",
                        lambda row, **changes: store["run"].append(changes))
    return store


def _check(store, seq=9):
    from tasks.P_agent.steps import CitationCheckParams

    return ActivityEnvironment().run(steps.check_citations, CitationCheckParams(
        run_id=RUN_ID, username="u", session_id="s", seq=seq))


def _answer_with_tool(store, text, kind="chat", citation_tool=True, **changes):
    store["messages"].append(agent_runs.RunMessageRow(
        idx=1, role="ai", run_id=RUN_ID, content=text,
        usage_json=json.dumps({"step_no": 1, "citation_tool": citation_tool})))
    store["row"] = _row(kind=kind, result=text, **changes)


@pytest.mark.parametrize("changes, expected", [
    ({}, True),
    ({"end_reason": "step_budget"}, False),
    ({"end_reason": "empty_response"}, False),
    ({"state": "completed"}, False),
    ({"state": "cancelled"}, False),
])
def test_check_citations_repairs_an_unresolved_label_unless_the_run_ended(
        citations_store, changes, expected):
    _answer_with_tool(citations_store, "The memo sets the budget [D1].", **changes)
    assert _check(citations_store).needed is expected


def test_a_label_that_a_successful_result_gives_needs_no_repair(citations_store):
    citations_store["session_citations"] = [_citation_result(5, "[D1]", "a" * 64)]
    _answer_with_tool(citations_store, "The memo sets the budget [D1].")
    assert _check(citations_store).needed is False
    assert citations_store["chat"] == []


def test_a_failed_citation_call_does_not_stop_the_check(citations_store):
    citations_store["session_citations"] = [
        _citation_result(5, "", "a" * 64, status="error", error="invalid_arguments")]
    _answer_with_tool(citations_store, "The memo sets the budget [D1].")
    repair = _check(citations_store)
    assert repair.needed is True and repair.next_seq == 10
    assert citations_store["run"][-1] == {"next_seq": 10}
    note = citations_store["messages"][-1]
    assert note.role == "human" and note.usage["repair_marker"] == "citation"
    assert note.usage["citation_check"]["unresolved"] == ["[D1]"]
    assert "[D1]" in note.content
    assert citations_store["chat"][-1]["role"] == "nag"


def test_a_label_bound_to_two_documents_conflicts(citations_store):
    citations_store["session_citations"] = [_citation_result(5, "[D1]", "a" * 64),
                                            _citation_result(7, "[D1]", "b" * 64)]
    _answer_with_tool(citations_store, "Both say so [D1].")
    assert _check(citations_store).needed is True
    assert citations_store["messages"][-1].usage["citation_check"]["conflicting"] == ["[D1]"]


def test_an_earlier_valid_handle_resolves_with_no_new_citation(citations_store):
    """A follow-up turn reuses `[D2]` from a citation result of an earlier thread."""
    citations_store["session_citations"] = [_citation_result(3, "[D2]", "c" * 64)]
    _answer_with_tool(citations_store, "As before, the memo says so [D2].")
    assert _check(citations_store).needed is False


@pytest.mark.parametrize("kind", ["chat", "planner", "subagent", "organizer"])
def test_every_role_with_the_citation_tool_gets_one_repair_round(citations_store, kind):
    _answer_with_tool(citations_store, "The memo says so [D4].", kind=kind,
                      depth=0 if kind != "subagent" else 1)
    first = _check(citations_store)
    assert first.needed is True
    # A retry of the activity finds the note as the newest message. It writes no second
    # message, and for a run that writes the transcript it writes the same rows again.
    count = len(citations_store["messages"])
    chat_rows = list(citations_store["chat"])
    assert _check(citations_store) == first
    assert len(citations_store["messages"]) == count
    if kind != "subagent":
        assert citations_store["chat"][-1] == chat_rows[-1]
        assert citations_store["run"][-1] == {"next_seq": 10}
    # A later answer of the thread gets no second round.
    citations_store["messages"].append(agent_runs.RunMessageRow(
        idx=count, role="ai", run_id=RUN_ID, content="Still [D4].",
        usage_json=json.dumps({"step_no": 2, "citation_tool": True})))
    citations_store["row"] = _row(kind=kind, result="Still [D4].")
    assert _check(citations_store).needed is False


def test_a_role_without_the_citation_tool_gets_no_check(citations_store):
    _answer_with_tool(citations_store, "The memo says so [D4].", kind="organizer",
                      citation_tool=False)
    assert _check(citations_store).needed is False


def test_a_document_name_with_no_label_still_gets_the_round_after_a_citation_call(
        citations_store):
    """A citation call in the thread does not stop the check."""
    citations_store["messages"].append(agent_runs.RunMessageRow(
        idx=2, role="tool", tool_name="search_collections", tool_call_id="s1",
        content=json.dumps({"items": [{"file_hash": "d" * 64, "path": "/memo-budget.txt"}]})))
    citations_store["session_citations"] = [_citation_result(5, "[D1]", "a" * 64)]
    _answer_with_tool(citations_store, "The file memo-budget.txt sets the budget.")
    assert _check(citations_store).needed is True
    assert citations_store["messages"][-1].content == citations.CITATION_NOTE


def test_the_first_reply_of_a_turn_still_writes_the_answer_row(store, monkeypatch):
    store["row"] = _row(next_seq=6, result="")
    _serve(monkeypatch, store, _frames(text="The answer."))
    _step(step_no=1)
    assert [r["content"] for r in store["chat"] if r["role"] == "assistant"] == [
        "The answer."]


def test_a_second_reply_with_reasoning_and_no_text_writes_no_answer_row(store, monkeypatch):
    """The thread holds its retry marker, so a second reply with no text and no call gives
    `empty_again`. Its reasoning stays in its `ai` message, and no answer row is written."""
    store["messages"].append(agent_runs.RunMessageRow(
        idx=1, role="human", content=steps.EMPTY_REPLY_TEXT,
        usage_json=json.dumps({steps.RETRY_MARKER_KEY: steps.EMPTY_RETRY_MARKER})))
    store["row"] = _row(next_seq=6, model_steps=1)
    _serve(monkeypatch, store, _frames(reasoning="The letters are dated 2018."))
    result = _step(step_no=2)
    assert result.outcome == "empty_again"
    assert [r for r in store["chat"] if r["role"] == "assistant"] == []
    assert "result" not in store["run"][-1]
    assert store["messages"][-1].reasoning == "The letters are dated 2018."


def test_the_answer_row_never_holds_reasoning(store, monkeypatch):
    """The answer row holds the text of the reply. The reasoning and the narration of the
    round go to its reasoning column."""
    store["messages"].append(agent_runs.RunMessageRow(
        idx=1, role="ai", run_id=RUN_ID, reasoning="The user wants the letters.",
        usage_json=json.dumps({"step_no": 1}), tool_calls_json=json.dumps([
            dict(_entry("s", "search_collections", {"query": "q"}), position=0, seq=5)])))
    store["messages"].append(agent_runs.RunMessageRow(
        idx=2, role="tool", tool_call_id="s", usage_json=json.dumps({"status": "ok"})))
    store["messages"].append(agent_runs.RunMessageRow(
        idx=3, role="ai", run_id=RUN_ID, content="Wait, I should read the letters.",
        reasoning="I need the dates.", usage_json=json.dumps({"step_no": 2}),
        tool_calls_json=json.dumps([dict(_entry("r", "read_documents", {"file_hash": ["h"]}),
                                         position=0, seq=6)])))
    store["messages"].append(agent_runs.RunMessageRow(
        idx=4, role="tool", tool_call_id="r", usage_json=json.dumps({"status": "ok"})))
    store["row"] = _row(next_seq=7, model_steps=2)
    _serve(monkeypatch, store, _frames(text="The letters are dated 2018.",
                                       reasoning="The final thoughts."))
    _step(step_no=3)
    [answer] = [r for r in store["chat"] if r["role"] == "assistant"]
    assert answer["content"] == "The letters are dated 2018."
    for text in ("wants the letters", "should read the letters", "need the dates",
                 "final thoughts"):
        assert text in answer["reasoning"]
        assert text not in answer["content"]


def test_the_stored_reply_names_the_model_that_answered_and_the_request_size(
        store, monkeypatch):
    size = {"tokens": 1200, "method": "tokenizer", "window": 32768, "fits": True}
    _serve(monkeypatch, store, _frames(
        text="The answer.", model="selected-model",
        usage={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10,
               "request_size": size}))
    _step()
    ai = next(m for m in store["messages"] if m.role == "ai")
    assert ai.usage["model"] == "selected-model"
    assert ai.usage["request_size"] == size
    [answer] = [r for r in store["chat"] if r["role"] == "assistant"]
    assert answer["model"] == "selected-model"


def test_an_older_service_reply_with_no_model_keeps_the_model_of_the_request(
        store, monkeypatch):
    _serve(monkeypatch, store, _frames(text="The answer."))
    _step()
    ai = next(m for m in store["messages"] if m.role == "ai")
    assert ai.usage["model"] == "test-model"


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
        usage_json=json.dumps({"step_no": 1})))
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
    assert "bound_names" not in bodies[0] and "budget_exhausted" not in bodies[0]
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


def test_the_workflow_row_of_a_timed_out_model_step_keeps_its_mode(store, step_events):
    ActivityEnvironment().run(steps.record_step_failure, StepFailure(
        run_id=RUN_ID, username="u", session_id="s", step="model", mode="tools",
        name="m", task_queue="chat-model-queue", error_class="heartbeat_timeout"))
    [event] = step_events
    assert (event.step, event.mode, event.attempt, event.error_class) == (
        "model", "tools", 0, "heartbeat_timeout")


def test_an_attempt_that_lost_its_heartbeat_writes_no_row(store, step_events, monkeypatch):
    from database import agent_step_events as events

    monkeypatch.setattr(events, "error_class_of", lambda exc: "heartbeat_timeout")

    def lost(url, body, read_seconds):
        raise RuntimeError("cancelled before the start-to-close limit")
        yield  # a generator, as `_lines` is
    monkeypatch.setattr(steps, "_lines", lost)
    with pytest.raises(RuntimeError):
        _step()
    assert step_events == []


def test_the_tool_index_of_an_older_reply_puts_delegations_after_the_other_calls():
    ai = agent_runs.RunMessageRow(idx=4, role="ai", tool_calls_json=json.dumps([
        {"kind": "delegation"}, {"kind": "parallel"}, {"kind": "ordered"}]))
    assert [steps.tool_idx(ai, p) for p in range(3)] == [7, 5, 6]


def test_run_message_sends_the_call_fields_and_the_tool_status():
    ai = agent_runs.RunMessageRow(idx=1, role="ai", tool_calls_json=json.dumps([
        dict(_entry("a", "t", {"x": 1}), position=0, seq=5)]))
    tool = agent_runs.RunMessageRow(idx=2, role="tool", tool_call_id="a", tool_name="t",
                                    usage_json=json.dumps({"status": "error"}))
    assert stream_writer.run_message(ai, RUN_ID)["tool_calls"] == [
        {"id": "a", "name": "t", "args": {"x": 1}}]
    assert stream_writer.run_message(tool, RUN_ID)["status"] == "error"


# ---------------------------------------------------------------- open_run


def test_pending_calls_leave_out_the_stored_delegations_of_an_older_run():
    ai = agent_runs.RunMessageRow(idx=1, role="ai", run_id="other", tool_calls_json=json.dumps([
        dict(_entry("s", "search_collections", {}), position=0, seq=5),
        dict(_entry("d", "run_subagent", {}, kind="delegation"), position=1, seq=6)]))
    messages = [agent_runs.RunMessageRow(idx=0, role="human"), ai]
    assert [c.call_id for c in activities.pending_calls(_row(), messages)] == ["s"]
    own = agent_runs.RunMessageRow(**{**ai.__dict__, "run_id": RUN_ID})
    assert [c.call_id for c in activities.pending_calls(_row(), [messages[0], own])] == ["s"]


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


def test_append_nag_writes_the_note_and_no_counter(monkeypatch, store):
    row = _row(next_seq=9)
    run_writes = []
    monkeypatch.setattr(agent_runs, "read_run", lambda *a: row)
    monkeypatch.setattr(agent_runs, "write_run", lambda r, **c: run_writes.append(c))
    nxt = ActivityEnvironment().run(activities.append_nag, AppendNagParams(
        run_id=RUN_ID, username="u", session_id="s", seq=9, idx=6, message="note text"))
    assert nxt == 10
    assert store["chat"] == [{"seq": 9, "role": "nag", "content": "note text"}]
    assert [(m.idx, m.role) for m in store["messages"]] == [(0, "human"), (6, "human")]
    assert run_writes == [{"next_seq": 10}]


# ------------------------------------------------------- the empty reply and the limits


def test_the_first_empty_reply_of_a_thread_writes_no_answer_and_gives_empty(store, monkeypatch):
    _serve(monkeypatch, store, _frames(reasoning="I'll try to read the file properly."))
    result = _step(step_no=1)
    assert (result.outcome, result.next_seq, result.next_idx) == ("empty", 5, 2)
    assert [r for r in store["chat"] if r["role"] == "assistant"] == []
    assert store["run"][-1] == {"next_seq": 5, "model_steps": 1, "prompt_tokens": 7,
                                "completion_tokens": 3}


@pytest.mark.parametrize("marker", ["usage", "legacy text"])
def test_an_empty_reply_after_the_retry_marker_gives_empty_again(store, monkeypatch, marker):
    store["messages"].append(agent_runs.RunMessageRow(idx=1, role="ai", run_id=RUN_ID,
                                                      usage_json=json.dumps({"step_no": 1})))
    usage = (json.dumps({steps.RETRY_MARKER_KEY: steps.EMPTY_RETRY_MARKER})
             if marker == "usage" else "")
    store["messages"].append(agent_runs.RunMessageRow(
        idx=2, role="human", content=steps.EMPTY_REPLY_TEXT, usage_json=usage))
    _serve(monkeypatch, store, _frames())
    result = _step(step_no=2)
    assert result.outcome == "empty_again"
    assert [r for r in store["chat"] if r["role"] == "assistant"] == []


def test_write_empty_note_writes_the_marker_and_no_counter(monkeypatch, store):
    run_writes = []
    monkeypatch.setattr(agent_runs, "write_run", lambda r, **c: run_writes.append(c))
    params = steps.EmptyNoteParams(run_id=RUN_ID, username="u", session_id="s", seq=9, idx=6)
    assert ActivityEnvironment().run(steps.write_empty_note, params) == 10
    [note] = [m for m in store["messages"] if m.idx == 6]
    assert (note.role, note.content) == ("human", steps.EMPTY_REPLY_TEXT)
    assert steps.is_retry_marker(note)
    assert store["chat"] == [{"seq": 9, "role": "nag", "content": steps.EMPTY_REPLY_TEXT}]
    assert run_writes == [{"next_seq": 10}]
    # A retry writes the same rows.
    assert ActivityEnvironment().run(steps.write_empty_note, params) == 10
    assert len([m for m in store["messages"] if m.idx == 6]) == 1


def test_write_empty_note_of_a_sub_agent_writes_no_chat_row(monkeypatch, store):
    store["row"] = _row(kind="subagent", depth=1)
    monkeypatch.setattr(agent_runs, "write_run", lambda r, **c: pytest.fail("no run write"))
    params = steps.EmptyNoteParams(run_id=RUN_ID, username="u", session_id="s", seq=9, idx=6)
    assert ActivityEnvironment().run(steps.write_empty_note, params) == 9
    assert store["chat"] == []


def _thread_with_evidence(store):
    """A thread with a search, a read and a reply that wrote text before its calls."""
    doc = "a" * 64
    store["messages"].extend([
        agent_runs.RunMessageRow(
            idx=1, role="ai", run_id=RUN_ID, content="The memo is the first lead.",
            usage_json=json.dumps({"step_no": 1, "model": "selected-model"}),
            tool_calls_json=json.dumps([
                dict(_entry("s", "search_collections", {"queries": ["memo"]}), position=0,
                     seq=5),
                dict(_entry("r", "read_documents", {"file_hash": [doc]}), position=1,
                     seq=6)])),
        agent_runs.RunMessageRow(
            idx=2, role="tool", tool_call_id="s", tool_name="search_collections",
            content=json.dumps({"items": [{"file_hash": "b" * 64, "collectionname": "c",
                                           "path": "/other.txt"}]}),
            usage_json=json.dumps({"status": "ok"})),
        agent_runs.RunMessageRow(
            idx=3, role="tool", tool_call_id="r", tool_name="read_documents",
            content=json.dumps({"items": [{"file_hash": doc, "collectionname": "c",
                                           "path": "/memo.txt", "page": 1}]}),
            usage_json=json.dumps({"status": "ok"})),
    ])


@pytest.mark.parametrize("reason, head", [
    ("step_budget", "limit of 600 model steps"),
    ("empty_response", "two replies with no text and no tool call"),
])
def test_write_incomplete_writes_the_evidence_with_no_model_call(store, monkeypatch, reason,
                                                                 head):
    _thread_with_evidence(store)
    store["row"] = _row(next_seq=7, model_steps=600)
    monkeypatch.setattr(steps, "_lines", lambda *a: pytest.fail("no model call"))
    params = steps.IncompleteParams(run_id=RUN_ID, username="u", session_id="s",
                                    reason=reason, limit=600)
    assert ActivityEnvironment().run(steps.write_incomplete, params) == 8
    [changes] = store["run"]
    assert changes["end_reason"] == reason and changes["next_seq"] == 8
    text = changes["result"]
    assert head in text
    assert "The memo is the first lead." in text
    assert "## Documents read\n- c/" + "a" * 64 + " /memo.txt. page 1" in text
    # A document that a search returned is listed apart, and not as read.
    assert "## Documents that the searches returned\n- c/" + "b" * 64 in text
    [row] = [r for r in store["chat"] if r["role"] == "assistant"]
    assert (row["seq"], row["content"], row["model"]) == (7, text, "selected-model")


def test_write_incomplete_retried_after_its_write_writes_nothing(store):
    store["row"] = _row(next_seq=8, end_reason="step_budget", result="done")
    params = steps.IncompleteParams(run_id=RUN_ID, username="u", session_id="s",
                                    reason="step_budget")
    assert ActivityEnvironment().run(steps.write_incomplete, params) == 8
    assert store["run"] == [] and store["chat"] == []


def test_write_incomplete_of_a_sub_agent_writes_the_result_only(store):
    _thread_with_evidence(store)
    store["row"] = _row(kind="subagent", depth=1)
    ActivityEnvironment().run(steps.write_incomplete, steps.IncompleteParams(
        run_id=RUN_ID, username="u", session_id="s", reason="step_budget"))
    [changes] = store["run"]
    assert changes["end_reason"] == "step_budget" and "memo.txt" in changes["result"]
    assert store["chat"] == []


# ---------------------------------------------------------------- the call chains


def _refs(*specs):
    return [CallRef(ai_idx=1, position=p, call_id=f"c{p}", name=name, kind=kind, seq=5 + p)
            for p, (name, kind) in enumerate(specs)]


def test_browser_calls_form_their_own_ordered_chain():
    calls = _refs(("browser_navigate", "parallel"), ("search_collections", "parallel"),
                  ("read_page", "parallel"), ("mark_todo", "ordered"),
                  ("browser_click", "parallel"), ("run_subagent", "delegation"))
    assert [c.name for c in calls if steps.runs_in_browser(c)] == [
        "browser_navigate", "read_page", "browser_click"]
    assert [c.name for c in calls if steps.runs_in_order(c)] == ["mark_todo"]
    assert not any(steps.runs_in_browser(c) and steps.runs_in_order(c) for c in calls)


def test_the_browser_tools_are_the_tools_of_the_browser_server():
    """The research agent's `execution.is_browser_tool` has the same rule. The two images
    share no module, so each test names the tools."""
    for name in ("read_page", "browser_navigate", "browser_snapshot", "browser_click",
                 "browser_type", "browser_select_option", "browser_press_key",
                 "browser_take_screenshot", "browser_wait_for"):
        assert steps.is_browser_tool(name), name
    for name in ("search_collections", "web_search", "read_documents", "read_more"):
        assert not steps.is_browser_tool(name), name
    calls = _refs(("browser_wait_for", "parallel"), ("browser_take_screenshot", "parallel"))
    assert [c.name for c in calls if steps.runs_in_browser(c)] == [
        "browser_wait_for", "browser_take_screenshot"]
