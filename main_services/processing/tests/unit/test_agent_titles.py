"""The title and the summary of a conversation.

The call before the first turn writes a title and a first summary from the user message.
The call after each turn writes a new summary and keeps the title, except when the first
call wrote no title.
"""

from types import SimpleNamespace

import pytest

from tasks.P_agent import activities, summarize
from tasks.P_agent.summarize import TitleSummary
from test_agent_context_accounting import COLUMNS, _row, fake  # noqa: F401


@pytest.fixture
def turn(monkeypatch):
    """A run of turn seq 3 with the answer "The answer.", and the recorded writes."""
    state = {"earlier": 0, "writes": [], "calls": []}
    run = SimpleNamespace(username="u1", session_id="s1", run_id="r1", turn_seq=3,
                          result="The answer.")
    monkeypatch.setattr("database.agent_runs.read_run", lambda *a: run)
    monkeypatch.setattr(activities, "_earlier_user_rows", lambda *a: state["earlier"])
    monkeypatch.setattr(activities, "_user_row_text", lambda *a: "Who paid for the tests?")
    monkeypatch.setattr(activities, "_session_summary", lambda *a: "Earlier summary.")
    monkeypatch.setattr(activities, "_record_summarizer_call", lambda *a: None)
    monkeypatch.setattr(activities, "_set_session_title",
                        lambda u, s, title, summary: state["writes"].append((title, summary)))
    return state


def _ref(**kw):
    return activities.SummarizeRef(run_id="r1", username="u1", session_id="s1", **kw)


def test_the_first_turn_gets_a_title_and_a_summary_from_the_prompt(turn, monkeypatch):
    def from_prompt(message, language):
        turn["calls"].append(message)
        return TitleSummary(title="Test payments", summary="The user asks who paid.")
    monkeypatch.setattr(summarize, "title_from_prompt", from_prompt)
    start = activities.title_at_start(activities.RunRef(run_id="r1", username="u1", session_id="s1"))
    assert (start.first_turn, start.titled) == (True, True)
    assert turn["calls"] == ["Who paid for the tests?"]
    assert turn["writes"] == [("Test payments", "The user asks who paid.")]


def test_a_later_turn_makes_no_title_call(turn, monkeypatch):
    turn["earlier"] = 1
    monkeypatch.setattr(summarize, "title_from_prompt", lambda *a: pytest.fail("no title call"))
    start = activities.title_at_start(activities.RunRef(run_id="r1", username="u1", session_id="s1"))
    assert (start.first_turn, start.titled) == (False, False)
    assert turn["writes"] == []


def test_a_failed_title_call_keeps_the_row_and_says_so(turn, monkeypatch):
    monkeypatch.setattr(summarize, "title_from_prompt",
                        lambda *a: TitleSummary(error="hit max_tokens"))
    start = activities.title_at_start(activities.RunRef(run_id="r1", username="u1", session_id="s1"))
    assert (start.first_turn, start.titled) == (True, False)
    assert turn["writes"] == []


def test_the_summary_after_a_turn_keeps_the_title(turn, monkeypatch):
    def after(previous, message, answer, language, with_title):
        turn["calls"].append((previous, message, answer, with_title))
        return TitleSummary(summary="The user asked who paid, and the answer names the payer.")
    monkeypatch.setattr(summarize, "summary_after_turn", after)
    assert activities.summarize_turn(_ref()) == "The user asked who paid, and the answer names the payer."
    assert turn["calls"] == [("Earlier summary.", "Who paid for the tests?", "The answer.", False)]
    assert turn["writes"] == [("", "The user asked who paid, and the answer names the payer.")]


def test_the_summary_after_an_untitled_first_turn_writes_a_title(turn, monkeypatch):
    monkeypatch.setattr(summarize, "summary_after_turn",
                        lambda p, m, a, l, with_title: TitleSummary(title="Payer" if with_title else "",
                                                                    summary="Summary."))
    activities.summarize_turn(_ref(with_title=True))
    assert turn["writes"] == [("Payer", "Summary.")]


def test_an_empty_title_keeps_the_stored_title(fake):
    client = fake([_row(10)])
    activities._set_session_title("u1", "s1", "", "new summary")
    _, rows, columns = client.inserted[0]
    assert rows[0][columns.index("title")] == "a title"
    assert rows[0][columns.index("summary")] == "new summary"


def test_a_one_line_summary_reply_is_the_summary():
    assert summarize.parse_summary("**Summary:** The user asks.\n") == "The user asks."
    assert summarize.parse_summary("  \n") == ""
