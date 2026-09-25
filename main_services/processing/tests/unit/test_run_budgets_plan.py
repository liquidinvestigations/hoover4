"""The plan section rule and the correction rule of `run_budgets.decide`.

`correction-bound` at the unit level: a section takes at most two `correct` runs, counted
across earlier batches and inside one call.
"""

from tasks.P_agent import run_budgets as rb

SECTION = "3c2b1a09-8f7e-4d6c-9b5a-4e3d2c1b0a9f"


def _b(purpose=None, node=SECTION, objective="x"):
    briefing = {"objective": objective, "known": "", "bring_back": ""}
    if node is not None:
        briefing["plan_node_id"] = node
    if purpose is not None:
        briefing["purpose"] = purpose
    return briefing


def _decide(briefings, kind="organizer", corrections=None, sections=frozenset({SECTION})):
    return rb.decide([("c1", briefings)], depth=0, used=0, limit=300, own_share=0,
                     kind=kind, sections=set(sections), corrections=corrections or {})


def test_a_third_correction_of_one_section_is_refused():
    decision = _decide([_b("correct", objective="fix 2"), _b("correct", objective="fix 3")],
                       corrections={SECTION: 1})
    assert [a.briefing["objective"] for a in decision.accepted] == ["fix 2"]
    assert decision.refused == [{"tool_call_id": "c1", "objective": "fix 3",
                                 "reason": rb.CORRECTION_LIMIT}]


def test_a_section_briefing_outside_an_organizer_is_refused():
    decision = _decide([_b("execute")], kind="chat")
    assert [r["reason"] for r in decision.refused] == [rb.PLAN_NODE_NOT_ALLOWED]


def test_a_node_that_is_not_an_approved_section_or_a_missing_purpose_is_refused():
    decision = _decide([_b("execute", node="not-a-section"), _b(None)])
    assert [r["reason"] for r in decision.refused] == [rb.PLAN_NODE_NOT_ALLOWED] * 2


def test_an_accepted_section_briefing_keeps_its_node_and_purpose():
    [accepted] = _decide([_b("review")]).accepted
    assert (accepted.briefing["plan_node_id"], accepted.briefing["purpose"]) == (
        SECTION, "review")


def test_a_briefing_with_no_node_loses_its_purpose():
    [accepted] = _decide([_b("review", node=None)], kind="chat").accepted
    assert "purpose" not in accepted.briefing and "plan_node_id" not in accepted.briefing
