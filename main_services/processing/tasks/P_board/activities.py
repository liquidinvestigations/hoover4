"""Board activities: plan, reason, open an explore turn, conclude it, convert its report,
record its end.

`board_plan` is the only writer of `board_state`, `board_intents` and the derived
`status_changed` rows. It folds the events of every live board, reconciles running intents
whose `BoardExplore` closed, submits the commands of its decisions and returns the work to
start or cancel. Every canonical event and fact goes through the command writer
(`commands.py`): the activities here submit command inputs, and `BoardCommands` writes the
rows. A board with an uncommitted command gets no new decision until it commits.

A decision to start work is a command too. The dispatcher starts an explore or an
assessment only after `board_plan` reports its start command as committed, so a refused
start runs nothing.

An explore is an ordinary chat turn: `open_explore_turn` writes the session, the user row and
the stream row that `send_message` writes for a person, and the turn runs as `AgentRun`. The
turn writes its result as a workspace report. `conclude_explore` reads the end of the turn:
a question, a failure, or the report to convert. `convert_explore_report` turns the pinned
report version into the fact with one model request (`conversion.py`) and submits it.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field

from temporalio import activity

from tasks.heartbeat import with_heartbeat
from tasks.P_agent.activities import AgentRunInput, effective_internet_tools
from tasks.P_board import model as m
from tasks.P_board import commands as cmd
from tasks.P_board.contracts import parse_reason
from tasks.P_board.fold import (
    canonical_events,
    earlier_objectives,
    fold,
    may_explore,
    plan,
    visible_facts,
)
from tasks.P_board.prompts import (
    goal_texts,
    open_question_keys,
    render_brief,
    render_reason,
)

log = logging.getLogger(__name__)

#: The namespace of the uuid5 keys of explore turns and runs.
BOARD_NAMESPACE = uuid.UUID("a7d1c3f2-5b8e-4c6a-9e0d-3f1b2c4d5e6f")

#: The `server_settings` key of the global cap on board model work.
SETTING_CAP = "board_max_parallel_explores"

#: A running intent younger than this is not reconciled, so a workflow that is starting is
#: not read as absent.
RECONCILE_GRACE_SECONDS = 60


@dataclass
class PlanInput:
    #: The boards with a reason in flight or a reason start that waits for its commit.
    in_flight_reasons: list[str] = field(default_factory=list)
    #: The start commands that the dispatcher waits for, as `<board_id> <request_id>`.
    awaiting: list[str] = field(default_factory=list)


@dataclass
class ReasonTask:
    board_id: str
    reason_no: int
    stalled: bool = False
    #: A final assessment of the used budget `assessed_budget`. Older tasks decode as False.
    final: bool = False
    assessed_budget: int = 0
    assessment_id: str = ""
    #: The request id of the start command.
    request_id: str = ""


@dataclass
class ExploreTask:
    board_id: str
    intent_id: str
    attempt: int
    #: The request id of the start command. Empty in a task of an older history.
    request_id: str = ""


@dataclass
class PlanOutput:
    reasons: list[ReasonTask] = field(default_factory=list)
    explores: list[ExploreTask] = field(default_factory=list)
    cancels: list[str] = field(default_factory=list)
    #: At most one board with a pending label or a stale summary (`labels.label_due`). A
    #: result in a history written before this field decodes with an empty list.
    labels: list[str] = field(default_factory=list)
    #: The boards whose `BoardCommands` must run: an input waits or a receipt is prepared.
    command_boards: list[str] = field(default_factory=list)
    #: The awaited start commands, as `<board_id> <request_id>`, that are committed or refused.
    committed: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)


@dataclass
class ReasonFailure:
    board_id: str
    reason_no: int
    stalled: bool = False
    error: str = ""


@dataclass
class FinalFailure:
    board_id: str
    assessed_budget: int
    error: str = ""


@dataclass
class TurnRequest:
    board_id: str
    intent_id: str
    attempt: int
    #: Always `explore`. It is part of the identity of the turn (`_turn_uuid`).
    phase: str = "explore"
    #: Why the `AgentRun` of the turn failed, or empty when it completed.
    turn_error: str = ""


@dataclass
class Concluded:
    """The end of an explore turn. `outcome` is `fact`, `question`, `failed`, `skipped`, or
    `convert` when `report` names the report version to convert."""

    outcome: str
    report: dict = field(default_factory=dict)


@dataclass
class OpenedTurn:
    skip_kind: str = ""
    skip_reason: str = ""
    workflow_id: str = ""
    run_input: AgentRunInput | None = None


@dataclass
class EndRequest:
    board_id: str
    intent_id: str
    attempt: int
    kind: str
    error: str = ""
    #: The report version of a failed conversion, `{name, version}`, or empty.
    report: dict = field(default_factory=dict)


# --------------------------------------------------------------------------------- plan


def _cap() -> int:
    from database.clickhouse import get_server_setting

    try:
        return max(1, int((get_server_setting(SETTING_CAP) or "1").strip()))
    except (TypeError, ValueError):
        return 1


async def _workflow_closed(client, workflow_id: str) -> tuple[bool, str]:
    from temporalio.client import WorkflowExecutionStatus
    from temporalio.service import RPCError, RPCStatusCode

    try:
        description = await client.get_workflow_handle(workflow_id).describe()
    except RPCError as exc:
        if exc.status == RPCStatusCode.NOT_FOUND:
            return True, "absent"
        raise
    if description.status == WorkflowExecutionStatus.RUNNING:
        return False, ""
    return True, description.status.name


def _reconcile(stale: list[tuple[str, object]]) -> list[tuple[str, str, dict]]:
    """The end commands of running intents whose `BoardExplore` closed without an end:
    `(board_id, request_id, body)`. A fact that the intent wrote without its event names
    itself, so its explore concludes in that fact."""
    from database import boards
    from temporalio.client import Client

    async def run() -> list:
        client = await Client.connect("temporal:7233")
        ends = []
        for board_id, intent in stale:
            closed, status = await _workflow_closed(client, m.explore_workflow_id(board_id, intent.intent_id))
            if not closed:
                continue
            attempt = intent.running_attempt
            body = {"intent_id": intent.intent_id, "attempt": attempt, "actor": "dispatcher"}
            written = [f for f in boards.facts_of_intent(board_id, intent.intent_id) if not f.request_id]
            if written:
                body.update(end=m.EXPLORE_CONCLUDED, existing_fact=written[0].fact_id)
            elif status == "absent":
                body.update(end=m.EXPLORE_CANCELLED, error="the explore workflow never started")
            else:
                body.update(end=m.EXPLORE_FAILED, error=f"the explore workflow ended with status {status}")
            ends.append((board_id, f"explore_end:{intent.intent_id}:{attempt}", body))
        return ends

    return asyncio.run(run())


def _answers(folded, answers: dict) -> list[dict]:
    """The goal answers of `answers` in goal order, for the state summary."""
    return [answers[g] for g in folded.goal_ids if g in answers]


def _state_rows(board, folded) -> tuple[dict, list[dict]]:
    from database import boards

    now = boards.now()
    by_kind: dict[str, int] = {}
    for intent in folded.intents.values():
        by_kind[intent.state] = by_kind.get(intent.state, 0) + 1
    summary = {"intents": by_kind, "facts": folded.fact_count, "sourced": folded.sourced_count,
               "hints": len(folded.hints), "rejected": len(folded.rejected),
               "review_statement": folded.review_statement,
               "answers_proposed": [dict(a, later_drops=folded.answer_drops.get(a["goal"], []))
                                    for a in _answers(folded, folded.proposed)],
               "answers_accepted": _answers(folded, folded.accepted),
               "not_answered": folded.not_answered,
               "max_explores": folded.max_explores,
               "explore_steps": folded.explore_steps,
               "explore_limit": m.EXPLORE_LIMIT,
               "limit_reached": folded.limit_reached,
               "decision_id": folded.decision_id,
               "review_reason": folded.review_reason,
               "extended": sorted(folded.extended),
               "grants": folded.grants,
               "final_at_budget": folded.final_at_budget,
               "final_ops": folded.final_ops,
               "intent_questions": {i.intent_id: i.questions for i in folded.intents.values() if i.questions},
               "intent_origins": {i.intent_id: {"origin": i.origin, "own": i.own, "fact_id": i.source_fact}
                                  for i in folded.intents.values()}}
    state = {"board_id": board.board_id, "status": folded.status,
             "explores_used": max(0, folded.explores_used), "reasons_done": folded.reasons_done,
             "stall_count": min(255, folded.stall_count),
             "invalid_reasons": min(255, folded.invalid_reasons),
             "checkpoint_json": json.dumps(folded.checkpoint, sort_keys=True),
             "summary_json": json.dumps(summary, sort_keys=True), "version": 0, "updated_at": now}
    intents = []
    for intent in folded.intents.values():
        intents.append({
            "board_id": board.board_id, "intent_id": intent.intent_id,
            "from_facts": intent.from_facts, "objective": intent.objective, "brief": intent.brief,
            "state": intent.state, "attempts": max(0, intent.attempts),
            "session_id": m.session_id_for(board.board_id, intent.intent_id) if intent.started else "",
            "fact_id": intent.fact_id, "question": intent.question, "last_error": intent.last_error[:2000],
            "created_at": intent.created_at or now, "version": 0, "updated_at": now})
    return state, intents


_COMPARED_STATE = ("status", "explores_used", "reasons_done", "stall_count", "invalid_reasons",
                   "checkpoint_json", "summary_json")
_COMPARED_INTENT = ("from_facts", "objective", "brief", "state", "attempts", "session_id",
                    "fact_id", "question", "last_error")


def _write_changed(board_id: str, state: dict, intents: list[dict]) -> None:
    from database import boards

    stored_state, stored_intents = boards.read_state_rows(board_id)
    version = time.time_ns()
    if stored_state and all(stored_state[k] == state[k] for k in _COMPARED_STATE):
        state = {}
    else:
        state["version"] = version
    changed = []
    for row in intents:
        old = stored_intents.get(row["intent_id"])
        if old and all(list(old[k]) == list(row[k]) if isinstance(row[k], list) else old[k] == row[k]
                       for k in _COMPARED_INTENT):
            continue
        row["version"] = version
        changed.append(row)
    boards.write_state(state, changed)


def status_rows(board_id: str, events: list, folded) -> list:
    """The derived `status_changed` rows of the transitions that the stored events lack.
    Each row is named by its causal event and its position there, and carries the time of
    its cause, so a repeated pass writes the same row."""
    from database import boards

    stored = {e.event_id for e in events if e.event_type == m.STATUS_CHANGED}
    rows = []
    for t in folded.transitions:
        event_id = f"{m.STATUS_CHANGED}:{t.event_id}:{t.ordinal}"
        if event_id in stored:
            continue
        rows.append(boards.EventRow(board_id, event_id, m.STATUS_CHANGED, "board", t.status,
                                    {"causal_event_id": t.event_id, "ordinal": t.ordinal,
                                     "prior": t.prior, "status": t.status, "causal_seq": t.seq},
                                    t.created_at))
    return rows


def _submit(board_id: str, request_id: str, kind: str, actor: str, body: dict) -> None:
    """Write one command input of the worker. A dropped board gets none: its command rows
    are deleted with the board, and a late input would stay without a writer."""
    from database import board_commands as bc
    from database import boards

    if boards.board_is_live(board_id):
        bc.submit(board_id, request_id, kind, actor, body)


@activity.defn
@with_heartbeat
def board_plan(inp: PlanInput) -> PlanOutput:
    """One pass of the dispatcher: fold, reconcile, decide, submit, and return the work.

    A board with an uncommitted command gets no new decision, and its pending explore starts
    take slots. The decisions are submitted as commands. The output names the boards whose
    command writer must run and the awaited start commands that are decided."""
    from database import board_commands as bc
    from database import boards

    live = boards.read_live_boards()
    awaited = [tuple(k.split(" ", 1)) for k in inp.awaiting if " " in k]
    decided = bc.states(awaited)
    committed = [f"{b} {r}" for (b, r), state in decided.items() if state == bc.COMMITTED]
    rejected = [f"{b} {r}" for (b, r), state in decided.items() if state in (bc.REJECTED, bc.UNKNOWN)]
    if not live:
        return PlanOutput(committed=committed, rejected=rejected)
    ids = [b.board_id for b in live]
    pending = bc.pending_commands(ids)
    busy = {b for b, _, _ in pending}
    reserved: dict[str, int] = {}
    for board_id, _request, kind in pending:
        if kind == cmd.START_EXPLORE:
            reserved[board_id] = reserved.get(board_id, 0) + 1
    in_flight = set(inp.in_flight_reasons)
    snapshots = {}
    stale = []
    cutoff = boards.now().timestamp() - RECONCILE_GRACE_SECONDS
    for board in live:
        events, facts = boards.read_events(board.board_id), boards.read_facts(board.board_id)
        folded = fold(board, events, facts)
        snapshots[board.board_id] = (events, visible_facts(facts, canonical_events(events)), folded)
        if board.board_id in busy:
            continue
        for intent in folded.by_state(m.RUNNING):
            since = intent.running_since
            if since is None or since.timestamp() < cutoff:
                stale.append((board.board_id, intent))
    submitted: set[str] = set()
    for board_id, request_id, body in (_reconcile(stale) if stale else []):
        _submit(board_id, request_id, cmd.EXPLORE_END, "dispatcher", body)
        submitted.add(board_id)
    folded_by_id = {board_id: snap[2] for board_id, snap in snapshots.items()}
    actions = plan(live, folded_by_id, in_flight, _cap(), busy | submitted, reserved)
    reasons, explores = [], []
    for reason in actions.reasons:
        request_id = f"reason_started:{reason.reason_no}"
        body = {"reason_no": reason.reason_no, "stalled": reason.stalled}
        if reason.final:
            body.update(final=True, assessed_budget=reason.assessed_budget, assessment_id=reason.assessment_id)
        _submit(reason.board_id, request_id, cmd.START_REASON, "dispatcher", body)
        submitted.add(reason.board_id)
        reasons.append(ReasonTask(reason.board_id, reason.reason_no, reason.stalled, reason.final,
                                  reason.assessed_budget, reason.assessment_id, request_id))
    for explore in actions.explores:
        request_id = f"explore_started:{explore.intent_id}:{explore.attempt}"
        _submit(explore.board_id, request_id, cmd.START_EXPLORE, "dispatcher",
                {"intent_id": explore.intent_id, "attempt": explore.attempt})
        submitted.add(explore.board_id)
        explores.append(ExploreTask(explore.board_id, explore.intent_id, explore.attempt, request_id))
    for board_id, why in actions.reviews:
        f = folded_by_id[board_id]
        _submit(board_id, f"review_proposed:{why}:{f.last_seq}", cmd.REVIEW_PROPOSED, "dispatcher",
                {"why": why})
        submitted.add(board_id)
    for board_id, budget in actions.final_failures:
        _submit(board_id, f"final_ended:final-{budget}", cmd.FINAL_ENDED, "dispatcher",
                {"assessed_budget": budget, "outcome": "failed",
                 "error": "the final assessment ended without a result"})
        submitted.add(board_id)
    for board in live:
        events, _facts, folded = snapshots[board.board_id]
        rows = status_rows(board.board_id, events, folded)
        if rows:
            boards.write_events(rows)
        state, intents = _state_rows(board, folded)
        _write_changed(board.board_id, state, intents)
    return PlanOutput(
        reasons=reasons, explores=explores,
        cancels=[m.explore_workflow_id(b, i) for b, i in actions.cancels],
        labels=_label_candidates([b for b in live if b.board_id not in busy | submitted], snapshots)[:1],
        command_boards=sorted(busy | submitted), committed=committed, rejected=rejected,
    )


@activity.defn
@with_heartbeat
def record_final_failure(failure: FinalFailure) -> None:
    """Record the end of a final assessment whose call failed in every attempt. The same
    request id makes a retry harmless."""
    _submit(failure.board_id, f"final_ended:final-{failure.assessed_budget}", cmd.FINAL_ENDED,
            "dispatcher", {"assessed_budget": failure.assessed_budget, "outcome": "failed",
                           "error": failure.error[:2000]})


def _label_candidates(live: list, snapshots: dict) -> list[str]:
    """The boards that need a label call now, in board order. Every board that is not
    dropped counts, also a completed board. A failed read costs the labels of this pass."""
    from database import boards
    from tasks.P_board.labels import label_due

    try:
        rows = boards.read_labels([b.board_id for b in live])
    except Exception:  # noqa: BLE001 - labels never cost a pass of the dispatcher
        log.warning("[P_board] could not read the board labels", exc_info=True)
        return []
    by_board: dict[str, list] = {}
    for row in rows:
        by_board.setdefault(row.board_id, []).append(row)
    now_ts = boards.now().timestamp()
    out = []
    for board in live:
        _events, facts, folded = snapshots[board.board_id]
        if label_due(facts, folded, by_board.get(board.board_id, []), now_ts):
            out.append(board.board_id)
    return out


# ------------------------------------------------------------------------------- reason


def _record_llm_call(owner: str, board_id: str, model: str, usage: dict, latency_ms: int,
                     ok: bool, error: str, reply_bytes: int, kind: str = "board_reason") -> None:
    """One `llm_call_events` row of a board model call. `kind` is `board_reason`,
    `board_label` or `board_summary`."""
    from tasks.P_agent.summarize import record_call

    record_call(owner, f"{m.SESSION_PREFIX}{board_id}", kind, model, usage, latency_ms, ok,
                error, reply_bytes)


def _read(board) -> tuple[list, list, object]:
    """The events, the visible facts and the fold of one board."""
    from database import boards

    events, facts = boards.read_events(board.board_id), boards.read_facts(board.board_id)
    folded = fold(board, events, facts)
    return events, visible_facts(facts, canonical_events(events)), folded


#: The connect timeout of the assessment request. The read timeout is
#: `board_reason_request_seconds`.
REASON_CONNECT_SECONDS = 10


def _reason_submitted(board_id: str, reason_no: int) -> bool:
    """Whether a `reason_result` command of this assessment exists, so an attempt after a
    lost worker makes no second model call."""
    from database import board_commands as bc

    key = (board_id, f"reason_result:{reason_no}")
    return bc.states([key]).get(key, bc.UNKNOWN) != bc.UNKNOWN


@activity.defn
@with_heartbeat
def board_reason(task: ReasonTask) -> str:
    """One reason call. Submits one `reason_result` command and returns its outcome.

    A final assessment runs on a board that is not active too, because its result ends its
    operation. Its reply holds answers only.

    An attempt that finds the `reason_result` command of its assessment returns `reused`
    and sends no request. A transport failure is raised as `summarize.TransportFailure`, so
    Temporal sends the request once more. After the last attempt the workflow records
    `model_failure` (`record_reason_failure`). A refused request (4xx) or a reply that is not
    a completion gives `model_failure` at once, because a second request cannot change it.
    """
    from database import boards
    from tasks.P_agent import summarize
    from tasks.P_agent.model_timeouts import TIMEOUTS

    board = boards.read_board(task.board_id)
    if board is None or board.is_deleted:
        return "skipped"
    if _reason_submitted(board.board_id, task.reason_no):
        return "reused"
    _events, facts, folded = _read(board)
    citations = boards.read_citations(board.board_id)
    if folded.status != m.ACTIVE and not task.final:
        return "skipped"
    prompt = render_reason(board, folded, facts, citations, task.stalled, final=task.final)
    # An assessment decides the next work of the board, so it uses the agent model of the
    # explores and the report conversion. Titles, summaries and board labels use the
    # short-call model. The first request keeps the reasoning phase, which a new board needs
    # to declare its first intents. On a board with history the model can reason until the
    # cap, so a cut or empty reply goes to a second request without reasoning.
    from tasks.llm_endpoints import chat_model, endpoint_for

    model = chat_model()
    endpoint = endpoint_for(model)
    body = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    timeout = (REASON_CONNECT_SECONDS, TIMEOUTS.board_reason_request_seconds)
    started = time.monotonic()
    text, usage, error = "", {}, ""
    try:
        response = summarize.post_or_raise(
            endpoint, {**body, "max_tokens": m.REASON_THINKING_TOKENS}, timeout=timeout)
        response.raise_for_status()
        reply = response.json()
        choice = reply["choices"][0]
        text = choice["message"].get("content") or ""
        if choice.get("finish_reason") == "length" or not text.strip():
            _record_llm_call(board.owner, board.board_id, model, reply.get("usage") or {},
                             int((time.monotonic() - started) * 1000), False,
                             "the reasoning reached the token limit before a reply", len(response.text))
            plain = {**body, "max_tokens": m.REASON_MAX_TOKENS}
            response = summarize.post_or_raise(endpoint, {**plain, **summarize.NO_THINKING}, timeout=timeout)
            if 400 <= response.status_code < 500:
                # A provider that does not accept the hint refuses the request, so the
                # request goes again without the hint.
                response = summarize.post_or_raise(endpoint, plain, timeout=timeout)
            response.raise_for_status()
            reply = response.json()
            text = reply["choices"][0]["message"].get("content") or ""
        usage = reply.get("usage") or {}
    except summarize.TransportFailure as exc:
        _record_llm_call(board.owner, board.board_id, model, {},
                         int((time.monotonic() - started) * 1000), False, str(exc), 0)
        raise
    except Exception as exc:  # noqa: BLE001 - a refused request is a model failure, recorded
        error = f"{type(exc).__name__}: {exc}"[:500]
    latency_ms = int((time.monotonic() - started) * 1000)
    live = [f for f in facts if f.fact_id not in folded.rejected and f.kind != m.GOAL]
    idle = not folded.by_state(m.OPEN) and not folded.by_state(m.RUNNING)
    if error:
        payload = {"outcome": m.MODEL_FAILURE, "error": error, "raw": "", "problems": []}
    else:
        payload = parse_reason(text, {f.fact_id for f in live},
                               {f.fact_id for f in live if f.kind == m.SOURCED},
                               earlier_objectives(folded), idle, folded.open_goals,
                               {f.fact_id for f in live if f.kind == m.NOT_FOUND}, goal_texts(facts),
                               set(folded.accepted),
                               {key for key, _q in open_question_keys(folded, facts)}, task.final)
    payload.update(situation=folded.situation(), model=model, latency_ms=latency_ms,
                   semantics=m.REASON_SEMANTICS,
                   prompt_tokens=int(usage.get("prompt_tokens") or 0),
                   completion_tokens=int(usage.get("completion_tokens") or 0),
                   stalled=task.stalled)
    if task.final:
        payload.update(final=True, assessed_budget=task.assessed_budget, assessment_id=task.assessment_id)
    if boards.board_is_live(board.board_id):
        try:
            boards.write_assessment(board.board_id, task.reason_no, prompt, text, error, model)
        except Exception:  # noqa: BLE001 - the stored prompt never costs the reason
            log.warning("[P_board] could not store the prompt of reason %s of %s",
                        task.reason_no, board.board_id, exc_info=True)
        _submit(board.board_id, f"reason_result:{task.reason_no}", cmd.REASON_RESULT, "reason",
                {"reason_no": task.reason_no, "payload": payload})
    _record_llm_call(board.owner, board.board_id, model, usage, latency_ms, not error, error, len(text))
    return payload["outcome"]


@activity.defn
@with_heartbeat
def record_reason_failure(failure: ReasonFailure) -> None:
    """Record `model_failure` for an assessment whose call failed in every attempt, or
    whose worker was lost. The command writer refuses a second result of one assessment,
    so a result that an earlier attempt submitted stays."""
    payload = {"outcome": m.MODEL_FAILURE, "error": failure.error[:500], "raw": "",
               "problems": [], "stalled": failure.stalled}
    _submit(failure.board_id, f"reason_result:{failure.reason_no}", cmd.REASON_RESULT, "reason",
            {"reason_no": failure.reason_no, "payload": payload})


# ------------------------------------------------------------------------------ explore


def _turn_uuid(req: TurnRequest) -> str:
    return uuid.uuid5(BOARD_NAMESPACE, f"{req.board_id}:{req.intent_id}:{req.attempt}:{req.phase}").hex


def _chat_closed() -> bool:
    from database.clickhouse import get_server_setting

    return (get_server_setting("chat_enabled") or "").strip().lower() in ("false", "0", "off")


def _ensure_session(board, session_id: str, title: str, collections: list[str]) -> None:
    from database import boards
    from database.clickhouse import get_global_client, insert_durable

    with get_global_client() as client:
        exists = client.query(
            "SELECT count() FROM chat_sessions FINAL WHERE username = {u:String} AND session_id = {s:String}",
            parameters={"u": board.owner, "s": session_id},
        ).result_rows[0][0]
        if exists:
            return
        now = boards.now().replace(microsecond=0)
        insert_durable(client, "chat_sessions",
                       [[session_id, board.owner, title[:200], collections,
                         int(effective_internet_tools(bool(board.internet_tools))), 1, now, now, 0]],
                       column_names=["session_id", "username", "title", "collections",
                                     "use_internet_tools", "options_locked", "created_at",
                                     "updated_at", "is_deleted"])


def _existing_user_seq(owner: str, session_id: str, turn_uuid: str) -> int | None:
    from database.clickhouse import get_global_client

    with get_global_client() as client:
        rows = client.query(
            "SELECT seq FROM chat_messages FINAL WHERE username = {u:String} AND session_id = {s:String} "
            "AND message_uuid = {m:String} AND role = 'user' LIMIT 1",
            parameters={"u": owner, "s": session_id, "m": turn_uuid},
        ).result_rows
    return int(rows[0][0]) if rows else None


def _next_seq(owner: str, session_id: str) -> int:
    """The next free seq, counting the stream rows, starting a session at 1."""
    from database.clickhouse import get_global_client

    with get_global_client() as client:
        rows = client.query(
            "SELECT max(seq), count() FROM (SELECT seq FROM chat_messages FINAL "
            "WHERE username = {u:String} AND session_id = {s:String} UNION ALL "
            "SELECT seq FROM chat_message_stream WHERE username = {u:String} AND session_id = {s:String})",
            parameters={"u": owner, "s": session_id},
        ).result_rows
    top, count = rows[0] if rows else (0, 0)
    return int(top) + 1 if count else 1


def _write_turn_rows(owner: str, session_id: str, seq: int, text: str, turn_uuid: str) -> None:
    from database import boards
    from database.clickhouse import get_global_client, insert_durable

    now = boards.now()
    with get_global_client() as client:
        insert_durable(client, "chat_messages",
                       [[session_id, owner, seq, "user", text, now.replace(microsecond=0),
                         now.replace(microsecond=0), now, turn_uuid]],
                       column_names=["session_id", "username", "seq", "role", "content",
                                     "created_at", "updated_at", "created_ms", "message_uuid"])
        insert_durable(client, "chat_message_stream",
                       [[session_id, owner, seq + 1, "assistant", "", 0, now, turn_uuid]],
                       column_names=["session_id", "username", "seq", "role", "content",
                                     "is_final", "updated_at", "message_uuid"])


@activity.defn
@with_heartbeat
def open_explore_turn(req: TurnRequest) -> OpenedTurn:
    """Write the rows of one explore turn and return the `AgentRun` input."""
    from database import boards
    from database.clickhouse import list_collections

    board = boards.read_board(req.board_id)
    if board is None or board.is_deleted:
        return OpenedTurn(skip_kind=m.EXPLORE_CANCELLED, skip_reason="the board was dropped")
    _events, facts, folded = _read(board)
    intent = folded.intents.get(req.intent_id)
    if not may_explore(folded, req.intent_id) or intent is None:
        return OpenedTurn(skip_kind=m.EXPLORE_CANCELLED, skip_reason=f"the board is {folded.status}")
    if _chat_closed():
        return OpenedTurn(skip_kind=m.EXPLORE_FAILED, skip_reason="chat is closed in the settings")
    existing = set(list_collections())
    collections = [c for c in board.collections if c in existing]
    if not collections:
        return OpenedTurn(skip_kind=m.EXPLORE_FAILED, skip_reason="none of the board collections exists")
    session_id = m.session_id_for(board.board_id, req.intent_id)
    _ensure_session(board, session_id, f"{board.title}: {req.intent_id}", collections)
    turn_uuid = _turn_uuid(req)
    seq = _existing_user_seq(board.owner, session_id, turn_uuid)
    if seq is None:
        seq = _next_seq(board.owner, session_id)
        text = render_brief(board, facts, boards.read_citations(board.board_id),
                            folded.hints, intent, collections, folded.explore_steps,
                            boards.read_labels([board.board_id]),
                            effective_internet_tools(bool(board.internet_tools)))
        _write_turn_rows(board.owner, session_id, seq, text, turn_uuid)
    steps = folded.explore_steps
    run_input = AgentRunInput(
        run_id=str(uuid.uuid5(BOARD_NAMESPACE, turn_uuid)), username=board.owner,
        session_id=session_id, turn_seq=seq, start_seq=seq + 1, turn_uuid=turn_uuid,
        allowed_collections=collections, llm_model="",  # empty: the agent model of hoover4.ini
        internet_tools=effective_internet_tools(bool(board.internet_tools)),
        max_model_steps=int(steps), board_turn=True)
    return OpenedTurn(workflow_id=f"chat-{session_id}-{seq + 1}", run_input=run_input)




def _turn_rows(owner: str, session_id: str, turn_seq: int) -> list[dict]:
    """The rows of a session after the user row at `turn_seq`, in seq order."""
    from database.clickhouse import get_global_client

    with get_global_client() as client:
        result = client.query(
            "SELECT seq, role, tool_name, content, tool_input, tool_output, usage_json, message_uuid "
            "FROM chat_messages FINAL "
            "WHERE username = {u:String} AND session_id = {s:String} AND seq > {t:UInt32} ORDER BY seq",
            parameters={"u": owner, "s": session_id, "t": int(turn_seq)},
        )
    return [dict(zip(result.column_names, r)) for r in result.result_rows]


def _usage(row: dict) -> dict:
    try:
        value = json.loads(row.get("usage_json") or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def turn_report(rows: list[dict], turn_uuid: str) -> tuple[dict, int]:
    """The report version that the turn pinned, `{name, version}`, and the seq of the
    assistant row that names it. The last assistant row of the turn names it in its
    metadata (`P_workspace.selection`). Empty and 0 when the turn wrote no report."""
    answers = [r for r in rows if r["role"] == "assistant" and r.get("message_uuid") in ("", turn_uuid)]
    if not answers:
        return {}, 0
    report = _usage(answers[-1]).get("report")
    if (isinstance(report, dict) and isinstance(report.get("name"), str)
            and isinstance(report.get("version"), int) and report["version"] > 0):
        return {"name": report["name"], "version": report["version"]}, int(answers[-1]["seq"])
    return {}, int(answers[-1]["seq"])


#: The outcome of `conclude_explore` for each end of a submitted explore.
_OUTCOMES = {m.EXPLORE_CONCLUDED: "fact", m.EXPLORE_QUESTION: "question", m.EXPLORE_FAILED: "failed"}


def _end_request(intent_id: str, attempt: int) -> str:
    """The request id of the end of one explore attempt. A conclusion and a later
    cancellation of one attempt share it, so the first end wins."""
    return f"explore_end:{intent_id}:{attempt}"


def _submitted_end(board_id: str, request_id: str) -> str | None:
    """The outcome of the end that an earlier attempt submitted, or None."""
    from database import board_commands as bc

    earlier = [i for i in bc.read_inputs(board_id) if i.request_id == request_id]
    return _OUTCOMES.get(str(earlier[0].body.get("end")), "skipped") if earlier else None


@activity.defn
@with_heartbeat
def conclude_explore(req: TurnRequest) -> Concluded:
    """Read the end of one explore turn and submit it, unless its report needs a conversion.

    A turn that asked the person a question ends in `question`. A failed turn and a turn
    without a report end in `failed`. A turn with a report returns `convert` and the pinned
    report version, and submits nothing. A retry after a submission returns the submitted
    end, so it never reads a later answer of the session as the same end.
    """
    from database import boards

    board = boards.read_board(req.board_id)
    if board is None or board.is_deleted:
        return Concluded("skipped")
    request_id = _end_request(req.intent_id, req.attempt)
    earlier = _submitted_end(board.board_id, request_id)
    if earlier is not None:
        return Concluded(earlier)
    session_id = m.session_id_for(board.board_id, req.intent_id)
    turn_uuid = _turn_uuid(req)
    turn_seq = _existing_user_seq(board.owner, session_id, turn_uuid)
    if turn_seq is None:
        return Concluded("skipped")
    rows = _turn_rows(board.owner, session_id, turn_seq)
    base = {"intent_id": req.intent_id, "attempt": req.attempt}
    asked = [r for r in rows if r["role"] == "tool" and r["tool_name"] == "ask_user"]
    answers = [r for r in rows if r["role"] == "assistant"]
    if asked and answers:
        _submit(board.board_id, request_id, cmd.EXPLORE_END, "explore",
                {**base, "end": m.EXPLORE_QUESTION, "question": answers[-1]["content"][:2000]})
        return Concluded("question")
    report, _seq = turn_report(rows, turn_uuid)
    if req.turn_error:
        error = f"the explore turn failed: {req.turn_error}"
    elif not report:
        error = "the explore turn wrote no report"
    else:
        return Concluded("convert", report)
    _submit(board.board_id, request_id, cmd.EXPLORE_END, "explore",
            {**base, "end": m.EXPLORE_FAILED, "error": error[:2000],
             **({"report": report} if report else {})})
    return Concluded("failed")


def _conversion_row(owner: str, session_id: str, turn_uuid: str) -> dict | None:
    """The stored conversion call of a turn: its tool row, or None."""
    from database.clickhouse import get_global_client

    with get_global_client() as client:
        result = client.query(
            "SELECT seq, tool_input FROM chat_messages FINAL WHERE username = {u:String} "
            "AND session_id = {s:String} AND message_uuid = {m:String} AND role = 'tool' "
            "AND tool_name = {t:String} ORDER BY seq DESC LIMIT 1",
            parameters={"u": owner, "s": session_id, "m": turn_uuid, "t": m.SUBMIT_FACT_TOOL},
        )
    if not result.result_rows:
        return None
    seq, tool_input = result.result_rows[0]
    try:
        args = json.loads(tool_input or "{}")
    except ValueError:
        return None
    return {"seq": int(seq), "args": args} if isinstance(args, dict) else None


def _write_conversion_row(owner: str, session_id: str, turn_uuid: str, args: dict,
                          report: dict, model: str) -> None:
    """Store the conversion call as a tool row of the turn, after its answer. The row is the
    checkpoint of the conversion: a retry reads it and makes no second model call. The
    transcript shows it as the submission of the board (`by`)."""
    from database import boards
    from database.clickhouse import get_global_client, insert_durable

    now = boards.now()
    seq = _next_seq(owner, session_id)
    output = {"success": True, "submitted": True, "by": "board", "report": report}
    with get_global_client() as client:
        insert_durable(client, "chat_messages",
                       [[session_id, owner, seq, "tool", "", m.SUBMIT_FACT_TOOL,
                         json.dumps(args, ensure_ascii=False), json.dumps(output),
                         model, now.replace(microsecond=0), now.replace(microsecond=0), now,
                         turn_uuid]],
                       column_names=["session_id", "username", "seq", "role", "content",
                                     "tool_name", "tool_input", "tool_output", "model",
                                     "created_at", "updated_at", "created_ms", "message_uuid"])


def _task_text(intent) -> str:
    return intent.objective + (f"\n{intent.brief}" if intent.brief else "")


#: The connect timeout of the conversion request. The read timeout is
#: `board_reason_request_seconds`.
CONVERT_CONNECT_SECONDS = 10


@activity.defn
@with_heartbeat
def convert_explore_report(req: TurnRequest) -> str:
    """Turn the pinned report of an explore turn into its fact, and submit the fact.

    The request goes to the agent model (`llm_endpoints.chat_model`) with only the fact
    function (`conversion.py`). The checked arguments are stored as the conversion row of
    the turn before the fact is submitted, so a retry reuses them and sends no request. A
    transport failure and a malformed reply are raised, so Temporal sends the request once
    more. The second attempt turns off the reasoning phase (`conversion.request_body`). A
    refused request (4xx) cannot change in a second request and is raised as not retryable.
    After the last attempt the workflow records `explore_failed`.
    """
    from temporalio.exceptions import ApplicationError

    from database import boards
    from database import chat_workspace as store
    from tasks.llm_endpoints import chat_model, endpoint_for
    from tasks.P_agent import summarize
    from tasks.P_agent.model_timeouts import TIMEOUTS
    from tasks.P_board import conversion

    board = boards.read_board(req.board_id)
    if board is None or board.is_deleted:
        return "skipped"
    request_id = _end_request(req.intent_id, req.attempt)
    earlier = _submitted_end(board.board_id, request_id)
    if earlier is not None:
        return earlier
    session_id = m.session_id_for(board.board_id, req.intent_id)
    turn_uuid = _turn_uuid(req)
    turn_seq = _existing_user_seq(board.owner, session_id, turn_uuid)
    if turn_seq is None:
        return "skipped"
    report, answer_seq = turn_report(_turn_rows(board.owner, session_id, turn_seq), turn_uuid)
    version = (store.read_version(board.owner, session_id, report["name"], report["version"])
               if report else None)
    if version is None:
        raise ApplicationError(f"the report {report or 'of the turn'} is missing", non_retryable=True)
    stored = _conversion_row(board.owner, session_id, turn_uuid)
    if stored is not None:
        args = conversion.check_args(stored["args"])
    else:
        _events, _facts, folded = _read(board)
        intent = folded.intents.get(req.intent_id)
        if intent is None:
            return "skipped"
        model = chat_model()
        retry = activity.in_activity() and activity.info().attempt > 1

        def send(reasoning: bool):
            body = conversion.request_body(model, _task_text(intent), version.name,
                                           version.content, version.citations, reasoning)
            return summarize.post_or_raise(
                endpoint_for(model), body,
                timeout=(CONVERT_CONNECT_SECONDS, TIMEOUTS.board_reason_request_seconds))

        started = time.monotonic()
        try:
            response = send(reasoning=not retry)
            if retry and 400 <= response.status_code < 500:
                # A provider that does not accept the hint refuses the request, so the
                # request goes again without the hint.
                response = send(reasoning=True)
        except summarize.TransportFailure as exc:
            _record_llm_call(board.owner, board.board_id, model, {},
                             int((time.monotonic() - started) * 1000), False, str(exc), 0,
                             kind="board_convert")
            raise
        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            error = f"HTTP {response.status_code}: {response.text[:200]}"
            _record_llm_call(board.owner, board.board_id, model, {}, latency_ms, False, error, 0,
                             kind="board_convert")
            raise ApplicationError(f"the conversion request was refused: {error}", non_retryable=True)
        reply = response.json()
        usage = reply.get("usage") or {} if isinstance(reply, dict) else {}
        try:
            args = conversion.parse_reply(reply)
        except conversion.MalformedConversion as exc:
            _record_llm_call(board.owner, board.board_id, model, usage, latency_ms, False, str(exc),
                             len(response.text), kind="board_convert")
            raise ApplicationError(f"the conversion reply is malformed: {exc}") from exc
        _record_llm_call(board.owner, board.board_id, model, usage, latency_ms, True, "",
                         len(response.text), kind="board_convert")
        _write_conversion_row(board.owner, session_id, turn_uuid, args, report, model)
    kind, citations, problems = conversion.resolve(args, version.citations)
    if not boards.board_is_live(board.board_id):
        return "skipped"
    fact = {"kind": kind, "claimed_kind": args["kind"], "text": args["fact"],
            "session_id": session_id, "answer_seq": answer_seq, "slug": args["slug"][:80],
            "open_questions": args["open_questions"], "problems": problems,
            "report": report}
    _submit(board.board_id, request_id, cmd.EXPLORE_END, "explore",
            {"intent_id": req.intent_id, "attempt": req.attempt, "end": m.EXPLORE_CONCLUDED,
             "fact": fact, "citations": citations})
    return "fact"


@activity.defn
@with_heartbeat
def record_explore_end(req: EndRequest) -> None:
    """Record a cancelled or failed explore that wrote no fact. A failed conversion names
    its report version."""
    from database import boards

    if not boards.board_is_live(req.board_id):
        return
    _submit(req.board_id, _end_request(req.intent_id, req.attempt), cmd.EXPLORE_END, "explore",
            {"intent_id": req.intent_id, "attempt": req.attempt, "end": req.kind, "error": req.error,
             **({"report": req.report} if req.report else {})})
