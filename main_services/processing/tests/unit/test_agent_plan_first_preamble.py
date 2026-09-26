"""Which prose reaches the transcript, and which is folded behind the disclosure.

`round_view` decides this from the stored `ai` messages of the round, because no step keeps
state. The tests build the thread in memory, so no database is involved.

The case that matters is the one a real turn found: a plan-first turn opens with
`read_todo`, not `write_todo`, and an exception written for the write alone hid exactly
the prose the protocol exists to produce.
"""

import json

from database import agent_runs
from tasks.P_agent.stream_writer import round_view


def _thread(*replies):
    """A thread of one human message and one `ai` message for each `(text, [names])`."""
    messages = [agent_runs.RunMessageRow(idx=0, role="human", content="question")]
    for text, names in replies:
        calls = [{"id": f"c{len(messages)}-{i}", "name": n, "args": {}}
                 for i, n in enumerate(names)]
        messages.append(agent_runs.RunMessageRow(
            idx=len(messages), role="ai", content=text, tool_calls_json=json.dumps(calls)))
    return messages


def test_the_prose_that_opens_a_plan_first_turn_stays_in_the_answer():
    prose, reasoning, _ = round_view(_thread(
        ("I understand the task as X. Two approaches: A, or B.", ["read_todo"]),
        ("", ["write_todo"])))
    assert "Two approaches" in prose
    assert reasoning == ""


def test_narration_before_real_work_is_still_folded_into_the_reasoning():
    prose, reasoning, _ = round_view(_thread(
        ("Let me search the collections first.", ["search_collections"])))
    assert prose == ""
    assert "search the collections" in reasoning


def test_the_opening_ends_at_the_first_tool_that_is_real_work():
    prose, reasoning, in_opening = round_view(_thread(
        ("I understand the task as X.", ["write_todo", "search_collections"]),
        ("Now let me check the plan again.", ["mark_todo"])))
    # The opening prose survived. The mid-turn narration did not, even though the tool in
    # front of it is a todo tool.
    assert "I understand the task as X." in prose
    assert "check the plan again" in reasoning
    assert in_opening is False


def test_a_call_with_no_prose_still_closes_the_opening():
    prose, reasoning, _ = round_view(_thread(
        ("", ["search_collections"]),
        ("Marking the first item done.", ["mark_todo"])))
    assert prose == ""
    assert "Marking the first item done." in reasoning


def test_a_nag_starts_a_new_round():
    messages = _thread(("Let me search.", ["search_collections"]))
    messages.append(agent_runs.RunMessageRow(idx=len(messages), role="human", content="nag"))
    messages.append(agent_runs.RunMessageRow(
        idx=len(messages), role="ai", content="Plan: A.",
        tool_calls_json=json.dumps([{"id": "x", "name": "read_todo", "args": {}}])))
    prose, reasoning, in_opening = round_view(messages)
    assert (prose, reasoning, in_opening) == ("Plan: A.", "", True)
