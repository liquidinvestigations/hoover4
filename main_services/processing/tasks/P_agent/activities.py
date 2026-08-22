"""Activities for durable AI agent turns.

**Every turn runs here** — an ordinary chat message and an exhaustive research run alike.
They differ in which agent they reach, how long they are allowed to take and which queue
they wait on, not in what they do. The website holds nothing open, so a browser reload, a
website restart and a worker crash all cost the turn nothing.

The ACL travels with the task. These activities never resolve permissions themselves —
the website resolved them against the caller's identity when the turn was submitted and
passed the resulting collection list in. The same goes for the model id: a forged one has
to be refused where the user is known, which is not here.
"""

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

#: One HTTP call to the agent. Generous, because an exhaustive research run is the point
#: of this path, but still bounded so a wedged agent fails the activity and lets
#: Temporal's retry policy take over instead of hanging a worker thread forever.
AGENT_TIMEOUT_SECONDS = int(os.getenv("RESEARCH_AGENT_TIMEOUT_SECONDS", "1800"))


@dataclass
class ResearchTaskParams:
    """Input for one durable agent turn -- an ordinary chat turn or a research run.

    `username` and `session_id` identify where the answer is written back to, and
    `allowed_collections` is the ACL the agent is bounded by. One dataclass serves both
    workflows because the two turns differ in which agent they reach and how long they
    are allowed to take, not in what they are told.
    """

    username: str
    session_id: str
    query: str
    allowed_collections: list[str] = field(default_factory=list)
    #: `seq` of the first row this task may write. The website reserves it when it
    #: submits, so a concurrent synchronous message cannot land on the same position.
    start_seq: int = 0
    #: The conversation's own switch, forwarded from the website. Defaults to true so a
    #: task submitted by an older caller behaves as it did.
    internet_tools: bool = True
    #: The resolved, allowlist-checked model id. The website resolves it -- a forged id
    #: must be refused where the user is known, not here. Empty falls back to the server
    #: setting, which is what a research task submitted by an older caller does.
    llm_model: str = ""
    #: The uuid every row of this turn carries, transcript and stream alike. Passed in
    #: rather than derived: the website writes the user row with it before the workflow
    #: exists, so the two processes must agree, and passing it is how they agree without
    #: a format that both sides have to keep reimplementing. Empty derives the research
    #: form from `(session_id, start_seq)`, which is what older callers rely on.
    turn_uuid: str = ""
    #: Whether this turn should name the conversation when it finishes. Set on the first
    #: turn only: the title is drawn from the exchange that started the thread. Defaults
    #: to false so an older caller keeps the title the website already wrote.
    summarize_session: bool = False
    #: Tool turns granted on top of the agent's own budget. The nag loop raises it by a
    #: fixed increment per nag (`tasks.P_agent.nagging`) so a nagged turn has room to do
    #: something without a nag resetting the budget outright.
    extra_tool_turns: int = 0


@activity.defn
@with_heartbeat
def run_research_agent(params: ResearchTaskParams) -> str:
    """Call the full research agent and return its answer.

    Raises on any failure so Temporal retries. Writing the answer into the chat is a
    separate activity: a retried research run must not append a second transcript.

    The agent is consumed through its streaming endpoint, and the events are mirrored
    into `chat_message_stream` as they arrive: a research run shows the same
    pending tool cards and growing answer as an inline chat turn instead of a static
    "Research task started" placeholder for the whole run. The returned payload is the
    same shape `/chat` produced, so the workflow's finalisation is unchanged.
    """
    activity.heartbeat("calling research agent")
    from tasks.P_agent.stream_writer import ResearchStreamWriter

    writer = ResearchStreamWriter(params)
    try:
        payload = writer.run()
    finally:
        writer.close()
    log.info(
        "[P_agent] research run finished for %s: %d chars, %d tool events",
        params.username,
        len(payload.get("answer", "")),
        len(payload.get("tool_calls", [])),
    )
    return json.dumps(payload)


@dataclass
class ReadTodoParams:
    """Whose todo list to read. One list per `(username, session_id)`."""

    username: str
    session_id: str


@activity.defn
@with_heartbeat
def read_chat_todo(params: ReadTodoParams) -> str:
    """The chat session's todo list as JSON, for the workflow's nag loop.

    An activity because the workflow cannot touch ClickHouse, and JSON because the
    snapshot crosses a Temporal payload. `updated_at` is dropped: the loop asks whether
    the plan is open and whether it moved, and a timestamp answers neither while being
    the one field that will not serialise.

    **Never raises.** A todo that cannot be read is reported as no todo at all, which
    makes the loop stop nagging -- the alternative is failing a turn whose answer is
    already written over a list that is only advisory.
    """
    from database import chat_todos

    try:
        todo = chat_todos.read_todo(params.username, params.session_id)
    except Exception:  # noqa: BLE001 - see the docstring: never worth the turn
        log.warning("[P_agent] could not read the todo for %s", params.session_id, exc_info=True)
        todo = chat_todos.empty_todo(params.session_id, params.username)
    return json.dumps({
        "version": int(todo["version"]),
        "goal": todo["goal"],
        "items": todo["items"],
    })


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


@activity.defn
@with_heartbeat
def write_chat_message(params: WriteResultParams) -> int:
    """Append one row to the global `chat_messages` table.

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
class SummarizeSessionParams:
    """One conversation to name, and the exchange to name it from."""

    username: str
    session_id: str
    user_message: str
    answer: str


@activity.defn
@with_heartbeat
def summarize_session(params: SummarizeSessionParams) -> str:
    """Name a conversation from its first exchange. Returns the title, or empty.

    **This activity cannot fail.** It runs after the answer is written and read, so
    everything that could go wrong here -- a dead endpoint, an unusable reply, an
    unreachable database -- is worth exactly one mediocre title and nothing more. It
    returns instead of raising, and the workflow shields the call as well, because the
    caller must not have to trust this one to be careful.

    The provisional title the website wrote from the first message stays in place
    whenever this produces nothing.
    """
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


def _record_summarizer_call(params: SummarizeSessionParams, result) -> None:
    """Record the call in the two tables `/admin/ai_status` reads.

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
                  result.model, 0, 0, 0, reply_bytes, result.latency_ms, ok,
                  result.error[:500]]],
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


def _provider_label() -> str:
    """A short, stable name for the endpoint that served the call."""
    from tasks.llm_catalog import provider_label

    name = (os.getenv("LLM_PROVIDER_NAME") or "").strip()
    if name:
        return name
    host = re.sub(r"^https?://", "", os.getenv("LLM_BASE_URL") or "").split("/")[0]
    return provider_label(host) if host else "unknown"
