"""Mirror a streaming research-agent run into `chat_message_stream`.

The Python twin of the website's streaming turn (`website/backend/src/api/chat/mod.rs`
— `TurnState`, `handle_stream_event`). The two must agree: a transcript should read
identically whether the turn ran inline or as a Temporal research task, and the poll
endpoint makes no distinction.

The rules copied from the Rust side, kept in the same words:

  * content before a tool call is narration about the call, not the answer — it moves
    to `reasoning` as each tool starts;
  * the assistant partial always sits one `seq` after the last tool row;
  * a stream row is rewritten as content grows (ReplacingMergeTree on `updated_at`),
    never appended;
  * a keepalive rewrite every KEEPALIVE_SECONDS bumps `updated_at` even when the model
    is quiet, or the website's stall detector would mark a healthy research run
    "interrupted" — research turns have no live-runs entry, so staleness is the only
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

log = logging.getLogger(__name__)


def _tool_name(content: Any) -> str:
    """Tool name out of a LangGraph tool event, whichever shape it arrives in.

    A start event carries it at the top level (the agent puts it there — the raw
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

    `server_settings.llm_default_chat_model` — the same key the website resolves against,
    so a deep-research answer and an inline one in the same conversation say the same
    thing. The worker used to write `os.getenv("LLM_MODEL")` into the row instead: unset
    in this container, so every research row recorded an empty model, while the agent
    quietly answered with whatever *its* container's env said.

    Empty means "no admin default configured" and is passed through as such — the agent
    then falls back to its own, which is the pre-existing behaviour and better than
    refusing the turn.
    """
    try:
        from database.clickhouse import get_server_setting

        return (get_server_setting("llm_default_chat_model") or "").strip()
    except Exception:  # noqa: BLE001 - a research turn must not die over a settings read
        log.warning("[P_agent] could not read llm_default_chat_model", exc_info=True)
        return ""


#: Where the full research agent lives on the shared `hoover4` network.
AGENT_URL = os.getenv("RESEARCH_AGENT_URL", "http://hoover4-full-research-agent:8000")

AGENT_TIMEOUT_SECONDS = int(os.getenv("RESEARCH_AGENT_TIMEOUT_SECONDS", "1800"))

#: Minimum interval between rewrites of the growing assistant partial. Each rewrite is
#: a ClickHouse insert; 300 ms reads as live without hammering the table.
STREAM_WRITE_MIN_INTERVAL = 0.3

#: How often open rows are rewritten unchanged so the stall detector keeps seeing the
#: turn as alive. Well under the website's CHAT_STREAM_STALL_SECONDS (default 60).
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
        self.turn_uuid = f"research-{params.session_id}-{params.start_seq}"
        self.answer = ""
        self.reasoning = ""
        self.tool_count = 0
        #: Started-but-not-ended tool calls, oldest first, as
        #: (seq, tool_call_index, name, summary, tool_call_id). A list rather than a
        #: single "currently running" slot because a graph node may run several tools at
        #: once, and one slot lets the second start overwrite the first — finalising the
        #: wrong row when its end arrives.
        self.pending_tools: list[tuple[int, int, str, str, str | None]] = []
        self.assistant_row_started = False
        self.tool_events: list[dict[str, Any]] = []
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
                self.answer,
                self.reasoning,
                "",
                0,
            ))
        return rows

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
            self.answer,
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
        # before the first event arrives. Two reasons, both load-bearing: the keepalive
        # only refreshes rows it knows are open, and a model that thinks for longer than
        # CHAT_STREAM_STALL_SECONDS before saying anything would otherwise let that
        # placeholder go stale and the page would call a healthy run interrupted.
        self._write_assistant(force=True)
        self._keepalive_thread = threading.Thread(
            target=self._keepalive_loop, daemon=True, name="research-stream-keepalive"
        )
        self._keepalive_thread.start()

        llm_model = _chat_model()
        response = requests.post(
            f"{AGENT_URL}/chat/stream",
            json={
                "session_id": self.params.session_id,
                "user_id": self.params.username,
                "message_id": f"{self.params.session_id}-{self.params.start_seq}",
                "query": self.params.query,
                "chat_history": [],
                "username": self.params.username,
                "allowed_collections": self.params.allowed_collections,
                "llm_model": llm_model,
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
            self._handle(kind, chunk.get("content"))

        # Final stream state: the assistant row is complete, every row goes final. The
        # workflow writes the finished chat_messages rows; these stay only for the TTL.
        if self.assistant_row_started:
            self._write_assistant(force=True)
        self._finish_stream_rows()

        answer = self.answer.strip()
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
        }

    def _handle(self, kind: str | None, content: Any) -> None:
        if kind == "reasoning":
            self.reasoning += str(content or "")
            self._write_assistant()
        elif kind == "response":
            self.answer += str(content or "")
            self._write_assistant()
        elif kind == "start_tool":
            # Narration before a tool call is not the answer.
            if self.answer.strip():
                if self.reasoning:
                    self.reasoning += "\n\n"
                self.reasoning += self.answer.strip()
                self.answer = ""
            # The tool takes the seq the assistant partial occupied; the assistant
            # resumes one later, so live and finalised transcripts order identically.
            tool_seq = self.params.start_seq + self.tool_count
            if self.assistant_row_started:
                self._mark_final(
                    tool_seq, "assistant", self.answer, reasoning=self.reasoning
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

    def _take_pending(self, tool_call_id):
        """Pop the start this end belongs to — by tool_call_id when it has one, else the
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
