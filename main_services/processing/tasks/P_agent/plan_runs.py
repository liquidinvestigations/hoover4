"""The plan layer of the `AgentRun` activities: the plan run state, the section documents
and `sections_json`.

A deep-research request is a plan run. A planner run builds the tree with the plan tools and
answers with an orientation. The person then approves, rejects or cancels it, and each
approve or reject starts a new run. An organizer run executes the approved tree by
delegation. No run waits for a person.

| plan run state | the run that causes it | writer here |
|---|---|---|
| `planning` | a round 0 planner starts | `open_plan_run` |
| `revising` | a planner of round 1 or later starts | `open_plan_run` |
| `awaiting_review` | the planner's thread answers | `write_plan_ending` |
| `executing` | organizer step 1 starts | `open_plan_run` |
| `completed` | an organizer run answers with no delegation | `write_plan_ending` |
| `failed` | a planner or organizer run fails | `write_plan_ending` |
| `cancelled` | a cancel reaches the depth 0 run | `write_plan_ending` |

The website writes `cancelled` only for a plan in `awaiting_review`, when no run is open.
Every write here reads the row first and writes `state_version + 1`, and a write whose
changes the row already holds writes nothing, so a retry changes nothing that the first
attempt wrote.

**Section documents.** A sub-agent thread with a `plan_node_id` writes its briefing as a
`prompt` document when its row is written, and the `completed` ending of the thread's last
run writes the report as a `report` document, or as a `review` document when its purpose
is `review`. Both are keyed by the thread's first run. The organizer writes the final report
as a `final` document.
"""

from __future__ import annotations

import json
import logging
import uuid

log = logging.getLogger(__name__)

#: The opening message of a planner round after a rejection. The comment follows it.
REJECTED_TEXT = "The person rejected plan version {version}. Their comment:"
#: The opening message of organizer step 1.
APPROVED_TEXT = "Run the approved plan, version {version}."

PLAN_KINDS = ("planner", "organizer")


def plan_id_for(plan_run_id: str) -> str:
    """The plan id of a plan run. One plan run has one tree."""
    from database import agent_plans

    return str(uuid.uuid5(agent_plans.PLAN_NAMESPACE, f"plan:{plan_run_id}"))


def open_plan_run(inp, question: str) -> str:
    """Write the plan run state of a new planner or organizer run. Return its opening text.

    `question` is the text of the user row at `turn_seq`, the deep-research message for
    round 0. A retry finds the state already moved and writes nothing again.
    """
    from database import agent_plans

    user, session, plan_run_id = inp.username, inp.session_id, inp.plan_run_id
    if not plan_run_id:
        raise RuntimeError(f"a {inp.kind} run needs a plan_run_id")
    if inp.kind == "planner" and not inp.decision_id:
        plan_id = plan_id_for(plan_run_id)
        agent_plans.create_plan_run(agent_plans.PlanRunRow(
            run_id=plan_run_id, plan_id=plan_id, username=user, session_id=session,
            start_seq=inp.start_seq, state=agent_plans.PLANNING,
        ))
        agent_plans.create_plan(user, session, plan_id, question)
        return question
    decision = agent_plans.read_decision(user, session, plan_run_id, inp.decision_id)
    if decision is None:
        raise RuntimeError(f"decision {inp.decision_id} of plan run {plan_run_id} has no row")
    current = agent_plans.read_plan_run(user, session, plan_run_id)
    if current is None:
        raise RuntimeError(f"plan run {plan_run_id} has no row")
    if inp.kind == "planner":
        if current.state == agent_plans.AWAITING_REVIEW:
            agent_plans.write_plan_run(user, session, plan_run_id, state=agent_plans.REVISING,
                                       review_round=current.review_round + 1)
        return f"{REJECTED_TEXT.format(version=decision.reviewed_version)}\n\n{decision.comment}"
    if current.state == agent_plans.AWAITING_REVIEW:
        agent_plans.write_plan_run(user, session, plan_run_id, state=agent_plans.EXECUTING,
                                   approved_version=decision.reviewed_version)
    return APPROVED_TEXT.format(version=decision.reviewed_version)


def _plan_rows(username: str, session_id: str, plan_run_id: str):
    from tasks.P_agent.activities import _read_rows

    return _read_rows("plan_run_id = {p:UUID}",
                      {"u": username, "s": session_id, "p": plan_run_id})


def section_entries(username: str, session_id: str, plan_run_id: str) -> list[dict]:
    """The `sections_json` entries of an approved plan, derived from the run rows and the
    documents. Empty before approval."""
    from database import agent_plans

    plan_run = agent_plans.read_plan_run(username, session_id, plan_run_id)
    if plan_run is None or not plan_run.approved_version:
        return []
    snapshot = agent_plans.read_snapshot(username, session_id, plan_run.plan_id,
                                         plan_run.approved_version)
    if snapshot is None:
        return []
    rows = _plan_rows(username, session_id, plan_run_id)
    by_thread: dict[str, list] = {}
    for row in rows:
        by_thread.setdefault(row.thread_id, []).append(row)
    runs = []
    for row in rows:
        if row.plan_node_id and not row.continues_run_id and row.depth >= 1:
            newest = by_thread.get(row.thread_id, [row])[-1]
            runs.append(agent_plans.SectionRun(row.plan_node_id, row.purpose, newest.state,
                                               row.started_at))
    documents = agent_plans.read_documents(username, session_id, plan_run_id)
    return agent_plans.section_states(snapshot, runs, documents)


def refresh_sections(username: str, session_id: str, plan_run_id: str) -> list[dict]:
    """Write `sections_json` of an executing plan run from the rows. Return the entries."""
    from database import agent_plans

    entries = section_entries(username, session_id, plan_run_id)
    if entries:
        agent_plans.write_plan_run(username, session_id, plan_run_id,
                                   sections_json=json.dumps(entries, sort_keys=True))
    return entries


def approved_sections(username: str, session_id: str, plan_run_id: str) -> dict[str, str]:
    """The sections of the approved tree as `{node_id: title}`, in tree order, for the plan
    section rule. The refusal of a briefing names them."""
    from database import agent_plans

    plan_run = agent_plans.read_plan_run(username, session_id, plan_run_id)
    if plan_run is None or not plan_run.approved_version:
        return {}
    snapshot = agent_plans.read_snapshot(username, session_id, plan_run.plan_id,
                                         plan_run.approved_version)
    if not snapshot:
        return {}
    return {node.node_id: node.text for node, _ in agent_plans.sections(snapshot)}


def final_answer(row, answer: str) -> str:
    """The organizer's answer with the generated `Failed sections` table appended."""
    from database import agent_plans

    table = agent_plans.failed_sections_table(
        refresh_sections(row.username, row.session_id, row.plan_run_id))
    return f"{answer.rstrip()}\n\n{table}" if table else answer


def plan_reference(row) -> str:
    """The `plan_reference_json` of a planner's answer row: the plan the card shows."""
    from database import agent_plans

    plan_run = agent_plans.read_plan_run(row.username, row.session_id, row.plan_run_id)
    if plan_run is None:
        return ""
    snapshot = agent_plans.read_snapshot(row.username, row.session_id, plan_run.plan_id)
    return json.dumps({"plan_id": plan_run.plan_id, "run_id": plan_run.run_id,
                       "reviewed_version": snapshot.version if snapshot else 0},
                      sort_keys=True)


def write_prompt_document(child, briefing_text: str) -> None:
    """The `prompt` document of a new sub-agent thread of a plan section."""
    from database import agent_plans

    if not (child.plan_run_id and child.plan_node_id):
        return
    agent_plans.write_document(
        child.username, child.session_id, child.plan_run_id, child.run_id,
        child.plan_node_id, _role(child.purpose), "prompt", briefing_text,
        attempt=1 if child.purpose == "correct" else 0,
    )


def _role(purpose: str) -> str:
    return "reviewer" if purpose == "review" else "executor"


def write_plan_ending(x, state: str, chain: list) -> None:
    """Design section 7.6 step 5, and the section document of a sub-agent thread.

    `x` is the run that ends and `chain` the earlier runs of its thread, newest first.
    """
    from database import agent_plans, agent_runs

    if not x.plan_run_id:
        return
    user, session, plan_run_id = x.username, x.session_id, x.plan_run_id
    first = chain[-1] if chain else x
    if x.depth >= 1:
        if state == agent_runs.COMPLETED and first.plan_node_id:
            kind = "review" if first.purpose == "review" else "report"
            agent_plans.write_document(user, session, plan_run_id, first.run_id,
                                       first.plan_node_id, _role(first.purpose), kind,
                                       x.result, attempt=1 if first.purpose == "correct" else 0)
        return
    if x.kind == "planner":
        if state == agent_runs.COMPLETED:
            plan_run = agent_plans.read_plan_run(user, session, plan_run_id)
            snapshot = (agent_plans.read_snapshot(user, session, plan_run.plan_id)
                        if plan_run else None)
            agent_plans.write_plan_run(user, session, plan_run_id,
                                       state=agent_plans.AWAITING_REVIEW,
                                       reviewed_version=snapshot.version if snapshot else 0)
        else:
            agent_plans.write_plan_run(user, session, plan_run_id, state=state)
        return
    if x.kind == "organizer":
        entries = section_entries(user, session, plan_run_id)
        changes = {"state": state}
        if entries:
            changes["sections_json"] = json.dumps(entries, sort_keys=True)
        if state == agent_runs.COMPLETED:
            plan_run = agent_plans.read_plan_run(user, session, plan_run_id)
            root = agent_plans.root_node_id(plan_run.plan_id) if plan_run else plan_run_id
            agent_plans.write_document(user, session, plan_run_id, x.run_id, root,
                                       "organizer", "final", x.result)
        agent_plans.write_plan_run(user, session, plan_run_id, **changes)


__all__ = [
    "APPROVED_TEXT", "PLAN_KINDS", "REJECTED_TEXT", "approved_sections", "final_answer",
    "open_plan_run", "plan_id_for", "plan_reference", "refresh_sections", "section_entries",
    "write_plan_ending", "write_prompt_document",
]
