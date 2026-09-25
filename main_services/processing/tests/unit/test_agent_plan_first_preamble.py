"""Which prose reaches the transcript, and which is folded behind the disclosure.

`RunStreamClient` decides this while a run streams. Everything it needs for the decision is
in memory, so the rule is exercised directly on a client whose row writes are stubbed out
-- a database would only be testing ClickHouse.

The case that matters is the one a real turn found: a plan-first turn opens with
`read_todo`, not `write_todo`, and an exception written for the write alone hid exactly
the prose the protocol exists to produce.
"""

import pytest

from database import agent_runs
from tasks.P_agent import stream_writer


class _Writer:
    def write(self, **changes):
        pass


class _Adapter:
    """The two calls the tests make, on a `RunStreamClient`."""

    def __init__(self, client):
        self.client = client

    def _handle(self, kind, content):
        if kind == "tool_start":
            content = {"tool_call_id": content["name"] + "-call", "name": content["name"],
                       "args": {}}
        self.client._handle_run_event(kind, content)

    def _answer_text(self):
        return self.client._answer_text()

    @property
    def reasoning(self):
        return self.client.reasoning


@pytest.fixture(autouse=True)
def no_writes(monkeypatch):
    monkeypatch.setattr(agent_runs, "write_message", lambda *a, **k: None)
    monkeypatch.setattr(stream_writer.ResearchStreamWriter, "_insert_stream_row",
                        lambda self, *a, **k: None)
    monkeypatch.setattr(stream_writer, "_chat_model", lambda: "test-model")


def _writer():
    """A client that decides but does not write: no ClickHouse in a unit test."""
    row = agent_runs.RunRow(run_id="00000000-0000-4000-8000-000000000001", username="u",
                            session_id="s", thread_id="00000000-0000-4000-8000-000000000001",
                            start_seq=1, next_seq=1)
    client = stream_writer.RunStreamClient(
        row, [agent_runs.RunMessageRow(idx=0, role="human", content="q")], _Writer(),
        turn_uuid="t", history=[], allowed_collections=[], llm_model="m",
        internet_tools=False, write_chat_row=lambda *a, **k: None)
    return _Adapter(client)


def _start(name):
    return {"name": name, "input": {}}


def test_the_prose_that_opens_a_plan_first_turn_stays_in_the_answer():
    writer = _writer()
    writer._handle("response", "I understand the task as X. Two approaches: A, or B.")
    writer._handle("tool_start", _start("read_todo"))
    writer._handle("tool_start", _start("write_todo"))
    assert "Two approaches" in writer._answer_text()
    assert writer.reasoning == ""


def test_narration_before_real_work_is_still_folded_into_the_reasoning():
    writer = _writer()
    writer._handle("response", "Let me search the collections first.")
    writer._handle("tool_start", _start("search_collections"))
    assert writer._answer_text() == ""
    assert "search the collections" in writer.reasoning


def test_the_opening_ends_at_the_first_tool_that_is_real_work():
    writer = _writer()
    writer._handle("response", "I understand the task as X.")
    writer._handle("tool_start", _start("write_todo"))
    writer._handle("tool_start", _start("search_collections"))
    writer._handle("response", "Now let me check the plan again.")
    writer._handle("tool_start", _start("mark_todo"))
    # The opening prose survived; the mid-turn narration did not, even though the tool
    # in front of it is a todo tool.
    assert "I understand the task as X." in writer._answer_text()
    assert "check the plan again" in writer.reasoning


def test_a_tool_start_with_no_prose_still_closes_the_opening():
    # The rule is applied on every tool start, not only when there is prose to place:
    # otherwise a silent search would leave the opening notionally still running and the
    # next todo call would keep narration it should not.
    writer = _writer()
    writer._handle("tool_start", _start("search_collections"))
    writer._handle("response", "Marking the first item done.")
    writer._handle("tool_start", _start("mark_todo"))
    assert writer._answer_text() == ""
    assert "Marking the first item done." in writer.reasoning
