"""The end of an explore turn: its report, the conversion into a fact, and the brief.

The board storage is `FakeBoardStore`. The chat rows, the workspace store and the model
endpoint are replaced in each test, so no service runs.
"""

import json
from types import SimpleNamespace

import pytest
from temporalio.exceptions import ApplicationError

from database import chat_workspace as store_mod
from database.boards import BoardRow, FactRow, LabelRow
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


def test_the_function_schema_has_no_large_length_limit():
    """The model server builds a grammar from the schema, and a large maxLength makes each
    token step slow for every request on the server."""
    def limits(node):
        if isinstance(node, dict):
            yield from (v for k, v in node.items() if k == "maxLength")
            for value in node.values():
                yield from limits(value)
        elif isinstance(node, list):
            for value in node:
                yield from limits(value)

    body = conversion.request_body("q-model", "Find", "report.md", "Approved [D1].", CITATIONS)
    assert all(limit <= 1000 for limit in limits(body["tools"]))


def test_the_function_has_no_fact_field_and_names_the_board_language():
    schema = conversion.submit_schema("fr")["function"]["parameters"]
    assert set(schema["properties"]) == {"kind", "open_questions", "slug"}
    assert schema["required"] == ["kind", "open_questions"]
    assert "in French" in schema["properties"]["slug"]["description"]
    body = conversion.request_body("q-model", "Trouver", "report.md", "Approuvé [D1].", CITATIONS,
                                   language="fr")
    assert "words in French" in body["messages"][0]["content"]
    assert body["tools"] == [conversion.submit_schema("fr")]
    assert body["max_tokens"] == conversion.CONVERSION_MAX_TOKENS


def test_the_convert_retry_policy_has_the_attempts_of_the_conversion():
    from tasks.P_board.workflows import EXTERNAL_RETRY

    assert EXTERNAL_RETRY.maximum_attempts == conversion.CONVERT_ATTEMPTS


def test_a_prompt_cuts_a_long_fact_and_keeps_a_short_one():
    from tasks.P_board.prompts import PROMPT_FACT_CHARS, clip_fact

    assert clip_fact("short") == "short"
    cut = clip_fact("y" * (PROMPT_FACT_CHARS + 10))
    assert cut.startswith("y" * PROMPT_FACT_CHARS) and cut.endswith("[cut: the finding has more text]")


def test_a_valid_call_is_read_and_a_malformed_call_is_refused():
    args = conversion.parse_reply(call_reply({"kind": "sourced", "open_questions": ["Who paid?"]}))
    assert args == {"kind": "sourced", "open_questions": ["Who paid?"], "slug": ""}
    # A `fact` field, as an older row or a model holds it, is ignored.
    older = conversion.parse_reply(call_reply({"fact": "placeholder", "kind": "inferred", "slug": "a-b"}))
    assert older == {"kind": "inferred", "open_questions": [], "slug": "a-b"}
    for bad in ({"choices": [{"message": {"content": "text"}}]},
                call_reply({"kind": "maybe"}),
                call_reply({"kind": "inferred", "open_questions": ["a", "b", "c", "d"]}),
                call_reply({"kind": "inferred", "open_questions": [""]}),
                call_reply({"kind": "inferred", "slug": "x" * 81})):
        with pytest.raises(conversion.MalformedConversion):
            conversion.parse_reply(bad)


def test_resolve_keeps_the_report_handles_only_and_downgrades_an_unsourced_fact():
    kind, rows, problems = conversion.resolve("Approved [D1], [W1] and [D7].", "sourced", CITATIONS)
    assert kind == m.SOURCED
    assert [r["label"] for r in rows] == ["D1", "W1"]
    assert rows[1]["path"] == "http://a.example/y" and rows[0]["quote_verified"] == 1
    assert "D7" in problems[0]
    kind, rows, problems = conversion.resolve("Approved.", "sourced", CITATIONS)
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


def test_a_stored_question_row_does_not_end_the_explore_in_question(board, turn):
    """An `ask_user` row of an earlier agent version is an ordinary tool row. The report of
    the turn decides its end."""
    turn["rows"] = [{"seq": 6, "role": "tool", "tool_name": "ask_user", "content": "", "usage_json": "",
                     "message_uuid": ""}, answer(report=REPORT)]
    concluded = activities.conclude_explore(request())
    assert concluded.outcome == "convert" and concluded.report == REPORT
    assert all(i.body.get("end") != m.EXPLORE_QUESTION for i in board.read_inputs("b1"))


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


def test_the_second_attempt_turns_off_reasoning_and_drops_a_refused_hint(board, turn, monkeypatch):
    turn["rows"] = [answer(report=REPORT)]
    turn["versions"][("report.md", 2)] = store_mod.FileVersion(
        OWNER, "s", "report.md", 2, content="Approved [D1].", citations=CITATIONS)
    reply = call_reply({"fact": "Approved [D1].", "kind": "sourced", "open_questions": []})
    sent = []

    def post(endpoint, body, timeout=None):
        sent.append(body)
        status = 400 if "chat_template_kwargs" in body else 200
        return SimpleNamespace(status_code=status, json=lambda: reply, text=json.dumps(reply))

    monkeypatch.setattr(summarize, "post_or_raise", post)
    monkeypatch.setattr(activities.activity, "in_activity", lambda: True)
    monkeypatch.setattr(activities.activity, "info", lambda: SimpleNamespace(attempt=2))
    assert activities.convert_explore_report(request()) == "fact"
    assert sent[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert len(sent) == 2 and "chat_template_kwargs" not in sent[1]


REPORT_TEXT = ("# Approval of the hedge\n\nThe board approved the hedge on 4 May 2001 [D1].\n\n"
               "## Open questions\n\n- Who paid?\n")


def _report(turn, text=REPORT_TEXT):
    turn["rows"] = [answer(report=REPORT)]
    turn["versions"][("report.md", 2)] = store_mod.FileVersion(
        OWNER, "s", "report.md", 2, content=text, citations=CITATIONS)


def _replies(monkeypatch, reply=None, status=200, error=None):
    sent = []

    def post(endpoint, body, timeout=None):
        sent.append(body)
        if error is not None:
            raise error
        return SimpleNamespace(status_code=status, json=lambda: reply, text=json.dumps(reply))

    monkeypatch.setattr(summarize, "post_or_raise", post)
    return sent


def _last_attempt(monkeypatch):
    monkeypatch.setattr(activities.activity, "in_activity", lambda: True)
    monkeypatch.setattr(activities.activity, "info", lambda: SimpleNamespace(attempt=2))


def _stored_fact(board):
    board.run_commands("b1")
    [row] = [f for f in board.read_facts("b1") if f.intent_id == "intent-approval"]
    return row


def test_the_finding_is_the_report_and_never_the_text_of_the_model(board, turn, monkeypatch):
    """The model of the demo wrote the fact "placeholder". The finding is the report, so a
    report without that word can never be stored as it."""
    assert "placeholder" not in REPORT_TEXT
    _report(turn)
    _replies(monkeypatch, call_reply({"fact": "placeholder", "kind": "sourced",
                                      "open_questions": ["Who paid?"], "slug": "hedge-approval"}))
    assert activities.convert_explore_report(request()) == "fact"
    body = end_of(board)
    assert body["fact"]["text"] == REPORT_TEXT and body["fact"]["problems"] == []
    assert body["fact"]["open_questions"] == ["Who paid?"] and body["fact"]["kind"] == m.SOURCED
    assert [c["label"] for c in body["citations"]] == ["D1"]
    assert "fact" not in turn["written"][0], "the conversion row stores the small call only"
    row = _stored_fact(board)
    assert row.text == REPORT_TEXT and row.fact_id == "finding-hedge-approval"


@pytest.mark.parametrize("failure", ["malformed", "transport"])
def test_the_last_failed_attempt_stores_the_report_with_the_values_of_the_code(
        board, turn, monkeypatch, failure):
    _report(turn)
    _last_attempt(monkeypatch)
    if failure == "transport":
        _replies(monkeypatch, error=summarize.TransportFailure("read timed out"))
    else:
        _replies(monkeypatch, {"choices": [{"message": {"content": "no call"}}]})
    assert activities.convert_explore_report(request()) == "fact"
    fact = end_of(board)["fact"]
    assert end_of(board)["end"] == m.EXPLORE_CONCLUDED
    assert fact["text"] == REPORT_TEXT and fact["kind"] == m.SOURCED and fact["open_questions"] == []
    assert fact["slug"] == "approval-of-the-hedge"
    assert fact["problems"][0].startswith("the kind and the open questions came from the code, "
                                          "the model call failed: ")
    assert turn["written"][0]["model_error"]
    assert _stored_fact(board).fact_id == "finding-approval-of-hedge"


def test_a_refused_request_stores_the_report_at_once_and_an_uncited_report_is_inferred(
        board, turn, monkeypatch):
    _report(turn, "No minutes of 2001 name an approval.")
    sent = _replies(monkeypatch, {"error": "bad request"}, status=400)
    assert activities.convert_explore_report(request()) == "fact"
    assert len(sent) == 1
    fact = end_of(board)["fact"]
    assert fact["kind"] == m.INFERRED and "HTTP 400" in fact["problems"][0]
    assert fact["text"] == "No minutes of 2001 name an approval."


def test_a_transport_failure_before_the_last_attempt_is_raised(board, turn, monkeypatch):
    _report(turn)
    _replies(monkeypatch, error=summarize.TransportFailure("read timed out"))
    with pytest.raises(summarize.TransportFailure):
        activities.convert_explore_report(request())
    assert turn["written"] == []


def test_an_older_conversion_row_with_a_fact_field_gives_the_report_as_the_finding(
        board, turn, monkeypatch):
    _report(turn)
    turn["conversion"] = {"seq": 9, "args": {"fact": "placeholder", "kind": "inferred",
                                             "open_questions": ["Who paid?"], "slug": "temp-placeholder"}}
    sent = _replies(monkeypatch, call_reply({"kind": "sourced", "open_questions": []}))
    assert activities.convert_explore_report(request()) == "fact"
    assert sent == [], "a retry reuses the stored call"
    fact = end_of(board)["fact"]
    assert fact["text"] == REPORT_TEXT and fact["claimed_kind"] == m.INFERRED
    assert fact["open_questions"] == ["Who paid?"]


def test_a_french_board_names_french_in_the_small_request_and_takes_the_french_prefix(
        board, turn, monkeypatch):
    from dataclasses import replace as replace_row

    board.boards["b1"] = replace_row(board.boards["b1"], language="fr")
    _report(turn, "# Année de parution\n\nLe livre parut en 2001 [D1].")
    sent = _replies(monkeypatch, call_reply({"kind": "sourced", "open_questions": [],
                                             "slug": "Année-Parution"}))
    assert activities.convert_explore_report(request()) == "fact"
    assert "words in French" in sent[0]["messages"][0]["content"]
    assert _stored_fact(board).fact_id == "constat-année-parution"


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


def test_the_brief_of_a_web_only_board_names_the_web_and_no_collection():
    facts = [FactRow("b1", "background", m.ORIGIN, "The investigation searches the web only.")]
    intent = SimpleNamespace(intent_id="intent-x", from_facts=[], objective="Find X", brief="")
    board = SimpleNamespace(internet_tools=True, collections=[])
    text = render_brief(board, facts, [], [], intent, [], m.BASE_EXPLORE_STEPS, [], True)
    assert "- Search the web. Read the text behind each claim." in text
    assert "[W1]" in text and "[D1]" not in text
    assert "collection" not in text.lower()
    assert '"not found in the sources read"' in text and "not found in the documents" not in text
    assert "the searches and the sources examined" in text


def test_the_reason_prompt_of_a_web_only_board_names_the_web_and_no_collection():
    from tasks.P_board.prompts import render_reason

    rows = [FactRow("b1", "goal-01", m.GOAL, "Who runs the mill?"),
            FactRow("b1", "background", m.ORIGIN, "The investigation searches the web only.")]
    web_only = BoardRow("b1", OWNER, "t", "g", collections=[])
    folded = fold(web_only, [], rows)
    prompt = render_reason(web_only, folded, rows, [], stalled=False, internet=True)
    assert "research agents explore on the web." in prompt
    assert "Collections: none, the explores search the web only\n" in prompt
    assert "in the document collections" not in prompt
    both = BoardRow("b1", OWNER, "t", "g", collections=["enron"])
    prompt = render_reason(both, fold(both, [], rows), rows, [], stalled=False, internet=True)
    assert "explore in the document collections and on the web." in prompt
    assert "Collections: enron\n" in prompt


def test_the_conversion_names_sources_and_keeps_the_web_handles_of_a_web_only_finding():
    web = [c for c in CITATIONS if c["handle"].startswith("[W")]
    body = conversion.request_body("q-model", "Find the approval", "report.md",
                                   "The hedge was approved [W1].", web)
    system = body["messages"][0]["content"]
    schema = json.dumps(conversion.SUBMIT_FACT_SCHEMA)
    assert "cited sources state the finding" in system and "cited documents" not in system
    assert "cited sources state the finding" in schema and "cited documents" not in schema
    assert "the sources examined" in system
    args = conversion.parse_reply(call_reply({"kind": "sourced", "open_questions": []}))
    kind, rows, problems = conversion.resolve("The hedge was approved [W1].", args["kind"], web)
    assert kind == m.SOURCED and problems == []
    assert [r["label"] for r in rows] == ["W1"]
    assert rows[0]["path"] == "http://a.example/y" and rows[0]["quote"] == "the hedge was approved"
    assert rows[0]["collectionname"] == "" and rows[0]["file_hash"] == ""


# ------------------------------------------------------------- the explore turn


@pytest.fixture
def opening(board, monkeypatch):
    """The writers of `open_explore_turn`, with the collections that exist."""
    from database import clickhouse

    from database import user_settings

    state = {"sessions": [], "rows": [], "existing": ["enron"], "settings": {}}
    monkeypatch.setattr(clickhouse, "list_collections", lambda: list(state["existing"]))
    monkeypatch.setattr(user_settings, "read_user_settings", lambda owner: dict(state["settings"]))
    monkeypatch.setattr(activities, "_ensure_session",
                        lambda b, session, title, collections: state["sessions"].append(collections))
    monkeypatch.setattr(activities, "_existing_user_seq", lambda owner, session, uuid: None)
    monkeypatch.setattr(activities, "_next_seq", lambda owner, session: 3)
    monkeypatch.setattr(activities, "_write_turn_rows",
                        lambda owner, session, seq, text, uuid, usage="": state["rows"].append((text, usage)))
    return state


def _set_board(board, monkeypatch, collections, internet_tools, enabled):
    from dataclasses import replace as replace_row

    board.boards["b1"] = replace_row(board.boards["b1"], collections=collections,
                                     internet_tools=internet_tools)
    monkeypatch.setenv("HOOVER4_INTERNET_TOOLS_ENABLED", "true" if enabled else "false")


def test_a_web_only_board_starts_an_explore_with_no_collection(board, opening, monkeypatch):
    _set_board(board, monkeypatch, [], 1, True)
    opened = activities.open_explore_turn(activities.TurnRequest("b1", "intent-approval", 1))
    assert opened.skip_kind == "" and opened.run_input is not None
    assert opened.run_input.allowed_collections == [] and opened.run_input.internet_tools is True
    assert opening["sessions"] == [[]]
    text, usage = opening["rows"][0]
    assert "- Search the web." in text and "collection" not in text.lower()
    assert json.loads(usage)["task"]["allowed_sources"]["text"] == "collections: none; the web is allowed"


@pytest.mark.parametrize("internet_tools,enabled", [(0, True), (1, False)])
def test_a_web_only_board_fails_its_explore_when_the_internet_tools_are_off(
        board, opening, monkeypatch, internet_tools, enabled):
    _set_board(board, monkeypatch, [], internet_tools, enabled)
    opened = activities.open_explore_turn(activities.TurnRequest("b1", "intent-approval", 1))
    assert opened.skip_kind == m.EXPLORE_FAILED
    assert opened.skip_reason == "the board has no collections and the internet tools are off"
    assert opening["sessions"] == [] and opening["rows"] == []


def test_a_board_whose_collections_are_gone_fails_and_does_not_become_web_only(
        board, opening, monkeypatch):
    _set_board(board, monkeypatch, ["epstein"], 1, True)
    opened = activities.open_explore_turn(activities.TurnRequest("b1", "intent-approval", 1))
    assert opened.skip_kind == m.EXPLORE_FAILED
    assert opened.skip_reason == "none of the board collections exists"
    _set_board(board, monkeypatch, ["enron", "epstein"], 0, True)
    opened = activities.open_explore_turn(activities.TurnRequest("b1", "intent-approval", 1))
    assert opened.run_input.allowed_collections == ["enron"] and opened.run_input.internet_tools is False


@pytest.mark.parametrize("settings,stored,expected", [
    ({"agent.language": "fr", "ui.language": "de"}, "es", "es"),
    ({"ui.language": "de"}, "es", "es"),
    ({}, "es", "es"),
    ({}, "", "en"),
    ({"agent.language": "xx"}, "pt", "pt"),
    ({"agent.language": "fr", "ui.language": "de"}, "", "fr"),
    ({"ui.language": "de"}, "", "de"),
])
def test_an_explore_takes_the_board_language_then_the_owner_language(
        board, opening, monkeypatch, settings, stored, expected):
    from dataclasses import replace as replace_row

    _set_board(board, monkeypatch, ["enron"], 0, True)
    board.boards["b1"] = replace_row(board.boards["b1"], language=stored)
    opening["settings"] = settings
    opened = activities.open_explore_turn(activities.TurnRequest("b1", "intent-approval", 1))
    assert opened.run_input.language == expected


# ---------------------------------------------- counts through report and answer

BILLS = __import__("pathlib").Path(__file__).parent / "fixtures" / "monitored_bills_38.csv"
EXPECTED = {"GA": 13, "MO": 9, "TN": 7, "SC": 5, "NC": 2, "WV": 1, "KY": 1}


def _state_counts() -> dict:
    import csv
    from collections import Counter

    with BILLS.open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 38
    return dict(Counter(row["state"] for row in rows))


def _count_text(counts: dict) -> str:
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ", ".join(f"{state} {count}" for state, count in ordered)


def test_the_38_row_fixture_counts_survive_report_finding_and_answer():
    """The synthetic 38-row table gives the retained counts. The finding is the report, so
    it keeps them. An answer that keeps them raises no number problem."""
    from tasks.P_board.contracts import parse_reason

    counts = _state_counts()
    assert counts == EXPECTED and sum(counts.values()) == 38
    report = (f"# Monitored bills\n\nThe table holds 38 bills. By state: {_count_text(counts)} [D1]. "
              "The counts come from the state column of all 38 rows, with no filter.")
    finding = report
    reply = json.dumps({"answers": [{"goal": "goal-01", "from": ["fact-bills"],
                                     "statement": f"The 38 bills by state: {_count_text(counts)}."}]})
    payload = parse_reason(reply, {"fact-bills"}, {"fact-bills"}, [], idle=True, goal_ids=["goal-01"],
                           fact_texts={"fact-bills": finding})
    assert payload["problems"] == [] and payload["outcome"] == "review"
    assert payload["proposals"][0]["statement"].endswith("GA 13, MO 9, TN 7, SC 5, NC 2, KY 1, WV 1.")


def test_the_explore_task_keeps_the_focused_objective_apart_from_the_brief():
    from tasks.P_board.fold import Folded, Intent

    folded = Folded(board_id="b1", goal_ids=["goal-01"])
    folded.corrections = {"correction-minutes": {"goal": "goal-01", "event_id": "e"}}
    intent = Intent(intent_id="intent-leader-minutes", reason_no=3, from_facts=["background"],
                    objective="Find the delegation leader in the 2001 minutes",
                    brief="Search the minutes. " * 200, correction="correction-minutes")
    rows = [FactRow("b1", "goal-01", m.GOAL, "Who led the delegation?"),
            FactRow("b1", "correction-minutes", m.CORRECTION, "Use the 2001 minutes.")]
    task = activities.explore_task(intent, rows, folded, ["enron"], web=False)
    assert task["objective"] == {"text": intent.objective, "source": "intent:intent-leader-minutes"}
    assert task["corrections"] == [{"text": "Use the 2001 minutes.", "source": "correction:correction-minutes"}]
    assert task["goals"] == [{"text": "Who led the delegation?", "source": "goal-01"}]
    assert task["allowed_sources"]["text"] == "collections: enron; the web is not allowed"
    assert list(task)[0] == "objective"


def test_opening_retry_keeps_language_after_settings_change(board, opening, monkeypatch):
    _set_board(board, monkeypatch, ["enron"], 0, True)
    opening["settings"] = {"agent.language": "de"}
    req = activities.TurnRequest("b1", "intent-approval", 1)
    first = activities.open_explore_turn(req)
    saved = json.loads(opening["rows"][0][1])
    assert saved["language"] == "de"
    monkeypatch.setattr(activities, "_existing_user_seq", lambda *args: 3)
    monkeypatch.setattr(activities, "_opening_language", lambda *args: saved["language"])
    opening["settings"] = {"agent.language": "fr"}
    retried = activities.open_explore_turn(req)
    assert retried.run_input.language == first.run_input.language == "de"
    assert retried.run_input.turn_uuid == first.run_input.turn_uuid
    assert len(opening["rows"]) == 1
    monkeypatch.setattr(activities, "_existing_user_seq", lambda *args: None)
    assert activities.open_explore_turn(req).run_input.language == "fr"


def test_explore_brief_separates_rejected_claim_and_correction_reason():
    board = BoardRow("b1", "owner", "Board", [], "")
    facts = [FactRow("b1", "good", m.SOURCED, "Accepted claim [D1]."),
             FactRow("b1", "bad", m.SOURCED, "Wrong meeting date [D2].")]
    from types import SimpleNamespace
    intent = SimpleNamespace(intent_id="intent", from_facts=["bad"], objective="Verify the date", brief="")
    text = render_brief(board, facts, [], [], intent, ["enron"], 60,
                        rejected={"bad": "The correct date is 4 May."})
    known = text.split("<facts>")[1].split("</facts>")[0]
    assert "Accepted claim" in known and "Wrong meeting date" not in known
    correction = text.split("<rejected>")[1].split("</rejected>")[0]
    assert "Wrong meeting date" in correction and "The correct date is 4 May." in correction
    assert "[D2]" not in correction
