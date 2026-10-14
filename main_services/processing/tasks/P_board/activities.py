"""Board activities: plan, reason, open an explore turn, conclude it, record its end.

`board_plan` is the only writer of `board_state` and `board_intents`. It folds the events of
every live board, reconciles running intents whose `BoardExplore` closed, writes the events of
its decisions and returns the work to start or cancel. The other activities write events and
facts only, so no two writers race on one row.

An explore is an ordinary chat turn: `open_explore_turn` writes the session, the user row and
the stream row that `send_message` writes for a person, and the turn runs as `AgentRun`.
`conclude_explore` reads the answer, resolves its citation labels from the session's
`cite_documents` results, and writes the board fact.
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
from tasks.P_agent.activities import AgentRunInput
from tasks.P_board import model as m
from tasks.P_board.contracts import labels_of, parse_explore_block, parse_reason
from tasks.P_board.fold import earlier_objectives, fold, plan
from tasks.P_board.prompts import CONCLUDE_REQUEST, goal_ids, render_brief, render_reason

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
    in_flight_reasons: list[str] = field(default_factory=list)


@dataclass
class ReasonTask:
    board_id: str
    reason_no: int
    stalled: bool = False


@dataclass
class ExploreTask:
    board_id: str
    intent_id: str
    attempt: int


@dataclass
class PlanOutput:
    reasons: list[ReasonTask] = field(default_factory=list)
    explores: list[ExploreTask] = field(default_factory=list)
    cancels: list[str] = field(default_factory=list)


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


def _event(board_id: str, event_id: str, event_type: str, actor: str, subject: str = "",
           payload: dict | None = None):
    from database import boards

    return boards.EventRow(board_id, event_id, event_type, actor, subject, payload or {})


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


def _reconcile(stale: list[tuple[str, object]]) -> list:
    """End events for running intents whose `BoardExplore` closed without one."""
    from database import boards
    from temporalio.client import Client

    async def run() -> list:
        client = await Client.connect("temporal:7233")
        events = []
        for board_id, intent in stale:
            closed, status = await _workflow_closed(client, m.explore_workflow_id(board_id, intent.intent_id))
            if not closed:
                continue
            attempt = intent.running_attempt
            fact_id = m.fact_id_for(intent.intent_id)
            if boards.fact_exists(board_id, fact_id):
                kind = next((f.kind for f in boards.read_facts(board_id) if f.fact_id == fact_id), "")
                events.append(_event(board_id, f"explore_concluded:{intent.intent_id}:{attempt}",
                                     m.EXPLORE_CONCLUDED, "dispatcher", intent.intent_id,
                                     {"attempt": attempt, "fact_id": fact_id, "kind": kind}))
            elif status == "absent":
                events.append(_event(board_id, f"explore_cancelled:{intent.intent_id}:{attempt}",
                                     m.EXPLORE_CANCELLED, "dispatcher", intent.intent_id,
                                     {"attempt": attempt, "error": "the explore workflow never started"}))
            else:
                events.append(_event(board_id, f"explore_failed:{intent.intent_id}:{attempt}",
                                     m.EXPLORE_FAILED, "dispatcher", intent.intent_id,
                                     {"attempt": attempt,
                                      "error": f"the explore workflow ended with status {status}"}))
        return events

    return asyncio.run(run())


def _state_rows(board, folded) -> tuple[dict, list[dict]]:
    from database import boards

    now = boards.now()
    by_kind: dict[str, int] = {}
    for intent in folded.intents.values():
        by_kind[intent.state] = by_kind.get(intent.state, 0) + 1
    summary = {"intents": by_kind, "facts": folded.fact_count, "sourced": folded.sourced_count,
               "hints": len(folded.hints), "rejected": len(folded.rejected),
               "review_statement": folded.review_statement, "review_from": folded.review_from,
               "review_goals": folded.review_goals, "max_explores": folded.max_explores,
               "explore_steps": folded.explore_steps}
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


@activity.defn
@with_heartbeat
def board_plan(inp: PlanInput) -> PlanOutput:
    """One pass of the dispatcher: fold, reconcile, decide, record, and return the work."""
    from database import boards

    live = boards.read_live_boards()
    if not live:
        return PlanOutput()
    snapshots = {}
    stale = []
    cutoff = boards.now().timestamp() - RECONCILE_GRACE_SECONDS
    for board in live:
        events, facts = boards.read_events(board.board_id), boards.read_facts(board.board_id)
        folded = fold(board, events, facts)
        snapshots[board.board_id] = (events, facts, folded)
        for intent in folded.by_state(m.RUNNING):
            since = intent.running_since
            if since is None or since.timestamp() < cutoff:
                stale.append((board.board_id, intent))
    if stale:
        ended = _reconcile(stale)
        if ended:
            boards.write_events(ended)
            for board_id in {e.board_id for e in ended}:
                board = next(b for b in live if b.board_id == board_id)
                events, facts = boards.read_events(board_id), boards.read_facts(board_id)
                snapshots[board_id] = (events, facts, fold(board, events, facts))
    folded_by_id = {board_id: snap[2] for board_id, snap in snapshots.items()}
    actions = plan(live, folded_by_id, set(inp.in_flight_reasons), _cap())
    decided = []
    for reason in actions.reasons:
        decided.append(_event(reason.board_id, f"reason_started:{reason.reason_no}", m.REASON_STARTED,
                              "dispatcher", str(reason.reason_no), {"stalled": reason.stalled}))
    for explore in actions.explores:
        decided.append(_event(explore.board_id, f"explore_started:{explore.intent_id}:{explore.attempt}",
                              m.EXPLORE_STARTED, "dispatcher", explore.intent_id,
                              {"attempt": explore.attempt}))
    for board_id, why in actions.reviews:
        f = folded_by_id[board_id]
        statement = ("The explore budget is used up." if why == "budget"
                     else "Reason gave no usable direction in several attempts.")
        decided.append(_event(board_id, f"review_proposed:{why}:{f.explores_used}:{f.reasons_done}",
                              m.REVIEW_PROPOSED, "dispatcher", why, {"reason": why, "statement": statement}))
    if decided:
        boards.write_events(decided)
    touched = {e.board_id for e in decided}
    for board in live:
        events, facts, folded = snapshots[board.board_id]
        if board.board_id in touched:
            events = boards.read_events(board.board_id)
            folded = fold(board, events, facts)
        state, intents = _state_rows(board, folded)
        _write_changed(board.board_id, state, intents)
    return PlanOutput(
        reasons=[ReasonTask(r.board_id, r.reason_no, r.stalled) for r in actions.reasons],
        explores=[ExploreTask(e.board_id, e.intent_id, e.attempt) for e in actions.explores],
        cancels=[m.explore_workflow_id(b, i) for b, i in actions.cancels],
    )


# ------------------------------------------------------------------------------- reason


def _explore_model(board) -> str:
    """The model of an explore turn: the board's model, else the model of the chat profile
    of an ordinary chat turn with the board's internet setting. Empty lets the turn use the
    default chat model."""
    from database.clickhouse import get_server_setting

    if (board.llm_model or "").strip():
        return board.llm_model.strip()
    key = "llm_model_full_research" if board.internet_tools else "llm_model_internal_search"
    try:
        return (get_server_setting(key) or "").strip()
    except Exception:  # noqa: BLE001 - a settings read failure falls back to the default model
        return ""


def _record_llm_call(owner: str, board_id: str, model: str, usage: dict, latency_ms: int,
                     ok: bool, error: str, reply_bytes: int) -> None:
    from database.clickhouse import get_global_client
    from database import boards
    from tasks.llm_endpoints import endpoint_for

    try:
        with get_global_client() as client:
            client.insert(
                "llm_call_events",
                [[boards.now(), owner, f"{m.SESSION_PREFIX}{board_id}", "board_reason", endpoint_for(model).label,
                  model, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0),
                  0, reply_bytes, latency_ms, 1 if ok else 0, error[:500]]],
                column_names=["event_time", "username", "session_id", "kind", "provider", "model_id",
                              "prompt_tokens", "completion_tokens", "reasoning_tokens",
                              "reply_bytes", "latency_ms", "ok", "error"],
            )
    except Exception:  # noqa: BLE001 - telemetry never costs a reason
        log.warning("[P_board] could not record the reason call", exc_info=True)


@activity.defn
@with_heartbeat
def board_reason(task: ReasonTask) -> str:
    """One reason call. Writes one `reason_result` event and returns its outcome."""
    from database import boards
    from tasks.P_agent import summarize

    board = boards.read_board(task.board_id)
    if board is None or board.is_deleted:
        return "skipped"
    events, facts = boards.read_events(board.board_id), boards.read_facts(board.board_id)
    citations = boards.read_citations(board.board_id)
    folded = fold(board, events, facts)
    if folded.status != m.ACTIVE:
        return "skipped"
    prompt = render_reason(board, folded, facts, citations, task.stalled)
    # A reason is a short decision call, so it uses the summarisation model, as titles
    # and follow-up suggestions do. The board's model is the model of its explores.
    model = summarize._model()
    from tasks.llm_endpoints import endpoint_for

    endpoint = endpoint_for(model)
    started = time.monotonic()
    text, usage, error = "", {}, ""
    try:
        response = summarize._post(endpoint, {"model": model, "max_tokens": 4000,
                                          "messages": [{"role": "user", "content": prompt}]})
        response.raise_for_status()
        reply = response.json()
        text = reply["choices"][0]["message"].get("content") or ""
        usage = reply.get("usage") or {}
    except Exception as exc:  # noqa: BLE001 - a failed call is an invalid outcome, recorded
        error = f"{type(exc).__name__}: {exc}"[:500]
    latency_ms = int((time.monotonic() - started) * 1000)
    live = [f for f in facts if f.fact_id not in folded.rejected and f.kind != m.GOAL]
    idle = not folded.by_state(m.OPEN) and not folded.by_state(m.RUNNING)
    if error:
        payload = {"outcome": "invalid", "error": error, "raw": "", "problems": []}
    else:
        payload = parse_reason(text, {f.fact_id for f in live},
                               {f.fact_id for f in live if f.kind == m.SOURCED},
                               earlier_objectives(folded), idle, goal_ids(facts),
                               {f.fact_id for f in live if f.kind == m.NOT_FOUND})
    payload.update(situation=folded.situation(), model=model, latency_ms=latency_ms,
                   prompt_tokens=int(usage.get("prompt_tokens") or 0),
                   completion_tokens=int(usage.get("completion_tokens") or 0),
                   stalled=task.stalled)
    if boards.board_is_live(board.board_id):
        boards.write_event(_event(board.board_id, f"reason_result:{task.reason_no}", m.REASON_RESULT,
                                  "reason", str(task.reason_no), payload))
    _record_llm_call(board.owner, board.board_id, model, usage, latency_ms, not error, error, len(text))
    return payload["outcome"]


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
                         int(bool(board.internet_tools)), 1, now, now, 0]],
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
    events, facts = boards.read_events(board.board_id), boards.read_facts(board.board_id)
    folded = fold(board, events, facts)
    intent = folded.intents.get(req.intent_id)
    if folded.status != m.ACTIVE or intent is None:
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
        allowed_collections=collections, llm_model=_explore_model(board),
        internet_tools=bool(board.internet_tools),
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


def _citation_index(rows: list[dict]) -> dict[str, dict]:
    """Handle to document, from every successful citation result of the session."""
    index: dict[str, dict] = {}
    for row in rows:
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


@activity.defn
@with_heartbeat
def conclude_explore(req: TurnRequest) -> str:
    """Turn the answer of one turn into a board fact, a question or a failure.

    Returns `fact`, `question`, `needs_conclude` (explore phase without a valid block),
    `failed` or `skipped`.
    """
    from database import boards

    board = boards.read_board(req.board_id)
    if board is None or board.is_deleted:
        return "skipped"
    session_id = m.session_id_for(board.board_id, req.intent_id)
    turn_seq = _existing_user_seq(board.owner, session_id, _turn_uuid(req))
    if turn_seq is None:
        return "skipped"
    rows = _turn_rows(board.owner, session_id, turn_seq)
    in_turn = [r for r in rows if r["in_turn"]]
    base = {"attempt": req.attempt, "phase": req.phase}
    asked = [r for r in in_turn if r["role"] == "tool" and r["tool_name"] == "ask_user"]
    answers = [r for r in in_turn if r["role"] == "assistant"]
    submitted = submitted_fact(in_turn)
    if submitted is None and asked and answers:
        boards.write_event(_event(board.board_id, f"explore_question:{req.intent_id}:{req.attempt}",
                                  m.EXPLORE_QUESTION, "explore", req.intent_id,
                                  {**base, "question": answers[-1]["content"][:2000]}))
        return "question"
    # The fact of a `submit_board_fact` call, else a fenced JSON block of the answer, which
    # explores before the tool wrote.
    block = submitted or (parse_explore_block(answers[-1]["content"]) if answers else None)
    if block is None:
        if req.phase == "explore":
            return "needs_conclude"
        boards.write_event(_event(board.board_id, f"explore_failed:{req.intent_id}:{req.attempt}",
                                  m.EXPLORE_FAILED, "explore", req.intent_id,
                                  {**base, "error": f"the turn ended without a {m.SUBMIT_FACT_TOOL} call"}))
        return "failed"
    text = str(block.get("fact") or "").strip()
    kind = str(block.get("kind") or "").strip()
    if not text or kind not in m.EXPLORE_KINDS:
        boards.write_event(_event(board.board_id, f"explore_failed:{req.intent_id}:{req.attempt}",
                                  m.EXPLORE_FAILED, "explore", req.intent_id,
                                  {**base, "error": f"the block has no fact or an unknown kind {kind!r}"}))
        return "failed"
    index = _citation_index(rows)
    problems, citations = [], []
    fact_id = m.fact_id_for(req.intent_id)
    unresolved = []
    for label in labels_of(text, block.get("citations")):
        ref = index.get(label)
        if ref is None:
            unresolved.append(label)
            continue
        citations.append(boards.CitationRow(
            board.board_id, fact_id, label, str(ref.get("collection_dataset") or ""),
            str(ref.get("collectionname") or ""), str(ref.get("file_hash") or ""),
            str(ref.get("path") or ref.get("url") or ""), int(ref.get("page_id") or 0),
            str(ref.get("quote") or "")[:4000], 1 if ref.get("quote_verified") else 0))
    if unresolved:
        problems.append("unresolved labels: " + ", ".join(unresolved))
    claimed = kind
    if kind == m.SOURCED and not any(c.quote_verified for c in citations):
        kind = m.INFERRED
        problems.append("a sourced fact without a verified citation became inferred")
    answer_seq = int(answers[-1]["seq"]) if answers else 0
    fact = boards.FactRow(
        board.board_id, fact_id, kind, text, req.intent_id, session_id, answer_seq,
        [str(q)[:500] for q in (block.get("open_questions") or [])][:3], problems)
    if not boards.board_is_live(board.board_id):
        return "skipped"
    boards.write_fact(fact, citations)
    boards.write_event(_event(board.board_id, f"explore_concluded:{req.intent_id}:{req.attempt}",
                              m.EXPLORE_CONCLUDED, "explore", req.intent_id,
                              {**base, "fact_id": fact_id, "kind": kind, "claimed_kind": claimed,
                               "problems": problems, "citations": len(citations)}))
    return "fact"


@activity.defn
@with_heartbeat
def record_explore_end(req: EndRequest) -> None:
    """Record a cancelled or failed explore that wrote no fact."""
    from database import boards

    if not boards.board_is_live(req.board_id):
        return
    boards.write_event(_event(req.board_id, f"{req.kind}:{req.intent_id}:{req.attempt}", req.kind,
                              "explore", req.intent_id, {"attempt": req.attempt, "error": req.error}))
