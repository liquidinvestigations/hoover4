"""Activities for durable AI agent turns.

**Every turn runs here**. An ordinary chat message and an exhaustive research run alike.
They differ in which agent they reach and which queue they wait on, not in what they do.
The website holds nothing open, so a browser reload, a website restart and a worker crash
all cost the turn nothing.

This module holds the short activities of `AgentRun`: open, section dispatch, note, ending,
fan-in and the title. The step activities, one model call or one tool call each, are in
`steps.py`.

The ACL travels with the task. These activities never resolve permissions themselves.
The website resolved them against the caller's identity when the turn was submitted and
passed the resulting collection list in. The same goes for the model id: a forged one has
to be refused where the user is known, which is not here.
"""

import contextlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests
from temporalio import activity
from tasks.heartbeat import with_heartbeat

log = logging.getLogger(__name__)

#: Where the full research agent lives on the shared `hoover4` network.
#: The two agent services, which differ in the tools they carry. A durable research turn
#: has to reach the same one an inline turn in that conversation would: the switch is a
#: property of the conversation, and answering a documents-only thread from the agent
#: that has the open web makes some answers in one transcript internet-backed and some
#: not, with nothing on screen saying which.
AGENT_URL = os.getenv("RESEARCH_AGENT_URL", "http://hoover4-full-research-agent:8000")
INTERNAL_AGENT_URL = os.getenv(
    "INTERNAL_SEARCH_AGENT_URL", "http://hoover4-internal-search-agent:8000"
)


def agent_url_for(internet_tools: bool) -> str:
    """The agent service a turn with these options belongs to."""
    return AGENT_URL if internet_tools else INTERNAL_AGENT_URL


@dataclass
class WriteResultParams:
    """One `chat_messages` row.

    The payload fields mirror the columns the website's synchronous chat path writes
    (`website/backend/src/db_chat`). They were missing here for a while, which is why
    research transcripts rendered as a raw JSON blob with the tool type shown as
    "tool" and an expand panel that opened onto nothing: the columns the UI reads were
    never populated on this path.
    """

    username: str
    session_id: str
    seq: int
    role: str
    content: str
    tool_name: str = ""
    #: JSON arguments the model passed to the tool.
    tool_input: str = ""
    #: JSON tool result, truncated to TOOL_PAYLOAD_CHARS.
    tool_output: str = ""
    #: JSON array of documents this step surfaced, for the result cards.
    doc_refs: str = ""
    #: Wall time the agent took to produce this row, 0 for anything else.
    agent_duration_ms: int = 0
    #: Model that produced the row, empty for user and tool rows. Recorded per message
    #: because model selection is per message -- a transcript that mixes two models is
    #: only readable if each row says which one wrote it.
    model: str = ""
    #: Reasoning kept out of the answer body and rendered behind the disclosure. A
    #: reasoning model narrates its plan on the same channel as its answer, and this is
    #: the column that stops the scratchpad reaching the transcript.
    reasoning: str = ""
    #: Prompt tokens of the first model call of the turn -- the conversation as the model
    #: received it, and what the next turn starts from. 0 when unknown.
    context_tokens: int = 0
    #: Largest prompt plus completion of any single model call in the turn. This is the
    #: number a compaction trigger fires on. 0 when unknown.
    peak_context_tokens: int = 0
    #: The model's context window as the catalog knew it at the time of the turn. 0 means
    #: the provider never stated one, and readers must show unknown rather than divide.
    context_window: int = 0
    #: The plan the plan card shows, as JSON, on a planner's answer row. Empty otherwise.
    plan_reference_json: str = ""


def write_chat_message(params: WriteResultParams) -> int:
    """Append one row to the global `chat_messages` table. The activities write every
    transcript row through it.

    The chat tables are global (a conversation spans collections), so this writes to
    `Hoover4_Processing`. Idempotent on retry: `chat_messages` is a ReplacingMergeTree
    keyed on `(username, session_id, seq)`, so re-writing the same row replaces it
    rather than duplicating it.
    """
    from database.clickhouse import get_global_client

    with get_global_client() as client:
        client.insert(
            "chat_messages",
            [[
                params.session_id,
                params.username,
                params.seq,
                params.role,
                params.content,
                params.tool_name,
                params.tool_input,
                params.tool_output,
                params.doc_refs,
                params.agent_duration_ms,
                params.model,
                params.reasoning,
                params.context_tokens,
                params.peak_context_tokens,
                params.context_window,
                params.plan_reference_json,
            ]],
            column_names=[
                "session_id",
                "username",
                "seq",
                "role",
                "content",
                "tool_name",
                "tool_input",
                "tool_output",
                "doc_refs",
                "agent_duration_ms",
                "model",
                "reasoning",
                "context_tokens",
                "peak_context_tokens",
                "context_window",
                "plan_reference_json",
            ],
        )
    if params.peak_context_tokens:
        _raise_session_peak(params.username, params.session_id, params.peak_context_tokens)
    log.info(
        "[P_agent] wrote %s message seq=%d to session %s",
        params.role, params.seq, params.session_id,
    )
    return params.seq


def _raise_session_peak(username: str, session_id: str, peak: int) -> None:
    """Carry the conversation's running peak up to `peak` if this turn beat it.

    A maximum rather than a sum, and idempotent for that reason: this activity is
    retried, and re-applying the same turn's peak leaves the row where it already was.

    Read-modify-write, like `_set_session_title` and for the same reason: the table is a
    ReplacingMergeTree keyed on `(username, session_id)`, so a partial row would silently
    reset the conversation's collections and both agent switches to their defaults.
    """
    from database.clickhouse import get_global_client

    columns = [
        "session_id", "username", "title", "collections", "summary",
        "use_internet_tools", "deep_research", "options_locked",
        "created_at", "updated_at", "is_deleted", "peak_context_tokens",
    ]
    try:
        with get_global_client() as client:
            rows = client.query(
                f"SELECT {', '.join(columns)} FROM chat_sessions FINAL "
                "WHERE username = {u:String} AND session_id = {s:String}",
                parameters={"u": username, "s": session_id},
            ).result_rows
            if not rows:
                return
            row = list(rows[0])
            if int(row[columns.index("peak_context_tokens")]) >= peak:
                return
            row[columns.index("peak_context_tokens")] = peak
            row[columns.index("updated_at")] = datetime.now(timezone.utc).replace(tzinfo=None)
            client.insert("chat_sessions", [row], column_names=columns)
    except Exception:  # noqa: BLE001 - an accounting number is never worth a turn
        log.warning("[P_agent] could not raise the context peak for session %s",
                    session_id, exc_info=True)


@dataclass
class TitleSessionParams:
    """One conversation to name, and the exchange to name it from."""

    username: str
    session_id: str
    user_message: str
    answer: str
    #: The chat lead run that answered the turn, for the `agent_step_events` row.
    run_id: str = ""


def title_session(params: TitleSessionParams) -> str:
    """Name a conversation from its first exchange. Returns the title, or empty.

    `summarize_if_first_turn` calls it. **It cannot fail.** It runs after the answer is
    written and read, so everything that could go wrong here -- a dead endpoint, an
    unusable reply, an unreachable database -- is worth exactly one mediocre title and
    nothing more. It returns instead of raising, and the workflow shields the call as well.

    The provisional title the website wrote from the first message stays in place
    whenever this produces nothing.
    """
    if activity.in_activity():
        activity.heartbeat("summarising the conversation")
    from tasks.P_agent.summarize import title_and_summary

    try:
        result = title_and_summary(params.user_message, params.answer)
    except Exception:  # noqa: BLE001 - see the docstring: a title is never worth a turn
        log.warning("[P_agent] the summariser raised", exc_info=True)
        return ""

    _record_summarizer_call(params, result)
    if not result.title:
        log.info(
            "[P_agent] session %s keeps its provisional title: %s",
            params.session_id, result.error or "no title produced",
        )
        return ""

    try:
        _set_session_title(params.username, params.session_id, result.title, result.summary)
    except Exception:  # noqa: BLE001
        log.warning("[P_agent] could not store the session title", exc_info=True)
        return ""
    return result.title


def _set_session_title(username: str, session_id: str, title: str, summary: str) -> None:
    """Rewrite one `chat_sessions` row with a new title and summary.

    Read-modify-write rather than an UPDATE: the table is a ReplacingMergeTree keyed on
    `(username, session_id)` and versioned by `updated_at`, so a whole row with a newer
    timestamp replaces the old one. Every other column is carried over unchanged -- most
    of them, the two agent switches especially, are the conversation's settings and would
    silently reset to their defaults if this wrote a partial row.
    """
    from database.clickhouse import get_global_client

    columns = [
        "session_id", "username", "title", "collections", "summary",
        "use_internet_tools", "deep_research", "options_locked",
        "created_at", "updated_at", "is_deleted", "peak_context_tokens",
    ]
    with get_global_client() as client:
        rows = client.query(
            f"SELECT {', '.join(columns)} FROM chat_sessions FINAL "
            "WHERE username = {u:String} AND session_id = {s:String}",
            parameters={"u": username, "s": session_id},
        ).result_rows
        if not rows:
            log.warning("[P_agent] session %s vanished before it could be titled", session_id)
            return
        row = list(rows[0])
        row[columns.index("title")] = title
        row[columns.index("summary")] = summary
        row[columns.index("updated_at")] = datetime.now(timezone.utc).replace(tzinfo=None)
        client.insert("chat_sessions", [row], column_names=columns)


def _record_summarizer_call(params: TitleSessionParams, result) -> None:
    """Record the call in the two tables `/admin/ai_status` reads, and its
    `agent_step_events` row.

    Written for a discarded answer as well as a failed request, and with `ok = 0` for
    both: the endpoint worked, the *call* produced nothing usable, and counting a
    discarded answer as a success would make the error rate say the summariser is healthy
    while every title falls back to the user's own words.
    """
    from database.clickhouse import get_global_client

    ok = 1 if result.title else 0
    username = params.username.strip()
    # Guests are one bucket: their usernames are per-session and would otherwise turn the
    # telemetry into a cardinality problem with one row per visitor.
    if not username or username == "guest" or username.startswith("guest-"):
        username = "guest"
    provider = _provider_label()
    reply_bytes = len(result.title) + len(result.summary)
    event_time = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        with get_global_client() as client:
            client.insert(
                "llm_call_events",
                [[event_time, username, params.session_id, "title", provider,
                  result.model, result.prompt_tokens, result.completion_tokens, 0,
                  reply_bytes, result.latency_ms, ok, result.error[:500]]],
                column_names=[
                    "event_time", "username", "session_id", "kind", "provider",
                    "model_id", "prompt_tokens", "completion_tokens", "reasoning_tokens",
                    "reply_bytes", "latency_ms", "ok", "error",
                ],
            )
            client.insert(
                "ai_service_telemetry",
                [[event_time, "llm", provider, username, params.session_id,
                  result.latency_ms, ok, result.model]],
                column_names=[
                    "event_time", "service", "provider", "username", "session_id",
                    "latency_ms", "ok", "detail",
                ],
            )
    except Exception:  # noqa: BLE001 - telemetry is never worth a turn either
        log.warning("[P_agent] could not record the summariser call", exc_info=True)
    from database import agent_step_events as events

    attempt, task_queue, queue_wait_ms = events.attempt_fields()
    events.record(events.StepEvent(
        username=username, session_id=params.session_id, run_id=params.run_id,
        run_kind="title", step="title", name=result.model, task_queue=task_queue,
        attempt=attempt, ok=bool(ok), queue_wait_ms=queue_wait_ms,
        duration_ms=result.latency_ms, error=result.error,
        prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens))


def _provider_label() -> str:
    """A short, stable name for the endpoint that served the call."""
    from tasks.llm_catalog import provider_label

    name = (os.getenv("LLM_PROVIDER_NAME") or "").strip()
    if name:
        return name
    host = re.sub(r"^https?://", "", os.getenv("LLM_BASE_URL") or "").split("/")[0]
    return provider_label(host) if host else "unknown"


# ------------------------------------------------------------------------- AgentRun
#
# The activities of the `AgentRun` workflow. Each takes ids and small counters only. The
# opening message, the thread, the tool results and the answer are read from and written to
# `agent_runs`, `agent_run_messages` and `chat_messages` inside the activity.


@dataclass
class AgentRunInput:
    """The input of one `AgentRun` workflow. Ids and settings, never text.

    A sub-agent and a continuation carry their own `run_id` and `kind`, and copy every
    other field from the input of the run that starts them, except `plan_run_id` and
    `decision_id`, which are empty. The row has no columns for `allowed_collections`,
    `llm_model`, `internet_tools` and `turn_uuid`. Their row already exists, written by the
    run that created them. A run of a plan takes `llm_model` and `internet_tools` from the
    plan's execution settings (`OpenedRun`), whatever its input holds.
    """

    run_id: str
    username: str
    session_id: str
    #: Read by `open_run` only, for a new top-level run.
    kind: str = "chat"
    #: Seq of the user row of the turn.
    turn_seq: int = 0
    #: First transcript seq the run may write.
    start_seq: int = 0
    #: The uuid of every stream row of the turn. The website writes the user row with it.
    turn_uuid: str = ""
    #: The collections the caller may read. A start through Temporal's HTTP route can store
    #: an empty list as `null`, so `None` is accepted and becomes `[]`. With an empty list
    #: the collection server refuses every call, and the website agent routes use the
    #: caller's own permitted collections.
    allowed_collections: list[str] | None = field(default_factory=list)
    #: Resolved and allowlist-checked by the website. Empty takes the server default.
    llm_model: str = ""
    #: The conversation's frozen switch. It selects the agent service.
    internet_tools: bool = False
    plan_run_id: str = ""
    #: The decision row that started a planner round or an organizer step.
    decision_id: str = ""
    #: The extra planner round for a plan with no section already ran.
    planner_retry_done: bool = False
    #: How the website resolved `llm_model` for a plan run from before the execution
    #: settings: `legacy_planner` or `configured_default`. Empty for every other start.
    model_source: str = ""

    def __post_init__(self):
        if self.allowed_collections is None:
            self.allowed_collections = []


@dataclass
class CallRef:
    """One call of the last `ai` message, as the workflow sees it. No argument text."""

    ai_idx: int
    #: The 0-based place of the call in the reply.
    position: int
    call_id: str
    #: A tool name.
    name: str
    #: `parallel` or `ordered`. A stored call of an older run can hold `delegation`.
    kind: str
    #: The transcript seq of the call's tool row.
    seq: int
    #: False for a call that gets one attempt only, such as a browser action.
    retry: bool = True


def call_refs(message) -> list[CallRef]:
    """The `CallRef` of each stored call entry of an `ai` message, in reply order."""
    out = []
    for position, entry in enumerate(message.tool_calls):
        out.append(CallRef(
            ai_idx=message.idx, position=int(entry.get("position", position)),
            call_id=str(entry.get("id") or ""), name=str(entry.get("name") or ""),
            kind=str(entry.get("kind") or "parallel"), seq=int(entry.get("seq") or 0),
            retry=bool(entry.get("retry", True)),
        ))
    return out


def pending_calls(row, messages) -> list[CallRef]:
    """The calls of the last `ai` message of the thread that have no `tool` message.

    A stored `delegation` call of an older run is left out. It was a `run_subagent` call,
    which no tool answers now.
    """
    last_ai = next((m for m in reversed(messages) if m.role == "ai"), None)
    if last_ai is None:
        return []
    answered = {m.tool_call_id for m in messages if m.role == "tool" and m.idx > last_ai.idx}
    return [c for c in call_refs(last_ai)
            if c.call_id not in answered and c.kind != "delegation"]


@dataclass
class OpenedRun:
    """What `open_run` returns: `closed`, or the row's routing fields and its steps."""

    state: str
    queue: str = ""
    kind: str = ""
    depth: int = 0
    is_chat_lead: bool = False
    #: The run serves a plan run. No step reads this field.
    plan: bool = False
    #: For `closed` after a stop: a continuation that `fan_in` wrote, for the workflow to
    #: start. A stopped turn continues no run, so it is empty in practice.
    continuation_run_id: str = ""
    #: `agent_runs.model_steps`, the model calls of the run thread so far.
    model_steps: int = 0
    #: The row continues another run, so the loop first adds the children's reports.
    continues: bool = False
    #: The unanswered calls of the thread, which the loop runs before its next model step.
    pending: list[CallRef] = field(default_factory=list)
    #: The model and the internet switch of a run of a plan, from the plan's execution
    #: settings. `frozen` is true when the plan has settings. The switch then replaces the
    #: input switch, and a model that is not empty replaces the input model. A run of no
    #: plan keeps its input.
    frozen: bool = False
    llm_model: str = ""
    internet_tools: bool = False
    #: The run is an organizer that starts the sections of its plan before any model call.
    dispatch: bool = False


@dataclass
class RunSummary:
    """How a round of the loop ended. Ids and counts only, well under 4 KiB with five
    children."""

    outcome: str
    next_seq: int = 0
    next_idx: int = 0
    children: list[str] = field(default_factory=list)
    batch_id: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    #: Empty for an answer. `step_budget` or `empty_response` for a run that stopped
    #: before an answer (`steps.write_incomplete`).
    end_reason: str = ""
    asked: bool = False


@dataclass
class Continuation:
    """A continuation run that `fan_in` or `continue_run` wrote, or empty for none."""

    run_id: str = ""
    workflow_id: str = ""


@dataclass
class AppendNagParams:
    """One note that starts a round. `message` is text that this worker holds: the note of
    the planner's extra round."""

    run_id: str
    username: str
    session_id: str
    seq: int
    idx: int
    message: str


@dataclass
class WriteEndingParams:
    """The terminal state of one run, and the cause of a failure."""

    run_id: str
    username: str
    session_id: str
    state: str
    error: str = ""
    turn_uuid: str = ""


@dataclass
class RunRef:
    """One run, by its owner and id."""

    run_id: str
    username: str
    session_id: str


def _insert_chat_row(username: str, session_id: str, seq: int, role: str, **fields) -> None:
    """Write one finished `chat_messages` row through the same writer as today."""
    write_chat_message(WriteResultParams(username=username, session_id=session_id, seq=seq,
                                         role=role, **fields))


def _user_row_text(username: str, session_id: str, seq: int) -> str:
    """The text of the user row at `seq`, the opening message of a chat lead."""
    from database.clickhouse import get_global_client

    with get_global_client() as client:
        rows = client.query(
            "SELECT content FROM chat_messages FINAL WHERE username = {u:String} "
            "AND session_id = {s:String} AND seq = {q:UInt32} AND role = 'user'",
            parameters={"u": username, "s": session_id, "q": seq},
        ).result_rows
    if not rows:
        raise RuntimeError(f"no user row at seq {seq} in session {session_id}")
    return str(rows[0][0])


def _earlier_user_rows(username: str, session_id: str, turn_seq: int) -> int:
    """The count of user rows of the session before `turn_seq`."""
    from database.clickhouse import get_global_client

    with get_global_client() as client:
        rows = client.query(
            "SELECT count() FROM chat_messages FINAL WHERE username = {u:String} "
            "AND session_id = {s:String} AND seq < {q:UInt32} AND role = 'user'",
            parameters={"u": username, "s": session_id, "q": turn_seq},
        ).result_rows
    return int(rows[0][0]) if rows else 0


def _opened(row) -> OpenedRun:
    from database import agent_runs
    from tasks.P_agent.stream_writer import prepare_thread

    from tasks.P_agent import plan_runs

    messages = prepare_thread(
        agent_runs.read_messages(row.username, row.session_id, row.thread_id))
    settings = plan_runs.frozen_settings(row.username, row.session_id,
                                         row.plan_run_id or "") or {}
    return OpenedRun(
        state=row.state, queue=row.queue, kind=row.kind, depth=row.depth,
        is_chat_lead=agent_runs.is_chat_lead(row), plan=bool(row.plan_run_id),
        model_steps=row.model_steps, continues=bool(row.continues_run_id),
        pending=pending_calls(row, messages),
        frozen=bool(settings),
        llm_model=str(settings.get("model") or ""),
        internet_tools=bool(settings.get("internet_tools")),
        dispatch=(row.kind == "organizer" and row.depth == 0 and bool(row.plan_run_id)
                  and not row.continues_run_id and row.state == agent_runs.RUNNING),
    )


@activity.defn
@with_heartbeat
def open_run(inp: AgentRunInput) -> OpenedRun:
    """Create a new top-level run, or read an existing one, and close a stopped turn.

    1. For a top-level run whose row does not exist, write the opening message at `idx` 0
       and then the row. Both keys come from the run id, so a retry writes the same rows.
       For a planner or organizer, first write the plan run state and the plan's execution
       settings (`plan_runs`).
    2. A terminal row returns `closed`.
    3. When the turn has a stop row, write the `cancelled` ending and run `fan_in` here, and
       return `closed`, so a workflow that starts after a stop never calls the agent.
    4. An organizer at depth 0 writes the plan run's `sections_json` from the rows, so each
       organizer step starts from the sections as they stand.
    5. Return the row's routing fields, `model_steps`, the unanswered calls of the thread
       (`pending_calls`), so a continue-as-new or a restarted run resumes there, and for a
       run of a plan the frozen model and internet switch.
    """
    from database import agent_runs
    from tasks.P_agent import plan_runs

    row = agent_runs.read_run(inp.username, inp.session_id, inp.run_id)
    if row is None:
        if inp.kind not in ("chat", *plan_runs.PLAN_KINDS):
            raise RuntimeError(f"open_run cannot create a {inp.kind!r} run")
        text = _user_row_text(inp.username, inp.session_id, inp.turn_seq)
        if inp.kind in plan_runs.PLAN_KINDS:
            text = plan_runs.open_plan_run(inp, text)
        agent_runs.write_message(
            inp.username, inp.session_id, inp.run_id, inp.run_id,
            agent_runs.RunMessageRow(idx=0, role="human", content=text, run_id=inp.run_id),
        )
        agent_runs.create_run(agent_runs.RunRow(
            run_id=inp.run_id, username=inp.username, session_id=inp.session_id,
            turn_seq=inp.turn_seq, thread_id=inp.run_id, depth=0, kind=inp.kind,
            queue=agent_runs.LEAD_QUEUES[inp.kind], workflow_id=activity.info().workflow_id,
            state=agent_runs.RUNNING, start_seq=inp.start_seq, next_seq=inp.start_seq,
            plan_run_id=inp.plan_run_id or None,
        ))
        row = agent_runs.read_run(inp.username, inp.session_id, inp.run_id)
        if row is None:
            raise RuntimeError(f"run {inp.run_id} was written and cannot be read")
    if agent_runs.is_terminal(row):
        return OpenedRun(state="closed")
    if agent_runs.turn_is_stopped(row.username, row.session_id, row.turn_seq):
        _write_ending(WriteEndingParams(row.run_id, row.username, row.session_id,
                                        agent_runs.CANCELLED, turn_uuid=inp.turn_uuid))
        # A stopped child still continues its parent: `fan_in` reads the sibling set, and
        # `continue_run` then ends the parent as `cancelled`, up to depth 0.
        continuation = _fan_in(row.username, row.session_id, row.run_id)
        return OpenedRun(state="closed", continuation_run_id=continuation.run_id)
    if row.kind == "organizer" and row.depth == 0 and row.plan_run_id:
        plan_runs.refresh_sections(row.username, row.session_id, row.plan_run_id)
    return _opened(row)


# ---------------------------------------------------------------------- the sections


def canonical_json(value) -> str:
    """One text for one value, so a retry writes the same bytes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _read_rows(where: str, parameters: dict):
    """Run rows of one owner that match `where`, oldest first."""
    from database import agent_runs

    with agent_runs._client() as client:
        rows = client.query(
            f"SELECT {', '.join(agent_runs.RUN_COLUMNS)} FROM agent_runs FINAL "
            "WHERE username = {u:String} AND session_id = {s:String} AND " + where +
            " ORDER BY started_at, run_id",
            parameters=parameters,
        ).result_rows
    return [agent_runs._from_db(r) for r in rows]


def _batch_children(row, batch_id: str):
    """The sub-agent rows of a batch in section order. Continuations are left out."""
    from database import agent_runs

    rows = _read_rows(
        "parent_run_id = {p:UUID} AND batch_id = {b:UUID} AND continues_run_id IS NULL",
        {"u": row.username, "s": row.session_id, "p": row.run_id, "b": batch_id},
    )
    order = {agent_runs.child_run_id(batch_id, i): i for i in range(len(rows) + 25)}
    return sorted(rows, key=lambda r: order.get(r.run_id, len(order)))


def _sibling_rows(row):
    """Every row of `row`'s parent and batch, continuations included."""
    return _read_rows(
        "parent_run_id = {p:UUID} AND batch_id = {b:UUID}",
        {"u": row.username, "s": row.session_id, "p": row.parent_run_id, "b": row.batch_id},
    )


def _plan_node_paths(row) -> dict[str, str]:
    """The number path of each node of the approved tree of the run's plan, or empty."""
    if not row.plan_run_id:
        return {}
    from database import agent_plans

    plan_run = agent_plans.read_plan_run(row.username, row.session_id, row.plan_run_id)
    if plan_run is None or not plan_run.approved_version:
        return {}
    snapshot = agent_plans.read_snapshot(row.username, row.session_id, plan_run.plan_id,
                                         plan_run.approved_version)
    return agent_plans.node_paths(snapshot) if snapshot else {}


#: The usage key of the message that gives an organizer the outcome of its sections. Its
#: value is the batch id, so a retry finds the message and writes it once.
SECTION_REPORTS_KEY = "section_reports"


def _add_section_reports(row, messages):
    """The message that gives a continued organizer the outcome of each section
    (`prepare_continuation`).

    The continued run started one sub-agent for each section of its plan. This writes one
    `human` message at the next index: `plan_runs.SECTIONS_ENDED_TEXT`, then the canonical
    JSON `{"sections": [...]}` with the outcome of each section in tree order
    (`plan_runs.section_outcome`), its `failed` flag and its cause from `sections_json`.
    Returns the thread with the message. A thread that holds the message already is
    returned as it is.
    """
    from database import agent_runs
    from tasks.P_agent import plan_runs

    continued = agent_runs.read_run(row.username, row.session_id, row.continues_run_id)
    if continued is None or continued.kind != "organizer" or not continued.delegated_batch_id:
        return messages
    batch_id = continued.delegated_batch_id
    if any(m.usage.get(SECTION_REPORTS_KEY) == batch_id for m in messages):
        return messages
    paths = _plan_node_paths(row)
    causes = {e.get("node_id"): e for e in plan_runs.section_entries(
        row.username, row.session_id, row.plan_run_id or "")}
    outcomes = []
    for child in _batch_children(continued, batch_id):
        outcome = plan_runs.section_outcome(child, paths)
        entry = causes.get(child.plan_node_id) or {}
        outcome["failed"] = bool(entry.get("failed"))
        if entry.get("cause"):
            outcome["cause"] = entry["cause"]
        outcomes.append(outcome)
    content = f"{plan_runs.SECTIONS_ENDED_TEXT}\n\n{canonical_json({'sections': outcomes})}"
    message = agent_runs.RunMessageRow(
        idx=max(m.idx for m in messages) + 1, role="human", content=content,
        run_id=row.run_id, usage_json=json.dumps({SECTION_REPORTS_KEY: batch_id}))
    agent_runs.write_message(row.username, row.session_id, row.thread_id, row.run_id, message)
    return [*messages, message]


def _dispatch_sections(row, collections: list[str], writer) -> "RunSummary":
    """Start the sections of an approved plan: one sub-agent for each direct child of the
    approved root, before the organizer's first model call.

    First it reads the row under the writer lock. A terminal row returns `closed`, and
    nothing below is written. A row that already waits for its batch returns its children,
    so a retry starts no second set.

    1. Prepare every assignment (`plan_runs.section_briefings`) from the approved version
       that `open_plan_run` froze.
    2. For each section at index `i`, write the child's opening message, its `prompt`
       document and its row, with the run id `child_run_id(batch_id_for(run_id), i)`. A
       child row that exists is not written again.
    3. Write this run's waiting state.

    No model call and no `run_subagent` call is written. Every key comes from the run id and
    the section index, and the organizer's workflow id is fixed for its plan run, so a
    retry and a competing start write the same rows.
    """
    from database import agent_runs
    from tasks.P_agent import plan_runs

    current = writer.read()
    if current is None or agent_runs.is_terminal(current):
        return RunSummary(outcome="closed", next_seq=current.next_seq if current else 0)
    if current.state == agent_runs.WAITING_FOR_CHILDREN and current.delegated_batch_id:
        children = [c.run_id for c in _batch_children(current, current.delegated_batch_id)]
        return RunSummary(outcome="delegated", next_seq=current.next_seq, children=children,
                          batch_id=current.delegated_batch_id)
    settings = plan_runs.frozen_settings(row.username, row.session_id,
                                         row.plan_run_id or "") or {}
    batch_id = agent_runs.batch_id_for(row.run_id)
    assignments = plan_runs.section_briefings(row.username, row.session_id,
                                              row.plan_run_id or "", collections, settings)
    children = []
    for i, (node_id, briefing, text) in enumerate(assignments):
        child_id = agent_runs.child_run_id(batch_id, i)
        children.append(child_id)
        if agent_runs.read_run(row.username, row.session_id, child_id) is not None:
            continue
        agent_runs.write_message(
            row.username, row.session_id, child_id, child_id,
            agent_runs.RunMessageRow(idx=0, role="human", run_id=child_id, content=text))
        child = agent_runs.RunRow(
            run_id=child_id, username=row.username, session_id=row.session_id,
            turn_seq=row.turn_seq, thread_id=child_id, parent_run_id=row.run_id,
            batch_id=batch_id, depth=row.depth + 1, kind="subagent",
            plan_run_id=row.plan_run_id, plan_node_id=node_id, purpose=briefing["purpose"],
            queue=row.queue, workflow_id=f"run-{child_id}", state=agent_runs.RUNNING,
            briefing=canonical_json(briefing))
        plan_runs.write_prompt_document(child, text)
        agent_runs.create_run(child)
    writer.write(state=agent_runs.WAITING_FOR_CHILDREN, delegated_batch_id=batch_id,
                 delegate_seq=current.next_seq, refused_json="[]")
    log.info("[P_agent] organizer %s started %d sections, batch %s", row.run_id,
             len(children), batch_id)
    return RunSummary(outcome="delegated", next_seq=current.next_seq, children=children,
                      batch_id=batch_id)


@dataclass
class DispatchParams:
    """The organizer run whose sections start, and the collections of its input."""

    run_id: str
    username: str
    session_id: str
    allowed_collections: list[str] | None = field(default_factory=list)


@activity.defn
@with_heartbeat
def dispatch_sections(params: DispatchParams) -> RunSummary:
    """Start the sections of the organizer's approved plan (`_dispatch_sections`). A turn
    with a stop row ends the organizer as `cancelled` here and starts nothing."""
    from database import agent_runs

    row = agent_runs.read_run(params.username, params.session_id, params.run_id)
    if row is None or agent_runs.is_terminal(row):
        return RunSummary(outcome="closed", next_seq=row.next_seq if row else 0)
    if agent_runs.turn_is_stopped(row.username, row.session_id, row.turn_seq):
        _write_ending(WriteEndingParams(row.run_id, row.username, row.session_id,
                                        agent_runs.CANCELLED))
        return RunSummary(outcome="closed", next_seq=row.next_seq)
    return _dispatch_sections(row, list(params.allowed_collections or []),
                              agent_runs.RunRowWriter(row))


def _fan_in(username: str, session_id: str, run_id: str) -> Continuation:
    """Continue the parent when the last sibling ends.

    Returns nothing for a run with no parent, and while one row of the sibling set is not
    terminal. A continuation row copies its parent and batch, so it takes the place of the
    run it continues in the set. Before the continuation, each plan sub-agent thread of the
    set that has no report documents gets them (`reports.ensure_reports`). That writes no
    run state and runs no model or tool.
    """
    from database import agent_runs

    row = agent_runs.read_run(username, session_id, run_id)
    if row is None or not row.parent_run_id or not row.batch_id:
        return Continuation()
    siblings = _sibling_rows(row)
    if not all(agent_runs.is_terminal(s) for s in siblings):
        return Continuation()
    # A plan sub-agent whose ending stopped before its report documents gets them here,
    # from its committed messages, before the parent reads the reports.
    from tasks.P_agent import reports

    reports.ensure_reports(siblings)
    return _continue_run(username, session_id, row.parent_run_id)


def _continue_run(username: str, session_id: str, parent_run_id: str) -> Continuation:
    """Write the continuation of a parent in `waiting_for_children`.

    A parent in another state returns nothing. A stopped turn ends the parent as `cancelled`
    and runs `fan_in` for it, up to depth 0. Up to three writers create the same row, two
    siblings and the sweep, and each writes it at `state_version` 1.
    """
    from database import agent_runs

    parent = agent_runs.read_run(username, session_id, parent_run_id)
    if parent is None or parent.state != agent_runs.WAITING_FOR_CHILDREN:
        return Continuation()
    if agent_runs.turn_is_stopped(parent.username, parent.session_id, parent.turn_seq):
        _write_ending(WriteEndingParams(parent.run_id, parent.username, parent.session_id,
                                        agent_runs.CANCELLED))
        _fan_in(parent.username, parent.session_id, parent.run_id)
        return Continuation()
    run_id = agent_runs.continuation_run_id(parent.delegated_batch_id)
    if agent_runs.read_run(username, session_id, run_id) is None:
        agent_runs.create_run(agent_runs.RunRow(
            run_id=run_id, username=parent.username, session_id=parent.session_id,
            turn_seq=parent.turn_seq, thread_id=parent.thread_id,
            parent_run_id=parent.parent_run_id, batch_id=parent.batch_id,
            continues_run_id=parent.run_id, depth=parent.depth, kind=parent.kind,
            plan_run_id=parent.plan_run_id, plan_node_id=parent.plan_node_id,
            purpose=parent.purpose, queue=parent.queue, workflow_id=f"run-{run_id}",
            state=agent_runs.RUNNING, tool_call_id=parent.tool_call_id,
            start_seq=parent.next_seq, next_seq=parent.next_seq,
            model_steps=parent.model_steps, prompt_tokens=parent.prompt_tokens,
            completion_tokens=parent.completion_tokens,
            subagent_share=parent.subagent_share,
        ))
    return Continuation(run_id=run_id, workflow_id=f"run-{run_id}")


@activity.defn
@with_heartbeat
def fan_in(ref: RunRef) -> Continuation:
    """Continue the parent of a run that ended, when it was the last of its batch."""
    return _fan_in(ref.username, ref.session_id, ref.run_id)


@activity.defn
@with_heartbeat
def continue_run(ref: RunRef) -> Continuation:
    """Continue an organizer whose approved plan gave no section to start."""
    return _continue_run(ref.username, ref.session_id, ref.run_id)


def _finish_stream_rows_from(username: str, session_id: str, turn_uuid: str, seq: int) -> None:
    """Mark final every open stream row of the turn at `seq` or above.

    A retry calls this first, so a row that the failed attempt left open does not stay on
    the page beside the rows the retry writes.
    """
    from tasks.P_agent.stream_writer import ResearchStreamWriter, _TurnParams

    stream = ResearchStreamWriter(_TurnParams(username, session_id, seq, turn_uuid))
    from database.clickhouse import get_global_client

    with get_global_client() as client:
        rows = client.query(
            "SELECT seq, argMax(role, updated_at), argMax(content, updated_at), "
            "argMax(reasoning, updated_at), argMax(tool_name, updated_at), "
            "argMax(tool_call_index, updated_at) FROM chat_message_stream "
            "WHERE username = {u:String} AND session_id = {s:String} "
            "AND message_uuid = {m:String} AND seq >= {q:UInt32} GROUP BY seq "
            "HAVING argMax(is_final, updated_at) = 0",
            parameters={"u": username, "s": session_id, "m": turn_uuid, "q": seq},
        ).result_rows
    for row_seq, role, content, reasoning, tool_name, idx in rows:
        stream._mark_final(row_seq, role, content, reasoning, tool_name, idx)


@activity.defn
@with_heartbeat
def append_nag(params: AppendNagParams) -> int:
    """Write a note that starts a round: a note row at `seq` for a run that writes the
    transcript, and the note text into the thread at `idx`.

    Every key comes from the parameters, so a retry writes the same rows. No counter is
    written. Returns the next free seq.
    """
    from database import agent_runs
    from tasks.P_agent.steps import NOTE_ROLE

    row = agent_runs.read_run(params.username, params.session_id, params.run_id)
    if row is None or agent_runs.is_terminal(row):
        return params.seq
    transcript = agent_runs.writes_transcript(row)
    if transcript:
        _insert_chat_row(row.username, row.session_id, params.seq, NOTE_ROLE,
                         content=params.message)
    agent_runs.write_message(
        row.username, row.session_id, row.thread_id, row.run_id,
        agent_runs.RunMessageRow(idx=params.idx, role="human", content=params.message,
                                 run_id=row.run_id),
    )
    agent_runs.write_run(row, next_seq=params.seq + int(transcript))
    return params.seq + int(transcript)


#: The ending rows of a run that did not complete. The website shows them as they are.
STOPPED_TEXT = "This turn was stopped."
FAILED_TEXT = "The assistant could not answer: {error}"


def _write_ending(params: WriteEndingParams) -> None:
    from database import agent_runs
    from tasks.P_agent.stream_writer import release_browser

    x = agent_runs.read_run(params.username, params.session_id, params.run_id)
    if x is None or agent_runs.is_terminal(x):
        return
    chain = []
    earlier = x.continues_run_id
    while earlier:
        row = agent_runs.read_run(x.username, x.session_id, earlier)
        if row is None:
            break
        chain.append(row)
        earlier = row.continues_run_id
    for row in chain:
        agent_runs.write_run(row, state=params.state, error=params.error, result=x.result)
    if params.state == agent_runs.CANCELLED:
        # A stop that lands while `_dispatch_sections` writes this run's children ends the
        # run before its workflow starts them. Each open child of its own batch then has no workflow,
        # and it ends here with the run.
        for child in _batch_children(x, agent_runs.batch_id_for(x.run_id)):
            if not agent_runs.is_terminal(child):
                _write_ending(WriteEndingParams(child.run_id, child.username,
                                                child.session_id, agent_runs.CANCELLED))
    if agent_runs.writes_transcript(x):
        if params.state == agent_runs.FAILED:
            _insert_chat_row(x.username, x.session_id, x.next_seq, "error",
                             content=FAILED_TEXT.format(error=params.error))
        elif params.state == agent_runs.CANCELLED:
            _insert_chat_row(x.username, x.session_id, x.next_seq, "error",
                             content=STOPPED_TEXT)
        if params.turn_uuid:
            _finish_stream_rows_from(x.username, x.session_id, params.turn_uuid, x.start_seq)
    if x.plan_run_id:
        from tasks.P_agent import plan_runs

        plan_runs.write_plan_ending(x, params.state, chain, params.error)
    for row in [x, *chain]:
        release_browser(row.run_id)
    next_seq = x.next_seq + (1 if params.state != agent_runs.COMPLETED
                             and agent_runs.writes_transcript(x) else 0)
    agent_runs.write_run_terminal(x, params.state, error=params.error, next_seq=next_seq)
    if x.plan_run_id and x.depth >= 1:
        # The report pair follows the terminal row, so a report failure cannot keep the
        # run open. `fan_in` writes a missing pair from the stored messages.
        from tasks.P_agent import reports

        try:
            reports.materialize(x, params.state, chain, params.error)
        except Exception:  # noqa: BLE001 - `ensure_reports` in `fan_in` repairs it
            log.exception("[P_agent] run %s: the report documents were not written, the "
                          "fan-in writes them", x.run_id)


@activity.defn
@with_heartbeat
def write_ending(params: WriteEndingParams) -> None:
    """Write the terminal state of a run, its ending row, and release its browsers.

    Returns at once for a terminal row. Otherwise it writes the state into each earlier run
    of the chain, ends each open child of the run's own batch for a `cancelled` ending (the
    run's workflow never started them), writes the ending row for a run that owns the transcript, marks the turn's
    stream rows final, releases the browsers, and writes this run's own row. The row is the
    completion marker, so a retry after a partial attempt runs every step again, and every
    step writes the same keys. After the row, a plan sub-agent thread gets its report
    documents. A failure there is logged and does not fail the ending, and `fan_in` writes
    the missing documents.
    """
    _write_ending(params)


@activity.defn
@with_heartbeat
def summarize_if_first_turn(ref: RunRef) -> str:
    """Name the conversation when this run answered its first turn. Returns the title.

    Reads the user message and the answer from the database, so neither crosses a Temporal
    payload. **Never raises**, like `title_session`.
    """
    from database import agent_runs

    try:
        row = agent_runs.read_run(ref.username, ref.session_id, ref.run_id)
        if row is None or not agent_runs.is_chat_lead(row):
            return ""
        if _earlier_user_rows(row.username, row.session_id, row.turn_seq):
            return ""
        question = _user_row_text(row.username, row.session_id, row.turn_seq)
    except Exception:  # noqa: BLE001 - a title is never worth a turn
        log.warning("[P_agent] could not read the first turn of %s", ref.session_id,
                    exc_info=True)
        return ""
    return title_session(TitleSessionParams(
        username=row.username, session_id=row.session_id, user_message=question,
        answer=row.result, run_id=row.run_id,
    ))
