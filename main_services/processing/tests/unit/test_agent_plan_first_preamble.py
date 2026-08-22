"""Which prose reaches the transcript, and which is folded behind the disclosure.

`ResearchStreamWriter` decides this while a turn runs. Everything it needs for the
decision is in memory, so the rule is exercised directly on an instance whose row writes
are stubbed out -- a database would only be testing ClickHouse.

The case that matters is the one a real turn found: a plan-first turn opens with
`read_todo`, not `write_todo`, and an exception written for the write alone hid exactly
the prose the protocol exists to produce.
"""

from tasks.P_agent.stream_writer import ResearchStreamWriter


class _Params:
    username = "u"
    session_id = "s"
    start_seq = 1
    allowed_collections = ()
    query = "q"
    turn_uuid = "t"


def _writer():
    """A writer that decides but does not write: no ClickHouse in a unit test."""
    writer = ResearchStreamWriter(_Params())
    writer._insert_stream_row = lambda *a, **k: None
    return writer


def _start(name):
    return {"name": name, "input": {}}


def test_the_prose_that_opens_a_plan_first_turn_stays_in_the_answer():
    writer = _writer()
    writer._handle("response", "I understand the task as X. Two approaches: A, or B.")
    writer._handle("start_tool", _start("read_todo"))
    writer._handle("start_tool", _start("write_todo"))
    assert "Two approaches" in writer._answer_text()
    assert writer.reasoning == ""


def test_narration_before_real_work_is_still_folded_into_the_reasoning():
    writer = _writer()
    writer._handle("response", "Let me search the collections first.")
    writer._handle("start_tool", _start("search_collections"))
    assert writer._answer_text() == ""
    assert "search the collections" in writer.reasoning


def test_the_opening_ends_at_the_first_tool_that_is_real_work():
    writer = _writer()
    writer._handle("response", "I understand the task as X.")
    writer._handle("start_tool", _start("write_todo"))
    writer._handle("start_tool", _start("search_collections"))
    writer._handle("response", "Now let me check the plan again.")
    writer._handle("start_tool", _start("mark_todo"))
    # The opening prose survived; the mid-turn narration did not, even though the tool
    # in front of it is a todo tool.
    assert "I understand the task as X." in writer._answer_text()
    assert "check the plan again" in writer.reasoning


def test_a_tool_start_with_no_prose_still_closes_the_opening():
    # The rule is applied on every tool start, not only when there is prose to place:
    # otherwise a silent search would leave the opening notionally still running and the
    # next todo call would keep narration it should not.
    writer = _writer()
    writer._handle("start_tool", _start("search_collections"))
    writer._handle("response", "Marking the first item done.")
    writer._handle("start_tool", _start("mark_todo"))
    assert writer._answer_text() == ""
    assert "Marking the first item done." in writer.reasoning
