"""Activities for durable AI agent turns.

**Every turn runs here**. An ordinary chat message and an exhaustive research run alike.
They differ in which agent they reach, how long they are allowed to take and which queue
they wait on, not in what they do. The website holds nothing open, so a browser reload, a
website restart and a worker crash all cost the turn nothing.

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
    run that created them.
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
    allowed_collections: list[str] = field(default_factory=list)
    #: Resolved and allowlist-checked by the website. Empty takes the server default.
    llm_model: str = ""
    #: The conversation's frozen switch. It selects the agent service.
    internet_tools: bool = False
    plan_run_id: str = ""
    #: The decision row that started a planner round or an organizer step.
    decision_id: str = ""


@dataclass
class OpenedRun:
    """What `open_run` returns: `closed`, or the row's routing fields and nag counters."""

    state: str
    queue: str = ""
    kind: str = ""
    depth: int = 0
    is_chat_lead: bool = False
    #: The run serves a plan run, so its agent activity takes the longer plan timeouts.
    plan: bool = False
    nags_this_turn: int = 0
    nags_without_progress: int = 0
    #: For `closed` after a stop: a continuation that `fan_in` wrote, for the workflow to
    #: start. A stopped turn continues no run, so it is empty in practice.
    continuation_run_id: str = ""


@dataclass
class RunAgentParams:
    """One `run_agent` call. The settings the row does not hold come from the input."""

    run_id: str
    username: str
    session_id: str
    turn_uuid: str = ""
    allowed_collections: list[str] = field(default_factory=list)
    llm_model: str = ""
    internet_tools: bool = False


@dataclass
class RunSummary:
    """What `run_agent` returns. Ids and counts only, well under 4 KiB with five children."""

    outcome: str
    next_seq: int = 0
    next_idx: int = 0
    children: list[str] = field(default_factory=list)
    batch_id: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class Continuation:
    """A continuation run that `fan_in` or `continue_run` wrote, or empty for none."""

    run_id: str = ""
    workflow_id: str = ""


@dataclass
class AppendNagParams:
    """One nag or nag stop row. `message` is text this worker generates from the todo."""

    run_id: str
    username: str
    session_id: str
    seq: int
    idx: int
    message: str
    #: True for a nag that starts a round: the text also goes into the thread.
    starts_round: bool
    nags_this_turn: int = 0
    nags_without_progress: int = 0
    extra_tool_turns: int = 0


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


def _opened(row) -> OpenedRun:
    from database import agent_runs

    return OpenedRun(
        state=row.state, queue=row.queue, kind=row.kind, depth=row.depth,
        is_chat_lead=agent_runs.is_chat_lead(row), plan=bool(row.plan_run_id),
        nags_this_turn=row.nags_this_turn, nags_without_progress=row.nags_without_progress,
    )


@activity.defn
@with_heartbeat
def open_run(inp: AgentRunInput) -> OpenedRun:
    """Create a new top-level run, or read an existing one, and close a stopped turn.

    1. For a top-level run whose row does not exist, write the opening message at `idx` 0
       and then the row. Both keys come from the run id, so a retry writes the same rows.
       For a planner or organizer, first write the plan run state (`plan_runs`).
    2. A terminal row returns `closed`.
    3. When the turn has a stop row, write the `cancelled` ending and run `fan_in` here, and
       return `closed`, so a workflow that starts after a stop never calls the agent.
    4. An organizer at depth 0 writes the plan run's `sections_json` from the rows, so each
       organizer step starts from the sections as they stand.
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


#: Seconds between two heartbeats of `run_agent`. A stop cancels the activity, and the worker
#: learns of the cancel only from the reply to a heartbeat. The chat-model and research
#: workers hold back a heartbeat for at most `RUN_AGENT_HEARTBEAT_THROTTLE`
#: (`tasks/run_worker.py`), so a stop reaches the running agent within about two beats.
RUN_AGENT_HEARTBEAT_SECONDS = 5.0


@activity.defn
@with_heartbeat(interval_seconds=RUN_AGENT_HEARTBEAT_SECONDS)
def run_agent(params: RunAgentParams) -> RunSummary:
    """Run one round of the agent for a run, and write every event as it arrives.

    1. Reads the row and the thread. A retry keeps an unanswered call, and the agent runs it
       before its next model call.
    2. A continuation adds the result of each `run_subagent` call of the run it continues
       (`_add_continuation_results`).
    3. Calls `POST /run/stream`, and writes the messages, the tool rows and the answer row.
    5. On `delegate`, writes the sub-agent runs and the waiting state (`_delegate`).
    6. On `end`, writes the answer.

    A retry resumes from the stored thread and the row's `next_seq`. It never starts again
    from zero. A retry of a run that already wrote its waiting state returns the same
    children. The run's browser is released at the end.
    """
    from database import agent_runs
    from tasks.P_agent.stream_writer import (
        KEEPALIVE_SECONDS, RunStreamClient, _chat_history, prepare_thread, release_browser,
    )

    row = agent_runs.read_run(params.username, params.session_id, params.run_id)
    if row is None:
        raise RuntimeError(f"run {params.run_id} has no row")
    if agent_runs.is_terminal(row):
        return RunSummary(outcome="closed", next_seq=row.next_seq)
    if row.state == agent_runs.WAITING_FOR_CHILDREN and row.delegated_batch_id:
        children = [c.run_id for c in _batch_children(row, row.delegated_batch_id)]
        return RunSummary(outcome="delegated", next_seq=row.next_seq, children=children,
                          batch_id=row.delegated_batch_id, prompt_tokens=row.prompt_tokens,
                          completion_tokens=row.completion_tokens)

    def chat_row(seq: int, role: str, **fields) -> None:
        _insert_chat_row(row.username, row.session_id, seq, role, **fields)

    messages = prepare_thread(
        agent_runs.read_messages(row.username, row.session_id, row.thread_id)
    )
    if row.continues_run_id:
        messages = _add_continuation_results(row, messages, chat_row)

    writer = agent_runs.RunRowWriter(row, interval=KEEPALIVE_SECONDS)
    writer.start_keepalive()
    history = (
        _chat_history(row.username, row.session_id, row.turn_seq)
        if agent_runs.writes_transcript(row) else []
    )

    client = RunStreamClient(
        row, messages, writer, turn_uuid=params.turn_uuid, history=history,
        allowed_collections=params.allowed_collections, llm_model=params.llm_model,
        internet_tools=params.internet_tools, write_chat_row=chat_row,
    )
    try:
        if activity.info().attempt > 1 and client.transcript:
            _finish_stream_rows_from(row.username, row.session_id, params.turn_uuid,
                                     client.next_seq)
        result = client.run()
    finally:
        # A cancellation raises inside this thread at any line. The cleanup is shielded
        # from it, so a stop never leaves the keepalive thread writing the row.
        with (activity.shield_thread_cancel_exception() if activity.in_activity()
              else contextlib.nullcontext()):
            client.close()
            writer.stop_keepalive()
            release_browser(row.run_id)

    usage = result.get("usage") or {}
    prompt = row.prompt_tokens + int(usage.get("prompt_tokens") or 0)
    completion = row.completion_tokens + int(usage.get("completion_tokens") or 0)
    if client.delegates:
        return _delegate(row, client, writer, chat_row, prompt, completion)
    seq = client.next_seq
    answer = result["answer"]
    plan_reference = ""
    if row.plan_run_id and row.depth == 0:
        from tasks.P_agent import plan_runs

        # The organizer's final report names every failed section, whatever the model
        # wrote. The planner's answer row carries the reference that the plan card reads.
        if row.kind == "organizer":
            answer = plan_runs.final_answer(row, answer)
        elif row.kind == "planner":
            plan_reference = plan_runs.plan_reference(row)
    if client.transcript:
        chat_row(
            seq, "assistant",
            content=answer or "(the assistant returned an empty answer)",
            plan_reference_json=plan_reference,
            reasoning=result.get("reasoning") or "",
            model=result.get("model") or "",
            context_tokens=int(usage.get("context_tokens") or 0),
            peak_context_tokens=int(usage.get("peak_context_tokens") or 0),
            context_window=int(usage.get("context_window") or 0),
        )
        client._finish_stream_rows()
        seq += 1
    writer.write(result=answer, next_seq=seq, prompt_tokens=prompt,
                 completion_tokens=completion, tool_turns_used=client.tool_turns_used)
    log.info("[P_agent] run %s answered: %d chars, next seq %d",
             row.run_id, len(answer), seq)
    return RunSummary(outcome="answered", next_seq=seq, next_idx=client.next_idx,
                      prompt_tokens=prompt, completion_tokens=completion)


# ------------------------------------------------------------------------- delegation

DELEGATION_TOOL = "run_subagent"


def canonical_json(value) -> str:
    """One text for one value, so a retry writes the same bytes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def render_briefing(briefing: dict) -> str:
    """The opening message of a sub-agent, in the form the in-process worker receives.

    The same text as `briefing_text` in `research_agent/subagents.py`. Two copies, because
    the two run in different images. They are one rule and move together.
    """
    parts = [f"Objective: {str(briefing.get('objective') or '').strip()}"]
    known = str(briefing.get("known") or "").strip()
    bring_back = str(briefing.get("bring_back") or "").strip()
    if known:
        parts.append(f"Already established, do not re-derive:\n{known}")
    if bring_back:
        parts.append(f"Bring back:\n{bring_back}")
    parts.append(
        "Answer this objective only. Write your report as prose, and cite the documents "
        "you relied on with `cite_documents` before you finish."
    )
    return "\n\n".join(parts)


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
    """The sub-agent rows of a batch in briefing order. Continuations are left out."""
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


def _delegation_rows(username: str, session_id: str, seq: int):
    """The `tool_input` of the transcript row at `seq`."""
    from database.clickhouse import get_global_client

    with get_global_client() as client:
        rows = client.query(
            "SELECT tool_input FROM chat_messages FINAL WHERE username = {u:String} "
            "AND session_id = {s:String} AND seq = {q:UInt32}",
            parameters={"u": username, "s": session_id, "q": seq},
        ).result_rows
    return str(rows[0][0]) if rows else ""


#: The fields of a `sections_json` entry that the organizer reads in a continuation.
ORGANIZER_SECTION_FIELDS = ("node_id", "title", "state", "review", "corrections",
                            "defect_classes", "failed")


def _organizer_sections(row) -> list[dict] | None:
    """The section states of the organizer's plan run, or `None` for any other run.

    The organizer chooses which section to review or correct next. The rule of a failed
    section (no accepting review after the newest work) is in `sections_json`, so the
    organizer reads the same state that the final report and the card read.
    """
    if not (row.kind == "organizer" and row.depth == 0 and row.plan_run_id):
        return None
    from database import agent_plans

    plan_run = agent_plans.read_plan_run(row.username, row.session_id, row.plan_run_id)
    try:
        entries = json.loads(plan_run.sections_json or "[]") if plan_run else []
    except ValueError:
        entries = []
    return [{k: e.get(k) for k in ORGANIZER_SECTION_FIELDS} for e in entries]


def _add_continuation_results(row, messages, chat_row):
    """Design step 2: the result of each `run_subagent` call of the continued run.

    The thread ends with the continued run's `ai` message, whose `run_subagent` calls have
    no `tool` message. For each such call, write one `tool` message at the next index. Its
    content is the canonical JSON `{"reports": [...], "refused": [...]}` from the child rows
    of that call and the continued run's `refused_json`. For the organizer of a plan it
    also holds `sections`, the state of each section from `sections_json`, which `open_run`
    wrote for this step. For a run that writes the
    transcript, rewrite the call's row at `delegate_seq + i` with this JSON as its output.
    Returns the thread with the new messages.
    """
    from database import agent_runs
    from tasks.P_agent.trajectory import truncate_json

    continued = agent_runs.read_run(row.username, row.session_id, row.continues_run_id)
    last_ai = next((m for m in reversed(messages) if m.role == "ai"), None)
    if continued is None or last_ai is None or last_ai.run_id != continued.run_id:
        return messages
    answered = {m.tool_call_id for m in messages if m.role == "tool" and m.idx > last_ai.idx}
    calls = [c for c in last_ai.tool_calls
             if c.get("name") == DELEGATION_TOOL and str(c.get("id") or "") not in answered]
    if not calls:
        return messages
    batch_id = continued.delegated_batch_id or ""
    children = _batch_children(continued, batch_id) if batch_id else []
    try:
        refused = json.loads(continued.refused_json or "[]")
    except ValueError:
        refused = []
    sections = _organizer_sections(row)
    next_idx = max(m.idx for m in messages) + 1
    out = list(messages)
    for i, call in enumerate(calls):
        call_id = str(call.get("id") or "")
        reports = []
        for child in children:
            if child.tool_call_id != call_id:
                continue
            try:
                task = json.loads(child.briefing or "{}").get("objective", "")
            except ValueError:
                task = ""
            reports.append({"task": task, "run_id": child.run_id, "state": child.state,
                            "report": child.result, "error": child.error})
        result = {
            "reports": reports,
            "refused": [r for r in refused if r.get("tool_call_id") == call_id],
        }
        if sections is not None:
            result["sections"] = sections
        content = canonical_json(result)
        seq = continued.delegate_seq + i
        message = agent_runs.RunMessageRow(
            idx=next_idx, role="tool", content=content, tool_call_id=call_id,
            tool_name=DELEGATION_TOOL, run_id=row.run_id,
            usage_json=json.dumps({"chat_seq": seq, "status": "ok"}),
        )
        agent_runs.write_message(row.username, row.session_id, row.thread_id, row.run_id,
                                 message)
        if agent_runs.writes_transcript(row):
            chat_row(seq, "tool", tool_name=DELEGATION_TOOL,
                     tool_input=_delegation_rows(row.username, row.session_id, seq),
                     tool_output=truncate_json(content),
                     content=canonical_json({"state": "reported"}))
        out.append(message)
        next_idx += 1
    return out


def _delegate(row, client, writer, chat_row, prompt: int, completion: int) -> "RunSummary":
    """Design step 5: the run stopped at `run_subagent`.

    First it reads the row under the writer lock. A terminal row returns `closed`, and
    nothing below is written.

    1. For a run that writes the transcript, write one `tool` row for each call from its
       seq, with the briefings, the call id and the batch id as `tool_input`.
    2. Apply the budgets of `run_budgets` to the briefings in call order.
    3. Write each accepted child's row and its opening message.
    4. Write this run's waiting state.

    Every key comes from the run id, so a retry writes the same rows. The children are
    written before the waiting state, and a retry that finds the waiting state returns the
    children without calling the agent.
    """
    from database import agent_runs
    from tasks.P_agent import run_budgets

    # A run that ended while this attempt streamed gets no children and no tool rows.
    current = writer.read()
    if current is None or agent_runs.is_terminal(current):
        log.info("[P_agent] run %s ended before its delegation, no child is written",
                 row.run_id)
        return RunSummary(outcome="closed", next_seq=current.next_seq if current else 0)
    batch_id = agent_runs.batch_id_for(row.run_id)
    calls = [(str(d.get("tool_call_id") or ""), [b for b in d.get("briefings") or []
                                                 if isinstance(b, dict)])
             for d in client.delegates]
    delegate_seq = row.delegate_seq
    next_seq = client.next_seq
    if client.transcript:
        seqs = []
        for call_id, briefings in calls:
            started = client.calls.pop(call_id, None)
            client.pending_tools = [p for p in client.pending_tools if p[4] != call_id]
            if started is None:
                seq, index, summary = client._free_seq(), client.tool_count, ""
                client.tool_count += 1
            else:
                seq, index, _, _, summary = started
            chat_row(seq, "tool", tool_name=DELEGATION_TOOL,
                     tool_input=canonical_json({"briefings": briefings, "tool_call_id": call_id,
                                                "batch_id": batch_id}),
                     tool_output="", content=canonical_json({"state": "delegated"}))
            client._mark_final(seq, "tool", summary, tool_name=DELEGATION_TOOL,
                               tool_call_index=index)
            seqs.append(seq)
        client._finish_stream_rows()
        delegate_seq = min(seqs)
        next_seq = max([client._free_seq(), max(seqs) + 1])

    used, limit = 0, 0
    if row.depth == 0:
        used = run_budgets.count_used(row.username, row.session_id, turn_seq=row.turn_seq,
                                      plan_run_id=row.plan_run_id, own_batch_id=batch_id)
        limit = run_budgets.limit_for(row.plan_run_id)
    sections, corrections = set(), {}
    if row.kind == "organizer" and row.plan_run_id:
        from tasks.P_agent import plan_runs

        sections = plan_runs.approved_sections(row.username, row.session_id, row.plan_run_id)
        corrections = run_budgets.count_corrections(
            row.username, row.session_id, plan_run_id=row.plan_run_id, own_batch_id=batch_id)
    decision = run_budgets.decide(calls, depth=row.depth, used=used, limit=limit,
                                  own_share=row.subagent_share, kind=row.kind,
                                  sections=sections, corrections=corrections)

    children = []
    for i, accepted in enumerate(decision.accepted):
        child_id = agent_runs.child_run_id(batch_id, i)
        children.append(child_id)
        text = render_briefing(accepted.briefing)
        agent_runs.write_message(
            row.username, row.session_id, child_id, child_id,
            agent_runs.RunMessageRow(idx=0, role="human", run_id=child_id, content=text),
        )
        # A child of a plan section copies the section and the purpose from its briefing.
        # The plan rule in `run_budgets` accepted both, and removed them from any other
        # briefing.
        child = agent_runs.RunRow(
            run_id=child_id, username=row.username, session_id=row.session_id,
            turn_seq=row.turn_seq, thread_id=child_id, parent_run_id=row.run_id,
            batch_id=batch_id, depth=row.depth + 1, kind="subagent",
            plan_run_id=row.plan_run_id,
            plan_node_id=accepted.briefing.get("plan_node_id") or None,
            purpose=str(accepted.briefing.get("purpose") or ""), queue=row.queue,
            workflow_id=f"run-{child_id}", state=agent_runs.RUNNING,
            briefing=canonical_json(accepted.briefing), tool_call_id=accepted.tool_call_id,
            subagent_share=accepted.share,
        )
        if agent_runs.read_run(row.username, row.session_id, child_id) is None:
            if child.plan_node_id:
                from tasks.P_agent import plan_runs

                plan_runs.write_prompt_document(child, text)
            agent_runs.create_run(child)

    writer.write(state=agent_runs.WAITING_FOR_CHILDREN, delegated_batch_id=batch_id,
                 delegate_seq=delegate_seq, next_seq=next_seq,
                 tool_turns_used=client.tool_turns_used,
                 refused_json=canonical_json(decision.refused),
                 subagent_share=decision.caller_share, prompt_tokens=prompt,
                 completion_tokens=completion)
    log.info("[P_agent] run %s delegated: %d children, %d refused, batch %s",
             row.run_id, len(children), len(decision.refused), batch_id)
    return RunSummary(outcome="delegated", next_seq=next_seq, next_idx=client.next_idx,
                      children=children, batch_id=batch_id, prompt_tokens=prompt,
                      completion_tokens=completion)


def _fan_in(username: str, session_id: str, run_id: str) -> Continuation:
    """Design section 7.7: continue the parent when the last sibling ends.

    Returns nothing for a run with no parent, and while one row of the sibling set is not
    terminal. A continuation row copies its parent and batch, so it takes the place of the
    run it continues in the set.
    """
    from database import agent_runs

    row = agent_runs.read_run(username, session_id, run_id)
    if row is None or not row.parent_run_id or not row.batch_id:
        return Continuation()
    if not all(agent_runs.is_terminal(s) for s in _sibling_rows(row)):
        return Continuation()
    return _continue_run(username, session_id, row.parent_run_id)


def _continue_run(username: str, session_id: str, parent_run_id: str) -> Continuation:
    """Design section 7.7: write the continuation of a parent in `waiting_for_children`.

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
            tool_turns_used=parent.tool_turns_used, extra_tool_turns=parent.extra_tool_turns,
            nags_this_turn=parent.nags_this_turn,
            nags_without_progress=parent.nags_without_progress,
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
    """Continue a run that delegated and had no briefing accepted."""
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
    """Write a nag row at `seq`, and for a nag round, the nag text into the thread.

    A nag round also writes the row's counters, the nag allowance and `tool_turns_used = 0`,
    so the next `run_agent` round has a fresh count plus the allowance. Every key comes
    from the parameters, so a retry writes the same rows. Returns the next free seq.
    """
    from database import agent_runs
    from tasks.P_agent import nagging

    row = agent_runs.read_run(params.username, params.session_id, params.run_id)
    if row is None or agent_runs.is_terminal(row):
        return params.seq
    _insert_chat_row(row.username, row.session_id, params.seq, nagging.NAG_ROLE,
                     content=params.message)
    changes: dict = {"next_seq": params.seq + 1}
    if params.starts_round:
        agent_runs.write_message(
            row.username, row.session_id, row.thread_id, row.run_id,
            agent_runs.RunMessageRow(idx=params.idx, role="human", content=params.message,
                                     run_id=row.run_id),
        )
        changes.update(
            nags_this_turn=params.nags_this_turn,
            nags_without_progress=params.nags_without_progress,
            extra_tool_turns=params.extra_tool_turns,
            tool_turns_used=0,
        )
    agent_runs.write_run(row, **changes)
    return params.seq + 1


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
        # A stop that lands while `_delegate` writes this run's children ends the run before
        # its workflow starts them. Each open child of its own batch then has no workflow,
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

        plan_runs.write_plan_ending(x, params.state, chain)
    for row in [x, *chain]:
        release_browser(row.run_id)
    next_seq = x.next_seq + (1 if params.state != agent_runs.COMPLETED
                             and agent_runs.writes_transcript(x) else 0)
    agent_runs.write_run_terminal(x, params.state, error=params.error, next_seq=next_seq)


@activity.defn
@with_heartbeat
def write_ending(params: WriteEndingParams) -> None:
    """Write the terminal state of a run, its ending row, and release its browsers.

    Returns at once for a terminal row. Otherwise it writes the state into each earlier run
    of the chain, ends each open child of the run's own batch for a `cancelled` ending (the
    run's workflow never started them), writes the ending row for a run that owns the transcript, marks the turn's
    stream rows final, releases the browsers, and writes this run's own row last. The row
    is the completion marker, so a retry after a partial attempt runs every step again, and
    every step writes the same keys.
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
    from database.clickhouse import get_global_client

    try:
        row = agent_runs.read_run(ref.username, ref.session_id, ref.run_id)
        if row is None or not agent_runs.is_chat_lead(row):
            return ""
        with get_global_client() as client:
            earlier = client.query(
                "SELECT count() FROM chat_messages FINAL WHERE username = {u:String} "
                "AND session_id = {s:String} AND seq < {q:UInt32} AND role = 'user'",
                parameters={"u": row.username, "s": row.session_id, "q": row.turn_seq},
            ).result_rows
        if earlier and int(earlier[0][0]):
            return ""
        question = _user_row_text(row.username, row.session_id, row.turn_seq)
    except Exception:  # noqa: BLE001 - a title is never worth a turn
        log.warning("[P_agent] could not read the first turn of %s", ref.session_id,
                    exc_info=True)
        return ""
    return title_session(TitleSessionParams(
        username=row.username, session_id=row.session_id, user_message=question,
        answer=row.result,
    ))
