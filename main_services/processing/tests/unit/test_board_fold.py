"""The board fold, the planner, the reason and explore contracts, and the prompts.

Every function under test is pure, so the rows are built here and no service runs.
"""

import json
from datetime import datetime, timedelta

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
    assert actions.reviews == [("b1", "stalled")]


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


def test_the_budget_sends_an_idle_board_to_review():
    b = board(max_explores=100)
    log = _spent(Log().add(m.BOARD_CREATED), m.BASE_EXPLORES).reason(99, n=1)
    f = fold(b, log.events, facts(("f1.1", m.INFERRED)))
    assert f.max_explores == m.BASE_EXPLORES, "the board row's budget is not read"
    actions = plan([b], {"b1": f}, set(), cap=1)
    assert actions.reviews == [("b1", "budget")] and actions.explores == []


def test_corrections_and_hints_grow_the_budget_up_to_the_caps():
    log = Log().add(m.BOARD_CREATED)
    f = fold(board(), log.events, facts())
    assert (f.max_explores, f.explore_steps) == (m.BASE_EXPLORES, m.BASE_EXPLORE_STEPS)
    log.add(m.HINT_ADDED, text="h")
    log.add(m.FACT_REJECTED, "f1.1", reason="wrong person")
    f = fold(board(), log.events, facts())
    assert f.max_explores == m.BASE_EXPLORES + m.HINT_EXPLORES + m.CORRECTION_EXPLORES
    assert f.explore_steps == m.BASE_EXPLORE_STEPS + m.HINT_EXPLORE_STEPS + m.CORRECTION_EXPLORE_STEPS
    for k in range(10):
        log.add(m.FACT_REJECTED, f"f9.{k}", reason="r")
    f = fold(board(), log.events, facts())
    assert (f.max_explores, f.explore_steps) == (m.MAX_EXPLORES, m.MAX_EXPLORE_STEPS)


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
    assert payload["outcome"] == "noop"
    assert any("leaves out the goals goal-2" in p for p in payload["problems"])
    both = json.dumps({"review": {"goals": [
        {"goal": "goal", "from": ["f1.1"], "statement": "a"},
        {"goal": "goal-2", "from": ["f2.1"], "statement": "not in the documents"}]}})
    payload = parse_reason(both, {"f1.1", "f2.1"}, {"f1.1"}, [], True, goals, {"f2.1"})
    assert payload["outcome"] == "review"
    assert [g["goal"] for g in payload["review"]["goals"]] == goals
    assert payload["review"]["from"] == ["f1.1", "f2.1"]
    only_absent = json.dumps({"review": {"goals": [
        {"goal": "goal", "from": ["f2.1"], "statement": "a"},
        {"goal": "goal-2", "from": ["f2.1"], "statement": "b"}]}})
    assert parse_reason(only_absent, {"f2.1"}, set(), [], True, goals, {"f2.1"})["outcome"] == "noop"


def test_a_review_without_goals_answers_the_first_goal():
    review = fold(board(), Log().add(m.BOARD_CREATED).reason(
        1, outcome="review", review=parse_reason(
            '{"review": {"from": ["f1.1"], "statement": "s"}}', {"f1.1"}, {"f1.1"}, [], True)["review"]
    ).events, facts(("f1.1", m.SOURCED)))
    assert review.status == m.REVIEW
    assert review.proposed == {"goal": {"goal": "goal", "from": ["f1.1"], "statement": "s", "reason_no": 1}}


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
    assert "'f1.1'" not in prompt.split("Valid facts:")[1]


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
    assert "Checks that changed your last reply:\n- dropped as a repeat: find X" in prompt
    assert "every remaining direction repeats a finished intent, return review" in prompt
    assert "applies every correction that concerns its facts" in prompt


def test_a_review_that_names_a_goal_by_its_text_names_that_goal():
    reply = json.dumps({"review": {"goals": [
        {"goal": "Who wrote?", "from": ["f1.1"], "statement": "a"},
        {"goal": "goal-2", "from": ["f1.2"], "statement": "b"},
    ]}})
    out = parse_reason(reply, {"f1.1", "f1.2"}, {"f1.1", "f1.2"}, [], True, ["goal", "goal-2"],
                       set(), {"Who wrote?": "goal", "What figures?": "goal-2"})
    assert out["outcome"] == "review"
    assert [g["goal"] for g in out["review"]["goals"]] == ["goal", "goal-2"]


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
    assert f.max_explores == before.max_explores + m.CORRECTION_EXPLORES
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
    assert out["outcome"] == "noop" and any("unknown goal 'goal'" in p for p in out["problems"])
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
    assert f.max_explores == before.max_explores + m.QUESTION_EXPLORES
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


def test_a_late_goal_reopens_a_board_and_grows_the_budget_above_the_cap():
    log = _completed()
    for k in range(10):
        log.add(m.FACT_REJECTED, f"f9.{k}", reason="r")
    capped = fold(board(), log.events, facts(("f1.1", m.SOURCED)))
    assert capped.max_explores == m.MAX_EXPLORES
    log.add(m.GOAL_ADDED, "goal-2", text="Find the auditor")
    log.add(m.GOAL_ADDED, "goal-2", text="Find the auditor")
    f = fold(board(), log.events, facts(("f1.1", m.SOURCED)))
    assert f.status == m.ACTIVE
    assert f.max_explores == m.MAX_EXPLORES + m.CORRECTION_EXPLORES, "one goal, counted once"
    assert f.explore_steps == m.MAX_EXPLORE_STEPS
    assert reason_due(f, in_flight=False)


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
