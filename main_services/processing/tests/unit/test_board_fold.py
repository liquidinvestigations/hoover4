"""The board fold, the planner, the reason and explore contracts, and the prompts.

Every function under test is pure, so the rows are built here and no service runs.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from database.boards import BoardRow, CitationRow, EventRow, FactRow
from tasks.P_board import model as m
from tasks.P_board.contracts import labels_of, parse_explore_block, parse_reason
from tasks.P_board.fold import fold, plan, reason_due
from tasks.P_board.prompts import call_guidance, fact_block, strip_labels

T0 = datetime(2026, 10, 14, 8, 0, 0)


def board(board_id="b1", **kw) -> BoardRow:
    values = dict(owner="admin", title="t", goal="g", collections=["enron"], max_explores=12,
                  max_parallel=1, explore_step_budget=40, created_at=T0)
    values.update(kw)
    return BoardRow(board_id=board_id, **values)


class Log:
    """Events in write order, one second apart."""

    def __init__(self, board_id="b1"):
        self.board_id = board_id
        self.events: list[EventRow] = []

    def add(self, event_type, subject="", event_id=None, **payload):
        at = T0 + timedelta(seconds=len(self.events))
        self.events.append(EventRow(self.board_id, event_id or f"{event_type}:{subject}:{len(self.events)}",
                                    event_type, "test", subject, payload, at))
        return self

    def reason(self, r, outcome="intents", n=2, **extra):
        self.add(m.REASON_STARTED, str(r))
        items = [{"from": ["origin"], "objective": f"objective {r}.{k}", "brief": ""} for k in range(1, n + 1)]
        payload = {"outcome": outcome, "situation": extra.pop("situation", {"facts": 0, "hints": 0, "rejected": 0})}
        if outcome == "intents":
            payload["intents"] = items
        payload.update(extra)
        return self.add(m.REASON_RESULT, str(r), **payload)


def facts(*items) -> list[FactRow]:
    rows = [FactRow("b1", "origin", m.ORIGIN, "o"), FactRow("b1", "goal", m.GOAL, "g")]
    rows += [FactRow("b1", fid, kind, "text") for fid, kind in items]
    return rows


def test_a_new_board_is_due_for_its_first_reason():
    f = fold(board(), Log().add(m.BOARD_CREATED).events, facts())
    assert f.status == m.ACTIVE
    assert reason_due(f, in_flight=False)
    assert not reason_due(f, in_flight=True)


def test_a_reason_declares_intents_with_deterministic_ids():
    f = fold(board(), Log().add(m.BOARD_CREATED).reason(1, n=3).events, facts())
    assert sorted(f.intents) == ["i1.1", "i1.2", "i1.3"]
    assert all(i.state == m.OPEN for i in f.intents.values())
    assert not reason_due(f, in_flight=False), "open intents wait before another reason"


def test_the_planner_respects_the_global_cap_across_boards():
    boards = [board("a"), board("b")]
    logs = {b.board_id: Log(b.board_id).add(m.BOARD_CREATED).reason(1) for b in boards}
    folded = {b.board_id: fold(b, logs[b.board_id].events, facts()) for b in boards}
    actions = plan(boards, folded, set(), cap=1)
    assert len(actions.explores) + len(actions.reasons) == 1
    actions = plan(boards, folded, set(), cap=3)
    assert len(actions.explores) == 2, "one explore per board, by max_parallel"


def test_a_free_slot_goes_to_the_board_with_the_least_work_in_flight():
    busy, new = board("a", created_at=T0, max_parallel=2), board("b", created_at=T0 + timedelta(hours=1), max_parallel=2)
    log = Log("a").add(m.BOARD_CREATED).reason(1, n=3)
    log.add(m.EXPLORE_STARTED, "i1.1", attempt=1)
    folded = {"a": fold(busy, log.events, facts()), "b": fold(new, Log("b").add(m.BOARD_CREATED).events, facts())}
    actions = plan([busy, new], folded, set(), cap=2)
    assert [r.board_id for r in actions.reasons] == ["b"], "the idle board gets its first reason"
    assert [e.board_id for e in actions.explores] == []
    # Both boards idle: the board with open intents does not win over a board that waits for
    # its first reason.
    log = Log("a").add(m.BOARD_CREATED).reason(1, n=1)
    log.add(m.EXPLORE_STARTED, "i1.1", attempt=1)
    log.add(m.EXPLORE_CONCLUDED, "i1.1", attempt=1, fact_id="f1.1", kind=m.SOURCED)
    log.reason(2, n=2, situation={"facts": 1, "hints": 0, "rejected": 0})
    folded["a"] = fold(busy, log.events, facts(("f1.1", m.SOURCED)))
    actions = plan([busy, new], folded, set(), cap=1)
    assert [r.board_id for r in actions.reasons] == ["b"] and not actions.explores


def test_a_reason_in_flight_takes_a_slot():
    b = board()
    f = fold(b, Log().add(m.BOARD_CREATED).reason(1).events, facts())
    assert plan([b], {"b1": f}, {"b1"}, cap=1).explores == []


def test_an_explore_start_counts_and_a_cancel_refunds():
    log = Log().add(m.BOARD_CREATED).reason(1)
    log.add(m.EXPLORE_STARTED, "i1.1", attempt=1)
    f = fold(board(), log.events, facts())
    assert f.intents["i1.1"].state == m.RUNNING and f.explores_used == 1
    log.add(m.EXPLORE_CANCELLED, "i1.1", attempt=1)
    f = fold(board(), log.events, facts())
    assert f.intents["i1.1"].state == m.OPEN
    assert f.explores_used == 0 and f.intents["i1.1"].attempts == 0


def test_concluded_wins_over_a_cancel_of_the_same_attempt():
    log = Log().add(m.BOARD_CREATED).reason(1)
    log.add(m.EXPLORE_STARTED, "i1.1", attempt=1)
    log.add(m.EXPLORE_CANCELLED, "i1.1", attempt=1)
    log.add(m.EXPLORE_CONCLUDED, "i1.1", attempt=1, fact_id="f1.1", kind=m.SOURCED)
    f = fold(board(), log.events, facts(("f1.1", m.SOURCED)))
    assert f.intents["i1.1"].state == m.CONCLUDED
    assert f.explores_used == 1


def test_two_failures_end_an_intent():
    log = Log().add(m.BOARD_CREATED).reason(1, n=1)
    for attempt in (1, 2):
        log.add(m.EXPLORE_STARTED, "i1.1", attempt=attempt)
        log.add(m.EXPLORE_FAILED, "i1.1", attempt=attempt, error="boom")
    f = fold(board(), log.events, facts())
    assert f.intents["i1.1"].state == m.FAILED
    assert f.stall_count == 2


def test_a_new_fact_makes_reason_due_once_no_intent_is_open():
    log = Log().add(m.BOARD_CREATED).reason(1, n=1)
    log.add(m.EXPLORE_STARTED, "i1.1", attempt=1)
    log.add(m.EXPLORE_CONCLUDED, "i1.1", attempt=1, fact_id="f1.1", kind=m.SOURCED)
    f = fold(board(), log.events, facts(("f1.1", m.SOURCED)))
    assert reason_due(f, in_flight=False)


def test_an_empty_reason_while_explores_run_moves_the_checkpoint():
    log = Log().add(m.BOARD_CREATED).reason(1, n=1)
    log.add(m.EXPLORE_STARTED, "i1.1", attempt=1)
    log.add(m.HINT_ADDED, "h1", text="look at 2001")
    log.reason(2, outcome="noop", idle=False, situation={"facts": 0, "hints": 1, "rejected": 0})
    f = fold(board(), log.events, facts())
    assert not reason_due(f, in_flight=False), "a valid empty result must not loop"


def test_invalid_reasons_keep_the_board_due_then_send_it_to_review():
    b = board()
    log = Log().add(m.BOARD_CREATED)
    for r in range(1, m.INVALID_REASON_LIMIT + 1):
        f = fold(b, log.events, facts())
        assert reason_due(f, in_flight=False)
        log.reason(r, outcome="invalid")
    f = fold(b, log.events, facts())
    actions = plan([b], {"b1": f}, set(), cap=1)
    assert actions.reviews == [("b1", m.STALLED_INVALID)]
    assert f.stall_causes == {m.CAUSE_INVALID: m.INVALID_REASON_LIMIT}


@pytest.mark.parametrize("outcomes, reason", [
    ([m.MODEL_FAILURE] * 3, m.MODEL_UNAVAILABLE),
    (["noop", "noop", m.MODEL_FAILURE], m.STALLED_NO_DIRECTION),
    (["invalid", m.MODEL_FAILURE, "noop"], m.STALLED_NO_DIRECTION),
    (["noop", "invalid", "invalid"], m.STALLED_INVALID),
])
def test_the_stall_review_names_the_cause_with_the_most_results(outcomes, reason):
    b = board()
    log = Log().add(m.BOARD_CREATED)
    for r, outcome in enumerate(outcomes, start=1):
        log.reason(r, outcome=outcome, idle=True)
    f = fold(b, log.events, facts())
    assert f.invalid_reasons == 3
    assert plan([b], {"b1": f}, set(), cap=1).reviews == [("b1", reason)]


def test_progress_clears_the_stall_causes():
    log = Log().add(m.BOARD_CREATED).reason(1, outcome=m.MODEL_FAILURE).reason(2, outcome="invalid")
    log.reason(3, n=1)
    f = fold(board(), log.events, facts())
    assert (f.invalid_reasons, f.stall_causes, f.last_stall_cause) == (0, {}, "")


def test_a_model_failure_keeps_the_board_due_and_is_not_invalid():
    log = Log().add(m.BOARD_CREATED).reason(1, outcome=m.MODEL_FAILURE, error="ReadTimeout")
    f = fold(board(), log.events, facts())
    assert reason_due(f, in_flight=False)
    assert f.stall_causes == {m.CAUSE_MODEL_FAILURE: 1}


def test_the_stall_statement_names_each_cause_and_count():
    from tasks.P_board.commands import stall_statement

    assert stall_statement({m.CAUSE_MODEL_FAILURE: 2, m.CAUSE_INVALID: 1}) == (
        "The last 3 assessments made no progress: 2 got no answer from the model, and 1 held "
        "no valid JSON.")
    assert stall_statement({m.CAUSE_NO_DIRECTION: 1}) == (
        "The last assessment made no progress: 1 gave no new direction.")


def test_a_pause_cancels_running_explores_and_a_resume_restores_work():
    b = board()
    log = Log().add(m.BOARD_CREATED).reason(1)
    log.add(m.EXPLORE_STARTED, "i1.1", attempt=1)
    log.add(m.PAUSE_REQUESTED, "p")
    f = fold(b, log.events, facts())
    assert f.status == m.PAUSED
    assert plan([b], {"b1": f}, set(), cap=1).cancels == [("b1", "i1.1")]
    log.add(m.EXPLORE_CANCELLED, "i1.1", attempt=1)
    log.add(m.RESUME_REQUESTED, "r")
    f = fold(b, log.events, facts())
    assert f.status == m.ACTIVE and f.intents["i1.1"].state == m.OPEN


def test_review_needs_a_person_to_complete():
    log = Log().add(m.BOARD_CREATED).reason(1, outcome="review", review={"from": ["f1"], "statement": "s"})
    f = fold(board(), log.events, facts())
    assert f.status == m.REVIEW
    log.add(m.REVIEW_ACCEPTED, "x")
    assert fold(board(), log.events, facts()).status == m.COMPLETED


def _spent(log, reasons):
    """`reasons` reasons of one intent each, every explore concluded inferred."""
    for r in range(1, reasons + 1):
        log.reason(r, n=1)
        log.add(m.EXPLORE_STARTED, f"i{r}.1", attempt=1)
        log.add(m.EXPLORE_CONCLUDED, f"i{r}.1", attempt=1, fact_id=f"f{r}.1", kind=m.INFERRED)
    return log


def test_the_budget_runs_one_final_assessment_then_sends_the_board_to_review():
    b = board(max_explores=100)
    budget = m.BASE_EXPLORES
    log = _spent(Log().add(m.BOARD_CREATED), budget).reason(99, n=1)
    rows = facts(("f1.1", m.INFERRED))
    f = fold(b, log.events, rows)
    assert f.max_explores == budget, "the board row's budget is not read"
    actions = plan([b], {"b1": f}, set(), cap=1)
    [final] = actions.reasons
    assert (final.final, final.assessed_budget, final.assessment_id) == (True, budget, f"final-{budget}")
    assert actions.explores == [] and actions.reviews == []
    log.add(m.REASON_STARTED, "100", final=True, assessed_budget=budget, assessment_id=f"final-{budget}")
    f = fold(b, log.events, rows)
    assert not reason_due(f, in_flight=False), "no reason while the final assessment runs"
    assert plan([b], {"b1": f}, {"b1"}, cap=1) == plan([], {}, set(), cap=1)
    assert plan([b], {"b1": f}, set(), cap=1).final_failures == [("b1", budget)]
    log.reason(100, outcome="noop", n=0, final=True, assessed_budget=budget)
    f = fold(b, log.events, rows)
    assert f.final_ops[str(budget)]["state"] == "terminal" and f.status == m.ACTIVE
    actions = plan([b], {"b1": f}, set(), cap=1)
    assert actions.reviews == [("b1", "budget")] and not actions.reasons
    log.add(m.REVIEW_PROPOSED, "budget", reason="budget", statement="The explore budget is used.")
    f = fold(b, log.events, rows)
    assert (f.status, f.review_reason, f.decision_id) == (m.REVIEW, "budget", log.events[-1].event_id)


def test_corrections_and_hints_grow_the_budget_up_to_the_caps():
    log = Log().add(m.BOARD_CREATED)
    f = fold(board(), log.events, facts())
    assert (f.max_explores, f.explore_steps) == (m.BASE_EXPLORES, m.BASE_EXPLORE_STEPS)
    log.add(m.HINT_ADDED, text="h")
    log.add(m.FACT_REJECTED, "f1.1", reason="wrong person")
    f = fold(board(), log.events, facts())
    assert f.max_explores == m.BASE_EXPLORES + 2 * m.ACTION_EXPLORES
    assert f.grants == {log.events[-2].event_id: m.ACTION_EXPLORES, log.events[-1].event_id: m.ACTION_EXPLORES}
    assert f.explore_steps == m.BASE_EXPLORE_STEPS + m.HINT_EXPLORE_STEPS + m.CORRECTION_EXPLORE_STEPS
    for k in range(80):
        log.add(m.FACT_REJECTED, f"f9.{k}", reason="r")
    f = fold(board(), log.events, facts())
    assert (f.max_explores, f.explore_steps) == (m.EXPLORE_LIMIT, m.MAX_EXPLORE_STEPS)
    assert f.grants[log.events[-1].event_id] == 0, "a grant above the limit is 0"


def test_a_question_waits_for_a_hint():
    log = Log().add(m.BOARD_CREATED).reason(1, n=1)
    log.add(m.EXPLORE_STARTED, "i1.1", attempt=1)
    log.add(m.EXPLORE_QUESTION, "i1.1", attempt=1, question="Which Kaminski?")
    f = fold(board(), log.events, facts())
    assert f.intents["i1.1"].state == m.QUESTION
    log.add(m.HINT_ADDED, "h", text="Vince Kaminski")
    assert fold(board(), log.events, facts()).intents["i1.1"].state == m.OPEN


def test_a_tombstoned_board_is_dropped():
    assert fold(board(is_deleted=1), Log().add(m.BOARD_CREATED).events, facts()).status == m.DROPPED


# ---------------------------------------------------------------------------- contracts


def test_parse_reason_accepts_a_fenced_reply_and_drops_repeats():
    reply = "```json\n" + json.dumps({"intents": [
        {"from": ["origin"], "objective": "Find emails that mention Raptor and LJM"},
        {"from": ["origin"], "objective": "Search emails mentioning Raptor and LJM together"},
        {"from": ["f9"], "objective": "Unknown source"},
    ]}) + "\n```"
    payload = parse_reason(reply, {"origin"}, set(), [], idle=True)
    assert payload["outcome"] == "intents"
    assert len(payload["intents"]) == 1
    assert any("repeat" in p for p in payload["problems"])
    assert any("unknown" in p for p in payload["problems"])


def test_parse_reason_refuses_review_from_an_inferred_fact():
    payload = parse_reason('{"review": {"from": ["f1.1"], "statement": "s"}}', {"origin", "f1.1"},
                           set(), [], idle=True)
    assert payload["outcome"] == "noop"
    assert payload["idle"] is True


def test_parse_reason_accepts_a_review_from_sourced_facts():
    payload = parse_reason('{"review": {"from": ["f1.1"], "statement": "s"}}', {"f1.1"}, {"f1.1"},
                           [], idle=False)
    assert payload["outcome"] == "review"


def test_a_review_names_each_goal():
    goals = ["goal", "goal-2"]
    one = '{"review": {"goals": [{"goal": "goal", "from": ["f1.1"], "statement": "a"}]}}'
    payload = parse_reason(one, {"f1.1", "f2.1"}, {"f1.1"}, [], True, goals, {"f2.1"})
    assert payload["outcome"] == "partial", "an answer for one goal of two is progress"
    assert [a["goal"] for a in payload["proposals"]] == ["goal"]
    both = json.dumps({"review": {"goals": [
        {"goal": "goal", "from": ["f1.1"], "statement": "a"},
        {"goal": "goal-2", "from": ["f2.1"], "statement": "not in the documents"}]}})
    payload = parse_reason(both, {"f1.1", "f2.1"}, {"f1.1"}, [], True, goals, {"f2.1"})
    assert payload["outcome"] == "review"
    assert [(a["goal"], a["answer_kind"]) for a in payload["proposals"]] == [
        ("goal", m.SUPPORTED), ("goal-2", m.NOT_ESTABLISHED)]
    absent = payload["proposals"][1]
    assert (absent["statement"], absent["commentary"]) == (m.NOT_ESTABLISHED_STATEMENT, "not in the documents")
    only_absent = json.dumps({"review": {"goals": [
        {"goal": "goal", "from": ["f2.1"], "statement": "a"},
        {"goal": "goal-2", "from": ["f2.1"], "statement": "b"}]}})
    out = parse_reason(only_absent, {"f2.1"}, set(), [], True, goals, {"f2.1"})
    assert out["outcome"] == "review"
    assert {a["answer_kind"] for a in out["proposals"]} == {m.NOT_ESTABLISHED}
    inferred = json.dumps({"answers": [{"goal": "goal", "from": ["f3.1"], "statement": "a"}]})
    out = parse_reason(inferred, {"f3.1"}, set(), [], True, goals)
    assert out["outcome"] == "noop" and "proposals" not in out, "an inferred fact supports no answer"


def test_an_inferred_fact_is_dropped_from_an_answer_that_names_a_sourced_fact():
    reply = json.dumps({"answers": [
        {"goal": "goal-01", "from": ["fact-a", "fact-guess", "origin", "fact-gone"], "statement": "s"}]})
    out = parse_reason(reply, {"fact-a", "fact-guess", "origin"}, {"fact-a"}, [], True, ["goal-01"])
    assert out["outcome"] == "review"
    [answer] = out["proposals"]
    assert (answer["from"], answer["answer_kind"]) == (["fact-a"], m.SUPPORTED)
    assert out["problems"] == [
        "dropped ['fact-gone'] from the answer of goal-01: not a fact",
        "dropped ['fact-guess', 'origin'] from the answer of goal-01: only sourced and "
        "not_found facts support an answer"]
    not_found = json.dumps({"answers": [{"goal": "goal-01", "from": ["fact-guess", "fact-none"],
                                         "statement": "s"}]})
    out = parse_reason(not_found, {"fact-guess", "fact-none"}, set(), [], True, ["goal-01"], {"fact-none"})
    assert [a["answer_kind"] for a in out["proposals"]] == [m.NOT_ESTABLISHED]


def test_the_prompt_lists_answer_facts_apart_from_other_facts():
    from tasks.P_board.prompts import render_reason

    rows = facts(("f1.1", m.SOURCED), ("f1.2", m.INFERRED), ("f1.3", m.NOT_FOUND))
    prompt = render_reason(board(), fold(board(), Log().add(m.BOARD_CREATED).events, rows), rows, [],
                           stalled=False)
    assert "Facts that can support an answer: ['f1.1', 'f1.3']\n" in prompt
    assert "Other facts: ['origin', 'f1.2']\n" in prompt
    assert "Valid facts" not in prompt


def test_the_prompt_reports_the_last_three_results():
    from tasks.P_board.prompts import render_reason

    log = Log().add(m.BOARD_CREATED)
    log.reason(1, outcome="noop", idle=True, problems=["dropped as a repeat: one"])
    log.reason(2, outcome="noop", idle=True, problems=["dropped as a repeat: two"])
    log.reason(3, outcome=m.MODEL_FAILURE)
    log.reason(4, outcome="invalid")
    folded = fold(board(), log.events, facts())
    assert [r["reason_no"] for r in folded.recent_reasons] == [2, 3, 4]
    prompt = render_reason(board(), folded, facts(), [], stalled=False)
    section = prompt.split("Checks that changed your last 3 replies, oldest first:\n")[1].split("\n\n")[0]
    assert section.splitlines() == [
        "- Assessment 2: dropped as a repeat: two",
        "- Assessment 3: the model request failed, so no reply was read.",
        "- Assessment 4: the reply held no valid JSON object."]


def test_a_review_without_goals_answers_the_first_goal():
    out = parse_reason('{"review": {"from": ["f1.1"], "statement": "s"}}', {"f1.1"}, {"f1.1"}, [], True)
    assert out["outcome"] == "review"
    log = Log().add(m.BOARD_CREATED).reason(1, outcome="review", proposals=out["proposals"])
    review = fold(board(), log.events, facts(("f1.1", m.SOURCED)))
    assert (review.status, review.review_reason) == (m.REVIEW, "answers")
    answer = review.proposed["goal"]
    assert (answer["from"], answer["statement"], answer["reason_no"], answer["answer_kind"]) == (
        ["f1.1"], "s", 1, m.SUPPORTED)
    assert answer["proposal_id"] == f"{log.events[-1].event_id}:goal"


def test_a_stored_legacy_review_keeps_its_status():
    log = Log().add(m.BOARD_CREATED).reason(1, outcome="review", review={
        "from": ["f1.1"], "goals": [{"goal": "goal", "from": ["f1.1"], "statement": "s"}]})
    f = fold(board(), log.events, facts(("f1.1", m.SOURCED), ("goal-2", m.GOAL)))
    assert f.status == m.REVIEW and list(f.proposed) == ["goal"], "a goal left out does not hold it back"


def test_a_submitted_fact_is_read_from_the_tool_row():
    from tasks.P_board.activities import submitted_fact

    args = {"fact": "Kaminski objected [D1].", "kind": "sourced", "open_questions": []}
    rows = [{"role": "tool", "tool_name": m.SUBMIT_FACT_TOOL, "tool_input": json.dumps(args),
             "tool_output": json.dumps({"success": True, "submitted": True})}]
    assert submitted_fact(rows) == args
    rows[0]["tool_output"] = json.dumps({"success": False, "error": "kind"})
    assert submitted_fact(rows) is None


def test_parse_reason_marks_text_without_json_invalid():
    assert parse_reason("We should look further.", set(), set(), [], True)["outcome"] == "invalid"


def test_the_explore_block_is_the_last_fenced_object():
    answer = ("Text [D1].\n\n```json\n{\"fact\": \"A [D1] and B [D2].\", \"kind\": \"sourced\", "
              "\"citations\": [\"D1\", \"D3\"], \"open_questions\": []}\n```")
    block = parse_explore_block(answer)
    assert block["kind"] == "sourced"
    assert labels_of(block["fact"], block["citations"]) == ["D1", "D2", "D3"]


def test_a_submit_call_written_as_text_is_read_as_the_block():
    answer = ('[submit_board_fact]{"fact": "No document shows it [D2].", "kind": "not_found", '
              '"open_questions": ["Was it forwarded?"]}')
    block = parse_explore_block(answer)
    assert block["kind"] == "not_found" and block["open_questions"] == ["Was it forwarded?"]
    assert parse_explore_block("[submit_board_fact]{not json") is None
    assert parse_explore_block("[other_tool]{\"fact\": \"x\", \"kind\": \"sourced\"}") is None


def test_a_reason_reply_without_its_opening_brace_is_read():
    reply = '```json\n  "intents": [\n    {"from": ["origin"], "objective": "Find the filings", "brief": ""}\n  ]\n}\n```'
    out = parse_reason(reply, {"origin"}, set(), [], True)
    assert out["outcome"] == "intents" and out["intents"][0]["objective"] == "Find the filings"
    unclosed = '```json\n"intents": [{"from": ["origin"], "objective": "Find the filings", "brief": ""}]\n```'
    assert parse_reason(unclosed, {"origin"}, set(), [], True)["outcome"] == "intents"


def test_recoverable_reason_replies_are_read():
    goals = json.dumps({"goals": [{"goal": "goal-2", "from": ["f1.1"], "statement": "b"}]})
    out = parse_reason(goals, {"f1.1"}, {"f1.1"}, [], True, ["goal-2"])
    assert out["outcome"] == "review", "a top-level goals list is a review"
    commas = '```json\n{"intents": [{"from": ["origin"], "objective": "Find it",},]}\n```'
    assert parse_reason(commas, {"origin"}, set(), [], True)["outcome"] == "intents"
    both = json.dumps({"review": {"goals": [{"goal": "goal", "from": ["f1.1"], "statement": "a"},
                                            {"goal": "goal-2", "from": ["f1.1"], "statement": "b"}]}})
    out = parse_reason(both, {"f1.1"}, {"f1.1"}, [], True, ["goal-2"], closed_ids={"goal"})
    assert out["outcome"] == "review" and [a["goal"] for a in out["proposals"]] == ["goal-2"]
    assert out["problems"] == ["dropped the answer of the accepted goal goal"]
    cited = json.dumps({"review": {"goals": [{"goal": "goal-2", "from": ["f1.1", "c0c5"],
                                              "statement": "b"}]}})
    out = parse_reason(cited, {"f1.1", "f1.2"}, {"f1.1"}, [], True, ["goal-2"])
    assert out["outcome"] == "review" and out["proposals"][0]["from"] == ["f1.1"]
    assert out["problems"] == ["dropped ['c0c5'] from the answer of goal-2: not a fact"]
    unsourced = cited.replace("c0c5", "f1.2")
    out = parse_reason(unsourced, {"f1.1", "f1.2"}, {"f1.1"}, [], True, ["goal-2"])
    assert out["outcome"] == "review" and out["proposals"][0]["from"] == ["f1.1"], (
        "an inferred fact beside a sourced fact is dropped, and the answer stays")


def test_labels_are_removed_before_a_fact_enters_another_session():
    assert strip_labels("Kaminski refused [D1], [D3] and asked for documents [D5].") == \
        "Kaminski refused and asked for documents."
    block = fact_block([FactRow("b1", "f1.1", m.SOURCED, "A claim [D2].")],
                       [CitationRow("b1", "f1.1", "D2", collectionname="enron", path="/inbox/9.")], set())
    assert "[D2]" not in block and "enron /inbox/9." in block


def test_a_rejected_fact_reaches_the_reason_prompt_and_frees_its_objective():
    from tasks.P_board.fold import earlier_objectives
    from tasks.P_board.prompts import render_reason

    log = Log().add(m.BOARD_CREATED).reason(1, n=2)
    log.add(m.EXPLORE_STARTED, "i1.1", attempt=1)
    log.add(m.EXPLORE_CONCLUDED, "i1.1", attempt=1, fact_id="f1.1", kind=m.SOURCED)
    log.add(m.FACT_REJECTED, "f1.1", reason="D4 names another sender")
    rows = facts(("f1.1", m.SOURCED))
    f = fold(board(), log.events, rows)
    assert f.rejected == {"f1.1": "D4 names another sender"}
    assert earlier_objectives(f) == ["objective 1.2"]
    prompt = render_reason(board(), f, rows, [], stalled=False)
    assert "- f1.1: text Rejected because: D4 names another sender" in prompt
    assert "-> f1.1 (rejected)" in prompt
    assert "'f1.1'" not in prompt.split("Facts that can support an answer:")[1]


def test_the_brief_call_guidance_grows_with_the_step_budget():
    assert call_guidance(m.BASE_EXPLORE_STEPS) == 15
    assert call_guidance(m.MAX_EXPLORE_STEPS) == 30
    assert call_guidance(m.CONCLUDE_STEP_BUDGET) == 1


def test_the_next_reason_reads_the_checks_that_changed_the_last_reply():
    from tasks.P_board.prompts import render_reason

    log = Log().add(m.BOARD_CREATED).reason(1, outcome="noop", idle=True,
                                            problems=["dropped as a repeat: find X"])
    rows = facts()
    folded = fold(board(), log.events, rows)
    assert folded.last_reason_problems == ["dropped as a repeat: find X"]
    prompt = render_reason(board(), folded, rows, [], stalled=False)
    assert ("Checks that changed your last 3 replies, oldest first:\n"
            "- Assessment 1: dropped as a repeat: find X") in prompt
    assert "every remaining direction repeats a finished intent, return answers" in prompt
    assert "applies every correction that concerns its facts" in prompt
    assert "A direction that no fact leads to lists origin, the background context." in prompt


def test_a_review_that_names_a_goal_by_its_text_names_that_goal():
    reply = json.dumps({"review": {"goals": [
        {"goal": "Who wrote?", "from": ["f1.1"], "statement": "a"},
        {"goal": "goal-2", "from": ["f1.2"], "statement": "b"},
    ]}})
    out = parse_reason(reply, {"f1.1", "f1.2"}, {"f1.1", "f1.2"}, [], True, ["goal", "goal-2"],
                       set(), {"Who wrote?": "goal", "What figures?": "goal-2"})
    assert out["outcome"] == "review"
    assert [a["goal"] for a in out["proposals"]] == ["goal", "goal-2"]


def _review(log: Log, r: int, goals=("goal",), facts_seen: int = 1) -> Log:
    """A reason `r` that proposes an answer from `f1.1` for each goal of `goals`."""
    answers = [{"goal": g, "from": ["f1.1"], "statement": f"answer of {g}"} for g in goals]
    return log.reason(r, outcome="review", review={"from": ["f1.1"], "goals": answers},
                      situation={"facts": facts_seen, "hints": 0, "rejected": 0})


def _explored() -> Log:
    """A board with one sourced fact `f1.1` and no open intent."""
    log = Log().add(m.BOARD_CREATED).reason(1, n=1)
    log.add(m.EXPLORE_STARTED, "i1.1", attempt=1)
    return log.add(m.EXPLORE_CONCLUDED, "i1.1", attempt=1, fact_id="f1.1", kind=m.SOURCED)


def _completed() -> Log:
    """A board with one sourced fact `f1.1` whose review the person accepted."""
    return _review(_explored(), 2).add(m.REVIEW_ACCEPTED, "x")


TWO_GOALS = (("f1.1", m.SOURCED), ("goal-2", m.GOAL))


def test_each_goal_answer_is_decided_separately():
    log = _review(_explored(), 2, goals=("goal", "goal-2"))
    rows = facts(*TWO_GOALS)
    f = fold(board(), log.events, rows)
    assert f.status == m.REVIEW and sorted(f.proposed) == ["goal", "goal-2"]
    log.add(m.GOAL_ANSWER_ACCEPTED, "goal", reason_no=2, **{"from": ["f1.1"]}, statement="answer of goal")
    f = fold(board(), log.events, rows)
    assert f.status == m.REVIEW, "the other answer still waits"
    assert list(f.accepted) == ["goal"] and list(f.proposed) == ["goal-2"]
    log.add(m.GOAL_ANSWER_ACCEPTED, "goal-2", reason_no=2)
    f = fold(board(), log.events, rows)
    assert f.status == m.COMPLETED and sorted(f.accepted) == ["goal", "goal-2"]


def test_a_rejected_answer_continues_the_board_at_once():
    log = _review(_explored(), 2, goals=("goal", "goal-2"))
    rows = facts(*TWO_GOALS)
    before = fold(board(), log.events, rows)
    log.add(m.GOAL_ANSWER_ACCEPTED, "goal", reason_no=2)
    log.add(m.GOAL_ANSWER_REJECTED, "c1", goal="goal-2", reason_no=2, correction="wrong year")
    f = fold(board(), log.events, rows + [FactRow("b1", "c1", m.CORRECTION, "wrong year")])
    assert f.status == m.ACTIVE and not f.proposed and list(f.accepted) == ["goal"]
    assert f.max_explores == before.max_explores + m.ACTION_EXPLORES
    assert reason_due(f, in_flight=False), "the correction is new work"
    assert f.open_goals == ["goal-2"]


def test_a_rejection_leaves_the_other_proposed_answers_waiting():
    log = _review(_explored(), 2, goals=("goal", "goal-2"))
    log.add(m.GOAL_ANSWER_REJECTED, "c1", goal="goal", reason_no=2, correction="no")
    f = fold(board(), log.events, facts(*TWO_GOALS))
    assert f.status == m.ACTIVE and list(f.proposed) == ["goal-2"]
    log.add(m.GOAL_ANSWER_ACCEPTED, "goal-2", reason_no=2)
    f = fold(board(), log.events, facts(*TWO_GOALS))
    assert f.status == m.ACTIVE and list(f.accepted) == ["goal-2"]


def test_a_decision_on_a_replaced_answer_does_nothing():
    log = _review(_explored(), 2)
    log.add(m.GOAL_ANSWER_REJECTED, "c1", goal="goal", reason_no=2, correction="no")
    log.add(m.EXPLORE_STARTED, "i1.1", attempt=2)
    _review(log, 3)
    log.add(m.GOAL_ANSWER_ACCEPTED, "goal", reason_no=2)
    f = fold(board(), log.events, facts(("f1.1", m.SOURCED)))
    assert f.status == m.REVIEW and not f.accepted and f.proposed["goal"]["reason_no"] == 3


def test_an_accepted_answer_stays_when_a_goal_reopens_the_board():
    log = _completed()
    log.add(m.GOAL_ADDED, "goal-2", text="Find the auditor")
    f = fold(board(), log.events, facts(*TWO_GOALS))
    assert f.status == m.ACTIVE and list(f.accepted) == ["goal"]
    assert f.open_goals == ["goal-2"]
    _review(log, 3, goals=("goal-2",), facts_seen=1)
    log.add(m.GOAL_ANSWER_ACCEPTED, "goal-2", reason_no=3)
    f = fold(board(), log.events, facts(*TWO_GOALS))
    assert f.status == m.COMPLETED and sorted(f.accepted) == ["goal", "goal-2"]


def test_a_review_skips_an_accepted_goal_and_the_prompt_marks_it():
    from tasks.P_board.prompts import render_reason

    log = _review(_explored(), 2, goals=("goal", "goal-2"))
    log.add(m.GOAL_ANSWER_ACCEPTED, "goal", reason_no=2)
    log.add(m.GOAL_ANSWER_REJECTED, "c1", goal="goal-2", reason_no=2, correction="no")
    rows = facts(*TWO_GOALS)
    f = fold(board(), log.events, rows)
    prompt = render_reason(board(), f, rows, [], stalled=False)
    assert "- goal (accepted, closed): g" in prompt
    assert "A goal marked accepted is closed." in prompt
    both = json.dumps({"review": {"goals": [{"goal": "goal", "from": ["f1.1"], "statement": "a"},
                                            {"goal": "goal-2", "from": ["f1.1"], "statement": "b"}]}})
    out = parse_reason(both, {"f1.1"}, {"f1.1"}, [], True, f.open_goals)
    assert out["outcome"] == "review" and [a["goal"] for a in out["proposals"]] == ["goal-2"]
    assert any("unknown goal 'goal'" in p for p in out["problems"])
    one = json.dumps({"review": {"goals": [{"goal": "goal-2", "from": ["f1.1"], "statement": "b"}]}})
    assert parse_reason(one, {"f1.1"}, {"f1.1"}, [], True, f.open_goals)["outcome"] == "review"


def test_an_explored_question_runs_alone_on_a_completed_board():
    log = _completed()
    before = fold(board(), log.events, facts(("f1.1", m.SOURCED)))
    assert before.status == m.COMPLETED and list(before.accepted) == ["goal"]
    log.add(m.QUESTION_EXPLORED, "i0.1", fact_id="f1.1", index=0, question="Who signed the memo?")
    f = fold(board(), log.events, facts(("f1.1", m.SOURCED)))
    assert f.status == m.COMPLETED and list(f.accepted) == ["goal"]
    intent = f.intents["i0.1"]
    assert (intent.state, intent.from_facts, intent.objective) == (m.OPEN, ["f1.1"], "Who signed the memo?")
    assert f.max_explores == before.max_explores + m.ACTION_EXPLORES
    actions = plan([board()], {"b1": f}, set(), cap=1)
    assert [e.intent_id for e in actions.explores] == ["i0.1"] and not actions.reasons
    from tasks.P_board.fold import may_explore

    assert may_explore(f, "i0.1") and not may_explore(f, "i1.1"), "the explore activity reads the same rule"
    # The same request again, and a subject that is not a question intent, add nothing.
    log.add(m.QUESTION_EXPLORED, "i0.1", fact_id="f1.1", index=0, question="other text")
    log.add(m.QUESTION_EXPLORED, "i3.1", fact_id="f1.1", index=1, question="q")
    again = fold(board(), log.events, facts(("f1.1", m.SOURCED)))
    assert again.intents["i0.1"].objective == "Who signed the memo?"
    assert "i3.1" not in again.intents
    assert again.max_explores == f.max_explores
    log.add(m.EXPLORE_STARTED, "i0.1", attempt=1)
    log.add(m.EXPLORE_CONCLUDED, "i0.1", attempt=1, fact_id="f0.1", kind=m.SOURCED)
    done = fold(board(), log.events, facts(("f1.1", m.SOURCED), ("f0.1", m.SOURCED)))
    assert done.status == m.COMPLETED and not reason_due(done, in_flight=False)
    assert not plan([board()], {"b1": done}, set(), cap=1).reasons


def test_a_question_waits_on_a_paused_board_and_feeds_an_active_one():
    log = _explored().add(m.PAUSE_REQUESTED)
    log.add(m.QUESTION_EXPLORED, "i0.1", fact_id="f1.1", index=0, question="q")
    f = fold(board(), log.events, facts(("f1.1", m.SOURCED)))
    assert f.status == m.PAUSED and not plan([board()], {"b1": f}, set(), cap=1).explores
    log.add(m.RESUME_REQUESTED)
    log.add(m.EXPLORE_STARTED, "i0.1", attempt=1)
    log.add(m.EXPLORE_CONCLUDED, "i0.1", attempt=1, fact_id="f0.1", kind=m.SOURCED)
    f = fold(board(), log.events, facts(("f1.1", m.SOURCED), ("f0.1", m.SOURCED)))
    assert f.status == m.ACTIVE and reason_due(f, in_flight=False)


def test_a_late_goal_reopens_a_board_and_grants_a_goal_budget_once():
    log = _completed()
    before = fold(board(), log.events, facts(("f1.1", m.SOURCED)))
    log.add(m.GOAL_ADDED, "goal-2", text="Find the auditor")
    log.add(m.GOAL_ADDED, "goal-2", text="Find the auditor")
    f = fold(board(), log.events, facts(("f1.1", m.SOURCED)))
    assert f.status == m.ACTIVE
    assert f.max_explores == before.max_explores + m.GOAL_EXPLORES, "one goal, counted once"
    assert [f.grants[e.event_id] for e in log.events[-2:]] == [m.GOAL_EXPLORES, 0]
    assert reason_due(f, in_flight=False)
    for k in range(80):
        log.add(m.FACT_REJECTED, f"f9.{k}", reason="r")
    assert fold(board(), log.events, facts(("f1.1", m.SOURCED))).max_explores == m.EXPLORE_LIMIT


def test_a_checkpoint_without_goals_added_keeps_a_board_idle():
    log = Log().add(m.BOARD_CREATED).reason(1, n=1)
    log.add(m.EXPLORE_STARTED, "i1.1", attempt=1)
    log.add(m.EXPLORE_CONCLUDED, "i1.1", attempt=1, fact_id="f1.1", kind=m.SOURCED)
    # A reason written before `goals_added` existed: three keys only.
    log.reason(2, outcome="noop", idle=False, situation={"facts": 1, "hints": 0, "rejected": 0})
    f = fold(board(), log.events, facts(("f1.1", m.SOURCED)))
    assert not reason_due(f, in_flight=False) or f.checkpoint.get("had_work")
    assert f.situation()["goals_added"] == 0
    seen = {k: f.checkpoint.get(k, 0) for k in ("facts", "hints", "rejected", "goals_added")}
    assert seen == f.situation()
    log.add(m.GOAL_ADDED, "goal-2", text="g2")
    assert reason_due(fold(board(), log.events, facts(("f1.1", m.SOURCED))), in_flight=False)


# ------------------------------------------------------------------ review entry rule 2


def _covering(r, semantics=None, n=1, **extra):
    """A reason result that proposes an answer for the only goal and declares `n` intents."""
    payload = {"proposals": [{"goal": "goal", "from": ["f1.1"], "statement": "s"}],
               "intents": [{"from": ["origin"], "objective": f"objective {r}.{k}", "brief": ""}
                           for k in range(1, n + 1)]}
    if semantics is not None:
        payload["semantics"] = semantics
    payload.update(extra)
    return payload


def test_a_legacy_result_with_answers_and_intents_keeps_its_review_and_decision():
    log = Log().add(m.BOARD_CREATED).reason(1, outcome="partial", **_covering(1))
    f = fold(board(), log.events, facts(("f1.1", m.SOURCED)))
    assert f.status == m.REVIEW, "rule 1 ignores the intents of the reply"
    log.add(m.REVIEW_ACCEPTED, "", review_id=f.decision_id)
    f = fold(board(), log.events, facts(("f1.1", m.SOURCED)))
    assert f.status == m.COMPLETED and sorted(f.accepted) == ["goal"]
    assert f.not_answered == [], "an older decision has no unanswered list"


def test_rule_two_runs_the_intents_of_the_reply_before_review():
    rows = facts(("f1.1", m.SOURCED))
    log = Log().add(m.BOARD_CREATED).reason(1, outcome="partial", **_covering(1, semantics=2))
    f = fold(board(), log.events, rows)
    assert f.status == m.ACTIVE and f.by_state(m.OPEN), "the intent runs first"
    log.add(m.EXPLORE_STARTED, "i1.1", attempt=1)
    log.reason(2, outcome="review", n=0, semantics=2,
               proposals=[{"goal": "goal", "from": ["f1.1"], "statement": "s2"}])
    assert fold(board(), log.events, rows).status == m.ACTIVE, "a running explore keeps it active"
    log.add(m.EXPLORE_CONCLUDED, "i1.1", attempt=1, fact_id="f1.2", kind=m.SOURCED)
    rows = facts(("f1.1", m.SOURCED), ("f1.2", m.SOURCED))
    log.reason(3, outcome="review", n=0, semantics=2,
               proposals=[{"goal": "goal", "from": ["f1.1", "f1.2"], "statement": "s3"}])
    f = fold(board(), log.events, rows)
    assert f.status == m.REVIEW and f.review_reason == "answers"


def test_a_finished_board_marks_the_goals_without_an_answer():
    b = board()
    log = Log().add(m.BOARD_CREATED, goals=["goal", "goal-2"])
    log.reason(1, outcome="partial", n=0, proposals=[{"goal": "goal", "from": ["f1.1"], "statement": "s"}])
    log.add(m.REVIEW_PROPOSED, "budget", reason="budget", statement="The explore budget is used.")
    rows = facts(("f1.1", m.SOURCED), ("goal-2", m.GOAL))
    f = fold(b, log.events, rows)
    assert f.status == m.REVIEW
    log.add(m.REVIEW_ACCEPTED, "", review_id=f.decision_id, unanswered=["goal-2"])
    f = fold(b, log.events, rows)
    assert (f.status, sorted(f.accepted), f.not_answered) == (m.COMPLETED, ["goal"], ["goal-2"])
    log.add(m.BUDGET_EXTENDED, "", review_id=f.decision_id)
    f = fold(b, log.events, rows)
    assert (f.status, f.not_answered) == (m.ACTIVE, []), "a reopening opens the goal again"


def test_a_hint_opens_a_goal_without_an_answer_again():
    log = Log().add(m.BOARD_CREATED, goals=["goal", "goal-2"])
    log.reason(1, outcome="partial", n=0, proposals=[{"goal": "goal", "from": ["f1.1"], "statement": "s"}])
    log.add(m.REVIEW_PROPOSED, "budget", reason="budget")
    rows = facts(("f1.1", m.SOURCED), ("goal-2", m.GOAL))
    f = fold(board(), log.events, rows)
    log.add(m.REVIEW_ACCEPTED, "", review_id=f.decision_id, unanswered=["goal-2"])
    log.add(m.HINT_ADDED, "", text="look at 2002")
    assert fold(board(), log.events, rows).not_answered == []


def test_a_proposal_counts_the_later_assessments_that_dropped_an_answer():
    rows = facts(("f1.1", m.SOURCED), ("goal-2", m.GOAL))
    log = Log().add(m.BOARD_CREATED, goals=["goal", "goal-2"])
    log.reason(1, outcome="partial", proposals=[{"goal": "goal", "from": ["f1.1"], "statement": "s"}])
    log.reason(2, outcome="noop", n=0, idle=True, dropped_answers=["goal"],
               problems=["the answer of goal names no fact"])
    log.reason(3, outcome="noop", n=0, idle=True,
               problems=["the answer of goal from ['f9'] names a fact that is not sourced or not found",
                         "the answer of goal-2 names no fact"])
    f = fold(board(), log.events, rows)
    assert f.answer_drops == {"goal": [2, 3]}, "a goal without a proposal counts nothing"
    assert f.proposed["goal"]["proposed_ms"] == int(T0.replace(tzinfo=timezone.utc).timestamp() * 1000) + 2000, (
        "the result is the third event, 2 s after T0")
    log.reason(4, outcome="partial", n=0, proposals=[{"goal": "goal", "from": ["f1.1"], "statement": "s4"}])
    assert fold(board(), log.events, rows).answer_drops == {}, "a new proposal starts the count again"


def test_the_parser_lists_the_goals_whose_answer_it_dropped():
    reply = json.dumps({"answers": [{"goal": "goal", "from": ["f1.2"], "statement": "s"},
                                    {"goal": "goal-2", "from": [], "statement": "s"}]})
    out = parse_reason(reply, {"f1.2"}, set(), [], True, ["goal", "goal-2"])
    assert out["dropped_answers"] == ["goal", "goal-2"]


def test_the_prompt_asks_for_ids_only_in_from_and_goal_fields():
    from tasks.P_board.prompts import render_reason

    rows = facts(("f1.1", m.SOURCED))
    prompt = render_reason(board(), fold(board(), Log().add(m.BOARD_CREATED).events, rows), rows, [],
                           stalled=False)
    assert ("Name goals and facts by their ids in `from` and `goal` fields only. Do not write ids "
            "in statements or objectives.") in prompt
    assert "give that goal in its `goal` field" in prompt
    assert "name that goal in its objective" not in prompt


def test_an_intent_keeps_a_goal_field_that_names_a_goal():
    reply = json.dumps({"intents": [
        {"from": ["origin"], "goal": "goal-01", "objective": "Find the approval date"},
        {"from": ["origin"], "goal": "goal-9", "objective": "Find the bank that paid"}]})
    out = parse_reason(reply, {"origin"}, set(), [], True, ["goal-01"])
    assert [i["goal"] for i in out["intents"]] == ["goal-01", ""]
