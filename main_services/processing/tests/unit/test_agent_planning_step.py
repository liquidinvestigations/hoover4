"""The first model step, earlier chat turns, compaction rows and the final step.

The database writers are the lists of `test_agent_run.store`, and the agent stream is a
list of frames. No Temporal server is needed.
"""

import json

import pytest

from database import agent_runs, chat_todos
from tasks.P_agent import activities, steps

from test_agent_run import (  # noqa: F401 - `store` and `step_events` are fixtures
    RUN_ID, _entry, _frames, _row, _serve, _step, step_events, store,
)

EARLIER_THREAD = "0b5e3c1a-2222-4222-8333-944455556666"


def _plan_frames(entries):
    return _frames(entries=entries)


# ---------------------------------------------------------------- the first step

def test_the_first_turn_sends_a_normal_model_step(store, monkeypatch):
    _serve(monkeypatch, store, _frames(text="The answer."))
    result = _step()
    assert store["requests"][0]["mode"] == "tools"
    assert result.outcome == "answered"
    assert store["messages"][-1].is_final == 1


# ---------------------------------------------------------------- the earlier turns


def test_the_earlier_turns_are_sent_as_whole_threads(store, monkeypatch):
    earlier = [
        agent_runs.RunMessageRow(idx=0, role="human", content="first", run_id=EARLIER_THREAD),
        agent_runs.RunMessageRow(
            idx=1, role="ai", run_id=EARLIER_THREAD,
            tool_calls_json=json.dumps([_entry("m", "mark_todo", {"ids": ["9"]})])),
        agent_runs.RunMessageRow(idx=2, role="tool", tool_call_id="m", tool_name="mark_todo",
                                 content="unknown step id 9", run_id=EARLIER_THREAD,
                                 usage_json=json.dumps({"status": "error"})),
        agent_runs.RunMessageRow(idx=3, role="ai", content="x" * 9000, run_id=EARLIER_THREAD),
    ]
    own = list(store["messages"])
    monkeypatch.setattr(agent_runs, "read_earlier_threads", lambda *a: [EARLIER_THREAD])
    monkeypatch.setattr(agent_runs, "read_messages",
                        lambda u, s, t: earlier if t == EARLIER_THREAD else own)
    _serve(monkeypatch, store, _frames(text="done"))
    _step()
    sent = store["requests"][0]["earlier"]
    assert [m["role"] for m in sent] == ["human", "ai", "tool", "ai"]
    assert sent[2]["status"] == "error" and sent[2]["content"] == "unknown step id 9"
    assert len(sent[3]["content"]) == 9000
    assert {m["thread_id"] for m in sent} == {EARLIER_THREAD}


# ---------------------------------------------------------------- compaction rows


def test_a_compaction_row_follows_its_reply_and_moves_the_results_one_up(store, monkeypatch):
    record = {"layer": "eviction", "evicted": [[RUN_ID, 0]], "summarised": [], "handoff": "",
              "tokens_before": 9, "threshold": 8}
    lines = _frames(entries=[_entry("a", "search_collections", {"query": "a"})])
    turn = json.loads(lines[0][len("data: "):])
    turn["compaction"] = record
    lines[0] = f"data: {json.dumps(turn)}"
    _serve(monkeypatch, store, lines)
    result = _step()
    rows = {m.idx: m for m in store["messages"]}
    assert rows[1].role == "ai" and rows[2].role == "compaction"
    assert json.loads(rows[2].content) == record
    assert steps.tool_idx(rows[1], 0) == 3
    assert result.calls[0].ai_idx == 1


# ---------------------------------------------------------------- the final step


def test_a_final_reply_with_a_call_is_the_answer_and_ends_the_loop(store, monkeypatch):
    _serve(monkeypatch, store, _frames(
        text="The answer.", entries=[_entry("x", "search_collections", {"query": "x"})]))
    result = _step(mode="final", reason="step_budget")
    assert result.outcome == "answered"
    results = [m for m in store["messages"] if m.role == "tool" and m.tool_call_id == "x"]
    assert len(results) == 1 and json.loads(results[0].content)["error"] == "not_run"
    assert [r["role"] for r in store["chat"]] == ["assistant"]
    assert "The answer." in store["chat"][0]["content"]


# ---------------------------------------------------------------- the index after a reply


COMPACTION = {"layer": "eviction", "evicted": [[RUN_ID, 0]], "summarised": [], "handoff": "",
              "tokens_before": 9, "threshold": 8}


def _reply_frames(text, entries, compaction):
    lines = _frames(text=text, entries=entries)
    if compaction:
        at = next(i for i, line in enumerate(lines) if '"model_turn"' in line)
        turn = json.loads(lines[at][len("data: "):])
        turn["compaction"] = COMPACTION
        lines[at] = f"data: {json.dumps(turn)}"
    return lines


def _two_calls():
    return [_entry("a", "search_collections", {"query": "a"}),
            _entry("b", "search_collections", {"query": "b"})]


@pytest.mark.parametrize("mode, reason, entries, compaction, expected_rows, next_idx", [
    # An answer with no call and a compaction row.
    ("tools", "", [], True, [(0, "human"), (1, "ai"), (2, "compaction")], 3),
    # A `final` `repeated_call` reply with 2 calls and no compaction.
    ("final", "repeated_call", _two_calls(), False,
     [(0, "human"), (1, "ai"), (2, "tool"), (3, "tool")], 4),
    # A `final` reply with 1 call and a compaction row.
    ("final", "repeated_call", _two_calls()[:1], True,
     [(0, "human"), (1, "ai"), (2, "compaction"), (3, "tool")], 4),
    # A reply with 2 calls in mode `tools`. The results are written by the tool steps.
    ("tools", "", _two_calls(), False, [(0, "human"), (1, "ai")], 4),
    # An answer with no call and no compaction.
    ("tools", "", [], False, [(0, "human"), (1, "ai")], 2),
])
def test_the_next_index_is_the_index_after_the_last_row_of_the_reply(
        store, monkeypatch, mode, reason, entries, compaction, expected_rows, next_idx):
    if mode == "final":
        # The reason's human message is already the last row, so the reply takes index 1.
        store["messages"][0].content = steps.FINAL_TEXT[reason]
    _serve(monkeypatch, store, _reply_frames("The answer." if not entries or mode == "final"
                                             else "", entries, compaction))
    result = _step(mode=mode, reason=reason)
    assert [(m.idx, m.role) for m in store["messages"]] == expected_rows
    for m in store["messages"]:
        if m.role == "tool":
            assert json.loads(m.content)["error"] == "not_run"
    assert result.next_idx == next_idx
    assert result.next_idx == steps.reply_end_idx(store["messages"][1])


def test_a_nag_after_a_compacted_answer_keeps_the_compaction_row(store, monkeypatch):
    monkeypatch.setattr(agent_runs, "write_run", lambda row, **changes: None)
    _serve(monkeypatch, store, _reply_frames("The answer.", [], True))
    result = _step()
    assert result.next_idx == 3
    activities.append_nag(activities.AppendNagParams(
        run_id=RUN_ID, username="u", session_id="s", seq=result.next_seq,
        idx=result.next_idx, message="nag", starts_round=True))
    rows = {m.idx: m for m in store["messages"]}
    assert rows[2].role == "compaction" and json.loads(rows[2].content) == COMPACTION
    assert (rows[3].role, rows[3].content) == ("human", "nag")


# ---------------------------------------------------------------- the todo store


def test_edit_steps_with_no_plan_is_refused_as_write_todo_refuses_an_empty_goal(monkeypatch):
    monkeypatch.setattr(chat_todos, "read_todo",
                        lambda u, s: {"goal": "", "items": [], "version": 0})
    with pytest.raises(chat_todos.TodoError, match="the goal is empty"):
        chat_todos.edit_steps("u", "s", ["a step"])
