"""`board_reason` stores the prompt and the whole reply of each assessment.

The board page shows them in the assessment details popup. The result goes to the command
writer as a `reason_result` command. The storage and the model call are replaced here, so no
service runs.
"""

from datetime import datetime

from database.boards import EventRow, FactRow
from tasks.P_agent import summarize
from tasks.P_board import activities
from tasks.P_board import commands as cmd
from tasks.P_board import model as m
from board_store_fake import FakeBoardStore

T0 = datetime(2026, 10, 14, 8, 0, 0)


class _Reply:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self.text}}], "usage": {"prompt_tokens": 7}}


def _patch(monkeypatch, live=True):
    store = FakeBoardStore().install(monkeypatch)
    store.add_board("b1", is_deleted=0 if live else 1)
    store.write_events([EventRow("b1", "e1", m.BOARD_CREATED, "admin", "", {}, T0)])
    store.publish_facts([FactRow("b1", "origin", m.ORIGIN, "o", created_at=T0),
                         FactRow("b1", "goal", m.GOAL, "g", created_at=T0)], [])
    monkeypatch.setenv("LLM_MODEL", "short-model")
    monkeypatch.setattr(activities, "_record_llm_call", lambda *a, **k: None)
    return store


def test_a_reason_stores_its_prompt_and_reply(monkeypatch):
    store = _patch(monkeypatch)
    reply = '{"intents": [{"from": ["origin"], "objective": "find the memo", "brief": "b"}]}'
    monkeypatch.setattr(summarize, "_post", lambda endpoint, body: _Reply(reply))
    assert activities.board_reason(activities.ReasonTask("b1", 1)) == "intents"
    (board_id, reason_no, prompt, text, error, model), = store.assessments
    assert (board_id, reason_no, text, error, model) == ("b1", 1, reply, "", "short-model")
    assert "You are the reasoning step" in prompt and "Goals:" in prompt
    [command] = store.read_inputs("b1")
    assert (command.request_id, command.kind, command.body["reason_no"]) == (
        "reason_result:1", cmd.REASON_RESULT, 1)
    assert command.body["payload"]["outcome"] == "intents"


def test_a_dropped_board_gets_no_assessment_row(monkeypatch):
    store = _patch(monkeypatch, live=False)
    monkeypatch.setattr(summarize, "_post", lambda endpoint, body: _Reply("{}"))
    activities.board_reason(activities.ReasonTask("b1", 2))
    assert store.assessments == [] and store.read_inputs("b1") == []


def test_a_final_assessment_proposes_answers_only(monkeypatch):
    store = _patch(monkeypatch)
    store.write_events([EventRow("b1", "e2", m.PAUSE_REQUESTED, "admin", "", {}, T0)])
    reply = '{"answers": [], "intents": [{"from": ["origin"], "objective": "find more"}]}'
    monkeypatch.setattr(summarize, "_post", lambda endpoint, body: _Reply(reply))
    task = activities.ReasonTask("b1", 3, final=True, assessed_budget=30, assessment_id="final-30")
    assert activities.board_reason(task) == "noop", "a final call runs on a board that is not active"
    payload = store.read_inputs("b1")[0].body["payload"]
    assert (payload["final"], payload["assessed_budget"], payload["assessment_id"]) == (True, 30, "final-30")
    assert "intents" not in payload
