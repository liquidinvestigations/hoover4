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


def test_a_refused_node_names_the_sections_of_the_approved_tree():
    sections = {SECTION: "Who signed the lease?", "s2": "Who controls the landlord?"}
    decision = rb.decide([("c1", [_b("execute", node="unknown")])], depth=0, used=0,
                         limit=300, own_share=0, kind="organizer", sections=sections,
                         corrections={})
    [refusal] = decision.refused
    assert refusal["reason"] == rb.PLAN_NODE_NOT_ALLOWED
    assert refusal["message"] == (
        f"The sections are: {SECTION} (Who signed the lease?), s2 (Who controls the landlord?). "
        + rb.SECTION_NOT_TASK)


def test_a_refusal_with_no_section_has_no_message():
    decision = _decide([_b("execute")], sections=frozenset())
    [refusal] = decision.refused
    assert refusal["reason"] == rb.PLAN_NODE_NOT_ALLOWED
    assert "message" not in refusal


def test_a_flat_plan_lets_the_organizer_brief_the_root():
    """The tree of a planner that put every node under the root: the root is the only
    section. The briefing rule reads the same sections as the approval rule, so a
    briefing of the root runs, and a briefing of one of its tasks is refused with the root
    named."""
    from database import agent_plans as ap

    snap = ap.initial_snapshot("0b8e6f8a-3f52-4a55-9d6c-6f6a1c1f2e10", "Where does D. I. appear?")
    for text in ("Survey across collections", "Roles and counts", "Examples", "Final report"):
        snap = ap.apply(snap, "append_node", text=text)
    sections = {node.node_id: node.text for node, _ in ap.sections(snap)}
    assert set(sections) == ap.section_ids(snap) == {snap.root_id}
    task = ap.children_of(snap, snap.root_id)[0].node_id
    decision = rb.decide([("c1", [_b("execute", node=snap.root_id, objective="survey"),
                                  _b("execute", node=task, objective="task")])],
                         depth=0, used=0, limit=300, own_share=0, kind="organizer",
                         sections=sections, corrections={})
    assert [a.briefing["objective"] for a in decision.accepted] == ["survey"]
    [refusal] = decision.refused
    assert refusal["reason"] == rb.PLAN_NODE_NOT_ALLOWED
    assert snap.root_id in refusal["message"] and rb.SECTION_NOT_TASK in refusal["message"]
