"""Write the live rows of the agent steps into `chat_message_stream` and
`agent_run_messages`.

`ModelStepWriter` writes the rows of one `model_step` as the reply of `POST /model_step`
streams, and `ToolCallWriter` the row of one `tool_call`. Their base class
`ResearchStreamWriter` holds the live transcript rules that every run that writes a
transcript applies. `round_view` derives the state of a round from the stored thread,
because no step keeps state.

The rules copied from the Rust side, kept in the same words:

  * content before a tool call is narration about the call, not the answer. It moves
    to `reasoning` as each tool starts;
  * the assistant partial always sits one `seq` after the last tool row;
  * a stream row is rewritten as content grows (ReplacingMergeTree on `updated_at`),
    never appended;
  * a keepalive rewrite every KEEPALIVE_SECONDS bumps `updated_at` even when the model
    is quiet, or the website's stall detector would mark a healthy research run
    "interrupted". Staleness is the signal the poll reads.
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


#: Minimum interval between rewrites of the growing assistant partial. Each rewrite is
#: a ClickHouse insert; 300 ms reads as live without hammering the table.
STREAM_WRITE_MIN_INTERVAL = 0.3

#: How often open rows are rewritten unchanged so the stall detector keeps seeing the
#: turn as alive. Well under the website's CHAT_STREAM_STALL_SECONDS (default 180).
KEEPALIVE_SECONDS = 30.0

#: Short: a dead agent host must fail the activity in seconds, not minutes.
CONNECT_TIMEOUT_SECONDS = 10


class ResearchStreamWriter:
    """The live transcript rows of one turn: the assistant partial, the tool rows, the
    keepalive and the final marks. The two step writers below feed it."""

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

        """
        self.in_plan_first_opening = (
            self.in_plan_first_opening and _tool_name(content) in PLAN_FIRST_TOOLS
        )
        return self.in_plan_first_opening

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


# ---------------------------------------------------------------------- the step stream

#: A `model_step` attempt that receives no line for this long fails. The heartbeat keeps a
#: silent attempt alive, so without this bound a wedged agent holds the slot for the whole
#: start-to-close limit. It is the read timeout of the step request. The agent service
#: sends an SSE comment line (`: keepalive`) every 30 s while a model call waits, and each
#: line restarts this timeout, so 300 s of silence means the agent service is gone or wedged.
#: The value stays fixed when the model is slow.
RUN_STREAM_IDLE_SECONDS = 300

#: The browser server, which keeps one browser for each run until the run releases it.
BROWSER_SERVER_URL = os.getenv("BROWSER_SERVER_URL", "http://hoover4-mcp-browser:8087")

def tool_row_fields(name: str, args: Any, content: str) -> dict[str, str]:
    """The `chat_messages` columns of one finished tool call, in today's row shape.

    A canonical broker page is stored as its own bytes, every other result as truncated
    JSON, and the summary is the start of the arguments.
    """
    from tasks.P_agent.trajectory import (
        TOOL_SUMMARY_CHARS, _dumps, call_query, extract_doc_refs, is_canonical_page,
        truncate, truncate_json,
    )

    tool_input = _dumps(args if args is not None else {})
    if is_canonical_page(content):
        # The row keeps the page's own bytes. The extractor reads the parsed page.
        tool_output = content
        result: Any = json.loads(content)
    else:
        try:
            result = json.loads(content)
        except (TypeError, ValueError):
            result = content
        tool_output = truncate_json(_dumps(result))
    refs = extract_doc_refs(name, result, call_query(args))
    return {
        "tool_name": name,
        "tool_input": truncate_json(tool_input),
        "tool_output": tool_output,
        "content": truncate(tool_input, TOOL_SUMMARY_CHARS),
        "doc_refs": _dumps(refs) if refs else "",
    }


class _TurnParams:
    """The fields `ResearchStreamWriter` reads, for one step of one run."""

    def __init__(self, username: str, session_id: str, start_seq: int, turn_uuid: str):
        self.username = username
        self.session_id = session_id
        self.start_seq = start_seq
        self.turn_uuid = turn_uuid


def tool_summary(name: str, args: Any) -> str:
    """The text of a live tool row: the name and the arguments, cut to 400 characters."""
    return json.dumps({"name": name, "input": args}, default=str)[:400]


class ModelStepWriter(ResearchStreamWriter):
    """The live rows of one `model_step`.

    It writes the assistant partial into `chat_message_stream` at `seq`, one seq after the
    last tool row, and the `ai` partial into `agent_run_messages` at `idx`, as the reply
    streams. `plan_prose` and `reasoning` are the round so far (`round_view`), so the
    partial row shows the whole round and not only this step. A keepalive thread rewrites
    the open rows every `KEEPALIVE_SECONDS`.
    """

    def __init__(self, row, turn_uuid: str, seq: int, idx: int, plan_prose: str = "",
                 reasoning: str = ""):
        from database import agent_runs

        super().__init__(_TurnParams(row.username, row.session_id, seq, turn_uuid))
        self.row = row
        self.transcript = agent_runs.writes_transcript(row)
        self.idx = idx
        self.plan_prose = plan_prose
        self.reasoning = reasoning
        self.partial_text = ""
        self.partial_reasoning = ""
        self._last_partial = 0.0

    def _insert_stream_row(self, *args, **kwargs) -> None:
        if self.transcript:
            super()._insert_stream_row(*args, **kwargs)

    def start(self) -> None:
        if not self.transcript:
            return
        self._write_assistant(force=True)
        self._keepalive_thread = threading.Thread(
            target=self._keepalive_loop, daemon=True, name="model-step-keepalive")
        self._keepalive_thread.start()

    def add(self, kind: str, text: str) -> None:
        """One `reasoning` or `response` frame."""
        if kind == "reasoning":
            if self.reasoning and not self.partial_reasoning:
                self.reasoning += "\n\n"
            self.reasoning += text
            self.partial_reasoning += text
        else:
            self.answer += text
            self.partial_text += text
        self._write_assistant()
        now = time.monotonic()
        if now - self._last_partial >= STREAM_WRITE_MIN_INTERVAL:
            self._last_partial = now
            from database import agent_runs

            agent_runs.write_message(
                self.row.username, self.row.session_id, self.row.thread_id, self.row.run_id,
                agent_runs.RunMessageRow(idx=self.idx, role="ai", run_id=self.row.run_id,
                                         content=self.partial_text,
                                         reasoning=self.partial_reasoning, is_final=0))

    def tool_rows(self, entries: list[dict[str, Any]]) -> None:
        """One live tool row for each call entry, at its seq. The first one takes the
        place of the assistant partial."""
        self.assistant_row_started = False
        for entry in entries:
            self._insert_stream_row(
                entry["seq"], "tool", tool_summary(entry["name"], entry.get("args")),
                tool_name=entry["name"], tool_call_index=entry["seq"] - self.row.start_seq)


class ToolCallWriter(ResearchStreamWriter):
    """The live tool row of one `tool_call`, kept fresh by the keepalive thread while the
    call runs, and marked final when it ends."""

    def __init__(self, row, turn_uuid: str, seq: int, name: str, args: Any):
        from database import agent_runs

        super().__init__(_TurnParams(row.username, row.session_id, seq, turn_uuid))
        self.transcript = agent_runs.writes_transcript(row)
        self.seq = seq
        self.name = name
        self.index = seq - row.start_seq
        self.summary = tool_summary(name, args)
        self.pending_tools = [(seq, self.index, name, self.summary, None)]

    def _insert_stream_row(self, *args, **kwargs) -> None:
        if self.transcript:
            super()._insert_stream_row(*args, **kwargs)

    def start(self) -> None:
        if not self.transcript:
            return
        self._keepalive_thread = threading.Thread(
            target=self._keepalive_loop, daemon=True, name="tool-call-keepalive")
        self._keepalive_thread.start()

    def finish(self) -> None:
        self.pending_tools = []
        self._mark_final(self.seq, "tool", self.summary, tool_name=self.name,
                         tool_call_index=self.index)


def round_view(messages) -> tuple[str, str, bool]:
    """The plan-first prose, the reasoning and the opening state of the current round.

    The round starts after the last `human` message of the thread. No step keeps state, so
    each step derives these from the stored `ai` messages of the round:

    * the opening holds while every call so far is in `PLAN_FIRST_TOOLS`. The text of an
      `ai` message whose first call is inside the opening is plan prose, which the answer
      shows (`ResearchStreamWriter._keeps_preamble` gives the rule).
    * the text of any other `ai` message with calls is narration, which moves to the
      reasoning. The reasoning of every `ai` message of the round is kept too.

    Returns `(plan_prose, reasoning, in_opening)`.
    """
    start = 0
    for i, message in enumerate(messages):
        if message.role == "human":
            start = i + 1
    plan, reasoning, in_opening = [], [], True
    for message in messages[start:]:
        if message.role != "ai":
            continue
        if (message.reasoning or "").strip():
            reasoning.append(message.reasoning.strip())
        names = [str(c.get("name") or "") for c in message.tool_calls]
        if not names:
            continue
        keep = in_opening and names[0] in PLAN_FIRST_TOOLS
        in_opening = in_opening and all(n in PLAN_FIRST_TOOLS for n in names)
        text = (message.content or "").strip()
        if text:
            (plan if keep else reasoning).append(text)
    return "\n\n".join(plan), "\n\n".join(reasoning), in_opening


def run_message(message, thread_id: str) -> dict[str, Any]:
    """One stored thread message in the `RunMessage` shape of a step request.

    A call entry sends its `id`, `name` and `args` only. A `tool` message carries the
    `status` of its stored usage, so the service rebuilds a failed call as an error. Every
    message carries its key, `thread_id` and `idx`, which a `compaction` row names.
    """
    out: dict[str, Any] = {"role": message.role, "content": message.content,
                           "thread_id": str(thread_id), "idx": int(message.idx)}
    if message.role == "ai":
        out["tool_calls"] = [
            {"id": str(c.get("id") or ""), "name": str(c.get("name") or ""),
             "args": c.get("args") if isinstance(c.get("args"), dict) else {}}
            for c in message.tool_calls
        ]
        usage = message.usage
        if usage:
            out["usage"] = {k: int(usage.get(k) or 0)
                            for k in ("input_tokens", "output_tokens", "total_tokens")}
    elif message.role == "tool":
        out["tool_call_id"] = message.tool_call_id
        out["name"] = message.tool_name or None
        status = message.usage.get("status")
        if status in ("ok", "error"):
            out["status"] = status
    return out


def prepare_thread(messages):
    """The complete messages of a thread, which a request sends.

    A partial (`is_final = 0`) is dropped, because its complete form never arrived. When the
    last `ai` message has calls with no `tool` message, the thread keeps them, and the loop
    runs the missing calls before its next model step.
    """
    return [m for m in messages if m.is_final]


def release_browser(run_id: str) -> None:
    """Release the run's browser. Best effort: the browser server also reaps idle browsers."""
    try:
        requests.post(f"{BROWSER_SERVER_URL}/runs/{run_id}/release", timeout=(5, 10))
    except Exception:  # noqa: BLE001 - a missed release costs one idle browser
        log.warning("[P_agent] could not release the browser of run %s", run_id, exc_info=True)
