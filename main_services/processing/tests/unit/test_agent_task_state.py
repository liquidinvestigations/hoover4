"""Verify the task record of a chat turn: amendments, source rules, output groups and
omissions (`tasks.P_agent.control.task_state`), and the method advice that reads it.

The cases are the reproduced defects of the worker probes and the output table of the
change design. No test makes a model or classifier request.
"""

import asyncio
from dataclasses import replace

import pytest

from tasks.P_agent.control import facts as F
from tasks.P_agent.control import task_state as TS
from tasks.P_agent.control.facts import ResultFact
from tasks.P_agent.control.model import ControlEvent, PolicyContext, freeze, plain


def _state(*requests, base=None):
    """The record after each request, as turns 1, 2 and so on."""
    state = base
    for turn, request in enumerate(requests, start=1):
        state = TS.derive(request, turn, state)
    return state


def _groups(state):
    return [(g["noun"], g["names"], g["count"]) for g in TS.requirements(state)["groups"]]


# --------------------------------------------------------------------- output groups

OUTPUT_TABLE = [
    ("Write summary.md from input.csv", ["summary.md"], 1, [("file", ["summary.md"], 1)]),
    ("Do not write a report. Answer in chat.", [], 0, []),
    ("Write two memos. Create three reports.", [], 5, [("memo", [], 2), ("report", [], 3)]),
    ("Write two files, a.md and b.md.", ["a.md", "b.md"], 2, [("file", ["a.md", "b.md"], 2)]),
    ("Write the counts in a short report.", [], 1, [("report", [], 1)]),
    ("Write two memos and three reports.", [], 5, [("memo", [], 2), ("report", [], 3)]),
    ("Write a report on the rents and save it as rents.md.", ["rents.md"], 1, [("report", ["rents.md"], 1)]),
    ("Read budget.csv and write a summary to summary.md.", ["summary.md"], 1, [("file", ["summary.md"], 1)]),
    ("Do not run `write_file report.md`. Answer in chat.", [], 0, []),
    ("For example, write a report.", [], 0, []),
]


@pytest.mark.parametrize("request_text,names,count,groups", OUTPUT_TABLE)
def test_output_groups_separate_inputs_prohibitions_and_distinct_outputs(request_text, names, count, groups):
    state = _state(request_text)
    required = TS.requirements(state)
    assert required["names"] == names and required["count"] == count
    assert _groups(state) == groups
    assert required["file"] is bool(groups)


def test_an_unnamed_plural_or_a_bound_is_no_exact_count():
    for text in ("Create separate markdown files for each year.", "Write up to three reports.",
                 "Write several memos."):
        required = TS.requirements(_state(text))
        assert required["file"] and not required["exact"] and required["count"] == 0
        assert TS.delivery(_state(text), ["one.md"])["state"] == "unknown"


def test_a_conditional_output_loads_no_requirement():
    state = _state("If you find a payment, write a report.")
    assert TS.requirements(state)["file"] and TS.requirements(state)["groups"] == []
    assert TS.delivery(state, ["report.md"]) == {**TS.delivery(state, ["report.md"]), "state": "unknown",
                                                 "evidence": False}


def test_a_structured_deliverable_states_its_count_and_one_file_is_no_delivery():
    state = TS.from_structured({"objective": {"text": "Compare the bids.", "source": "intent"},
                                "deliverables": [{"text": "Three reports", "source": "intent"}]})
    assert _groups(state) == [("report", [], 3)]
    one = TS.delivery(state, ["first.md"])
    assert one["state"] == "incomplete" and one["evidence"] is False and one["missing_unnamed"] == 2
    assert TS.delivery(state, ["a.md", "b.md", "c.md"])["state"] == "complete"
    assert TS.delivery(state, ["a.md", "a.md", "a.md"])["state"] == "incomplete"


def test_a_continuation_keeps_the_objective_and_the_unfinished_outputs():
    first = _state("Write two memos. Create three reports.")
    follow = TS.derive("Continue.", 2, TS.record_delivery(first, [{"name": "memo-1.md", "version": 1}], 1))
    assert follow["request"] == {"turn": 2, "kind": "continuation"}
    assert follow["objective"]["turn"] == 1 and _groups(follow) == _groups(first)
    assert TS.text_task(follow)["amendments"] == [{"text": "Continue.", "source": "user", "turn": 2}]
    # The file of the earlier turn counts. Four more distinct files complete the five.
    assert TS.delivery(follow, ["a.md", "b.md", "c.md"])["state"] == "incomplete"
    assert TS.delivery(follow, ["a.md", "b.md", "c.md", "d.md"])["state"] == "complete"


def test_a_cancellation_amends_the_identified_group_or_stays_unresolved():
    first = _state("Write two memos. Create three reports.")
    skipped = TS.derive("Skip the second report.", 2, first)
    assert skipped["request"]["kind"] == "amendment" and skipped["interpretation_state"] == "resolved"
    assert _groups(skipped) == [("memo", [], 2), ("report", [], 2)]
    assert skipped["output_spec"]["groups"][1]["cancelled"][0]["item"] == 2
    named = TS.derive("Drop b.md.", 2, _state("Write three files: a.md, b.md and c.md."))
    assert _groups(named) == [("file", ["a.md", "c.md"], 2)]
    whole = TS.derive("Skip the memos.", 2, first)
    assert _groups(whole) == [("report", [], 3)]
    unknown = TS.derive("Skip the spreadsheet.", 2, first)
    assert unknown["interpretation_state"] == "unresolved"
    assert unknown["unresolved"][0]["text"] == "Skip the spreadsheet."
    assert _groups(unknown) == _groups(first)
    assert TS.delivery(unknown, [f"{n}.md" for n in range(5)])["state"] == "unknown"


def test_a_revision_of_one_file_uses_its_new_version():
    first = _state("Write report.md on the leases.")
    revised = TS.derive("Now save it as report.md.", 2, first)
    assert TS.requirements(revised)["names"] == ["report.md"]


# ------------------------------------------------------------------------- source rules


def test_a_permission_supersedes_the_conflicting_restrictions_and_continue_keeps_it():
    """The worker probe: the web permission of turn 2 replaced neither restriction, and
    `Continue.` lost the permission and the report."""
    first = _state("Use only the selected collections. Do not use the web.")
    changed = TS.derive("You may now use the web. Write a report.", 2, first)
    follow = TS.derive("Continue.", 3, changed)
    for state in (changed, follow):
        assert [(r["text"], r["status"], r["superseded_by"]) for r in state["source_rules"]] == [
            ("Use only the selected collections.", "superseded", 2),
            ("Do not use the web.", "superseded", 2),
            ("You may now use the web.", "active", None)]
        assert TS.source_scope(state)["web"] == "allowed"
        task = TS.text_task(state)
        assert "constraints" not in task
        assert task["allowed_sources"] == [{"text": "You may now use the web.", "source": "user", "turn": 2}]
        assert _groups(state) == [("report", [], 1)]
    assert follow["request"]["kind"] == "continuation"
    assert [a["turn"] for a in TS.text_task(follow)["amendments"]] == [2, 3]


def test_a_later_restriction_replaces_the_rule_of_its_subject():
    state = _state("Use only the enron collection. Who approved the loan?",
                   "Use only the testdata collection instead.")
    assert [(r["turn"], r["status"]) for r in state["source_rules"]] == [(1, "superseded"), (2, "active")]
    narrower = _state("Use only the selected collections.", "Do not read the e-mails.")
    assert [r["status"] for r in narrower["source_rules"]] == ["active", "active"]
    assert TS.source_scope(narrower)["web"] == "forbidden"
    revoked = _state("You can use the web.", "Do not use the web.")
    assert TS.source_scope(revoked)["web"] == "forbidden"


def test_a_new_objective_keeps_session_rules_and_drops_task_rules_and_outputs():
    state = _state("Search only the enron collection. Write two memos on the loans.",
                   "Do not use the web for this one.",
                   "Who signed the 2001 lease with Fortress Holdings?")
    assert state["request"]["kind"] == "new" and state["objective"]["turn"] == 3
    assert TS.requirements(state)["groups"] == [] and state["amendments"] == []
    assert [(r["turn"], r["status"]) for r in state["source_rules"]] == [(1, "active"), (2, "expired")]
    assert TS.text_task(state)["constraints"] == [{"text": "Search only the enron collection.",
                                                   "source": "user", "turn": 1}]


def test_a_short_follow_up_question_is_unresolved_and_keeps_the_earlier_objective():
    first = _state("Write two memos on the loans.")
    follow = TS.derive("And the second one?", 2, first)
    assert follow["interpretation_state"] == "unresolved"
    assert follow["objective"]["text"] == "Write two memos on the loans."
    assert TS.text_task(follow)["amendments"] == [{"text": "And the second one?", "source": "user", "turn": 2}]
    assert _groups(follow) == _groups(first)
    assert TS.delivery(follow, ["a.md", "b.md"]) == {**TS.delivery(follow, ["a.md", "b.md"]),
                                                    "state": "unknown", "evidence": False}


UNRECOGNIZED = [
    ("Write three reports, a.md, b.md and c.md, about the Enron trades.", "Make the second one shorter.",
     [("report", ["a.md", "b.md", "c.md"], 3)]),
    ("Write a report on the 2001 trades.", "Include the dates of each trade as well.", [("report", [], 1)]),
    ("Write a report on the 2001 trades.", "Also include the dates of each trade.", [("report", [], 1)]),
    ("Write report.md. Do not use the web.", "Please write it into notes.md instead.", [("report", ["report.md"], 1)]),
    ("Write a report on the 2001 trades.", "Use a table with one row per trade.", [("report", [], 1)]),
]


@pytest.mark.parametrize("first,second,groups", UNRECOGNIZED)
def test_an_unrecognized_message_keeps_the_objective_and_its_outputs_unresolved(first, second, groups):
    """The verification probe: an amendment that the rules do not recognize became a new
    objective and dropped the report group."""
    state = TS.derive(second, 2, TS.record_delivery(_state(first), [{"name": "a.md", "version": 1}], 1))
    assert (state["request"]["kind"], state["interpretation_state"]) == ("unresolved", "unresolved")
    assert state["objective"]["text"] == first and _groups(state) == groups
    task = TS.text_task(state)
    assert task["objective"]["turn"] == 1 and task["amendments"][-1]["text"] == second
    for delivered in ([], ["b.md", "c.md", "report.md", "notes.md"]):
        out = TS.delivery(state, delivered)
        assert (out["state"], out["evidence"]) == ("unknown", False)
    text, _ = F.task_text(task, 6000)
    assert second in text and "objective:" in text
    # A later continuation keeps the record unresolved.
    assert TS.derive("Continue.", 3, state)["interpretation_state"] == "unresolved"


@pytest.mark.parametrize("request_text", [
    "What is the capital of France?",
    "Who signed the 2001 lease with Fortress Holdings?",
    "Find the emails of Kenneth Lay about Raptor.",
    "New question: which banks financed the LJM partnerships?",
    "Write a memo on the California power contracts.",
])
def test_an_explicit_new_objective_starts_a_resolved_task_and_keeps_session_rules(request_text):
    first = _state("Use only the enron collection. Write three reports, a.md, b.md and c.md, about the trades.")
    state = TS.derive(request_text, 2, first)
    assert (state["request"]["kind"], state["interpretation_state"]) == ("new", "resolved")
    assert state["objective"]["text"] == request_text
    assert [g["noun"] for g in TS.requirements(state)["groups"]] == (["memo"] if "memo" in request_text else [])
    assert TS.text_task(state)["constraints"][0]["text"] == "Use only the enron collection."


def test_a_new_objective_after_an_unresolved_message_is_resolved_again():
    state = TS.derive("Make it shorter.", 2, _state("Write a report on the 2001 trades."))
    after = TS.derive("What is the capital of France?", 3, state)
    assert after["interpretation_state"] == "resolved" and after["unresolved"] == []
    assert TS.delivery(after, [])["state"] == "none"


@pytest.mark.parametrize("request_text", [
    "Write a report for each of the three companies.",
    "Write one memo per customer.",
    "Write a short report on each document in the folder.",
    "Create a file for every person named in the emails.",
])
def test_a_singular_count_for_each_item_is_no_exact_count(request_text):
    state = _state(request_text)
    required = TS.requirements(state)
    assert required["file"] and not required["exact"] and required["count"] == 0
    out = TS.delivery(state, ["one.md"])
    assert (out["state"], out["evidence"]) == ("unknown", False)


def test_a_numeral_count_with_each_stays_exact():
    assert _groups(_state("Write three reports, one for each company.")) == [("report", [], 3)]
    assert _groups(_state("Write a report for Alice and a report for Bob.")) == [("report", [], 1), ("report", [], 1)]
    structured = TS.from_structured({"objective": {"text": "x", "source": "intent"},
                                     "deliverables": [{"text": "A report for each company", "source": "intent"}]})
    assert _groups(structured) == [("report", [], None)]


def test_long_tasks_keep_every_rule_and_name_their_omissions():
    rules = [f"Do not use the web source number {n}." for n in range(12)]
    long = "Use only the archive folder " + "named carefully " * 40 + "for this work."
    state = _state(" ".join(rules), long)
    texts = TS.text_task(state)["constraints"]
    assert len(texts) == 13 and any(t["text"] == long for t in texts)
    assert state["omissions"] == []
    huge = _state("Find the leases. " + "x" * (TS.MAX_OBJECTIVE_CHARS + 10))
    assert huge["omissions"][0]["field"] == "objective" and huge["omissions"][0]["count"] == 27
    assert not TS.complete_interpretation(huge)
    assert TS.delivery(huge, [])["state"] == "unknown"


def test_the_text_task_projection_names_the_characters_it_omits():
    state = _state("Use only the testdata collection. " + "Find the lease. " * 400)
    text, omitted = F.task_text(TS.text_task(state), 600)
    assert omitted > 0 and f"[{omitted} characters of the task are omitted here]" in text
    assert text.startswith("objective: Use only the testdata collection.")


def test_reconstruction_of_legacy_turns_and_its_incomplete_state():
    legacy = [{"request": "Use only the enron collection. Write two memos on the loans.", "turn": 1,
               "delivered": [{"name": "loan-1.md", "version": 1}]},
              {"request": "Continue.", "turn": 2}]
    state = TS.derive("Continue.", 3, TS.reconstruct(legacy, complete=True))
    assert state["objective"]["turn"] == 1 and TS.complete_interpretation(state)
    assert TS.delivery(state, ["loan-2.md"])["state"] == "complete"
    partial = TS.derive("Continue.", 3, TS.reconstruct(legacy[1:], complete=False))
    assert partial["reconstruction"]["complete"] is False
    assert TS.delivery(partial, ["a.md", "b.md"])["state"] == "unknown"
    stored = {"state": _state("Write a memo on the loans."), "delivered": [{"name": "memo.md", "version": 2}]}
    based = TS.derive("Continue.", 2, TS.reconstruct([stored], complete=False))
    assert based["reconstruction"]["source"] == "state" and TS.delivery(based, [])["state"] == "complete"


def test_the_legacy_chat_task_adapter_keeps_its_text_fields():
    first = F.chat_task("Search only the enron collection. Who approved the talking points?", 1, [])
    assert first == {"objective": {"text": "Search only the enron collection. Who approved the talking points?",
                                   "source": "user", "turn": 1},
                     "constraints": [{"text": "Search only the enron collection.", "source": "user", "turn": 1}]}
    record = TS.from_structured({"objective": {"text": "Continue.", "source": "user", "turn": 2}}, legacy=True)
    assert record["reconstruction"]["source"] == "legacy" and not TS.complete_interpretation(record)


def test_a_board_task_stays_authoritative_for_its_focused_objective():
    task = {"objective": {"text": "Name the leader of the delegation.", "source": "intent"},
            "deliverables": [{"text": "A report file leader.md", "source": "intent"}],
            "brief": {"text": "Write two memos and three reports for the board.", "source": "intent"}}
    state = TS.from_structured(task)
    assert state["objective"]["text"] == "Name the leader of the delegation."
    assert _groups(state) == [("report", ["leader.md"], 1)]
    assert TS.complete_interpretation(state)


# ------------------------------------------------------------------------ method advice


def _fact(name, status="ok", args=None, **fields):
    return ResultFact(fields.pop("call_id", "c"), name, 1, 2, fields.pop("origin", "model"), status,
                      args or {}, **fields)


def _context(request, results=(), tools=("search_collections", "search_passages", "web_search", "read_page"),
             state=None, choice=None, capabilities=("documents", "web")):
    state = state if state is not None else _state(request)
    turn = {"progress": {"level": 0, "units": 2}}
    if choice:
        turn["preparation"] = {"sources": {"choice": choice}}
    return PolicyContext(run_id="r", thread_id="r", profile="full_research:web", definition_revision="t",
                         request=request, callable_tools=frozenset(tools), listed_skills=freeze({}),
                         visible_skills=frozenset(), results=tuple(results), batch=tuple(results[-1:]),
                         turn=freeze(turn), counters=freeze({"model_steps": 2}),
                         capabilities=frozenset(capabilities), collections=("testdata",),
                         task=freeze(TS.text_task(state)), task_state=freeze(state))


class _Signals:
    def __init__(self, score):
        self.score = score
        self.states = []

    async def ask(self, state, questions, instructions=""):
        from tasks.P_agent.control.model import ClassifierResult
        self.states.append(state)
        return ClassifierResult("ok", freeze({q: {"noul": self.score} for q in questions}))


def _level_note(context, parameters):
    from tasks.P_agent.control.handlers.progress import Handler
    result = asyncio.run(Handler().evaluate(ControlEvent("batch", "tool_batch_completed", 1, "model"),
                                            context, parameters, _Signals(0.0)))
    return next(a.arguments["text"] for a in result.actions if a.kind == "append_note")


WEB_PDF = "Read https://example.org/report.pdf and say whether it names Ortwin Pell."


@pytest.mark.parametrize("signals", [False, True])
def test_a_web_pdf_task_gets_no_collection_step(signals):
    """The captured failure: a turn that read one web PDF got collection-search steps."""
    page = _fact("read_page", args={"urls": ["https://example.org/report.pdf"]}, continuation=True,
                 reads=(("https://example.org/report.pdf", "ok"),))
    stalled = _fact("read_page", args={"urls": ["https://example.org/report.pdf"], "offset": 9000},
                    status="error", call_id="c2")
    note = _level_note(_context(WEB_PDF, (page, stalled)), {"signals": signals})
    assert "search_collections" not in note and "search_passages" not in note
    assert "find" in note


def test_a_collection_only_task_gets_no_web_step():
    request = "Use only the testdata collection. Who approved the transfer?"
    search = _fact("search_collections", args={"query": "transfer"}, item_count=0)
    note = _level_note(_context(request, (search,), choice="both"), {"signals": False})
    assert "web" not in note.split("Search steps still available:")[1].lower()
    assert "search_collections" in note


def test_a_mixed_task_gets_the_steps_of_both_methods():
    request = "Compare the stored contract with the public filing on the web."
    results = (_fact("search_collections", args={"query": "contract"}, item_count=0),
               _fact("read_page", args={"urls": ["https://example.org"]}, status="error", call_id="c2"))
    note = _level_note(_context(request, results), {"signals": False})
    assert "search_passages" in note and "web_search" in note


def test_a_turn_without_method_evidence_gets_no_step_list():
    note = _level_note(_context("What is 17 times 3?", (_fact("update_plan"),)), {"signals": False})
    assert "Search steps still available" not in note and "search steps are complete" not in note


def test_a_forbidden_web_gets_no_web_step_even_after_a_web_search():
    request = "Do not use the web. Who signed the lease?"
    results = (_fact("web_search", args={"queries": ["lease"]}, item_count=0),)
    note = _level_note(_context(request, results), {"signals": False})
    steps = note.split("Search steps still available:")[1]
    assert "web" not in steps.lower() and "search_collections" in steps


@pytest.mark.parametrize("batch,expected", [
    ([_fact("table_page", status="refused", error_code="invalid_argument")], ["call_arguments"]),
    ([_fact("read_page", status="error", args={"urls": ["https://a.example"]})], ["web_research"]),
    ([_fact("read_page", args={"urls": ["https://a.example"]}, reads=(("https://a.example", "ok"),))], []),
])
def test_result_evidence_selects_recovery_skills_without_a_classifier(batch, expected):
    from tasks.P_agent.control.handlers.result_skills import Handler
    context = replace(_context(WEB_PDF, tuple(batch)), listed_skills=freeze({"web_research": {}, "call_arguments": {}}))
    result = asyncio.run(Handler().evaluate(ControlEvent("batch", "tool_batch_completed", 1, "model"), context,
                                            {"events": {"call_arguments": "argument_error"}}, object()))
    assert sorted(a.target_id for a in result.actions) == expected


class _Prepared(_Signals):
    """A preparation classifier that answers the source choice and every other question."""

    def __init__(self):
        super().__init__(0.0)

    async def ask(self, state, questions, instructions=""):
        from tasks.P_agent.control.model import ClassifierResult
        self.states.append(state)
        answers = {q: {"noul": 0.0} for q in questions}
        if "sources=" in questions:
            answers["sources="] = {"choice": "documents", "probabilities": {"documents": 1.0}}
        return ClassifierResult("ok", freeze(answers))


@pytest.mark.parametrize("classifier", [False, True])
def test_the_report_skill_follows_the_task_record_in_both_definitions(classifier):
    from tasks.P_agent.control.handlers.preparation import Handler

    first = _state("Use only the testdata collection. Who approved the transfer?")
    amended = TS.derive("Now write the counts in a short report.", 2, first)
    context = replace(_context("Now write the counts in a short report.", state=amended),
                      listed_skills=freeze({"report": {}}))
    services = _Prepared()
    result = asyncio.run(Handler().evaluate(ControlEvent("start", "turn_started", 0, "runtime"), context,
                                            {"classifier": classifier, "names": False}, services))
    assert "report" in [a.target_id for a in result.actions if a.kind == "load_skill"]
    if classifier:
        shown = services.states[0]["request"]
        assert shown.startswith("objective: Use only the testdata collection. Who approved the transfer?")
        assert "amendments:\n- Now write the counts in a short report." in shown
    inputs = replace(context, task_state=freeze(_state("Write summary.md from input.csv")))
    assert [a.target_id for a in asyncio.run(Handler().evaluate(
        ControlEvent("start", "turn_started", 0, "runtime"), inputs, {"classifier": False}, object())).actions] == ["report"]
    none = replace(context, task_state=freeze(_state("Do not write a report. Answer in chat.")))
    assert asyncio.run(Handler().evaluate(ControlEvent("start", "turn_started", 0, "runtime"), none,
                                          {"classifier": False}, object())).actions == ()


def test_the_progress_input_shows_the_amended_task_without_superseded_rules():
    from tasks.P_agent.control.handlers.progress import Handler
    state = TS.derive("Continue.", 3, TS.derive("You may now use the web. Write a report.", 2,
                                               _state("Use only the selected collections. Do not use the web.")))
    signals = _Signals(0.0)
    search = _fact("web_search", args={"queries": ["x"]}, item_count=0)
    asyncio.run(Handler().evaluate(ControlEvent("batch", "tool_batch_completed", 1, "model"),
                                   _context("Continue.", (search,), state=state), {}, signals))
    shown = signals.states[0]["request"]
    assert "Do not use the web." not in shown and "allowed_sources:\n- You may now use the web." in shown
    assert "amendments:\n- You may now use the web. Write a report.\n- Continue." in shown


def test_one_written_file_is_no_evidence_for_a_three_report_deliverable():
    from tasks.P_agent.control.handlers.progress import COMPLETION_ADVICE, Handler, delivery
    state = TS.from_structured({"objective": {"text": "Compare the bids.", "source": "intent"},
                                "deliverables": [{"text": "Three reports", "source": "intent"}]})
    one = _fact("write_file", file_version=("first.md", 1, True), call_id="w1")
    search = _fact("search_collections", args={"query": "x"}, item_count=0)
    assert delivery(state, [one])["state"] == "incomplete"
    unchanged = _fact("write_file", file_version=("first.md", 1, False), call_id="w2")
    assert delivery(state, [one, unchanged])["delivered"] == ["first.md"]
    context = replace(_context("Compare the bids.", (one, search), state=state))
    result = asyncio.run(Handler().evaluate(ControlEvent("batch", "tool_batch_completed", 1, "model"),
                                            context, {}, _Signals(0.95)))
    ledger = plain(result.facts)
    assert ledger["delivery"]["state"] == "incomplete" and ledger["delivery_evidence"] is False
    assert all(COMPLETION_ADVICE not in a.arguments.get("text", "") for a in result.actions)
