"""The plan rules of `run_budgets.decide`: the section rule, one run a section, one
correction a plan, no review, no section-less briefing in a plan, and no nested sub-agent.
"""

import json

from tasks.P_agent import run_budgets as rb

SECTION = "3c2b1a09-8f7e-4d6c-9b5a-4e3d2c1b0a9f"
FOUR = ("s1", "s2", "s3", "s4")


def _b(purpose=None, node=SECTION, objective="x", sections=None):
    briefing = {"objective": objective, "known": "", "bring_back": ""}
    if node is not None:
        briefing["plan_node_id"] = node
    if purpose is not None:
        briefing["purpose"] = purpose
    if sections is not None:
        briefing["sections"] = sections
    return briefing


def _decide(briefings, kind="organizer", runs=None, sections=frozenset({SECTION}),
            in_plan=True, depth=0):
    return rb.decide([("c1", briefings)], depth=depth, used=0, limit=rb.plan_limit(),
                     own_share=0, kind=kind, sections=set(sections), section_runs=runs or {},
                     max_depth=1 if in_plan else rb.MAX_DEPTH, in_plan=in_plan)


def test_four_sections_run_once_each_and_a_fifth_briefing_is_refused():
    briefings = [_b("execute", node=n, objective=n) for n in FOUR]
    first = _decide(briefings, sections=FOUR)
    assert [a.briefing["objective"] for a in first.accepted] == list(FOUR)
    assert all(a.share == 0 for a in first.accepted)
    again = _decide([_b("execute", node="s2", objective="again")], sections=FOUR,
                    runs={f"execute:{n}": 1 for n in FOUR})
    assert [r["reason"] for r in again.refused] == [rb.SECTION_ALREADY_RUN]


def test_a_second_execute_of_one_section_in_one_call_is_refused():
    decision = _decide([_b("execute", objective="a"), _b("execute", objective="b")])
    assert [a.briefing["objective"] for a in decision.accepted] == ["a"]
    assert [r["reason"] for r in decision.refused] == [rb.SECTION_ALREADY_RUN]


def test_one_correction_names_two_sections_and_a_second_is_refused():
    decision = _decide([_b("correct", node="s1", sections=["s1", "s3", "s1"], objective="fix"),
                        _b("correct", node="s2", objective="fix again")], sections=FOUR)
    [accepted] = decision.accepted
    assert accepted.briefing["sections"] == ["s1", "s3"]
    assert [r["reason"] for r in decision.refused] == [rb.CORRECTION_LIMIT]
    later = _decide([_b("correct", node="s2")], sections=FOUR, runs={"correct": 1})
    assert [r["reason"] for r in later.refused] == [rb.CORRECTION_LIMIT]


def test_a_correction_whose_sections_leave_out_its_node_or_name_a_task_is_refused():
    decision = _decide([_b("correct", node="s1", sections=["s2"]),
                        _b("correct", node="s1", sections=["s1", "task"])], sections=FOUR)
    assert [r["reason"] for r in decision.refused] == [rb.PLAN_NODE_NOT_ALLOWED] * 2


def test_a_correction_with_no_sections_corrects_its_node():
    [accepted] = _decide([_b("correct")]).accepted
    assert accepted.briefing["sections"] == [SECTION]


def test_a_review_briefing_is_refused():
    decision = _decide([_b("review")])
    assert [r["reason"] for r in decision.refused] == [rb.REVIEW_NOT_ALLOWED]


def test_an_organizer_briefing_with_no_node_in_a_plan_is_refused():
    decision = _decide([_b("execute", node=None)])
    [refusal] = decision.refused
    assert refusal["reason"] == rb.PLAN_NODE_REQUIRED
    assert SECTION in refusal["message"]


def test_a_plan_subagent_cannot_delegate():
    decision = _decide([_b(None, node=None)], kind="subagent", depth=1)
    assert [r["reason"] for r in decision.refused] == [rb.DEPTH_LIMIT]


def test_the_plan_budget_is_at_most_five(monkeypatch):
    monkeypatch.setenv("AGENT_PLAN_RUN_BUDGET", "300")
    assert rb.plan_limit() == 5
    monkeypatch.setenv("AGENT_PLAN_RUN_BUDGET", "3")
    assert rb.plan_limit() == 3


def test_a_section_briefing_outside_an_organizer_is_refused():
    decision = _decide([_b("execute")], kind="chat", in_plan=False)
    assert [r["reason"] for r in decision.refused] == [rb.PLAN_NODE_NOT_ALLOWED]


def test_a_node_that_is_not_an_approved_section_or_a_missing_purpose_is_refused():
    decision = _decide([_b("execute", node="not-a-section"), _b(None)])
    assert [r["reason"] for r in decision.refused] == [rb.PLAN_NODE_NOT_ALLOWED] * 2


def test_an_accepted_section_briefing_keeps_its_node_and_purpose():
    [accepted] = _decide([_b("execute", sections=["other"])]).accepted
    assert (accepted.briefing["plan_node_id"], accepted.briefing["purpose"]) == (
        SECTION, "execute")
    assert "sections" not in accepted.briefing


def test_a_briefing_with_no_node_outside_a_plan_loses_its_purpose():
    [accepted] = _decide([_b("correct", node=None, sections=["a"])], kind="chat",
                         in_plan=False).accepted
    assert not {"purpose", "plan_node_id", "sections"} & set(accepted.briefing)


def test_a_refused_node_names_the_sections_of_the_approved_tree():
    sections = {SECTION: "Who signed the lease?", "s2": "Who controls the landlord?"}
    decision = rb.decide([("c1", [_b("execute", node="unknown")])], depth=0, used=0,
                         limit=5, own_share=0, kind="organizer", sections=sections,
                         section_runs={}, max_depth=1, in_plan=True)
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
                         depth=0, used=0, limit=5, own_share=0, kind="organizer",
                         sections=sections, section_runs={}, max_depth=1, in_plan=True)
    assert [a.briefing["objective"] for a in decision.accepted] == ["survey"]
    [refusal] = decision.refused
    assert refusal["reason"] == rb.PLAN_NODE_NOT_ALLOWED
    assert snap.root_id in refusal["message"] and rb.SECTION_NOT_TASK in refusal["message"]


def _row(run_id, node, purpose, state="completed", minute=0, briefing=None, depth=1):
    from datetime import datetime, timedelta

    from database import agent_runs

    return agent_runs.RunRow(
        run_id=run_id, username="u", session_id="s", turn_seq=1, thread_id=run_id,
        depth=depth, kind="subagent", plan_run_id="p", plan_node_id=node, purpose=purpose,
        state=state, briefing=json.dumps(briefing or {}), result=f"report of {run_id}",
        started_at=datetime(2026, 1, 1) + timedelta(minutes=minute))


def test_one_correction_of_two_sections_gives_an_entry_for_each(monkeypatch):
    """Sections A and B each ran once. Correction C names both and writes one report under
    A, and both sections read that report."""
    from database import agent_plans as ap
    from tasks.P_agent import plan_runs

    snap = ap.initial_snapshot("0b8e6f8a-3f52-4a55-9d6c-6f6a1c1f2e10", "Who owns the lease?")
    for text in ("A", "B"):
        snap = ap.apply(snap, "append_node", text=text)
    ids = {n.text: n.node_id for n in snap.nodes}
    for text in ("A", "B"):
        snap = ap.apply(snap, "append_child", parent_id=ids[text], text=text + "1")
    a, b = ids["A"], ids["B"]
    written = []
    monkeypatch.setattr(ap, "write_document", lambda *args, **kw: written.append(args))
    c = _row("c", a, "correct", minute=5, briefing={"sections": [a, b]})
    plan_runs.write_plan_ending(c, "completed", [])
    [(_, _, _, run_id, node, role, kind, body)] = written
    assert (run_id, node, role, kind) == ("c", a, "executor", "report")

    docs = [ap.PlanDocument(ap.document_id(r, "report"), n, "executor", "report", 0, "x",
                            None) for r, n in (("ra", a), ("rb", b), ("c", a))]
    rows = [_row("ra", a, "execute"), _row("rb", b, "execute"), c]
    monkeypatch.setattr(ap, "read_plan_run", lambda *args: ap.PlanRunRow(
        "p", snap.plan_id, "u", "s", approved_version=snap.version))
    monkeypatch.setattr(ap, "read_snapshot", lambda *args: snap)
    monkeypatch.setattr(ap, "read_documents", lambda *args: docs)
    monkeypatch.setattr(plan_runs, "_plan_rows", lambda *args: rows)
    entries = plan_runs.section_entries("u", "s", "p")
    assert [(e["node_id"], e["failed"], e["corrections"]) for e in entries] == [
        (a, False, 1), (b, False, 1)]
    docs.pop()
    assert [e["failed"] for e in plan_runs.section_entries("u", "s", "p")] == [True, True]


def test_a_plan_subagent_step_request_cannot_delegate():
    from types import SimpleNamespace

    from tasks.P_agent import steps

    params = SimpleNamespace(allowed_collections=[], llm_model="m")
    plan_child = _row("x", SECTION, "review")
    body = steps._step_run(plan_child, params)
    assert (body["can_delegate"], body["purpose"]) == (False, None)
    chat_child = _row("y", None, "", depth=1)
    chat_child.plan_run_id = None
    assert steps._step_run(chat_child, params)["can_delegate"] is True
    organizer = _row("z", None, "", depth=0)
    assert steps._step_run(organizer, params)["can_delegate"] is True
