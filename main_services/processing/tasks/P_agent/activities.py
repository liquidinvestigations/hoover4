"""Activities for durable AI agent turns.

**Every turn runs here**. An ordinary chat message and an exhaustive research run alike.
They differ in which agent they reach and which queue they wait on, not in what they do.
The website holds nothing open, so a browser reload, a website restart and a worker crash
all cost the turn nothing.

This module holds the short activities of `AgentRun`: open, ending and the title. The step activities, one model call or one tool call each, are in
`steps.py`.

The ACL travels with the task. These activities never resolve permissions themselves.
The website resolved them against the caller's identity when the turn was submitted and
passed the resulting collection list in. The same goes for the model id: a forged one has
to be refused where the user is known, which is not here.
"""

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

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
        "use_internet_tools", "options_locked",
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
        "use_internet_tools", "options_locked",
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

    The row has no columns for `allowed_collections`, `llm_model`, `internet_tools` and
    `turn_uuid`.
    """

    run_id: str
    username: str
    session_id: str
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
    #: `parallel` or `ordered`.
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
    """The calls of the last `ai` message of the thread that have no `tool` message."""
    last_ai = next((m for m in reversed(messages) if m.role == "ai"), None)
    if last_ai is None:
        return []
    answered = {m.tool_call_id for m in messages if m.role == "tool" and m.idx > last_ai.idx}
    return [c for c in call_refs(last_ai)
            if c.call_id not in answered]


@dataclass
class OpenedRun:
    """What `open_run` returns: `closed`, or the run's steps and unanswered calls."""

    state: str
    #: `agent_runs.model_steps`, the model calls of the run thread so far.
    model_steps: int = 0
    #: The unanswered calls of the thread, which the loop runs before its next model step.
    pending: list[CallRef] = field(default_factory=list)


@dataclass
class RunSummary:
    """How a round of the loop ended. Ids and counts only."""

    outcome: str
    next_seq: int = 0
    next_idx: int = 0
    #: Empty for an answer. `step_budget` or `empty_response` for a run that stopped
    #: before an answer (`steps.write_incomplete`).
    end_reason: str = ""
    asked: bool = False


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

    messages = prepare_thread(
        agent_runs.read_messages(row.username, row.session_id, row.thread_id))
    return OpenedRun(state=row.state, model_steps=row.model_steps,
                     pending=pending_calls(row, messages))


@activity.defn
@with_heartbeat
def open_run(inp: AgentRunInput) -> OpenedRun:
    """Create a new top-level run, or read an existing one, and close a stopped turn.

    1. When the row does not exist, write the opening message at `idx` 0 and then the row.
       Both keys come from the run id, so a retry writes the same rows.
    2. A terminal row returns `closed`.
    3. When the turn has a stop row, write the `cancelled` ending and return `closed`, so a
       workflow that starts after a stop never calls the agent.
    4. Return `model_steps` and the unanswered calls of the thread (`pending_calls`), so a
       continue-as-new or a restarted run resumes there.
    """
    from database import agent_runs

    row = agent_runs.read_run(inp.username, inp.session_id, inp.run_id)
    if row is None:
        text = _user_row_text(inp.username, inp.session_id, inp.turn_seq)
        agent_runs.write_message(
            inp.username, inp.session_id, inp.run_id, inp.run_id,
            agent_runs.RunMessageRow(idx=0, role="human", content=text, run_id=inp.run_id),
        )
        agent_runs.create_run(agent_runs.RunRow(
            run_id=inp.run_id, username=inp.username, session_id=inp.session_id,
            turn_seq=inp.turn_seq, thread_id=inp.run_id,
            queue=agent_runs.CHAT_MODEL_QUEUE, workflow_id=activity.info().workflow_id,
            state=agent_runs.RUNNING, start_seq=inp.start_seq, next_seq=inp.start_seq,
        ))
        row = agent_runs.read_run(inp.username, inp.session_id, inp.run_id)
        if row is None:
            raise RuntimeError(f"run {inp.run_id} was written and cannot be read")
    if agent_runs.is_terminal(row):
        return OpenedRun(state="closed")
    if agent_runs.turn_is_stopped(row.username, row.session_id, row.turn_seq):
        _write_ending(WriteEndingParams(row.run_id, row.username, row.session_id,
                                        agent_runs.CANCELLED, turn_uuid=inp.turn_uuid))
        return OpenedRun(state="closed")
    return _opened(row)


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


#: The ending rows of a run that did not complete. The website shows them as they are.
STOPPED_TEXT = "This turn was stopped."
FAILED_TEXT = "The assistant could not answer: {error}"


def _write_ending(params: WriteEndingParams) -> None:
    from database import agent_runs
    from tasks.P_agent.stream_writer import release_browser

    x = agent_runs.read_run(params.username, params.session_id, params.run_id)
    if x is None or agent_runs.is_terminal(x):
        return
    if params.state == agent_runs.FAILED:
        _insert_chat_row(x.username, x.session_id, x.next_seq, "error",
                         content=FAILED_TEXT.format(error=params.error))
    elif params.state == agent_runs.CANCELLED:
        _insert_chat_row(x.username, x.session_id, x.next_seq, "error", content=STOPPED_TEXT)
    if params.turn_uuid:
        _finish_stream_rows_from(x.username, x.session_id, params.turn_uuid, x.start_seq)
    release_browser(x.run_id)
    next_seq = x.next_seq + (1 if params.state != agent_runs.COMPLETED else 0)
    agent_runs.write_run_terminal(x, params.state, error=params.error, next_seq=next_seq)


@activity.defn
@with_heartbeat
def write_ending(params: WriteEndingParams) -> None:
    """Write the terminal state of a run, its ending row, and release its browsers.

    Returns at once for a terminal row. Otherwise it writes the ending row, marks the turn's
    stream rows final, releases the browser, and writes this run's own row. The row is the
    completion marker, so a retry after a partial attempt runs every step again, and every
    step writes the same keys.
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
        if row is None:
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
