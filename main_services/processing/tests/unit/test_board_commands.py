"""The board command writer: node identity, ordering, retries, refusals and recovery.

The storage is `FakeBoardStore`, so no service runs. `store.run_commands` does what
`BoardCommands` does: it runs `commands.step` until the board has no command left.
"""

import json
from datetime import timedelta

import pytest

from database import board_commands as bc
from database.boards import EventRow, FactRow
from tasks.P_board import activities
from tasks.P_board import commands as cmd
from tasks.P_board import model as m
from tasks.P_board.fold import canonical_events, fold, visible_facts
from board_store_fake import T0, FakeBoardStore

OWNER = "admin"


@pytest.fixture
def store(monkeypatch):
    return FakeBoardStore().install(monkeypatch)


def slugs(store):
    store.settings[cmd.IDENTITY_SETTING] = str(cmd.SLUG_IDENTITY)


def create(store, board_id="b1", goals=("Who approved the hedges?",), origin="The Enron emails."):
    store.add_board(board_id, owner=OWNER, max_parallel=2)
    store.submit(board_id, f"create:{board_id}", cmd.CREATE_BOARD, OWNER,
                 {"goals": list(goals), "origin": origin})
    store.run_commands(board_id)


def folded(store, board_id="b1"):
    return fold(store.read_board(board_id), store.read_events(board_id), store.read_facts(board_id))


def visible(store, board_id="b1"):
    return [f.fact_id for f in visible_facts(store.read_facts(board_id),
                                             canonical_events(store.read_events(board_id)))]


def receipt(store, request_id, board_id="b1"):
    return store.read_receipts(board_id)[request_id]


def reason(store, number, intents, board_id="b1", **payload):
    """Start assessment `number` and commit its result with `intents`."""
    store.submit(board_id, f"reason_started:{number}", cmd.START_REASON, "dispatcher",
                 {"reason_no": number, "stalled": False})
    body = {"outcome": "intents", "situation": {"facts": 0, "hints": 0, "rejected": 0, "goals_added": 0},
            "intents": intents, "problems": [], **payload}
    store.submit(board_id, f"reason_result:{number}", cmd.REASON_RESULT, "reason",
                 {"reason_no": number, "payload": body})
    store.run_commands(board_id)


def intent(objective, position, slug="", questions=()):
    return {"from": ["background"], "objective": objective, "brief": "", "position": position,
            "slug": slug, "questions": list(questions)}


def explore(store, intent_id, fact="Kaminski refused [D1].", slug="", board_id="b1", attempt=1):
    store.submit(board_id, f"explore_started:{intent_id}:{attempt}", cmd.START_EXPLORE, "dispatcher",
                 {"intent_id": intent_id, "attempt": attempt})
    store.submit(board_id, f"explore_end:{intent_id}:{attempt}", cmd.EXPLORE_END, "explore", {
        "intent_id": intent_id, "attempt": attempt, "phase": "explore", "end": m.EXPLORE_CONCLUDED,
        "fact": {"kind": m.SOURCED, "claimed_kind": m.SOURCED, "text": fact, "session_id": "s",
                 "answer_seq": 7, "slug": slug, "problems": [],
                 "open_questions": ["Who replied to the memo?", "Which bank paid the money?"]},
        "citations": [{"label": "D1", "collection_dataset": "enron", "collectionname": "enron",
                       "file_hash": "h", "path": "/a", "page_id": 1, "quote": "q", "quote_verified": 1}]})
    store.run_commands(board_id)
    return receipt(store, f"explore_end:{intent_id}:{attempt}", board_id).result.get("fact_id")


# --------------------------------------------------------------------------- identity


def test_a_slug_board_gets_fixed_goal_and_background_ids(store):
    slugs(store)
    create(store, goals=("First?", "Second?"))
    assert sorted(f.fact_id for f in store.read_facts("b1")) == ["background", "goal-01", "goal-02"]
    f = folded(store)
    assert f.goal_ids == ["goal-01", "goal-02"] and f.initial_goals == ["goal-01", "goal-02"]
    assert f.max_explores == m.BASE_EXPLORES + m.GOAL_EXPLORES
    [created] = store.read_events("b1")
    assert (created.payload["seq"], created.payload["goals"]) == (1, ["goal-01", "goal-02"])


def test_a_legacy_board_keeps_the_legacy_ids(store):
    create(store, goals=("First?", "Second?"))
    assert sorted(f.fact_id for f in store.read_facts("b1")) == ["goal", "goal-2", "origin"]
    reason(store, 1, [intent("Find the memo", 1), intent("Find the reply", 2)])
    assert sorted(folded(store).intents) == ["i1.1", "i1.2"]
    assert explore(store, "i1.1") == "f1.1"
    assert store.read_labels(["b1"]) == [], "a legacy node gets its slug from the label task"


def test_new_intent_ids_are_slugs_with_collision_suffixes_and_keep_their_positions(store):
    slugs(store)
    create(store)
    reason(store, 1, [intent("Check the contracts", 1, slug="check-contracts"),
                      intent("Check the contracts of LJM", 3, slug="check contracts")])
    f = folded(store)
    assert sorted(f.intents) == ["intent-check-contracts", "intent-check-contracts-2"]
    assignments = receipt(store, "reason_result:1").prepared["assignments"]
    assert assignments == {"assessment:1:1": "intent-check-contracts",
                           "assessment:1:3": "intent-check-contracts-2"}, "a dropped intent renumbers nothing"
    labels = {r.node_id: r.slug for r in store.read_labels(["b1"])}
    assert labels == {"intent-check-contracts": "intent-check-contracts",
                      "intent-check-contracts-2": "intent-check-contracts-2"}


def test_a_slug_falls_back_to_the_text_then_to_the_kind_word(store):
    slugs(store)
    create(store)
    reason(store, 1, [intent("Find the Raptor valuation memo", 1, slug="intent"),
                      intent("?? !!", 2)])
    assert sorted(folded(store).intents) == ["intent-direction", "intent-raptor-valuation-memo"], (
        "a type word or a stop word is no slug word")


def test_a_fact_takes_its_slug_and_a_reserved_name_is_never_taken(store):
    slugs(store)
    create(store)
    reason(store, 1, [intent("Find the memo", 1, slug="background")])
    [intent_id] = folded(store).intents
    assert intent_id == "intent-memo", "the candidate is a type word, so the text gives the slug"
    fact_id = explore(store, intent_id, slug="contract payment")
    assert fact_id == "fact-contract-payment" and fact_id not in cmd.RESERVED
    assert receipt(store, "explore_end:intent-memo:1").prepared["assignments"] == {
        "fact:intent-memo": "fact-contract-payment"}
    [row] = [f for f in store.read_facts("b1") if f.fact_id == fact_id]
    assert (row.session_id, row.answer_seq, row.request_id) == ("s", 7, "explore_end:intent-memo:1")


def test_a_mixed_board_keeps_its_legacy_nodes_and_adds_slug_nodes(store):
    store.add_board("b1", owner=OWNER, max_parallel=2)
    store.publish_facts([FactRow("b1", "origin", m.ORIGIN, "o", created_at=T0),
                         FactRow("b1", "goal", m.GOAL, "g", created_at=T0),
                         FactRow("b1", "f1.1", m.SOURCED, "legacy fact", intent_id="i1.1",
                                 open_questions=["Who signed the memo?"],
                                 created_at=T0 + timedelta(seconds=3))], [])
    store.write_events([
        EventRow("b1", "e1", m.BOARD_CREATED, OWNER, "", {}, T0),
        EventRow("b1", "e2", m.REASON_STARTED, "dispatcher", "1", {}, T0 + timedelta(seconds=1)),
        EventRow("b1", "e3", m.REASON_RESULT, "reason", "1", {
            "outcome": "intents", "situation": {"facts": 0, "hints": 0, "rejected": 0},
            "intents": [{"from": ["origin"], "objective": "Find the memo"}]}, T0 + timedelta(seconds=1)),
        EventRow("b1", "e4", m.EXPLORE_STARTED, "dispatcher", "i1.1", {"attempt": 1}, T0 + timedelta(seconds=2)),
        EventRow("b1", "e5", m.EXPLORE_CONCLUDED, "explore", "i1.1",
                 {"attempt": 1, "fact_id": "f1.1", "kind": m.SOURCED}, T0 + timedelta(seconds=3)),
    ])
    slugs(store)
    store.submit("b1", "goal:1", cmd.ADD_GOAL, OWNER, {"text": "Who signed?"})
    store.submit("b1", "q:1", cmd.EXPLORE_QUESTION, OWNER, {"fact_id": "f1.1", "index": 0})
    store.run_commands("b1")
    f = folded(store)
    assert f.goal_ids == ["goal", "goal-02"] and f.initial_goals == ["goal"]
    assert sorted(f.intents) == ["i1.1", "intent-signed-memo"]
    assert f.intents["intent-signed-memo"].questions == ["f1.1#1"]
    assert receipt(store, "goal:1").prepared["legacy_frontier"] == {"events": 5, "last_event_id": "e5"}
    seqs = [e.payload.get("seq") for e in canonical_events(store.read_events("b1"))]
    assert seqs == [None] * 5 + [1, 2], "the legacy events come first, then the sequenced ones"


# ------------------------------------------------------------------- retries and order


def test_a_retried_request_is_one_command_and_another_body_is_refused(store):
    create(store)
    store.submit("b1", "hint:1", cmd.ADD_HINT, OWNER, {"text": "look at 2001"})
    store.submit("b1", "hint:1", cmd.ADD_HINT, OWNER, {"text": "look at 2001"})
    store.submit("b1", "hint:1", cmd.ADD_HINT, OWNER, {"text": "look at 2002"})
    store.run_commands("b1")
    assert folded(store).hints == ["look at 2001"]
    accepted = receipt(store, "hint:1")
    assert accepted.state == bc.COMMITTED and accepted.payload_digest == bc.digest({"text": "look at 2001"})
    assert store.states([("b1", "hint:1"), ("b1", "hint:2")]) == {
        ("b1", "hint:1"): bc.COMMITTED, ("b1", "hint:2"): bc.UNKNOWN}


@pytest.mark.parametrize("cut", ["publish_facts", "write_labels", "write_events", "receipt_committed"])
def test_an_interrupted_command_writes_the_same_rows_on_retry(store, cut):
    slugs(store)
    create(store)
    reason(store, 1, [intent("Find the memo", 1, slug="memo")])
    store.submit("b1", "explore_started:intent-memo:1", cmd.START_EXPLORE, "dispatcher",
                 {"intent_id": "intent-memo", "attempt": 1})
    store.run_commands("b1")
    store.submit("b1", "explore_end:intent-memo:1", cmd.EXPLORE_END, "explore", {
        "intent_id": "intent-memo", "attempt": 1, "end": m.EXPLORE_CONCLUDED,
        "fact": {"kind": m.SOURCED, "text": "The memo [D1].", "slug": "memo found", "answer_seq": 4}})
    store.fail_on = cut
    with pytest.raises(RuntimeError):
        cmd.step("b1")
    if cut != "receipt_committed":
        assert "fact-memo-found" not in visible(store), "no reader sees a fact before its event"
    # A concurrent command waits behind the prepared one.
    store.submit("b1", "hint:1", cmd.ADD_HINT, OWNER, {"text": "h"})
    store.run_commands("b1")
    assert visible(store).count("fact-memo-found") == 1
    assert [r.fact_id for r in store.read_facts("b1") if r.kind == m.SOURCED] == ["fact-memo-found"]
    f = folded(store)
    assert f.intents["intent-memo"].fact_id == "fact-memo-found"
    events = canonical_events(store.read_events("b1"))
    assert [e.event_type for e in events][-2:] == [m.EXPLORE_CONCLUDED, m.HINT_ADDED]
    assert [e.payload["seq"] for e in events] == list(range(1, len(events) + 1))


def test_two_people_asking_the_same_open_question_get_one_intent(store):
    slugs(store)
    create(store)
    reason(store, 1, [intent("Find the memo", 1, slug="memo")])
    fact_id = explore(store, "intent-memo")
    store.submit("b1", "q:a", cmd.EXPLORE_QUESTION, OWNER, {"fact_id": fact_id, "index": 1})
    store.submit("b1", "q:b", cmd.EXPLORE_QUESTION, OWNER, {"fact_id": fact_id, "index": 1})
    store.submit("b1", "q:c", cmd.EXPLORE_QUESTION, OWNER,
                 {"fact_id": fact_id, "question": "Which bank paid the money?"})
    store.run_commands("b1")
    first = receipt(store, "q:a").result["intent_id"]
    assert first == "intent-bank-paid-money"
    assert receipt(store, "q:b").state == bc.REJECTED and f"already explored in {first}" in receipt(store, "q:b").error
    assert receipt(store, "q:c").result["intent_id"] == f"{first}-2", "the same words take a suffix"
    f = folded(store)
    assert f.questions_explored == {first, f"{first}-2"}
    assert f.max_explores == m.BASE_EXPLORES + 2 * m.ACTION_EXPLORES


def test_an_assessment_binding_and_a_person_question_bind_a_key_once(store):
    slugs(store)
    create(store)
    reason(store, 1, [intent("Find the memo", 1, slug="memo")])
    fact_id = explore(store, "intent-memo")
    key = m.question_key(fact_id, 0)
    reason(store, 2, [intent("Who replied to the memo", 1, slug="reply", questions=[key]),
                      intent("Who else replied", 2, slug="reply-other", questions=[key])])
    f = folded(store)
    assert f.holder(key).intent_id == "intent-reply"
    problems = [e for e in store.read_events("b1") if e.event_type == m.REASON_RESULT][-1].payload["problems"]
    assert any("discarded the binding" in p for p in problems)
    store.submit("b1", "q:1", cmd.EXPLORE_QUESTION, OWNER, {"fact_id": fact_id, "index": 0})
    store.run_commands("b1")
    assert receipt(store, "q:1").state == bc.REJECTED


def test_a_person_command_of_another_user_is_refused(store):
    create(store)
    store.submit("b1", "hint:x", cmd.ADD_HINT, "mallory", {"text": "h"})
    store.run_commands("b1")
    assert receipt(store, "hint:x").state == bc.REJECTED and folded(store).hints == []


def test_a_dropped_board_refuses_every_command(store):
    create(store)
    store.boards["b1"] = store.boards["b1"].__class__(**{**store.boards["b1"].__dict__, "is_deleted": 1})
    store.submit("b1", "hint:1", cmd.ADD_HINT, OWNER, {"text": "h"})
    store.run_commands("b1")
    assert receipt(store, "hint:1").error == "The board is dropped."


# --------------------------------------------------------------------------- budgets


def _at_budget(store, used, hints=0, board_id="b1"):
    """A legacy board with `hints` hints and `used` concluded explores, one intent each."""
    store.add_board(board_id, owner=OWNER)
    store.publish_facts([FactRow(board_id, "origin", m.ORIGIN, "o", created_at=T0),
                         FactRow(board_id, "goal", m.GOAL, "g", created_at=T0)], [])
    at = iter(T0 + timedelta(milliseconds=k) for k in range(1, 100000))
    rows = [EventRow(board_id, "created", m.BOARD_CREATED, OWNER, "", {}, next(at))]
    rows += [EventRow(board_id, f"h{k}", m.HINT_ADDED, OWNER, "", {"text": f"h{k}"}, next(at)) for k in range(hints)]
    rows.append(EventRow(board_id, "r1", m.REASON_STARTED, "dispatcher", "1", {}, next(at)))
    rows.append(EventRow(board_id, "r1r", m.REASON_RESULT, "reason", "1", {
        "outcome": "intents", "situation": {"facts": 0, "hints": hints, "rejected": 0},
        "intents": [{"from": ["origin"], "objective": f"objective {k}"} for k in range(1, used + 1)]}, next(at)))
    for k in range(1, used + 1):
        rows.append(EventRow(board_id, f"s{k}", m.EXPLORE_STARTED, "dispatcher", f"i1.{k}", {"attempt": 1}, next(at)))
        rows.append(EventRow(board_id, f"c{k}", m.EXPLORE_CONCLUDED, "explore", f"i1.{k}",
                             {"attempt": 1, "fact_id": f"f1.{k}", "kind": m.INFERRED}, next(at)))
    store.write_events(rows)


def test_the_board_limit_refuses_more_work(store):
    _at_budget(store, m.EXPLORE_LIMIT, hints=70)
    f = folded(store)
    assert (f.max_explores, f.explores_used, f.limit_reached) == (m.EXPLORE_LIMIT, m.EXPLORE_LIMIT, True)
    store.submit("b1", "hint:1", cmd.ADD_HINT, OWNER, {"text": "h"})
    store.submit("b1", "goal:1", cmd.ADD_GOAL, OWNER, {"text": "g2"})
    store.run_commands("b1")
    assert receipt(store, "hint:1").error == cmd.LIMIT_TEXT and receipt(store, "goal:1").error == cmd.LIMIT_TEXT


def test_a_used_budget_runs_one_final_assessment_and_a_failure_ends_it(store, monkeypatch):
    _at_budget(store, m.BASE_EXPLORES)
    monkeypatch.setattr(activities, "_cap", lambda: 4)
    out = activities.board_plan(activities.PlanInput())
    [task] = out.reasons
    assert (task.final, task.assessed_budget, task.request_id) == (True, m.BASE_EXPLORES, "reason_started:2")
    assert out.command_boards == ["b1"]
    again = activities.board_plan(activities.PlanInput(in_flight_reasons=["b1"], awaiting=[f"b1 {task.request_id}"]))
    assert not again.reasons and not again.committed, "a board with a waiting command gets no decision"
    store.run_commands("b1")
    out = activities.board_plan(activities.PlanInput(in_flight_reasons=["b1"], awaiting=[f"b1 {task.request_id}"]))
    assert out.committed == [f"b1 {task.request_id}"] and not out.reasons
    activities.record_final_failure(activities.FinalFailure("b1", m.BASE_EXPLORES, "the model is down"))
    activities.record_final_failure(activities.FinalFailure("b1", m.BASE_EXPLORES, "the model is down"))
    store.run_commands("b1")
    f = folded(store)
    assert f.final_ops[str(m.BASE_EXPLORES)]["state"] == "terminal"
    out = activities.board_plan(activities.PlanInput())
    assert not out.reasons, "a failed final assessment is not called again"
    store.run_commands("b1")
    f = folded(store)
    assert (f.status, f.review_reason) == (m.REVIEW, "budget")
    store.submit("b1", "extend:1", cmd.EXTEND_BUDGET, OWNER, {"expected_id": f.decision_id})
    store.submit("b1", "extend:2", cmd.EXTEND_BUDGET, OWNER, {"expected_id": f.decision_id})
    store.run_commands("b1")
    assert receipt(store, "extend:1").result["grant"] == m.EXTENSION_EXPLORES
    assert receipt(store, "extend:2").state == bc.REJECTED
    f = folded(store)
    assert f.status == m.ACTIVE and f.max_explores == m.BASE_EXPLORES + m.EXTENSION_EXPLORES


def test_an_extension_grants_only_the_remaining_budget(store):
    _at_budget(store, 278, hints=62)
    f = folded(store)
    assert f.max_explores == m.BASE_EXPLORES + 62 * m.ACTION_EXPLORES == 278
    store.write_events([EventRow("b1", "rv", m.REVIEW_PROPOSED, "dispatcher", "budget",
                                 {"reason": "budget"}, T0 + timedelta(minutes=5))])
    store.submit("b1", "extend:1", cmd.EXTEND_BUDGET, OWNER, {"expected_id": "rv"})
    store.run_commands("b1")
    assert receipt(store, "extend:1").result["grant"] == m.EXPLORE_LIMIT - 278
    f = folded(store)
    assert f.max_explores == m.EXPLORE_LIMIT and f.grants[canonical_events(store.read_events("b1"))[-1].event_id] == 22


# ------------------------------------------------------------------------- the plan


def test_a_pending_explore_start_takes_its_slot_until_it_commits(store, monkeypatch):
    slugs(store)
    create(store)
    reason(store, 1, [intent("Find the memo", 1, slug="memo"), intent("Find the reply", 2, slug="reply")])
    store.boards["b1"] = store.boards["b1"].__class__(**{**store.boards["b1"].__dict__, "max_parallel": 1})
    monkeypatch.setattr(activities, "_cap", lambda: 1)
    out = activities.board_plan(activities.PlanInput())
    [task] = out.explores
    assert task.request_id == "explore_started:intent-memo:1"
    key = f"b1 {task.request_id}"
    out = activities.board_plan(activities.PlanInput(awaiting=[key]))
    assert not out.explores and out.command_boards == ["b1"] and not out.committed
    store.run_commands("b1")
    out = activities.board_plan(activities.PlanInput(awaiting=[key]))
    assert out.committed == [key] and not out.explores, "the running explore keeps the slot"
    assert folded(store).intents["intent-memo"].state == m.RUNNING


def test_a_refused_start_is_reported(store, monkeypatch):
    slugs(store)
    create(store)
    reason(store, 1, [intent("Find the memo", 1, slug="memo")])
    monkeypatch.setattr(activities, "_cap", lambda: 1)
    [task] = activities.board_plan(activities.PlanInput()).explores
    store.submit("b1", "pause:1", cmd.SET_PAUSED, OWNER, {"paused": True})
    # The pause is written after the start, so the start commits first. A start after the
    # pause is refused.
    store.run_commands("b1")
    store.submit("b1", "explore_started:intent-memo:2", cmd.START_EXPLORE, "dispatcher",
                 {"intent_id": "intent-memo", "attempt": 2})
    store.run_commands("b1")
    out = activities.board_plan(activities.PlanInput(awaiting=[f"b1 {task.request_id}", "b1 explore_started:intent-memo:2"]))
    assert out.committed == [f"b1 {task.request_id}"] and out.rejected == ["b1 explore_started:intent-memo:2"]
    assert out.cancels == [m.explore_workflow_id("b1", "intent-memo")]


def test_an_explore_end_after_a_retry_is_one_fact(store, monkeypatch):
    slugs(store)
    create(store)
    reason(store, 1, [intent("Find the memo", 1, slug="memo")])
    fact_id = explore(store, "intent-memo")
    store.submit("b1", "explore_end:intent-memo:1", cmd.EXPLORE_END, "explore",
                 {"intent_id": "intent-memo", "attempt": 1, "end": m.EXPLORE_CANCELLED, "error": "late"})
    store.run_commands("b1")
    assert visible(store).count(fact_id) == 1
    assert folded(store).intents["intent-memo"].state == m.CONCLUDED


def test_a_retried_conclusion_returns_the_submitted_end(store, monkeypatch):
    slugs(store)
    create(store)
    reason(store, 1, [intent("Find the memo", 1, slug="memo")])
    explore(store, "intent-memo")

    def no_read(*args):
        raise AssertionError("a retry must not read a later answer of the session")

    monkeypatch.setattr(activities, "_existing_user_seq", no_read)
    request = activities.TurnRequest("b1", "intent-memo", 1, "explore")
    assert activities.conclude_explore(request).outcome == "fact"
    assert activities.convert_explore_report(request) == "fact"


def test_a_slug_stem_is_ascii_and_bounded():
    assert cmd.slug_stem("", "Zahlung an Société Générale über 5 Mio.", "fact") == "zahlung-an-societe-generale"
    long = cmd.slug_stem("internationalization-responsibilities-counterparty-reconciliation-statements", "", "fact")
    assert len(long) <= 40 and long.startswith("internationalization")
    assert cmd.slug_stem("", "", "correction") == "note"
    assert cmd.slug_stem("", "日本語のみ", "intent") == "direction"


def test_a_session_of_a_slug_intent_names_its_intent():
    session = m.session_id_for("0a1b2c", "intent-check-contracts-2")
    assert session == "board-0a1b2c-intent-check-contracts-2"
    assert len(m.explore_workflow_id("0" * 32, "intent-" + "x" * 40 + "-99")) < 200


def test_finishing_a_review_lists_the_goals_without_a_proposal(store):
    slugs(store)
    create(store, goals=("First?", "Second?"))
    reason(store, 1, [intent("Find the memo", 1, slug="find-memo")])
    fact = explore(store, "intent-find-memo")
    reason(store, 2, [], outcome="partial",
           proposals=[{"goal": "goal-01", "from": [fact], "statement": "s"}])
    store.submit("b1", "review_proposed:budget:9", cmd.REVIEW_PROPOSED, "dispatcher", {"why": "budget"})
    store.run_commands("b1")
    f = folded(store)
    assert f.status == m.REVIEW
    store.submit("b1", "finish", cmd.REVIEW_DECISION, OWNER, {"review_id": f.decision_id, "accept": True})
    store.run_commands("b1")
    [accepted] = [e for e in store.read_events("b1") if e.event_type == m.REVIEW_ACCEPTED]
    assert accepted.payload["unanswered"] == ["goal-02"]
    f = folded(store)
    assert (f.status, f.not_answered) == (m.COMPLETED, ["goal-02"])
