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
    def __init__(self, text, status_code=200, finish="stop"):
        self.text = text
        self.status_code = status_code
        self.finish = finish

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return {"choices": [{"message": {"content": self.text}, "finish_reason": self.finish}],
                "usage": {"prompt_tokens": 7}}


def _patch(monkeypatch, live=True):
    store = FakeBoardStore().install(monkeypatch)
    store.add_board("b1", is_deleted=0 if live else 1)
    store.write_events([EventRow("b1", "e1", m.BOARD_CREATED, "admin", "", {}, T0)])
    store.publish_facts([FactRow("b1", "origin", m.ORIGIN, "o", created_at=T0),
                         FactRow("b1", "goal", m.GOAL, "g", created_at=T0)], [])
    monkeypatch.setenv("LLM_MODEL", "short-model")
    monkeypatch.setenv("LLM_QUALITY_MODEL", "agent-model")
    monkeypatch.setattr(activities, "_record_llm_call", lambda *a, **k: None)
    return store


def test_a_reason_cut_in_its_reasoning_goes_again_without_reasoning(monkeypatch):
    _patch(monkeypatch)
    sent = []
    good = '{"intents": [{"from": ["origin"], "objective": "find the memo", "brief": "b"}]}'

    def post(endpoint, body, timeout=None):
        sent.append(body)
        if len(sent) == 1:
            return _Reply("", finish="length")
        if "chat_template_kwargs" in body:
            return _Reply("refused", status_code=400)
        return _Reply(good)

    monkeypatch.setattr(summarize, "_post", post)
    assert activities.board_reason(activities.ReasonTask("b1", 1)) == "intents"
    assert sent[0]["max_tokens"] == m.REASON_THINKING_TOKENS and "chat_template_kwargs" not in sent[0]
    assert sent[1]["chat_template_kwargs"] == {"enable_thinking": False}
    assert sent[1]["max_tokens"] == m.REASON_MAX_TOKENS
    assert len(sent) == 3 and "chat_template_kwargs" not in sent[2]


def test_a_reason_with_a_reply_sends_one_request(monkeypatch):
    _patch(monkeypatch)
    sent = []
    good = '{"intents": [{"from": ["origin"], "objective": "find the memo", "brief": "b"}]}'
    monkeypatch.setattr(summarize, "_post", lambda endpoint, body, timeout=None: sent.append(body) or _Reply(good))
    assert activities.board_reason(activities.ReasonTask("b1", 1)) == "intents"
    assert len(sent) == 1


def test_a_reason_stores_its_prompt_and_reply(monkeypatch):
    store = _patch(monkeypatch)
    reply = '{"intents": [{"from": ["origin"], "objective": "find the memo", "brief": "b"}]}'
    monkeypatch.setattr(summarize, "_post", lambda endpoint, body, timeout=None: _Reply(reply))
    assert activities.board_reason(activities.ReasonTask("b1", 1)) == "intents"
    (board_id, reason_no, prompt, text, error, model), = store.assessments
    # An assessment uses the agent model, not the short-call model.
    assert (board_id, reason_no, text, error, model) == ("b1", 1, reply, "", "agent-model")
    assert "You are the reasoning step" in prompt and "Goals:" in prompt
    [command] = store.read_inputs("b1")
    assert (command.request_id, command.kind, command.body["reason_no"]) == (
        "reason_result:1", cmd.REASON_RESULT, 1)
    assert command.body["payload"]["outcome"] == "intents"


def test_a_dropped_board_gets_no_assessment_row(monkeypatch):
    store = _patch(monkeypatch, live=False)
    monkeypatch.setattr(summarize, "_post", lambda endpoint, body, timeout=None: _Reply("{}"))
    activities.board_reason(activities.ReasonTask("b1", 2))
    assert store.assessments == [] and store.read_inputs("b1") == []


def test_a_final_assessment_proposes_answers_only(monkeypatch):
    store = _patch(monkeypatch)
    store.write_events([EventRow("b1", "e2", m.PAUSE_REQUESTED, "admin", "", {}, T0)])
    reply = '{"answers": [], "intents": [{"from": ["origin"], "objective": "find more"}]}'
    monkeypatch.setattr(summarize, "_post", lambda endpoint, body, timeout=None: _Reply(reply))
    task = activities.ReasonTask("b1", 3, final=True, assessed_budget=30, assessment_id="final-30")
    assert activities.board_reason(task) == "noop", "a final call runs on a board that is not active"
    payload = store.read_inputs("b1")[0].body["payload"]
    assert (payload["final"], payload["assessed_budget"], payload["assessment_id"]) == (True, 30, "final-30")
    assert "intents" not in payload


def test_an_attempt_after_a_submitted_result_sends_no_request(monkeypatch):
    store = _patch(monkeypatch)
    store.submit("b1", "reason_result:4", cmd.REASON_RESULT, "reason", {"reason_no": 4, "payload": {}})

    def refuse(*a, **k):
        raise AssertionError("a reused assessment sends no request")

    monkeypatch.setattr(summarize, "_post", refuse)
    assert activities.board_reason(activities.ReasonTask("b1", 4)) == "reused"
    assert store.assessments == []


def test_a_transport_failure_is_raised_and_stores_nothing(monkeypatch):
    import pytest
    import requests

    store = _patch(monkeypatch)
    calls = []
    monkeypatch.setattr(activities, "_record_llm_call", lambda *a, **k: calls.append(a))
    sent = []

    def timeout(endpoint, body, timeout=None):
        sent.append(timeout)
        raise requests.ReadTimeout("read timeout")

    monkeypatch.setattr(summarize, "_post", timeout)
    with pytest.raises(summarize.TransportFailure):
        activities.board_reason(activities.ReasonTask("b1", 5))
    assert store.read_inputs("b1") == [] and store.assessments == []
    from tasks.P_agent.model_timeouts import TIMEOUTS

    assert sent == [(activities.REASON_CONNECT_SECONDS, TIMEOUTS.board_reason_request_seconds)]
    assert calls and calls[0][5] is False, "the failed attempt is recorded"
    monkeypatch.setattr(summarize, "_post", lambda endpoint, body, timeout=None: _Reply("busy", 503))
    with pytest.raises(summarize.TransportFailure):
        activities.board_reason(activities.ReasonTask("b1", 5))


def test_a_refused_request_is_a_model_failure(monkeypatch):
    store = _patch(monkeypatch)
    monkeypatch.setattr(summarize, "_post", lambda endpoint, body, timeout=None: _Reply("too long", 400))
    assert activities.board_reason(activities.ReasonTask("b1", 6)) == m.MODEL_FAILURE
    payload = store.read_inputs("b1")[0].body["payload"]
    assert payload["outcome"] == m.MODEL_FAILURE and "400" in payload["error"]


def test_an_exhausted_assessment_records_a_model_failure(monkeypatch):
    store = _patch(monkeypatch)
    activities.record_reason_failure(activities.ReasonFailure("b1", 7, True, "ReadTimeout: x"))
    [command] = store.read_inputs("b1")
    assert command.request_id == "reason_result:7"
    assert command.body["payload"] == {"outcome": m.MODEL_FAILURE, "error": "ReadTimeout: x", "raw": "",
                                       "problems": [], "stalled": True}
