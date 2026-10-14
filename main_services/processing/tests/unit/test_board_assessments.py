"""`board_reason` stores the prompt and the whole reply of each assessment.

The board page shows them in the assessment details popup. The storage and the model call
are replaced here, so no service runs.
"""

from datetime import datetime

from database import boards
from database.boards import BoardRow, EventRow, FactRow
from tasks.P_agent import summarize
from tasks.P_board import activities
from tasks.P_board import model as m

T0 = datetime(2026, 10, 14, 8, 0, 0)


class _Reply:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self.text}}], "usage": {"prompt_tokens": 7}}


def _patch(monkeypatch, live=True):
    board = BoardRow("b1", "admin", "t", "g", collections=["enron"], created_at=T0)
    written = {"assessments": [], "events": []}
    monkeypatch.setenv("LLM_MODEL", "short-model")
    monkeypatch.setattr(boards, "read_board", lambda b: board)
    monkeypatch.setattr(boards, "read_events",
                        lambda b: [EventRow("b1", "e1", m.BOARD_CREATED, "admin", "", {}, T0)])
    monkeypatch.setattr(boards, "read_facts", lambda b: [FactRow("b1", "origin", m.ORIGIN, "o"),
                                                         FactRow("b1", "goal", m.GOAL, "g")])
    monkeypatch.setattr(boards, "read_citations", lambda b: [])
    monkeypatch.setattr(boards, "board_is_live", lambda b: live)
    monkeypatch.setattr(boards, "write_assessment",
                        lambda *args: written["assessments"].append(args))
    monkeypatch.setattr(boards, "write_event", lambda e: written["events"].append(e))
    monkeypatch.setattr(activities, "_record_llm_call", lambda *a, **k: None)
    return written


def test_a_reason_stores_its_prompt_and_reply(monkeypatch):
    written = _patch(monkeypatch)
    reply = '{"intents": [{"from": ["origin"], "objective": "find the memo", "brief": "b"}]}'
    monkeypatch.setattr(summarize, "_post", lambda endpoint, body: _Reply(reply))
    assert activities.board_reason(activities.ReasonTask("b1", 1)) == "intents"
    (board_id, reason_no, prompt, text, error, model), = written["assessments"]
    assert (board_id, reason_no, text, error, model) == ("b1", 1, reply, "", "short-model")
    assert "You are the reasoning step" in prompt and "Goals:" in prompt
    assert written["events"][0].event_type == m.REASON_RESULT


def test_a_dropped_board_gets_no_assessment_row(monkeypatch):
    written = _patch(monkeypatch, live=False)
    monkeypatch.setattr(summarize, "_post", lambda endpoint, body: _Reply("{}"))
    activities.board_reason(activities.ReasonTask("b1", 2))
    assert written["assessments"] == [] and written["events"] == []
