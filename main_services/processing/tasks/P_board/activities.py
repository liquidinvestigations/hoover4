"""Board activities: plan, reason, open an explore turn, conclude it, record its end.

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
the stream row that `send_message` writes for a person, and the turn runs as `AgentRun`.
`conclude_explore` reads the answer, resolves its citation labels from the session's
`cite_documents` results, and submits the fact.
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
from tasks.P_board.contracts import labels_of, parse_explore_block, parse_reason
from tasks.P_board.fold import (
    canonical_events,
    earlier_objectives,
    fold,
    may_explore,
    plan,
    visible_facts,
)
from tasks.P_board.prompts import (
    CONCLUDE_REQUEST,
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
    phase: str = "explore"


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
    # A reason is a short decision call, so it uses the summarisation model, as titles
    # and follow-up suggestions do. The board's model is the model of its explores.
    model = summarize._model()
    from tasks.llm_endpoints import endpoint_for

    endpoint = endpoint_for(model)
    started = time.monotonic()
    text, usage, error = "", {}, ""
    try:
        response = summarize.post_or_raise(
            endpoint, {"model": model, "max_tokens": m.REASON_MAX_TOKENS,
                       "messages": [{"role": "user", "content": prompt}]},
            timeout=(REASON_CONNECT_SECONDS, TIMEOUTS.board_reason_request_seconds))
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
    """Write the rows of one explore or conclude turn and return the `AgentRun` input."""
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
        if req.phase == "conclude":
            text = CONCLUDE_REQUEST
        else:
            text = render_brief(board, facts, boards.read_citations(board.board_id),
                                folded.hints, intent, collections, folded.explore_steps)
        _write_turn_rows(board.owner, session_id, seq, text, turn_uuid)
    steps = m.CONCLUDE_STEP_BUDGET if req.phase == "conclude" else folded.explore_steps
    run_input = AgentRunInput(
        run_id=str(uuid.uuid5(BOARD_NAMESPACE, turn_uuid)), username=board.owner,
        session_id=session_id, turn_seq=seq, start_seq=seq + 1, turn_uuid=turn_uuid,
        allowed_collections=collections, llm_model="",  # empty: the agent model of hoover4.ini
        internet_tools=effective_internet_tools(bool(board.internet_tools)),
        max_model_steps=int(steps), board_turn=True)
    return OpenedTurn(workflow_id=f"chat-{session_id}-{seq + 1}", run_input=run_input)


def _turn_rows(owner: str, session_id: str, turn_seq: int) -> list[dict]:
    from database.clickhouse import get_global_client

    with get_global_client() as client:
        result = client.query(
            "SELECT seq, role, tool_name, content, tool_input, tool_output, doc_refs, usage_json "
            "FROM chat_messages FINAL "
            "WHERE username = {u:String} AND session_id = {s:String} ORDER BY seq",
            parameters={"u": owner, "s": session_id},
        )
    rows = [dict(zip(result.column_names, r)) for r in result.result_rows]
    for row in rows:
        row["in_turn"] = row["seq"] > turn_seq
    return rows


#: The keys under which a stored tool result nests its citation objects.
_NESTED_KEYS = ("output", "content", "text", "citations", "items", "structuredContent")


def page_citations(output: str) -> list[dict]:
    """The verified web page citations of a stored `cite_pages` result: objects with a
    handle `[W1]` to `[W200]`, `quote_verified`, an artifact id and a version, read through
    the stored wrappers. **Mirrored in `website/common/src/chat_pages.rs`**
    (`extract_page_refs`)."""
    found: list[dict] = []

    def collect(value, depth: int) -> None:
        if depth > 8:
            return
        if isinstance(value, str):
            try:
                collect(json.loads(value), depth + 1)
            except ValueError:
                pass
        elif isinstance(value, list):
            for item in value:
                collect(item, depth + 1)
        elif isinstance(value, dict):
            handle = str(value.get("handle") or "")
            number = handle[2:-1] if handle.startswith("[W") and handle.endswith("]") else ""
            if (number.isdigit() and 1 <= int(number) <= 200 and value.get("quote_verified") is True
                    and value.get("artifact_id") and value.get("version")):
                found.append(value)
            for key in _NESTED_KEYS:
                if key in value:
                    collect(value[key], depth + 1)

    collect(output or "", 0)
    return found


def _citation_index(rows: list[dict]) -> dict[str, dict]:
    """Handle to source, from every successful citation result of the session. A document
    handle comes from the `doc_refs` of a `cite_documents` row. A web handle comes from the
    verified citations in the `tool_output` of a `cite_pages` row, and becomes a citation
    whose path is the page address and whose quote is its first verified term."""
    index: dict[str, dict] = {}
    for row in rows:
        if row["tool_name"] == "cite_pages":
            for page in page_citations(row.get("tool_output") or ""):
                terms = [str(t) for t in page.get("terms") or [] if str(t).strip()]
                quotes = [str(q) for q in page.get("quotes") or [] if str(q).strip()]
                index[str(page["handle"]).strip("[]")] = {
                    "url": str(page.get("final_url") or page.get("url") or ""),
                    "quote": (terms or quotes or [""])[0], "quote_verified": True}
        if row["tool_name"] not in ("cite_documents", "cite_pages") or not row["doc_refs"]:
            continue
        try:
            refs = json.loads(row["doc_refs"])
        except ValueError:
            continue
        for ref in refs if isinstance(refs, list) else []:
            handle = str(ref.get("handle") or "").strip("[]")
            if handle:
                index[handle] = ref
    return index


def submitted_fact(rows: list[dict]) -> dict | None:
    """The arguments of the last successful `submit_board_fact` call of a turn, or None."""
    for row in reversed(rows):
        if row["role"] != "tool" or row["tool_name"] != m.SUBMIT_FACT_TOOL:
            continue
        try:
            result = json.loads(row.get("tool_output") or "{}")
            args = json.loads(row.get("tool_input") or "{}")
        except ValueError:
            continue
        if isinstance(result, dict) and result.get("submitted") and isinstance(args, dict):
            return args
    return None


#: The outcome of `conclude_explore` for each end of a submitted explore.
_OUTCOMES = {m.EXPLORE_CONCLUDED: "fact", m.EXPLORE_QUESTION: "question", m.EXPLORE_FAILED: "failed"}


def _end_request(intent_id: str, attempt: int) -> str:
    """The request id of the end of one explore attempt. A conclusion and a later
    cancellation of one attempt share it, so the first end wins."""
    return f"explore_end:{intent_id}:{attempt}"


@activity.defn
@with_heartbeat
def conclude_explore(req: TurnRequest) -> str:
    """Turn the answer of one turn into a board fact, a question or a failure, and submit it.

    Returns `fact`, `question`, `needs_conclude` (explore phase without a valid block),
    `failed` or `skipped`. A retry after the submission returns the submitted end, so it
    never reads a later answer of the session as the same fact.
    """
    from database import board_commands as bc
    from database import boards

    board = boards.read_board(req.board_id)
    if board is None or board.is_deleted:
        return "skipped"
    request_id = _end_request(req.intent_id, req.attempt)
    earlier = [i for i in bc.read_inputs(board.board_id) if i.request_id == request_id]
    if earlier:
        return _OUTCOMES.get(str(earlier[0].body.get("end")), "skipped")
    session_id = m.session_id_for(board.board_id, req.intent_id)
    turn_seq = _existing_user_seq(board.owner, session_id, _turn_uuid(req))
    if turn_seq is None:
        return "skipped"
    rows = _turn_rows(board.owner, session_id, turn_seq)
    in_turn = [r for r in rows if r["in_turn"]]
    base = {"intent_id": req.intent_id, "attempt": req.attempt, "phase": req.phase}
    asked = [r for r in in_turn if r["role"] == "tool" and r["tool_name"] == "ask_user"]
    answers = [r for r in in_turn if r["role"] == "assistant"]
    submitted = submitted_fact(in_turn)
    if submitted is None and asked and answers:
        _submit(board.board_id, request_id, cmd.EXPLORE_END, "explore",
                {**base, "end": m.EXPLORE_QUESTION, "question": answers[-1]["content"][:2000]})
        return "question"
    # The fact of a `submit_board_fact` call, else a fenced JSON block of the answer, which
    # explores before the tool wrote.
    block = submitted or (parse_explore_block(answers[-1]["content"]) if answers else None)
    if block is None:
        if req.phase == "explore":
            return "needs_conclude"
        _submit(board.board_id, request_id, cmd.EXPLORE_END, "explore",
                {**base, "end": m.EXPLORE_FAILED, "error": f"the turn ended without a {m.SUBMIT_FACT_TOOL} call"})
        return "failed"
    text = str(block.get("fact") or "").strip()
    kind = str(block.get("kind") or "").strip()
    if not text or kind not in m.EXPLORE_KINDS:
        _submit(board.board_id, request_id, cmd.EXPLORE_END, "explore",
                {**base, "end": m.EXPLORE_FAILED, "error": f"the block has no fact or an unknown kind {kind!r}"})
        return "failed"
    index = _citation_index(rows)
    problems, citations = [], []
    unresolved = []
    for label in labels_of(text, block.get("citations")):
        ref = index.get(label)
        if ref is None:
            unresolved.append(label)
            continue
        citations.append({
            "label": label, "collection_dataset": str(ref.get("collection_dataset") or ""),
            "collectionname": str(ref.get("collectionname") or ""), "file_hash": str(ref.get("file_hash") or ""),
            "path": str(ref.get("path") or ref.get("url") or ""), "page_id": int(ref.get("page_id") or 0),
            "quote": str(ref.get("quote") or "")[:4000], "quote_verified": 1 if ref.get("quote_verified") else 0})
    if unresolved:
        problems.append("unresolved labels: " + ", ".join(unresolved))
    claimed = kind
    if kind == m.SOURCED and not any(c["quote_verified"] for c in citations):
        kind = m.INFERRED
        problems.append("a sourced fact without a verified citation became inferred")
    answer_seq = int(answers[-1]["seq"]) if answers else 0
    if not boards.board_is_live(board.board_id):
        return "skipped"
    fact = {"kind": kind, "claimed_kind": claimed, "text": text, "session_id": session_id,
            "answer_seq": answer_seq, "slug": str(block.get("slug") or "")[:80],
            "open_questions": [str(q)[:500] for q in (block.get("open_questions") or [])][:3],
            "problems": problems}
    _submit(board.board_id, request_id, cmd.EXPLORE_END, "explore",
            {**base, "end": m.EXPLORE_CONCLUDED, "fact": fact, "citations": citations})
    return "fact"


@activity.defn
@with_heartbeat
def record_explore_end(req: EndRequest) -> None:
    """Record a cancelled or failed explore that wrote no fact."""
    from database import boards

    if not boards.board_is_live(req.board_id):
        return
    _submit(req.board_id, _end_request(req.intent_id, req.attempt), cmd.EXPLORE_END, "explore",
            {"intent_id": req.intent_id, "attempt": req.attempt, "end": req.kind, "error": req.error})
