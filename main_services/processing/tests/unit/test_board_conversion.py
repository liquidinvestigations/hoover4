"""The end of an explore turn: its report, the conversion into a fact, and the brief.

The board storage is `FakeBoardStore`. The chat rows, the workspace store and the model
endpoint are replaced in each test, so no service runs.
"""

import json
from types import SimpleNamespace

import pytest
from temporalio.exceptions import ApplicationError

from database import chat_workspace as store_mod
from database.boards import FactRow, LabelRow
from tasks.P_agent import summarize
from tasks.P_board import activities, conversion
from tasks.P_board import commands as cmd
from tasks.P_board import model as m
from tasks.P_board.fold import fold
from tasks.P_board.prompts import render_brief
from board_store_fake import FakeBoardStore

OWNER = "admin"
REPORT = {"name": "report.md", "version": 2}
CITATIONS = [{"handle": "[D1]", "collectionname": "enron", "collection_dataset": "enron",
              "file_hash": "h1", "path": "/memo.eml", "page_id": 1, "quote": "approved the hedge"},
             {"handle": "[W1]", "url": "http://a.example/x", "final_url": "http://a.example/y",
              "version": "v1", "quote": "the hedge was approved"}]


def call_reply(args) -> dict:
    return {"choices": [{"message": {"tool_calls": [
        {"function": {"name": m.SUBMIT_FACT_TOOL, "arguments": json.dumps(args)}}]}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


# ------------------------------------------------------------------------- the request


def test_the_request_offers_only_the_fact_function_with_a_named_choice():
    body = conversion.request_body("q-model", "Find the approval", "report.md",
                                   "Approved [D1].", CITATIONS)
    assert [t["function"]["name"] for t in body["tools"]] == [m.SUBMIT_FACT_TOOL]
    assert body["tool_choice"] == {"type": "function", "function": {"name": m.SUBMIT_FACT_TOOL}}
    user = body["messages"][1]["content"]
    assert "Approved [D1]." in user and "Find the approval" in user
    assert "[D1] enron /memo.eml" in user and "[W1] http://a.example/y" in user
    for kind in m.EXPLORE_KINDS:
        assert f"- {kind}:" in body["messages"][0]["content"]


def test_a_valid_call_is_read_and_a_malformed_call_is_refused():
    args = conversion.parse_reply(call_reply({"fact": "Approved [D1].", "kind": "sourced",
                                              "open_questions": ["Who paid?"]}))
    assert args == {"fact": "Approved [D1].", "kind": "sourced", "open_questions": ["Who paid?"],
                    "slug": ""}
    for bad in ({"choices": [{"message": {"content": "text"}}]},
                call_reply({"fact": "", "kind": "sourced"}),
                call_reply({"fact": "x", "kind": "maybe"}),
                call_reply({"fact": "x", "kind": "inferred", "open_questions": ["a", "b", "c", "d"]}),
                call_reply({"fact": "x", "kind": "inferred", "slug": "x" * 81})):
        with pytest.raises(conversion.MalformedConversion):
            conversion.parse_reply(bad)


def test_resolve_keeps_the_report_handles_only_and_downgrades_an_unsourced_fact():
    kind, rows, problems = conversion.resolve(
        {"fact": "Approved [D1], [W1] and [D7].", "kind": "sourced"}, CITATIONS)
    assert kind == m.SOURCED
    assert [r["label"] for r in rows] == ["D1", "W1"]
    assert rows[1]["path"] == "http://a.example/y" and rows[0]["quote_verified"] == 1
    assert "D7" in problems[0]
    kind, rows, problems = conversion.resolve({"fact": "Approved.", "kind": "sourced"}, CITATIONS)
    assert kind == m.INFERRED and rows == [] and "became inferred" in problems[0]


# ---------------------------------------------------------------------- the end of a turn


@pytest.fixture
def board(monkeypatch):
    fake = FakeBoardStore().install(monkeypatch)
    fake.settings[cmd.IDENTITY_SETTING] = str(cmd.SLUG_IDENTITY)
    fake.add_board("b1", owner=OWNER, max_parallel=2)
    fake.submit("b1", "create:b1", cmd.CREATE_BOARD, OWNER,
                {"goals": ["Who approved the hedges?"], "origin": "The Enron emails."})
    fake.submit("b1", "reason_started:1", cmd.START_REASON, "dispatcher", {"reason_no": 1, "stalled": False})
    fake.submit("b1", "reason_result:1", cmd.REASON_RESULT, "reason", {"reason_no": 1, "payload": {
        "outcome": "intents", "situation": {"facts": 0, "hints": 0, "rejected": 0, "goals_added": 0},
        "intents": [{"from": ["background"], "objective": "Find the approval", "brief": "",
                     "position": 1, "slug": "approval", "questions": []}], "problems": []}})
    fake.submit("b1", "explore_started:intent-approval:1", cmd.START_EXPLORE, "dispatcher",
                {"intent_id": "intent-approval", "attempt": 1})
    fake.run_commands("b1")
    return fake


@pytest.fixture
def turn(monkeypatch):
    """The chat rows after the user row of the turn, the stored conversion row and the
    report store."""
    state = {"rows": [], "conversion": None, "written": [], "versions": {}}
    monkeypatch.setattr(activities, "_existing_user_seq", lambda owner, session, uuid: 4)
    monkeypatch.setattr(activities, "_turn_rows", lambda owner, session, seq: state["rows"])
    monkeypatch.setattr(activities, "_conversion_row", lambda owner, session, uuid: state["conversion"])

    def write(owner, session, uuid, args, report, model):
        state["written"].append(args)
        state["conversion"] = {"seq": 9, "args": args}

    monkeypatch.setattr(activities, "_write_conversion_row", write)
    monkeypatch.setattr(activities, "_record_llm_call", lambda *a, **k: None)
    monkeypatch.setattr(store_mod, "read_version",
                        lambda owner, session, name, version=None: state["versions"].get((name, version)))
    return state


def request(error=""):
    return activities.TurnRequest("b1", "intent-approval", 1, turn_error=error)


def answer(seq=8, report=None):
    return {"seq": seq, "role": "assistant", "tool_name": "", "content": "I wrote report.md.",
            "usage_json": json.dumps({"report": report} if report else {}), "message_uuid": ""}


def end_of(board):
    [inp] = [i for i in board.read_inputs("b1") if i.request_id == "explore_end:intent-approval:1"]
    return inp.body


def test_a_turn_without_a_report_fails(board, turn):
    turn["rows"] = [answer()]
    assert activities.conclude_explore(request()).outcome == "failed"
    assert end_of(board)["end"] == m.EXPLORE_FAILED
    assert "no report" in end_of(board)["error"]


def test_a_question_ends_the_turn_without_a_conversion(board, turn):
    turn["rows"] = [{"seq": 6, "role": "tool", "tool_name": "ask_user", "content": "", "usage_json": "",
                     "message_uuid": ""}, answer(report=REPORT)]
    assert activities.conclude_explore(request()).outcome == "question"
    assert end_of(board)["end"] == m.EXPLORE_QUESTION


def test_a_failed_turn_keeps_its_report_reference_and_submits_no_fact(board, turn):
    turn["rows"] = [answer(report=REPORT)]
    assert activities.conclude_explore(request("timed out")).outcome == "failed"
    assert end_of(board)["report"] == REPORT and "timed out" in end_of(board)["error"]


def test_a_report_is_converted_once_and_a_retry_reuses_the_stored_call(board, turn, monkeypatch):
    turn["rows"] = [answer(report=REPORT)]
    turn["versions"][("report.md", 2)] = store_mod.FileVersion(
        OWNER, "s", "report.md", 2, content="The board approved [D1].", citations=CITATIONS)
    concluded = activities.conclude_explore(request())
    assert concluded.outcome == "convert" and concluded.report == REPORT
    assert board.read_inputs("b1")[-1].request_id != "explore_end:intent-approval:1"

    sent = []

    def post(endpoint, body, timeout=None):
        sent.append(body)
        reply = call_reply({"fact": "The board approved the hedge [D1].", "kind": "sourced",
                            "open_questions": [], "slug": "hedge-approval"})
        return SimpleNamespace(status_code=200, json=lambda: reply, text=json.dumps(reply))

    monkeypatch.setattr(summarize, "post_or_raise", post)
    # The first attempt stops after its conversion row, before the submission. The second
    # attempt reuses the stored call and sends no request.
    submit, lost = activities._submit, []
    monkeypatch.setattr(activities, "_submit",
                        lambda *a, **k: lost.append(a) if not lost else submit(*a, **k))
    assert activities.convert_explore_report(request()) == "fact"
    assert activities.convert_explore_report(request()) == "fact"
    assert len(sent) == 1 and len(turn["written"]) == 1
    body = end_of(board)
    assert body["end"] == m.EXPLORE_CONCLUDED and body["fact"]["report"] == REPORT
    assert body["fact"]["answer_seq"] == 8 and body["citations"][0]["file_hash"] == "h1"
    board.run_commands("b1")
    assert fold(board.read_board("b1"), board.read_events("b1"),
                board.read_facts("b1")).intents["intent-approval"].state == m.CONCLUDED


def test_a_malformed_conversion_reply_is_raised_for_the_second_attempt(board, turn, monkeypatch):
    turn["rows"] = [answer(report=REPORT)]
    turn["versions"][("report.md", 2)] = store_mod.FileVersion(
        OWNER, "s", "report.md", 2, content="Approved [D1].", citations=CITATIONS)
    reply = {"choices": [{"message": {"content": "no call"}}]}
    monkeypatch.setattr(summarize, "post_or_raise", lambda endpoint, body, timeout=None:
                        SimpleNamespace(status_code=200, json=lambda: reply, text="x"))
    with pytest.raises(ApplicationError) as caught:
        activities.convert_explore_report(request())
    assert not caught.value.non_retryable
    assert turn["written"] == []
    assert not [i for i in board.read_inputs("b1") if i.request_id == "explore_end:intent-approval:1"]


def test_a_failed_explore_is_not_sent_again(board):
    board.submit("b1", "explore_end:intent-approval:1", cmd.EXPLORE_END, "explore",
                 {"intent_id": "intent-approval", "attempt": 1, "end": m.EXPLORE_FAILED,
                  "error": "the explore turn wrote no report"})
    board.run_commands("b1")
    folded = fold(board.read_board("b1"), board.read_events("b1"), board.read_facts("b1"))
    assert folded.intents["intent-approval"].state == m.FAILED


# --------------------------------------------------------------------------- the brief


def test_the_brief_gives_full_text_to_the_from_facts_and_labels_to_the_others():
    long_text = " ".join(f"word{n}" for n in range(60))
    facts = [FactRow("b1", "background", m.ORIGIN, "The Enron emails of 2001."),
             FactRow("b1", "fact-memo", m.SOURCED, "The memo names Kaminski as author [D1]."),
             FactRow("b1", "fact-bank", m.SOURCED, "The bank paid on 4 May [D2]."),
             FactRow("b1", "fact-long", m.INFERRED, long_text)]
    labels = [LabelRow("b1", "fact-bank", "fact", title="Bank payment", summary="The bank paid in May")]
    intent = SimpleNamespace(intent_id="intent-x", from_facts=["fact-memo"], objective="Find X", brief="")
    board = SimpleNamespace(internet_tools=False)
    text = render_brief(board, facts, [], [], intent, ["enron"], m.BASE_EXPLORE_STEPS, labels, False)
    assert "The Enron emails of 2001." in text
    assert "The memo names Kaminski as author." in text
    assert "fact-bank (sourced): Bank payment. The bank paid in May." in text
    assert "word39 ..." in text and "word40" not in text
    assert "Search only these collections: enron" in text
    assert m.SUBMIT_FACT_TOOL not in text and "report" in text
    web = render_brief(board, facts, [], [], intent, ["enron"], m.BASE_EXPLORE_STEPS, labels, True)
    assert "Use the web when" in web and "[W1]" in web
