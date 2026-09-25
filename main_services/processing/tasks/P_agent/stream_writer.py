"""Mirror a streaming research-agent run into `chat_message_stream`.

The Python twin of the website's streaming turn (`website/backend/src/api/chat/mod.rs`,
`TurnState`, `handle_stream_event`). The two must agree: a transcript should read
identically whether the turn ran inline or as a Temporal research task, and the poll
endpoint makes no distinction.

The rules copied from the Rust side, kept in the same words:

  * content before a tool call is narration about the call, not the answer. It moves
    to `reasoning` as each tool starts;
  * the assistant partial always sits one `seq` after the last tool row;
  * a stream row is rewritten as content grows (ReplacingMergeTree on `updated_at`),
    never appended;
  * a keepalive rewrite every KEEPALIVE_SECONDS bumps `updated_at` even when the model
    is quiet, or the website's stall detector would mark a healthy research run
    "interrupted". Research turns have no live-runs entry, so staleness is the only
    signal the poll has.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

import requests
from temporalio import activity
from temporalio.exceptions import CancelledError

log = logging.getLogger(__name__)

#: The tool calls a plan-first opening is made of. Prose in front of any of them, before
#: any other tool has run, is the plan being proposed and belongs in the answer -- see
#: `_keeps_preamble`. `read_todo` is in the list because the protocol tells the model to
#: check whether a plan is needed before writing one, so a plan-first turn opens with a
#: read and not a write.
PLAN_FIRST_TOOLS = ("read_todo", "write_todo", "edit_todo", "mark_todo")


def _tool_name(content: Any) -> str:
    """Tool name out of a LangGraph tool event, whichever shape it arrives in.

    A start event carries it at the top level (the agent puts it there, the raw
    `event["data"]` has only `input`); an end event carries it under `output.name`.
    """
    if not isinstance(content, dict):
        return ""
    name = content.get("name") or content.get("tool")
    if not name:
        output = content.get("output")
        if isinstance(output, dict):
            name = output.get("name")
    return str(name or "")


def _tool_call_id(content: Any) -> str | None:
    if not isinstance(content, dict):
        return None
    output = content.get("output")
    if isinstance(output, dict) and output.get("tool_call_id"):
        return str(output["tool_call_id"])
    return str(content["tool_call_id"]) if content.get("tool_call_id") else None

def _chat_model() -> str:
    """The model a research turn runs on, and the one its transcript row records.

    `server_settings.llm_default_chat_model`, the same key the website resolves against,
    so a deep-research answer and an inline one in the same conversation say the same
    thing. The worker used to write `os.getenv("LLM_MODEL")` into the row instead: unset
    in this container, so every research row recorded an empty model, while the agent
    quietly answered with whatever *its* container's env said.

    Empty means "no admin default configured" and is passed through as such. The agent
    then falls back to its own, which is the pre-existing behaviour and better than
    refusing the turn.
    """
    try:
        from database.clickhouse import get_server_setting

        return (get_server_setting("llm_default_chat_model") or "").strip()
    except Exception:  # noqa: BLE001 - a research turn must not die over a settings read
        log.warning("[P_agent] could not read llm_default_chat_model", exc_info=True)
        return ""


def context_window_for(model_id: str) -> int:
    """The catalog's context window for one model id, or 0 when nothing knows it.

    Copied onto the transcript row at write time rather than joined at read time: the
    catalog is refreshed on a schedule, and a model re-listed with a different window
    would otherwise silently restate every past turn's percentage.

    **0 is the representation of "the provider never said."** It is not a fallback and
    nothing may substitute a plausible number for it -- a compaction trigger downstream
    divides by this, and a wrong denominator is trusted exactly as a right one is.

    The catalog is keyed by (provider, model), and which provider served this turn is
    not on the row. Two providers listing the same model id with different windows is
    the ambiguous case, and the **smallest** stated window wins. Guessing high reads as
    plenty of room left and lets a turn run into a real overflow; guessing low only
    compacts something that did not quite need it yet. Rows that state nothing are
    excluded rather than winning as 0.
    """
    if not model_id:
        return 0
    try:
        from database.clickhouse import get_global_client

        with get_global_client() as client:
            rows = client.query(
                "SELECT argMax(context_window, updated_at) AS w FROM llm_models "
                "WHERE model_id = {m:String} GROUP BY provider, model_id "
                "HAVING w > 0 ORDER BY w ASC LIMIT 1",
                parameters={"m": model_id},
            ).result_rows
    except Exception:  # noqa: BLE001 - a missing denominator is not worth a turn
        log.warning("[P_agent] could not read the context window for %s", model_id,
                    exc_info=True)
        return 0
    return int(rows[0][0]) if rows else 0


#: How many prior turns of the conversation the agent is given.
#:
#: A durable research turn sent an EMPTY history answers a follow-up question in an open
#: thread with no idea what "it" refers to, and the answer reads as a non-sequitur.
#: Bounded rather than whole: the transcript grows without limit and the oldest turns are
#: the least relevant to the question just asked.
CHAT_HISTORY_TURNS = int(os.getenv("RESEARCH_CHAT_HISTORY_TURNS", "20"))

#: Per message, so one enormous pasted document in the history cannot crowd out the
#: question itself.
CHAT_HISTORY_MESSAGE_CHARS = 4000


def _chat_history(username: str, session_id: str, before_seq: int) -> list[dict]:
    """The conversation so far, in the agent service's own vocabulary.

    Read from `chat_messages` here rather than serialised by the caller: a durable task
    can start minutes after it was submitted and is retried independently, so the history
    it needs is whatever the transcript says at the moment it runs.
    """
    from database.clickhouse import get_global_client

    try:
        with get_global_client() as client:
            rows = client.query(
                "SELECT role, content FROM chat_messages FINAL "
                "WHERE username = {u:String} AND session_id = {s:String} "
                "AND seq < {seq:UInt32} AND role IN ('user', 'assistant') "
                "AND content != '' "
                "ORDER BY seq DESC LIMIT {limit:UInt32}",
                parameters={"u": username, "s": session_id, "seq": before_seq,
                            "limit": CHAT_HISTORY_TURNS},
            ).result_rows
    except Exception as exc:  # noqa: BLE001
        # A turn with no history is a worse answer, not a failed one.
        log.warning("[P_agent] could not read chat history: %s", exc)
        return []
    return [
        {"type": "human" if role == "user" else "ai",
         "content": str(content)[:CHAT_HISTORY_MESSAGE_CHARS]}
        for role, content in reversed(rows)
    ]


AGENT_TIMEOUT_SECONDS = int(os.getenv("RESEARCH_AGENT_TIMEOUT_SECONDS", "1800"))

#: Minimum interval between rewrites of the growing assistant partial. Each rewrite is
#: a ClickHouse insert; 300 ms reads as live without hammering the table.
STREAM_WRITE_MIN_INTERVAL = 0.3

#: How often open rows are rewritten unchanged so the stall detector keeps seeing the
#: turn as alive. Well under the website's CHAT_STREAM_STALL_SECONDS (default 180).
KEEPALIVE_SECONDS = 30.0

#: Short: a dead agent host must fail the activity in seconds, not minutes.
CONNECT_TIMEOUT_SECONDS = 10


class ResearchStreamWriter:
    """Consume the agent's `/chat/stream` for one research task and mirror it live.

    Produces the same payload dict `/chat` returned, so the workflow's finalisation
    code does not change.
    """

    def __init__(self, params):
        self.params = params
        # The website writes the user row with this uuid before the workflow exists, so
        # it is passed in rather than agreed by two copies of one format string. The
        # derived form stays for the research path, whose caller does not send one.
        self.turn_uuid = (
            getattr(params, "turn_uuid", "")
            or f"research-{params.session_id}-{params.start_seq}"
        )
        self.answer = ""
        #: The plan-first opening, held apart from `answer` so the next fold into
        #: `reasoning` cannot sweep it up with the narration around it. It is prepended
        #: to every rendering of the answer.
        self.plan_prose = ""
        self.reasoning = ""
        self.tool_count = 0
        #: Started-but-not-ended tool calls, oldest first, as
        #: (seq, tool_call_index, name, summary, tool_call_id). A list rather than a
        #: single "currently running" slot because a graph node may run several tools at
        #: once, and one slot lets the second start overwrite the first, finalising the
        #: wrong row when its end arrives.
        self.pending_tools: list[tuple[int, int, str, str, str | None]] = []
        self.assistant_row_started = False
        #: True until the first tool call that is not part of the plan-first opening.
        self.in_plan_first_opening = True
        self.tool_events: list[dict[str, Any]] = []
        #: Token counts from the agent's `end` frame. Empty until it arrives, and empty
        #: for good if the provider reported no usage -- which the workflow records as 0
        #: and every reader shows as unknown.
        self.usage: dict[str, Any] = {}
        self._last_write = 0.0
        self._closed = threading.Event()
        self._keepalive_thread: threading.Thread | None = None

    # ------------------------------------------------------------------ stream table

    def _insert_stream_row(
        self,
        seq: int,
        role: str,
        content: str,
        reasoning: str = "",
        tool_name: str = "",
        tool_call_index: int = 0,
        is_final: bool = False,
    ) -> None:
        from database.clickhouse import get_global_client

        with get_global_client() as client:
            client.insert(
                "chat_message_stream",
                [[
                    self.params.session_id,
                    self.params.username,
                    seq,
                    role,
                    content,
                    reasoning,
                    tool_name,
                    1 if is_final else 0,
                    self.turn_uuid,
                    tool_call_index,
                ]],
                column_names=[
                    "session_id",
                    "username",
                    "seq",
                    "role",
                    "content",
                    "reasoning",
                    "tool_name",
                    "is_final",
                    "message_uuid",
                    "tool_call_index",
                ],
            )

    def _open_rows(self) -> list[tuple[int, str, str, str, str, int]]:
        """The rows a keepalive must refresh: every running tool row and the assistant
        partial, whichever exist. Each as (seq, role, content, reasoning, tool_name,
        tool_call_index)."""
        rows: list[tuple[int, str, str, str, str, int]] = []
        for seq, index, name, summary, _ in self.pending_tools:
            rows.append((seq, "tool", summary, "", name, index))
        if self.assistant_row_started:
            rows.append((
                self.params.start_seq + self.tool_count,
                "assistant",
                self._answer_text(),
                self.reasoning,
                "",
                0,
            ))
        return rows

    def _answer_text(self) -> str:
        """The answer as the transcript should show it: the plan-first opening, then
        whatever the model has said since."""
        return "\n\n".join(part for part in (self.plan_prose, self.answer.strip()) if part)

    def _keepalive_loop(self) -> None:
        while not self._closed.wait(KEEPALIVE_SECONDS):
            for seq, role, content, reasoning, tool_name, idx in self._open_rows():
                try:
                    self._insert_stream_row(seq, role, content, reasoning, tool_name, idx)
                except Exception:  # noqa: BLE001 - a keepalive must never kill the run
                    log.warning("[P_agent] stream keepalive write failed", exc_info=True)

    def _write_assistant(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_write < STREAM_WRITE_MIN_INTERVAL:
            return
        self._last_write = now
        self.assistant_row_started = True
        self._insert_stream_row(
            self.params.start_seq + self.tool_count,
            "assistant",
            self._answer_text(),
            reasoning=self.reasoning,
        )

    def _mark_final(self, seq: int, role: str, content: str, reasoning: str = "",
                    tool_name: str = "", tool_call_index: int = 0) -> None:
        self._insert_stream_row(
            seq, role, content, reasoning, tool_name, tool_call_index, is_final=True
        )

    # ------------------------------------------------------------------ the run

    def run(self) -> dict[str, Any]:
        """Stream the agent run; return the `/chat`-shaped payload."""
        # Take over the placeholder row the website wrote when it accepted the task,
        # before the first event arrives. Two reasons, and neither can be dropped: the keepalive
        # only refreshes rows it knows are open, and a model that spends more time reasoning
        # than CHAT_STREAM_STALL_SECONDS before saying anything would otherwise let that
        # placeholder go stale and the page would call a healthy run interrupted.
        self._write_assistant(force=True)
        self._keepalive_thread = threading.Thread(
            target=self._keepalive_loop, daemon=True, name="research-stream-keepalive"
        )
        self._keepalive_thread.start()

        # The website resolved and allowlist-checked this against the caller's identity,
        # which cannot be done here. Only fall back to the server default when nothing
        # was sent, which is the research path's older callers.
        llm_model = getattr(self.params, "llm_model", "") or _chat_model()
        from .activities import agent_url_for

        agent_url = agent_url_for(getattr(self.params, "internet_tools", True))
        response = requests.post(
            f"{agent_url}/chat/stream",
            json={
                "session_id": self.params.session_id,
                "user_id": self.params.username,
                "message_id": f"{self.params.session_id}-{self.params.start_seq}",
                "query": self.params.query,
                "chat_history": _chat_history(
                    self.params.username, self.params.session_id, self.params.start_seq
                ),
                "username": self.params.username,
                "allowed_collections": self.params.allowed_collections,
                "llm_model": llm_model,
                "extra_tool_turns": getattr(self.params, "extra_tool_turns", 0),
            },
            timeout=(CONNECT_TIMEOUT_SECONDS, AGENT_TIMEOUT_SECONDS),
            stream=True,
        )
        response.raise_for_status()

        # The feed is `data: {json}\n\n` frames; the JSON itself contains no newlines,
        # so iter_lines is a complete frame parser here.
        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            try:
                chunk = json.loads(line[len("data: "):])
            except ValueError:
                log.warning("[P_agent] unparseable stream frame: %.200s", line)
                continue
            kind = chunk.get("type")
            if kind == "error":
                raise RuntimeError(chunk.get("content") or "unknown agent error")
            # Token counts ride on the `end` frame beside `content`, not inside it, so
            # they are taken here rather than in `_handle`.
            if kind == "end" and isinstance(chunk.get("usage"), dict):
                self.usage = dict(chunk["usage"])
            self._handle(kind, chunk.get("content"))

        # Final stream state: the assistant row is complete, every row goes final. The
        # workflow writes the finished chat_messages rows; these stay only for the TTL.
        if self.assistant_row_started:
            self._write_assistant(force=True)
        self._finish_stream_rows()

        answer = self._answer_text()
        reasoning = self.reasoning.strip()
        if not answer and reasoning:
            # Same fallback as the inline path: a turn that called tools and then said
            # nothing new answers with its narration rather than a blank bubble.
            answer = reasoning
            reasoning = ""
        return {
            "answer": answer,
            "reasoning": reasoning,
            "tool_calls": self.tool_events,
            "model": llm_model,
            # Empty when the provider reported no usage at all. The workflow writes 0 in
            # that case and every reader renders 0 as unknown, never as free.
            "usage": {**self.usage, "context_window": context_window_for(llm_model)},
        }

    def _handle(self, kind: str | None, content: Any) -> None:
        if kind == "reasoning":
            self.reasoning += str(content or "")
            self._write_assistant()
        elif kind == "response":
            self.answer += str(content or "")
            self._write_assistant()
        elif kind == "start_tool":
            # Narration before a tool call is not the answer -- except the block that
            # opens a plan-first turn, which stays in it. See `_keeps_preamble`.
            keep_preamble = self._keeps_preamble(content)
            if self.answer.strip():
                if keep_preamble:
                    if self.plan_prose:
                        self.plan_prose += "\n\n"
                    self.plan_prose += self.answer.strip()
                else:
                    if self.reasoning:
                        self.reasoning += "\n\n"
                    self.reasoning += self.answer.strip()
                self.answer = ""
            # The tool takes the seq the assistant partial occupied; the assistant
            # resumes one later, so live and finalised transcripts order identically.
            tool_seq = self.params.start_seq + self.tool_count
            if self.assistant_row_started:
                self._mark_final(
                    tool_seq, "assistant", self._answer_text(), reasoning=self.reasoning
                )
                self.assistant_row_started = False
            name = _tool_name(content)
            summary = json.dumps(content, default=str)[:400] if content else ""
            index = self.tool_count
            self._insert_stream_row(
                tool_seq, "tool", summary, tool_name=name, tool_call_index=index
            )
            self.pending_tools.append((tool_seq, index, name, summary, _tool_call_id(content)))
            self.tool_events.append({"phase": "start", "content": content})
            self.tool_count += 1
        elif kind == "end_tool":
            self.tool_events.append({"phase": "end", "content": content})
            match = self._take_pending(_tool_call_id(content))
            if match is not None:
                seq, index, name, summary, _ = match
                self._mark_final(
                    seq, "tool", summary, tool_name=name, tool_call_index=index
                )
            # Reopen the assistant row so the turn always owns one non-final row: the
            # website's stall detector reads staleness, and a research run that goes
            # quiet between tools with nothing open would read as finished.
            self._write_assistant(force=True)
        # start / start_reasoning / start_response / end need no row writes.

    def _keeps_preamble(self, content: Any) -> bool:
        """Whether the prose before this tool call belongs in the answer, closing the
        plan-first opening if this call is not part of it.

        **Call it once per tool start, whether or not there is prose to place.** It is
        what ends the opening, so skipping it when the answer happens to be empty would
        leave a later todo call still inside an opening that finished several tools ago.

        Both agent profiles are told to open a fresh plan by restating the task and
        weighing two or three approaches before writing the chosen one into the todo.
        That prose is the part a user would correct, so it is shown rather than folded
        into `reasoning` behind the disclosure. Bounded by the opening: it holds while
        every tool called so far has been a todo tool, and ends for good at the first
        call that is real work.

        The agent has the same rule in `research_agent/agent.py::keeps_preamble`, for
        its own non-streaming path. Two copies because the two run in different images;
        they are one rule and must move together.
        """
        self.in_plan_first_opening = (
            self.in_plan_first_opening and _tool_name(content) in PLAN_FIRST_TOOLS
        )
        return self.in_plan_first_opening

    def _take_pending(self, tool_call_id):
        """Pop the start this end belongs to, by tool_call_id when it has one, else the
        oldest unmatched start. Same rules as `trajectory.pair_tool_calls`."""
        if tool_call_id:
            for i, entry in enumerate(self.pending_tools):
                if entry[4] == tool_call_id:
                    return self.pending_tools.pop(i)
        if self.pending_tools:
            return self.pending_tools.pop(0)
        return None

    def _finish_stream_rows(self) -> None:
        """Mark this turn's rows final: the poll's `is_final = 0` filter hides them, and
        the finished chat_messages rows are what renders from then on."""
        from database.clickhouse import get_global_client

        with get_global_client() as client:
            rows = client.query(
                "SELECT seq, argMax(role, updated_at), argMax(content, updated_at), "
                "argMax(reasoning, updated_at), argMax(tool_name, updated_at), "
                "argMax(tool_call_index, updated_at) "
                "FROM chat_message_stream "
                "WHERE username = {u:String} AND session_id = {s:String} "
                "AND message_uuid = {m:String} "
                "GROUP BY seq "
                "HAVING argMax(is_final, updated_at) = 0",
                parameters={
                    "u": self.params.username,
                    "s": self.params.session_id,
                    "m": self.turn_uuid,
                },
            ).result_rows
        for seq, role, content, reasoning, tool_name, idx in rows:
            self._mark_final(seq, role, content, reasoning, tool_name, idx)

    def close(self) -> None:
        self._closed.set()
        if self._keepalive_thread is not None:
            self._keepalive_thread.join(timeout=2)


# ---------------------------------------------------------------------- the run stream

#: An attempt that receives no agent event for this long fails. The heartbeat keeps a
#: silent attempt alive, so without this bound a wedged agent holds the slot for the whole
#: start-to-close timeout. It is the read timeout of the stream request.
RUN_STREAM_IDLE_SECONDS = 300

#: The browser server, which keeps one browser for each run until the run releases it.
BROWSER_SERVER_URL = os.getenv("BROWSER_SERVER_URL", "http://hoover4-mcp-browser:8087")

def tool_row_fields(name: str, args: Any, content: str) -> dict[str, str]:
    """The `chat_messages` columns of one finished tool call, in today's row shape.

    The same rules as `trajectory.pair_tool_calls`: a canonical broker page is stored as its
    own bytes, every other result as truncated JSON, and the summary is the start of the
    arguments.
    """
    from tasks.P_agent.trajectory import (
        TOOL_SUMMARY_CHARS, _dumps, extract_doc_refs, is_canonical_page, truncate,
        truncate_json,
    )

    tool_input = _dumps(args if args is not None else {})
    if is_canonical_page(content):
        tool_output = content
        result: Any = content
    else:
        try:
            result = json.loads(content)
        except (TypeError, ValueError):
            result = content
        tool_output = truncate_json(_dumps(result))
    refs = extract_doc_refs(name, result)
    return {
        "tool_name": name,
        "tool_input": truncate_json(tool_input),
        "tool_output": tool_output,
        "content": truncate(tool_input, TOOL_SUMMARY_CHARS),
        "doc_refs": _dumps(refs) if refs else "",
    }


class _TurnParams:
    """The fields `ResearchStreamWriter` reads, for one attempt of one run."""

    def __init__(self, username: str, session_id: str, start_seq: int, turn_uuid: str):
        self.username = username
        self.session_id = session_id
        self.start_seq = start_seq
        self.turn_uuid = turn_uuid


class RunStreamClient(ResearchStreamWriter):
    """Consume `POST /run/stream` for one attempt of one agent run.

    It writes every event as it arrives, so the database holds the run and no answer or tool
    result crosses a Temporal payload:

    * `model_turn`, `tool_start` and `tool_result` go into `agent_run_messages`, at the
      message index the agent gives. A streaming partial of the next model message is an
      `is_final = 0` row, rewritten at most every `STREAM_WRITE_MIN_INTERVAL` seconds.
    * For a run that writes the transcript, the live rows go into `chat_message_stream` as
      the parent class writes them. A tool call takes its transcript seq when it starts, and
      its finished row goes into `chat_messages` at that seq when its result arrives. The
      result is paired with its call by `tool_call_id`, never by arrival order, so two
      parallel calls keep their own arguments.

    The run row is written through one `RunRowWriter`, so the keepalive and the state
    writes cannot replace each other.
    """

    def __init__(self, row, messages, writer, *, turn_uuid: str, history: list[dict],
                 allowed_collections: list[str], llm_model: str, internet_tools: bool,
                 write_chat_row):
        from database import agent_runs

        self.row = row
        self.run_writer = writer
        self.transcript = agent_runs.writes_transcript(row)
        self.messages = messages
        self.history = history
        self.allowed_collections = allowed_collections
        self.llm_model = llm_model or _chat_model()
        self.internet_tools = internet_tools
        self._write_chat_row = write_chat_row
        self.next_idx = (max(m.idx for m in messages) + 1) if messages else 0
        seqs = list(agent_runs.iter_thread_tool_seqs(messages))
        self.next_seq = max([row.next_seq] + [s + 1 for s in seqs])
        super().__init__(_TurnParams(row.username, row.session_id, self.next_seq, turn_uuid))
        #: Started calls, by `tool_call_id`: (seq, stream index, name, args, summary).
        self.calls: dict[str, tuple[int, int, str, Any, str]] = {}
        self.tool_turns_used = row.tool_turns_used
        self.partial_text = ""
        self.partial_reasoning = ""
        self._last_partial = 0.0
        self.model = self.llm_model
        #: The `delegate` events of this attempt, in call order. A run that delegates
        #: sends them after the `tool_start` of each `run_subagent` call and before `end`.
        self.delegates: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ writes

    def _message(self, idx: int, role: str, **fields) -> None:
        from database import agent_runs

        agent_runs.write_message(
            self.row.username, self.row.session_id, self.row.thread_id, self.row.run_id,
            agent_runs.RunMessageRow(idx=idx, role=role, run_id=self.row.run_id, **fields),
        )

    def _insert_stream_row(self, *args, **kwargs) -> None:
        if self.transcript:
            super()._insert_stream_row(*args, **kwargs)

    def _write_partial(self) -> None:
        now = time.monotonic()
        if now - self._last_partial < STREAM_WRITE_MIN_INTERVAL:
            return
        self._last_partial = now
        self._message(self.next_idx, "ai", content=self.partial_text,
                      reasoning=self.partial_reasoning, is_final=0)

    def _free_seq(self) -> int:
        """The lowest seq that no started-and-unfinished call holds, after every row so far."""
        return self.params.start_seq + self.tool_count

    def _record_progress(self) -> None:
        pending = [seq for seq, *_ in self.calls.values()]
        self.next_seq = min(pending) if pending else self._free_seq()
        self.run_writer.write(next_seq=self.next_seq, tool_turns_used=self.tool_turns_used)

    # ------------------------------------------------------------------ the request

    def request_body(self) -> dict[str, Any]:
        from database import agent_runs

        return {
            "run_id": self.row.run_id,
            "kind": self.row.kind,
            "depth": self.row.depth,
            "username": self.row.username,
            "session_id": self.row.session_id,
            "allowed_collections": self.allowed_collections,
            "llm_model": self.llm_model,
            "history": self.history if agent_runs.writes_transcript(self.row) else [],
            "messages": [run_message(m) for m in self.messages],
            "tool_turns_used": self.row.tool_turns_used,
            "extra_tool_turns": self.row.extra_tool_turns,
            "can_delegate": self.row.depth < 2,
        }

    def run(self) -> dict[str, Any]:
        """Stream the run; return the answer fields. Raises on an agent error."""
        if self.transcript:
            self._write_assistant(force=True)
            self._keepalive_thread = threading.Thread(
                target=self._keepalive_loop, daemon=True, name="run-stream-keepalive"
            )
            self._keepalive_thread.start()

        from .activities import agent_url_for

        response = requests.post(
            f"{agent_url_for(self.internet_tools)}/run/stream",
            json=self.request_body(),
            timeout=(CONNECT_TIMEOUT_SECONDS, RUN_STREAM_IDLE_SECONDS),
            stream=True,
        )
        with response:
            return self._read_stream(response)

    def _read_stream(self, response) -> dict[str, Any]:
        response.raise_for_status()
        ended = False
        for line in response.iter_lines(decode_unicode=True):
            # A stop cancels the attempt. The workflow waits for the attempt to end before
            # it writes the ending, so the attempt stops at the first event after the
            # cancellation and writes nothing more.
            if activity.in_activity() and activity.is_cancelled():
                raise CancelledError("the run was stopped")
            if not line or not line.startswith("data: "):
                continue
            try:
                chunk = json.loads(line[len("data: "):])
            except ValueError:
                log.warning("[P_agent] unparseable run frame: %.200s", line)
                continue
            kind = chunk.get("type")
            if kind == "error":
                raise RuntimeError(chunk.get("content") or "unknown agent error")
            if kind == "end":
                if isinstance(chunk.get("usage"), dict):
                    self.usage = dict(chunk["usage"])
                self.model = chunk.get("model") or self.model
                ended = True
                continue
            self._handle_run_event(kind, chunk.get("content"))
        if not ended:
            raise RuntimeError("the agent stream ended without an end event")

        if self.transcript and self.assistant_row_started:
            self._write_assistant(force=True)
        answer = self._answer_text()
        reasoning = self.reasoning.strip()
        if not answer and reasoning:
            answer, reasoning = reasoning, ""
        return {"answer": answer, "reasoning": reasoning, "model": self.model,
                "usage": {**self.usage, "context_window": context_window_for(self.model)}}

    # ------------------------------------------------------------------ the events

    def _handle_run_event(self, kind: str | None, content: Any) -> None:
        if kind == "reasoning":
            text = str(content or "")
            self.reasoning += text
            self.partial_reasoning += text
            self._write_assistant()
            self._write_partial()
        elif kind == "response":
            text = str(content or "")
            self.answer += text
            self.partial_text += text
            self._write_assistant()
            self._write_partial()
        elif kind == "model_turn" and isinstance(content, dict):
            self._model_turn(content)
        elif kind == "tool_start" and isinstance(content, dict):
            self._tool_start(content)
        elif kind == "tool_result" and isinstance(content, dict):
            self._tool_result(content)
        elif kind == "delegate" and isinstance(content, dict):
            self.delegates.append(content)

    def _model_turn(self, content: dict[str, Any]) -> None:
        idx = int(content.get("index", self.next_idx))
        calls = [
            {"id": str(c.get("id") or ""), "name": str(c.get("name") or ""),
             "args": c.get("args") if isinstance(c.get("args"), dict) else {}}
            for c in content.get("tool_calls") or []
        ]
        self._message(
            idx, "ai",
            content=str(content.get("text") or ""),
            reasoning=str(content.get("reasoning") or ""),
            tool_calls_json=json.dumps(calls),
            usage_json=json.dumps(content.get("usage") or {}),
            is_final=1,
        )
        self.next_idx = idx + 1
        self.partial_text = ""
        self.partial_reasoning = ""
        if calls:
            self.tool_turns_used += 1
            self.run_writer.write(tool_turns_used=self.tool_turns_used)

    def _tool_start(self, content: dict[str, Any]) -> None:
        call_id = str(content.get("tool_call_id") or "")
        name = str(content.get("name") or "")
        args = content.get("args")
        # The prose before a call is narration, except a plan-first opening. The parent
        # class applies that rule and moves the assistant partial one seq down.
        keep_preamble = self._keeps_preamble({"name": name})
        if self.answer.strip():
            if keep_preamble:
                self.plan_prose = "\n\n".join(p for p in (self.plan_prose, self.answer.strip()) if p)
            else:
                self.reasoning = "\n\n".join(p for p in (self.reasoning, self.answer.strip()) if p)
            self.answer = ""
        seq = self._free_seq()
        if self.assistant_row_started:
            self._mark_final(seq, "assistant", self._answer_text(), reasoning=self.reasoning)
            self.assistant_row_started = False
        summary = json.dumps({"name": name, "input": args}, default=str)[:400]
        index = self.tool_count
        self._insert_stream_row(seq, "tool", summary, tool_name=name, tool_call_index=index)
        self.pending_tools.append((seq, index, name, summary, call_id))
        self.calls[call_id] = (seq, index, name, args, summary)
        self.tool_count += 1

    def _tool_result(self, content: dict[str, Any]) -> None:
        call_id = str(content.get("tool_call_id") or "")
        name = str(content.get("name") or "")
        text = content.get("content")
        text = text if isinstance(text, str) else json.dumps(text, default=str)
        started = self.calls.pop(call_id, None)
        self.pending_tools = [p for p in self.pending_tools if p[4] != call_id]
        if started is None:
            # A result with no start: the call still gets a seq, so its row is not lost.
            seq, index, args, summary = self._free_seq(), self.tool_count, {}, ""
            self.tool_count += 1
        else:
            seq, index, _, args, summary = started
        idx = int(content.get("index", self.next_idx))
        self._message(
            idx, "tool", content=text, tool_call_id=call_id, tool_name=name,
            usage_json=json.dumps({"chat_seq": seq, "status": content.get("status") or "ok",
                                   "measure": content.get("measure")}, default=str),
        )
        self.next_idx = max(self.next_idx, idx + 1)
        if self.transcript:
            self._write_chat_row(seq=seq, role="tool", **tool_row_fields(name, args, text))
            self._mark_final(seq, "tool", summary, tool_name=name, tool_call_index=index)
        self._record_progress()
        if self.transcript:
            self._write_assistant(force=True)


def run_message(message) -> dict[str, Any]:
    """One stored thread message in the `RunMessage` shape of the agent's run request."""
    out: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.role == "ai":
        out["tool_calls"] = message.tool_calls
        usage = message.usage
        if usage:
            out["usage"] = {k: int(usage.get(k) or 0)
                            for k in ("input_tokens", "output_tokens", "total_tokens")}
    elif message.role == "tool":
        out["tool_call_id"] = message.tool_call_id
        out["name"] = message.tool_name or None
    return out


def prepare_thread(messages):
    """The complete messages of a thread, which a request sends.

    A partial (`is_final = 0`) is dropped, because its complete form never arrived. When the
    last `ai` message has calls with no `tool` message, the thread keeps them, and the agent
    runs the missing calls before its next model call.
    """
    return [m for m in messages if m.is_final]


def release_browser(run_id: str) -> None:
    """Release the run's browser. Best effort: the browser server also reaps idle browsers."""
    try:
        requests.post(f"{BROWSER_SERVER_URL}/runs/{run_id}/release", timeout=(5, 10))
    except Exception:  # noqa: BLE001 - a missed release costs one idle browser
        log.warning("[P_agent] could not release the browser of run %s", run_id, exc_info=True)
