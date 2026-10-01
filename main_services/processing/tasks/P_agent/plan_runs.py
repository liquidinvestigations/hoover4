"""The plan layer of the `AgentRun` activities: the plan run state, the frozen execution
settings, the section assignments, the section documents and `sections_json`.

A deep-research request is a plan run. A planner run builds the tree with the plan tools and
answers with an orientation. The person then approves, rejects or cancels it, and each
approve or reject starts a new run. An approval starts the organizer. Before its first model
call, the controller starts one sub-agent for each section of the approved tree, and the
organizer then combines their reports. No run waits for a person.

| plan run state | the run that causes it | writer here |
|---|---|---|
| `planning` | a round 0 planner starts | `open_plan_run` |
| `revising` | a planner of round 1 or later starts | `open_plan_run` |
| `awaiting_review` | the planner's thread answers | `write_plan_ending` |
| `executing` | the organizer starts | `open_plan_run` |
| `completed` | the organizer answers after the sections ended | `write_plan_ending` |
| `failed` | a planner or organizer run fails | `write_plan_ending` |
| `cancelled` | a cancel reaches the depth 0 run | `write_plan_ending` |

The website writes `cancelled` only for a plan in `awaiting_review`, when no run is open.
Every write here reads the row first and writes `state_version + 1`, and a write whose
changes the row already holds writes nothing, so a retry changes nothing that the first
attempt wrote.

**Execution settings.** The first run of a plan writes the `execution_settings` document:
the resolved model, the internet switch, the source of the model and the plan contract.
Every later run of the plan, planner, organizer and sub-agent alike, runs with that model
and switch (`frozen_settings`). The collections are not in it: the website checks them at
each start, and the collection server checks them at each call.

**Sections.** A section is a direct child of the approved root. `section_briefings` gives
one assignment for each, with the person's request, the clarifications, the orientation, the
evidence of the planner, the section's whole subtree and the permitted collections.

**Section documents.** A sub-agent thread of a section writes its briefing as a `prompt`
document when its row is written. Every ending of the thread's last run, completed, failed
or cancelled, writes the text report as a `report` document and the typed report as a
`report_data` document (`reports.py`), after the run's terminal row. All three are keyed by
the thread's first run and written under its `plan_node_id`. The organizer writes the final
report as a `final` document.
"""

from __future__ import annotations

import json
import logging
import uuid

log = logging.getLogger(__name__)

#: The opening message of a planner round after a rejection. The comment follows it.
REJECTED_TEXT = "The person rejected plan version {version}. Their comment:"
ANSWERED_QUESTION_TEXT = "The person answered your question: {comment}"
#: The opening message of the organizer.
APPROVED_TEXT = "Run the approved plan, version {version}."
#: The message that gives the organizer the outcome of each section, before the JSON.
SECTIONS_ENDED_TEXT = (
    "Every section of the approved plan ended. The JSON below gives the outcome of each "
    "section, and its report text when the run wrote one. Read a whole report, its "
    "evidence and its failures with read_plan_report and the section's node. Combine the "
    "reports into one answer to the root question.")

PLAN_KINDS = ("planner", "organizer")

#: The source of the frozen model of a plan run: the model of the first planner request,
#: the model that the website resolved for an older plan, or the configured default.
MODEL_SOURCES = ("request", "legacy_planner", "configured_default")

#: The most characters of each part of the planning context in a section briefing.
MAX_CONTEXT_CHARS = 6_000
#: The most documents of the planner's evidence that a section briefing names.
MAX_BRIEFING_DOCUMENTS = 20


def plan_id_for(plan_run_id: str) -> str:
    """The plan id of a plan run. One plan run has one tree."""
    from database import agent_plans

    return str(uuid.uuid5(agent_plans.PLAN_NAMESPACE, f"plan:{plan_run_id}"))


def _settings_of(inp, source: str = "") -> dict:
    from tasks.P_agent.stream_writer import _chat_model
    from database import agent_plans

    model = (inp.llm_model or "").strip()
    if not source:
        source = "request" if model else "configured_default"
    return {"version": 1, "plan_contract": agent_plans.PLAN_CONTRACT,
            "model": model or _chat_model(), "model_source": source,
            "internet_tools": bool(inp.internet_tools)}


def freeze_settings(inp) -> dict:
    """The execution settings of the plan run of `inp`, written once. A plan run from
    before the settings gets them from this input, with the source that the website
    resolved (`inp.model_source`)."""
    from database import agent_plans

    user, session, plan_run_id = inp.username, inp.session_id, inp.plan_run_id
    stored = agent_plans.read_execution_settings(user, session, plan_run_id)
    if stored is not None:
        return stored
    settings = _settings_of(inp, getattr(inp, "model_source", "") or "")
    agent_plans.write_execution_settings(
        user, session, plan_run_id, agent_plans.root_node_id(plan_id_for(plan_run_id)),
        settings)
    log.info("[P_agent] plan run %s runs with model %s (%s)", plan_run_id,
             settings["model"], settings["model_source"])
    return settings


def frozen_settings(username: str, session_id: str, plan_run_id: str) -> dict | None:
    """The execution settings of a plan run, or None for a plan run from before them."""
    from database import agent_plans

    if not plan_run_id:
        return None
    return agent_plans.read_execution_settings(username, session_id, plan_run_id)


def open_plan_run(inp, question: str) -> str:
    """Write the plan run state and the execution settings of a new planner or organizer
    run. Return its opening text.

    `question` is the text of the user row at `turn_seq`, the deep-research message for
    round 0. A retry finds the state already moved and writes nothing again. The organizer
    freezes the version of its decision as the approved version.
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
        freeze_settings(inp)
        return question
    decision = agent_plans.read_decision(user, session, plan_run_id, inp.decision_id)
    if decision is None:
        raise RuntimeError(f"decision {inp.decision_id} of plan run {plan_run_id} has no row")
    current = agent_plans.read_plan_run(user, session, plan_run_id)
    if current is None:
        raise RuntimeError(f"plan run {plan_run_id} has no row")
    freeze_settings(inp)
    if inp.kind == "planner":
        if current.state == agent_plans.AWAITING_REVIEW:
            agent_plans.write_plan_run(user, session, plan_run_id, state=agent_plans.REVISING,
                                       review_round=current.review_round + 1)
        if _last_planner_asked(user, session, plan_run_id, inp.run_id):
            return ANSWERED_QUESTION_TEXT.format(comment=decision.comment)
        return f"{REJECTED_TEXT.format(version=decision.reviewed_version)}\n\n{decision.comment}"
    if decision.action != "approve":
        raise RuntimeError(f"decision {inp.decision_id} is {decision.action!r}, not an approval")
    if current.state == agent_plans.AWAITING_REVIEW:
        agent_plans.write_plan_run(user, session, plan_run_id, state=agent_plans.EXECUTING,
                                   approved_version=decision.reviewed_version)
    return APPROVED_TEXT.format(version=decision.reviewed_version)


def _plan_rows(username: str, session_id: str, plan_run_id: str):
    from tasks.P_agent.activities import _read_rows

    return _read_rows("plan_run_id = {p:UUID}",
                      {"u": username, "s": session_id, "p": plan_run_id})


def _last_planner_asked(username: str, session_id: str, plan_run_id: str,
                        current_run_id: str) -> bool:
    """Return whether the preceding planner round ended with a question call."""
    prior = [row for row in _plan_rows(username, session_id, plan_run_id)
             if row.kind == "planner" and row.run_id != current_run_id]
    return bool(prior) and _asked(prior[-1])


def _asked(row) -> bool:
    """Whether the thread of a planner row holds a successful question call."""
    from database import agent_runs

    messages = agent_runs.read_messages(row.username, row.session_id, row.thread_id)
    return any(message.role == "tool" and message.tool_name == "ask_user"
               and message.usage.get("status") == "ok" for message in messages)


def _approved_snapshot(username: str, session_id: str, plan_run_id: str):
    from database import agent_plans

    plan_run = agent_plans.read_plan_run(username, session_id, plan_run_id)
    if plan_run is None or not plan_run.approved_version:
        return None, None
    snapshot = agent_plans.read_snapshot(username, session_id, plan_run.plan_id,
                                         plan_run.approved_version)
    return plan_run, snapshot


def section_entries(username: str, session_id: str, plan_run_id: str) -> list[dict]:
    """The `sections_json` entries of an approved plan, derived from the run rows and the
    report documents (`agent_plans.section_states`). Empty before approval. A plan run from
    before the execution settings keeps its stored entries, whose sections follow the older
    rule."""
    from database import agent_plans

    plan_run, snapshot = _approved_snapshot(username, session_id, plan_run_id)
    if plan_run is None or snapshot is None:
        return []
    if frozen_settings(username, session_id, plan_run_id) is None:
        try:
            stored = json.loads(plan_run.sections_json or "[]")
        except ValueError:
            stored = []
        return stored if isinstance(stored, list) else []
    rows = _plan_rows(username, session_id, plan_run_id)
    by_thread: dict[str, list] = {}
    for row in rows:
        by_thread.setdefault(row.thread_id, []).append(row)
    documents = {d.document_id for d in agent_plans.read_documents(username, session_id,
                                                                   plan_run_id)}
    runs = []
    for row in rows:
        if not row.plan_node_id or row.continues_run_id or row.depth < 1:
            continue
        newest = by_thread.get(row.thread_id, [row])[-1]
        data = agent_plans.read_report_data(username, session_id, plan_run_id, row.run_id)
        report = ("typed" if data is not None else
                  "text" if agent_plans.document_id(row.run_id, "report") in documents else "")
        execution = (data or {}).get("execution") or {}
        runs.append(agent_plans.SectionRun(
            row.plan_node_id, newest.state, run_id=row.run_id, end_reason=newest.end_reason,
            error=newest.error, report=report, incomplete=bool(execution.get("incomplete"))))
    return agent_plans.section_states(snapshot, runs)


def refresh_sections(username: str, session_id: str, plan_run_id: str) -> list[dict]:
    """Write `sections_json` of an executing plan run from the rows. Return the entries."""
    from database import agent_plans

    entries = section_entries(username, session_id, plan_run_id)
    if entries:
        agent_plans.write_plan_run(username, session_id, plan_run_id,
                                   sections_json=json.dumps(entries, sort_keys=True))
    return entries


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


def planner_visible_answer(row, answer: str) -> str:
    """Keep unfinished or raw plan data out of the planner's answer row."""
    from database import agent_plans

    plan_run = agent_plans.read_plan_run(row.username, row.session_id, row.plan_run_id)
    snapshot = (agent_plans.read_snapshot(row.username, row.session_id, plan_run.plan_id)
                if plan_run else None)
    if snapshot is None or not agent_plans.sections(snapshot):
        return "The plan has no section. Research cannot start from this plan."
    stripped = (answer or "").strip()
    if stripped.startswith(("{", "[{", "```json", "write_plan(")):
        return "The plan is ready for review. Its sections appear below."
    return answer


# ------------------------------------------------------------------ section assignments


def _clip(text: str, limit: int = MAX_CONTEXT_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"\n[cut at {limit:,} of {len(text):,} characters]"


def planning_context(username: str, session_id: str, plan_run_id: str) -> dict:
    """The context that every section briefing of a plan repeats: the person's request,
    the clarifications of later planner rounds, the orientation of the newest planner, and
    the documents that the planners read or cited."""
    from database import agent_runs
    from tasks.P_agent import reports

    rows = _plan_rows(username, session_id, plan_run_id)
    planners = [r for r in rows if r.kind == "planner" and r.depth == 0
                and not r.continues_run_id]
    by_thread: dict[str, list] = {}
    for row in rows:
        by_thread.setdefault(row.thread_id, []).append(row)
    request, clarifications, documents = "", [], []
    seen: set[tuple[str, str]] = set()
    for i, planner in enumerate(planners):
        messages = agent_runs.read_messages(username, session_id, planner.thread_id)
        opening = messages[0].content if messages else ""
        if i == 0:
            request = opening
        else:
            prior = by_thread.get(planners[i - 1].thread_id, [planners[i - 1]])[-1]
            if _asked(prior) and prior.result:
                clarifications.append(f"The planner asked: {_clip(prior.result, 2_000)}")
            clarifications.append(_clip(opening, 2_000))
        entries, _ = reports.thread_evidence(messages, planner.thread_id)
        for entry in entries:
            ref = entry.get("reference") or {}
            key = (str(ref.get("collectionname") or ""), str(ref.get("file_hash") or ""))
            if (entry.get("kind") not in (reports.KIND_READ, reports.KIND_CITATION)
                    or entry.get("status") == reports.STATUS_ERROR or not key[1]
                    or key in seen or len(documents) >= MAX_BRIEFING_DOCUMENTS):
                continue
            seen.add(key)
            documents.append({"collectionname": key[0], "file_hash": key[1],
                              "path": str(ref.get("path") or "")})
    orientation = ""
    if planners:
        newest = by_thread.get(planners[-1].thread_id, [planners[-1]])[-1]
        orientation = newest.result or ""
    return {"request": _clip(request), "clarifications": clarifications,
            "orientation": _clip(orientation), "documents": documents}


def render_section_briefing(section: str, subtree: str, context: dict,
                            collections: list[str], internet_tools: bool) -> str:
    """The opening message of the sub-agent of one section."""
    parts = [f"Objective: research section {section} of the approved plan, with every "
             "task under it, in their order.",
             f"The section and its tasks:\n{subtree}"]
    if context.get("request"):
        parts.append(f"The person's request:\n{context['request']}")
    if context.get("clarifications"):
        parts.append("Clarifications from the planning rounds:\n"
                     + "\n\n".join(context["clarifications"]))
    if context.get("orientation"):
        parts.append(f"The planner's orientation, a guide that is not evidence:\n"
                     f"{context['orientation']}")
    if context.get("documents"):
        lines = [f"- {d['collectionname']} {d['path'] or '(no path)'} file_hash "
                 f"{d['file_hash']}" for d in context["documents"]]
        parts.append("Documents that the planner read or cited:\n" + "\n".join(lines))
    scope = ", ".join(collections) if collections else "none"
    parts.append(f"Permitted collections: {scope}. Web tools: "
                 f"{'available' if internet_tools else 'not available'}.")
    parts.append("Answer this section only. Other researchers run the other sections. "
                 "Write your report as prose, cite the documents you relied on with "
                 "`cite_documents`, and name each task that you could not complete and why.")
    return "\n\n".join(parts)


def section_briefings(username: str, session_id: str, plan_run_id: str,
                      collections: list[str], settings: dict) -> list[tuple[str, dict, str]]:
    """`(node_id, briefing, text)` of each section of the approved tree, in tree order.
    The briefing is the stored JSON of the sub-agent row, and the text its opening
    message."""
    from database import agent_plans

    plan_run, snapshot = _approved_snapshot(username, session_id, plan_run_id)
    if plan_run is None or snapshot is None:
        return []
    paths = agent_plans.node_paths(snapshot)
    context = planning_context(username, session_id, plan_run_id)
    out = []
    for node, _tasks in agent_plans.sections(snapshot):
        subtree = agent_plans.render_tree(snapshot, node.node_id)
        briefing = {
            "controller": True, "objective": node.text, "plan_node_id": node.node_id,
            "section": paths[node.node_id], "purpose": agent_plans.EXECUTE,
            "approved_version": plan_run.approved_version,
            "model": settings.get("model", ""),
            "internet_tools": bool(settings.get("internet_tools")),
            "collections": list(collections),
        }
        text = render_section_briefing(paths[node.node_id], subtree, context,
                                       list(collections), bool(settings.get("internet_tools")))
        out.append((node.node_id, briefing, text))
    return out


def section_outcome(child, paths: dict[str, str]) -> dict:
    """The outcome of one section's sub-agent in the organizer's message: the node that
    `read_plan_report` takes, the state and failure cause, the report text, and the counts
    of the typed report. The organizer reads the evidence itself through the tool."""
    from database import agent_plans

    node = child.plan_node_id or ""
    out: dict = {"node": paths.get(node, node), "state": child.state}
    if child.end_reason:
        out["end_reason"] = child.end_reason
    if child.error:
        out["error"] = child.error
    data = agent_plans.read_report_data(child.username, child.session_id, child.plan_run_id,
                                        child.run_id)
    if data is not None:
        diagnostics = data.get("diagnostics") or {}
        out["evidence"] = {
            "documents_read": sum(1 for e in data.get("documents_read") or []
                                  if e.get("status") != "error"),
            "failed_items": int(diagnostics.get("failed_items") or 0),
            "citations": sum(1 for e in data.get("citations") or []
                             if e.get("status") == "ok"),
            "notes": len(data.get("notes") or []),
        }
        if not (child.result or "").strip() and data.get("recent_text"):
            out["latest_text"] = str(data["recent_text"][-1].get("text") or "")
    out["report"] = child.result or ""
    return out


def write_prompt_document(child, briefing_text: str) -> None:
    """The `prompt` document of a new sub-agent thread of a plan section."""
    from database import agent_plans

    if not (child.plan_run_id and child.plan_node_id):
        return
    agent_plans.write_document(
        child.username, child.session_id, child.plan_run_id, child.run_id,
        child.plan_node_id, "executor", "prompt", briefing_text)


def write_plan_ending(x, state: str, chain: list, error: str = "") -> None:
    """Write the plan state when a planner or organizer run ends.

    `x` is the run that ends, `chain` the earlier runs of its thread, newest first, and
    `error` the error of a failed ending. It writes nothing for a sub-agent thread: its
    `report` and `report_data` documents follow its terminal row in
    `activities._write_ending`, in every terminal state. A completed organizer completes
    the plan whatever its sections did, and `sections_json` names each failed section.
    """
    from database import agent_plans, agent_runs

    if not x.plan_run_id:
        return
    user, session, plan_run_id = x.username, x.session_id, x.plan_run_id
    if x.depth >= 1:
        # A sub-agent thread's report pair is written by `_write_ending` after the run's
        # terminal row (`reports.materialize`).
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
    "ANSWERED_QUESTION_TEXT", "APPROVED_TEXT", "MODEL_SOURCES", "PLAN_KINDS",
    "REJECTED_TEXT", "SECTIONS_ENDED_TEXT", "final_answer", "freeze_settings",
    "frozen_settings", "open_plan_run", "plan_id_for", "plan_reference", "planning_context",
    "refresh_sections", "render_section_briefing", "section_briefings", "section_entries",
    "section_outcome", "write_plan_ending", "write_prompt_document",
]
