"""The step activities of `AgentRun`: one model call or one tool call each.

The workflow runs the loop. Each step reads the run row and the stored thread, does one
thing, and writes its result into the thread, so a retry, a worker restart and a
continue-as-new resume from the thread. No text crosses a Temporal payload: a step input
and result hold ids, counts and tool names.

* `model_step` sends `POST /model_step` to the agent service and writes the reply. A reply
  with calls writes the `ai` message and one live tool row for each call. A reply with no
  call writes the `ai` message and the answer row. When the service compacted the input of
  the call, a `compaction` row follows the `ai` message.
* `tool_call` sends `POST /tool_call` for one stored call and writes its `tool` message and
  its finished tool row.
* `delegate_step` writes the children of the `run_subagent` calls of the last reply.
* `prepare_continuation` adds the children's reports to the thread of a continuation.
* `record_step_failure` stores a `tool_unavailable` result for a tool step that failed.
* `plan_has_sections` answers whether the planner wrote a plan section.
* `needs_citations` answers whether a chat answer gets the citation round.
* `write_repeat_note` writes the repeat note, or the text after an empty reply, as a nag.
* `write_found_documents` writes the listing of a sub-agent that answered with no text.

A stored write has a fixed key (`(thread_id, idx)`, `(username, session_id, seq)`), so a
retry writes the same rows. The `ai` message of a step carries `step_no` in its usage, and a
retry that finds it makes no second model call.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

import requests
from temporalio import activity
from temporalio.exceptions import CancelledError

from tasks.heartbeat import with_heartbeat
from tasks.P_agent.activities import (
    DELEGATION_TOOL, CallRef, RunSummary, _add_continuation_results, _delegate,
    _finish_stream_rows_from, _insert_chat_row, agent_url_for, call_refs, canonical_json,
)
from tasks.P_agent import thread_facts
from tasks.P_agent.model_timeouts import STEP_HEARTBEAT_SECONDS

log = logging.getLogger(__name__)

#: The read timeout of `POST /tool_call`. The tool itself has `TOOL_CALL_TIMEOUT` (300 s),
#: and the extra 10 s lets the service answer a tool that timed out inside it.
TOOL_READ_SECONDS = 310

#: The connect timeout of both step requests. A dead agent host fails the step in seconds.
CONNECT_SECONDS = 10

#: The count of model steps in a row whose calls are repeats or exempt reads. The first
#: step that reaches it gets the repeat note, and the second gets one `final` step, which
#: binds no tool.
REPEAT_STEP_LIMIT = 3

#: The human message of a `final` step, for each reason.
FINAL_TEXT = {
    "step_budget": (
        "This run has used all its model steps. Stop now and write the final answer from "
        "what the results above contain. Name the documents you rely on. If they contain "
        "nothing relevant, say so."),
    "repeated_call": (
        f"Your last {REPEAT_STEP_LIMIT} replies only repeated earlier calls, so none of "
        "them ran. Stop now and write the final answer from what the results above "
        "contain. Name the documents you rely on. If they contain nothing relevant, say "
        "so."),
}

#: The stored result of a call that a `final` step did not run: the first sentence of the
#: human message of that step.
NOT_RUN_TEXT = {
    "step_budget": "This run has used all its model steps.",
    "repeated_call": (f"Your last {REPEAT_STEP_LIMIT} replies only repeated earlier calls, "
                      "so none of them ran."),
}

#: A call runs this many times with the same key before the next one is refused. A todo
#: or plan write and a delegation keep 1 run
#: (`runs_allowed`).
REPEAT_RUNS_ALLOWED = 3

#: Reads of state that changes while the run waits. They never repeat.
REPEAT_EXEMPT = ("read_todo", "read_plan",
                 "browser_snapshot", "browser_take_screenshot", "browser_wait_for",
                 "browser_tabs", "browser_console_messages", "browser_network_requests",
                 "browser_navigate", "browser_click", "browser_type",
                 "browser_select_option", "browser_press_key")

#: The writes of the todo list and of the plan tree. Their key holds the store version, so
#: a write repeats only when no write of its store succeeded after the earlier one.
TODO_WRITES = frozenset({"write_todo", "edit_todo", "mark_todo"})
PLAN_WRITES = frozenset({"append_node", "append_child", "move_node", "edit_node", "remove_node"})
STORE_OF = dict([(n, "todo") for n in TODO_WRITES | {"read_todo"}]
                + [(n, "plan") for n in PLAN_WRITES | {"read_plan"}])

#: The stored results of a call that repeats an earlier call, by the kind of the earlier
#: call. The call does not run. The other calls of its reply run.
REPEAT_TEXT_EMPTY = ("This call has the same name and arguments as {source}, which found "
                     "nothing, so it was not run. Send another query, remove a filter, or "
                     "write down that the documents hold nothing on this.")
#: The `{source}` of REPEAT_TEXT_EMPTY, for one earlier call and for more than one.
REPEAT_SOURCE_ONE = "call {call_id} of step {step_no}"
REPEAT_SOURCE_MANY = "{runs} earlier calls, the first being call {call_id} of step {step_no}"
REPEAT_TEXT_RESULT = ("This call has the same name and arguments as call {call_id} of step "
                      "{step_no}, so it was not run. Its result is above. Use it, and go on "
                      "to your next todo item.")
REPEAT_TEXT_START = ("This call has the same name and arguments as call {call_id}, which this "
                     "run made at its start, so it was not run. Its result is above.")
REPEAT_TEXT_DELEGATION = ("This call sends the same briefings as call {call_id} of step "
                          "{step_no}, so no sub-agent was started. The reports of those "
                          "briefings are in the result of that call above. Use them, or send "
                          "briefings with new objectives.")
#: The text of a source with a result when more than one earlier call ran with the key.
REPEAT_TEXT_COUNT = ("This call has the same name and arguments as {runs} earlier calls, the "
                     "first being call {call_id} of step {step_no}, so it was not run. Use "
                     "those results, or change the arguments.")

#: The skill that each kind of refusal names, for a run of kind `chat` or `subagent`.
REPEAT_SKILLS = {"empty": "no_results", "result": "after_a_result", "start": "after_a_result"}
REPEAT_SKILL_KINDS = ("chat", "subagent")

#: Mirrors `research_agent/stumbles.py` SKILL_LINE. The two images share no module.
SKILL_LINE = "The skill `{skill}` shows how to fix this."

#: The first words of the repeat note. They differ from FINAL_TEXT["repeated_call"], so a
#: count of the human rows that start with them finds notes only.
REPEAT_NOTE_HEAD = f"Repeat note. Your last {REPEAT_STEP_LIMIT} replies only repeated earlier calls"

#: The most lines of one list of the repeat note, the newest.
REPEAT_NOTE_LINES = 20

#: The human message of a second `final` step of a sub-agent whose forced answer was empty.
EMPTY_ANSWER_TEXT = ("Your reply was empty. Write your report now, from the results above. "
                     "Name the documents you rely on. If they contain nothing relevant, say so.")

#: The human message after a `tools` reply with no text and no call, once in a thread.
EMPTY_REPLY_TEXT = ("Your last reply had no text and no tool call. Make the call you planned, "
                    "or write your answer now from the results above.")

#: The error class of the stored result of a repeated call.
REPEATED_CALL_CLASS = "repeated_call"

#: The tools that read or change the plan tree or the todo list. The calls of one reply to
#: these tools run one after the other, in the order of the reply, because each one reads
#: the state that the call before it wrote.
STATE_TOOLS = frozenset({
    "append_node", "append_child", "move_node", "edit_node", "remove_node", "read_plan",
    "write_todo", "edit_todo", "mark_todo", "read_todo",
})


def runs_in_order(call) -> bool:
    """Whether a call of a reply runs in the ordered chain of its reply: a call that the
    agent service classed `ordered`, or a call to one of `STATE_TOOLS`."""
    return call.kind == "ordered" or (call.kind != "delegation" and call.name in STATE_TOOLS)

#: The stored result of a tool step that did not finish after its last attempt.
TOOL_UNAVAILABLE_TEXT = ("The tool call did not finish ({error_class}). Try it again, or use "
                         "another tool.")

#: The line that an answer gets when the compaction of a model call of its round
#: summarised the thread. Eviction leaves every result in the transcript, so it adds no
#: line. A summary replaces the model's own working prose, so the answer says so.
SUMMARY_NOTICE = (
    "\n\n---\n\n*This turn grew past the model's context window, so its earlier steps were "
    "summarised before the answer was written. Every step is unchanged above, and every "
    "citation still points at the document it was made from.*"
)


#: The note warning, written as a `human` row after a reply whose `model_turn` frame sets
#: `note_warning`. Mirrors `NOTE_WARNING_TEXT` in the research agent's `compaction.py`,
#: which decides when the warning is due and finds it by its start. The images share no
#: module, so a test compares the two strings.
NOTE_WARNING_TEXT = (
    "Your context is at {pct} percent of its limit. The older steps of this run will soon "
    "be replaced by a record. Save each fact that you need later with `write_note` now."
)
#: The chat role of the compaction line: one row for each compaction of a run that writes
#: the transcript, at the first seq of its step.
COMPACTION_ROLE = "compaction"


class ModelRequestRejected(Exception):
    """The agent service refused the model request, and a repeat cannot fix it (an HTTP 4xx
    other than 408 and 429). The workflow does not retry this type."""


@dataclass
class StepRef:
    """The common input of a step: ids and settings only."""

    run_id: str
    username: str
    session_id: str
    turn_uuid: str = ""
    allowed_collections: list[str] = field(default_factory=list)
    llm_model: str = ""
    internet_tools: bool = False


@dataclass
class ModelStepParams(StepRef):
    #: 1 for the first model call of the run thread.
    step_no: int = 1
    #: `tools` or `final` for an answer with no tool.
    mode: str = "tools"
    #: `step_budget` or `repeated_call`, for mode `final`.
    final_reason: str = ""
    #: A second `final` step of a sub-agent, after an empty answer. The human text is
    #: EMPTY_ANSWER_TEXT with the "Bring back" text. `final_reason` keeps the first reason.
    empty_retry: bool = False


@dataclass
class ModelStepResult:
    #: `answered`, `calls` or `closed`. A `plan` step whose reply has no call gives
    #: `no_plan`, and writes no answer. A `tools` reply with no text and no call, in a
    #: thread with no EMPTY_REPLY_TEXT row, gives `empty`, and writes no answer.
    outcome: str
    #: The calls of the reply that the loop runs. A repeated call has its result already,
    #: and is not in the list.
    calls: list[CallRef] = field(default_factory=list)
    #: The count of model steps in a row, this one included, that hold only repeated calls
    #: and exempt reads, with one repeat at least (`repeat_streak`). 0 otherwise.
    repeat_streak: int = 0
    next_seq: int = 0
    #: The thread index after the last row of the reply (`reply_end_idx`). A `closed` or
    #: `no_plan` result gives the index of its `ai` message.
    next_idx: int = 0
    #: The repeat notes that this run wrote in its thread: its human rows that start with
    #: REPEAT_NOTE_HEAD.
    repeat_notes: int = 0
    #: A reply with no call and no text that wrote the answer row or gives `empty`.
    empty_answer: bool = False


@dataclass
class ToolCallParams(StepRef):
    call: Optional[CallRef] = None


@dataclass
class ToolCallResult:
    #: `ok`, `error` or `closed`.
    status: str
    error_class: str = ""


@dataclass
class AskedAnswerParams(StepRef):
    call: Optional[CallRef] = None


@dataclass
class StepFailure(StepRef):
    #: `model` or `tool`.
    step: str = ""
    #: `tools`, `final` or `plan` for a model step, empty for a tool step.
    mode: str = ""
    #: The model id or the tool name.
    name: str = ""
    #: `schedule_to_start_timeout`, `heartbeat_timeout`, `start_to_close_timeout` or
    #: `activity_error`.
    error_class: str = ""
    task_queue: str = ""
    #: A tool step only.
    call: Optional[CallRef] = None


# ------------------------------------------------------------------------------ helpers


def args_digest(name: str, args: Any) -> str:
    """The sha1 hex of the name, a newline, and the canonical JSON of the arguments. The
    agent service computes the same digest for each call entry."""
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(f"{name}\n{canonical}".encode("utf-8")).hexdigest()


def tool_idx(ai, position: int) -> int:
    """The thread index of the `tool` message of call `position` of the `ai` message.

    The calls that are not delegations take the indexes after the `ai` message in reply
    order, and the delegations follow them. When the reply has a `compaction` row, the row
    takes the index after the `ai` message, and the results start one index later.
    """
    entries = ai.tool_calls
    first = ai.idx + 1 + (1 if ai.usage.get("compaction") else 0)
    plain = [i for i, e in enumerate(entries) if e.get("kind") != "delegation"]
    if position in plain:
        return first + plain.index(position)
    delegations = [i for i, e in enumerate(entries) if e.get("kind") == "delegation"]
    return first + len(plain) + delegations.index(position)


def reply_end_idx(ai) -> int:
    """The thread index after the last row of a reply: the `ai` message, its `compaction`
    row, and one `tool` result for each call."""
    return ai.idx + 1 + (1 if ai.usage.get("compaction") else 0) + len(ai.tool_calls)


def _answer_of(messages, call_id: str):
    """The `tool` message that answers `call_id`, or None."""
    return next((m for m in messages if m.role == "tool" and m.tool_call_id == call_id), None)


def _last_ai(messages):
    return next((m for m in reversed(messages) if m.role == "ai"), None)


def _raise_if_cancelled() -> None:
    if activity.in_activity() and activity.is_cancelled():
        raise CancelledError("the run was stopped")


def _step_run(row, params: StepRef) -> dict[str, Any]:
    """The fields of every step request, from the run row and the input."""
    from tasks.P_agent.stream_writer import _chat_model

    return {
        "run_id": row.run_id,
        "kind": row.kind,
        "depth": row.depth,
        # The purpose of a plan sub-agent. The agent service takes `execute` and `correct`
        # only, so a `review` row of an older plan run sends none.
        "purpose": row.purpose if row.purpose in ("execute", "correct") else None,
        "username": row.username,
        "session_id": row.session_id,
        "allowed_collections": list(params.allowed_collections or []),
        "llm_model": params.llm_model or _chat_model(),
        "can_delegate": row.kind == "organizer" and row.depth == 0,
    }


def _lines(url: str, body: dict, read_seconds: float) -> Iterator[str]:
    """The lines of a streamed POST.

    The request runs in a thread of its own. This thread waits for each line in turns of
    half a second, so a stop ends the wait within a second, and the response is closed.
    """
    lines: queue.Queue = queue.Queue()
    holder: dict[str, Any] = {}

    def pump() -> None:
        try:
            response = requests.post(url, json=body, timeout=(CONNECT_SECONDS, read_seconds),
                                     stream=True)
            holder["response"] = response
            with response:
                response.raise_for_status()
                for line in response.iter_lines(decode_unicode=True):
                    lines.put(("line", line))
            lines.put(("end", None))
        except BaseException as exc:  # noqa: BLE001 - raised again in the activity thread
            lines.put(("error", exc))

    threading.Thread(target=pump, daemon=True, name="step-stream").start()
    try:
        while True:
            try:
                # Positional, because the HTTP timeout check reads every `timeout=`.
                kind, item = lines.get(True, 0.5)
            except queue.Empty:
                _raise_if_cancelled()
                continue
            if kind == "end":
                return
            if kind == "error":
                raise item
            _raise_if_cancelled()
            yield item
    finally:
        response = holder.get("response")
        if response is not None:
            with contextlib.suppress(Exception):
                response.close()


def _post_json(url: str, body: dict, read_seconds: float) -> dict[str, Any]:
    """The JSON answer of a POST that runs in a thread of its own.

    This thread waits in turns of half a second, so a stop ends the wait within a second.
    The request thread then ends when the service answers, and its answer is not used.
    """
    done = threading.Event()
    holder: dict[str, Any] = {}

    def call() -> None:
        try:
            response = requests.post(url, json=body, timeout=(CONNECT_SECONDS, read_seconds))
            response.raise_for_status()
            holder["value"] = response.json()
        except BaseException as exc:  # noqa: BLE001 - raised again in the activity thread
            holder["error"] = exc
        finally:
            done.set()

    threading.Thread(target=call, daemon=True, name="step-request").start()
    while not done.wait(0.5):
        _raise_if_cancelled()
    _raise_if_cancelled()
    if "error" in holder:
        raise holder["error"]
    value = holder.get("value")
    if not isinstance(value, dict):
        raise RuntimeError("the agent service answered /tool_call with no object")
    return value


def _chat_row(row):
    def write(seq: int, role: str, **fields) -> None:
        _insert_chat_row(row.username, row.session_id, seq, role, **fields)
    return write


def _write_tool_result(row, turn_uuid: str, ai, call: CallRef, content: str, status: str,
                       measure: Any = None, error_class: str = "", doc_refs: Any = None) -> None:
    """The `tool` message of one call, and for a run that writes the transcript, its
    finished tool row at the call's seq and the final stream row. `doc_refs` is the list
    that the `/tool_call` response carried beside the result, or None. The run message
    does not store it."""
    from database import agent_runs
    from tasks.P_agent.stream_writer import ToolCallWriter, tool_row_fields

    entry = ai.tool_calls[call.position]
    agent_runs.write_message(
        row.username, row.session_id, row.thread_id, row.run_id,
        agent_runs.RunMessageRow(
            idx=tool_idx(ai, call.position), role="tool", content=content,
            tool_call_id=call.call_id, tool_name=call.name, run_id=row.run_id,
            usage_json=json.dumps({"chat_seq": call.seq, "status": status, "measure": measure,
                                   "error_class": error_class}, default=str)))
    if agent_runs.writes_transcript(row):
        _chat_row(row)(call.seq, "tool", **tool_row_fields(call.name, entry.get("args"), content, doc_refs))
        ToolCallWriter(row, turn_uuid, call.seq, call.name, entry.get("args")).finish()


class PastLimit(Exception):
    """A `plan` attempt got its reply after its start-to-close limit."""

    error_class = "start_to_close_timeout"


def _raise_if_past_limit(started: float) -> None:
    """Refuse the reply of a `plan` attempt that passed its start-to-close limit.

    A `plan` step gets one attempt, and the workflow goes on to the loop when it times out.
    A reply that arrives later must not be written, because the next step writes at the
    same thread index. The cancellation of a timed-out attempt arrives only with a
    heartbeat, so this check reads the clock.
    """
    if not activity.in_activity():
        return
    limit = activity.info().start_to_close_timeout
    if limit is not None and time.monotonic() - started >= limit.total_seconds():
        raise PastLimit("the reply arrived after the start-to-close limit, and is not written")


def _read_thread(row):
    from database import agent_runs
    from tasks.P_agent.stream_writer import prepare_thread

    return prepare_thread(agent_runs.read_messages(row.username, row.session_id, row.thread_id))


def _earlier_turns(row) -> list[dict[str, Any]]:
    """The stored threads of the earlier chat turns of the session, in turn order, as
    `RunMessage` rows. Each thread is sent whole, with its tool calls and results. A
    sub-agent thread is not sent, because its report is a result of the lead's thread."""
    from database import agent_runs
    from tasks.P_agent.stream_writer import prepare_thread, run_message

    out: list[dict[str, Any]] = []
    for thread_id in agent_runs.read_earlier_threads(row.username, row.session_id,
                                                     row.turn_seq):
        messages = prepare_thread(agent_runs.read_messages(row.username, row.session_id,
                                                           thread_id))
        out.extend(run_message(m, thread_id) for m in messages)
    return out


def _write_compaction(row, ai, record: dict) -> None:
    """The `compaction` row of a reply, at the index after its `ai` message."""
    from database import agent_runs

    agent_runs.write_message(
        row.username, row.session_id, row.thread_id, row.run_id,
        agent_runs.RunMessageRow(idx=ai.idx + 1, role="compaction",
                                 content=json.dumps(record, sort_keys=True), run_id=row.run_id))


def compaction_line(record: dict, tokens_after: int, parts: int = 0) -> dict:
    """The done content of the compaction line, from the stored record of the reply.

    `parts` is the count of summary parts that the `compaction` frame gave. `part_states`
    holds `ok` or `failed` for each part, from the record.
    """
    states = [str(s) for s in record.get("parts") or []]
    return {"state": "done", "tokens_before": int(record.get("tokens_before") or 0),
            "target": int(record.get("target") or 0), "parts": int(parts or len(states)),
            "tokens_after": int(tokens_after or 0),
            "steps_summarised": int(record.get("steps_summarised") or 0),
            "target_reached": bool(record.get("target_reached")),
            "record": str(record.get("handoff") or ""), "part_states": states}


def _stored_compaction(messages, ai) -> Optional[dict]:
    """The record of the `compaction` row that follows `ai`, or None."""
    for m in messages:
        if m.idx == ai.idx + 1 and m.role == "compaction":
            try:
                return json.loads(m.content or "{}")
            except ValueError:
                return None
    return None


def note_warning_text(ai) -> str:
    """The note warning for a reply. The percent is the reply's tokens against the stated
    window of its model, and 0 when the catalogue states none."""
    from tasks.P_agent.stream_writer import context_window_for

    used = int(ai.usage.get("input_tokens") or 0) + int(ai.usage.get("output_tokens") or 0)
    window = context_window_for(str(ai.usage.get("model") or ""))
    return NOTE_WARNING_TEXT.format(pct=round(100 * used / window) if window else 0)


def _write_note_warning(row, ai, seq: int) -> int:
    """The note warning as a `human` row at `reply_end_idx(ai)`, and for a run that writes
    the transcript, as a `nag` chat row at `seq`. Returns the next free seq."""
    from database import agent_runs
    from tasks.P_agent import nagging

    text = note_warning_text(ai)
    agent_runs.write_message(
        row.username, row.session_id, row.thread_id, row.run_id,
        agent_runs.RunMessageRow(idx=reply_end_idx(ai), role="human", content=text,
                                 run_id=row.run_id))
    if not agent_runs.writes_transcript(row):
        return seq
    _insert_chat_row(row.username, row.session_id, seq, nagging.NAG_ROLE, content=text)
    return seq + 1


def _close_final_calls(row, params: ModelStepParams, messages, ai) -> None:
    """A `final` step binds no tool, so its reply is the answer. Each call of the reply gets
    a `not_run` result in the thread, and no tool row, so the loop ends."""
    from database import agent_runs

    for call in call_refs(ai):
        if _answer_of(messages, call.call_id) is not None:
            continue
        content = json.dumps({"success": False, "error": "not_run",
                              "message": NOT_RUN_TEXT.get(params.final_reason, "")})
        agent_runs.write_message(
            row.username, row.session_id, row.thread_id, row.run_id,
            agent_runs.RunMessageRow(
                idx=tool_idx(ai, call.position), role="tool", content=content,
                tool_call_id=call.call_id, tool_name=call.name, run_id=row.run_id,
                usage_json=json.dumps({"status": "error", "error_class": "not_run"})))


def _read_row(params: StepRef):
    from database import agent_runs

    row = agent_runs.read_run(params.username, params.session_id, params.run_id)
    if row is None:
        raise RuntimeError(f"run {params.run_id} has no row")
    return row


@contextlib.contextmanager
def _step_event(row, step: str, name: str, mode: str = "",
                tool_call_id: str = "") -> Iterator[Any]:
    """The `agent_step_events` row of this attempt, written when the block ends.

    The block sets `ok`, the tokens and the error class of a result. An exception sets
    `ok` 0 and its class, and is raised again. An attempt that lost its heartbeat writes
    no row, because the workflow writes the row of that failure.
    """
    from database import agent_step_events as events

    attempt, task_queue, queue_wait_ms = events.attempt_fields()
    event = events.StepEvent(
        username=row.username, session_id=row.session_id, run_id=row.run_id,
        run_kind=row.kind, step=step, name=name, task_queue=task_queue, attempt=attempt,
        ok=False, mode=mode, tool_call_id=tool_call_id, queue_wait_ms=queue_wait_ms)
    started = time.monotonic()
    try:
        yield event
    except BaseException as exc:
        event.ok = False
        event.error_class = events.error_class_of(exc)
        event.error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        event.duration_ms = int((time.monotonic() - started) * 1000)
        if event.error_class not in events.ATTEMPT_WRITES_NO_ROW:
            with (activity.shield_thread_cancel_exception() if activity.in_activity()
                  else contextlib.nullcontext()):
                events.record(event)


# --------------------------------------------------------------------------- model_step


def _result_failed(result) -> bool:
    """True when a tool result is an error: its status is `error`, or the tool's own JSON
    object says `"success": false` or carries a non-empty `error`. A tool server answers a
    refusal with a normal result, so the status alone misses it."""
    if result.usage.get("status") == "error":
        return True
    text = (result.content or "").lstrip()
    if not text.startswith("{"):
        return False
    try:
        body = json.loads(text)
    except ValueError:
        return False
    return isinstance(body, dict) and (body.get("success") is False or bool(body.get("error")))


@dataclass(frozen=True)
class RepeatSource:
    """The earlier call that a refused call repeats."""

    call_id: str
    step_no: int
    #: `empty`, `result`, `delegation` or `start`.
    kind: str
    #: The successful runs of the key before this call.
    runs: int = 1


def _version(result) -> Optional[int]:
    """The store version that a todo or plan result reports, or None."""
    body = thread_facts.json_object(result.content)
    value = body.get("version") if body else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def compacted_indexes(earlier, thread_id: str) -> set[int]:
    """The indexes of this thread that a `compaction` row evicted, summarised, dropped or
    cut. A call whose source is one of them is not a repeat, because its result left the
    list that the model reads."""
    out: set[int] = set()
    for m in earlier:
        if m.role != "compaction":
            continue
        record = thread_facts.json_object(m.content) or {}
        keys = []
        for name in ("evicted", "summarised", "dropped"):
            keys.extend(k for k in record.get(name) or [] if isinstance(k, list))
        keys.extend(c[:2] for c in record.get("cuts") or [] if isinstance(c, list))
        for key in keys:
            if len(key) >= 2 and str(key[0]) == str(thread_id):
                with contextlib.suppress(TypeError, ValueError):
                    out.add(int(key[1]))
    return out


def _key(name: str, args: Any, versions: dict) -> tuple:
    """The repeat key of a call: the name and the argument digest, and for a todo or plan
    write, its store and the store version."""
    digest = args_digest(name, args or {})
    if name in TODO_WRITES | PLAN_WRITES:
        store = STORE_OF[name]
        return (name, digest, store, versions.get(store))
    return (name, digest)


def _step_versions(ai, results: dict) -> dict:
    """The newest version that the successful todo and plan results of one `ai` message
    report, for each store. This is the version after the step of that message."""
    out: dict = {}
    for e in ai.tool_calls:
        result = results.get(str(e.get("id") or ""))
        store = STORE_OF.get(str(e.get("name") or ""))
        if result is None or store is None or _result_failed(result):
            continue
        version = _version(result)
        if version is not None and (out.get(store) is None or version > out[store]):
            out[store] = version
    return out


def runs_allowed(name: str, source: RepeatSource) -> int:
    """The successful runs of one key before the next call with it is refused. A todo or
    plan write adds the same change again, and a delegation starts the same sub-agents again."""
    if name in TODO_WRITES | PLAN_WRITES or source.kind == "delegation":
        return 1
    return REPEAT_RUNS_ALLOWED


def repeat_sources(earlier, ai_entries: list[dict], thread_id: str = "") -> dict[int, RepeatSource]:
    """The calls of this reply that repeat earlier calls, as `{position: RepeatSource}`.

    A call repeats when the thread holds `runs_allowed` successful runs of its key
    (`_key`) or more. A run whose result failed (`_result_failed`) does not count, because
    the state that made it fail can change. A run whose result a compaction removed
    (`compacted_indexes`) does not count, because the model no longer reads it. The reads
    of REPEAT_EXEMPT never repeat.

    The key of a todo or plan write holds the store version. For an earlier write it is
    the newest version that the results of its `ai` message report. For the new call it is
    the newest version that a successful result of the thread reports. The write repeats
    only when no write of its store succeeded after the step of the earlier write.
    """
    results = {m.tool_call_id: m for m in earlier if m.role == "tool"}
    gone = compacted_indexes(earlier, thread_id)
    first: dict[tuple, RepeatSource] = {}
    runs: dict[tuple, int] = {}
    latest: dict = {}
    for m in earlier:
        if m.role == "tool" and m.tool_name in STORE_OF and not _result_failed(m):
            version = _version(m)
            if version is not None:
                latest[STORE_OF[m.tool_name]] = version
        if m.role != "ai":
            continue
        after_step = _step_versions(m, results)
        for e in m.tool_calls:
            result = results.get(str(e.get("id") or ""))
            if result is None or _result_failed(result) or result.idx in gone:
                continue
            name = str(e.get("name") or "")
            kind = ("start" if m.usage.get("synthetic") else
                    "delegation" if e.get("kind") == "delegation" else
                    "empty" if thread_facts.found_nothing(name, result.content) else "result")
            key = _key(name, e.get("args"), after_step)
            runs[key] = runs.get(key, 0) + 1
            first.setdefault(key, RepeatSource(str(e.get("id") or ""),
                                               int(m.usage.get("step_no") or 0), kind))
    out: dict[int, RepeatSource] = {}
    for position, e in enumerate(ai_entries):
        name = str(e.get("name") or "")
        if name in REPEAT_EXEMPT:
            continue
        key = _key(name, e.get("args"), latest)
        source = first.get(key)
        if source is not None and runs[key] >= runs_allowed(name, source):
            out[int(e.get("position", position))] = RepeatSource(
                source.call_id, source.step_no, source.kind, runs[key])
    return out


def _step_kind(names: list[str], repeated: list[bool]) -> str:
    """`neutral` for a step of exempt reads only, `repeat` for a step of repeats and exempt
    reads with one repeat at least, else `other`."""
    if not names:
        return "other"
    if all(n in REPEAT_EXEMPT for n in names):
        return "neutral"
    if any(repeated) and all(r or n in REPEAT_EXEMPT for n, r in zip(names, repeated)):
        return "repeat"
    return "other"


def repeat_streak(earlier, ai, repeats: dict) -> int:
    """The count of `repeat` steps in a row, `ai` included (`_step_kind`). A `neutral` step
    neither adds to the count nor ends it. A `human` message ends the count."""
    names = [str(e.get("name") or "") for e in ai.tool_calls]
    now = [int(e.get("position", i)) in repeats for i, e in enumerate(ai.tool_calls)]
    if _step_kind(names, now) != "repeat":
        return 0
    results = {m.tool_call_id: m for m in earlier if m.role == "tool"}
    streak = 1
    for m in reversed(earlier):
        if m.role == "human":
            break
        if m.role != "ai":
            continue
        ids = [str(e.get("id") or "") for e in m.tool_calls]
        names = [str(e.get("name") or "") for e in m.tool_calls]
        repeated = [i in results and results[i].usage.get("error_class") == REPEATED_CALL_CLASS
                    for i in ids]
        kind = _step_kind(names, repeated)
        if kind == "neutral":
            continue
        if kind != "repeat":
            break
        streak += 1
    return streak


def repeat_text(source: RepeatSource, run_kind: str) -> str:
    """The stored message of a refused call: the text of the kind of its source, which
    names the count of earlier runs when it is more than 1, and the skill line for a run
    of kind `chat` or `subagent`."""
    fields = {"call_id": source.call_id, "step_no": source.step_no, "runs": source.runs}
    many = source.runs > 1
    if source.kind == "delegation":
        return REPEAT_TEXT_DELEGATION.format(**fields)
    if source.kind == "empty":
        text = REPEAT_TEXT_EMPTY.format(source=(REPEAT_SOURCE_MANY if many
                                                else REPEAT_SOURCE_ONE).format(**fields))
    elif source.kind == "start":
        text = REPEAT_TEXT_START.format(**fields)
    else:
        text = (REPEAT_TEXT_COUNT if many else REPEAT_TEXT_RESULT).format(**fields)
    skill = REPEAT_SKILLS.get(source.kind)
    if skill and run_kind in REPEAT_SKILL_KINDS:
        text += " " + SKILL_LINE.format(skill=skill)
    return text


def _write_repeats(row, params: StepRef, ai, repeats: dict) -> None:
    """The result of each repeated call of a reply. The call does not run. A retry writes
    the same rows at the same keys."""
    for call in call_refs(ai):
        source = repeats.get(call.position)
        if source is None:
            continue
        content = json.dumps({"success": False, "error": REPEATED_CALL_CLASS,
                              "message": repeat_text(source, row.kind)})
        _write_tool_result(row, params.turn_uuid, ai, call, content, "error",
                           error_class=REPEATED_CALL_CLASS)


def repeat_notes(messages, run_id: str) -> int:
    """The repeat notes that run `run_id` wrote in its thread."""
    return sum(1 for m in messages if m.role == "human" and m.run_id == run_id
               and (m.content or "").startswith(REPEAT_NOTE_HEAD))


def repeat_note_text(messages, todo: Optional[dict]) -> str:
    """The repeat note: the open todo items when `todo` is given, and the searches that
    found nothing, each list the newest REPEAT_NOTE_LINES."""
    from tasks.P_agent import nagging

    lines = [f"{REPEAT_NOTE_HEAD}, so none of them ran."]
    if todo is not None:
        items = nagging.open_items(todo)[-REPEAT_NOTE_LINES:]
        if items:
            lines.append("These todo items are still open:")
            lines.extend(f"- {i.get('id')} {json.dumps(str(i.get('text') or ''), ensure_ascii=False)}"
                         for i in items)
    empty = thread_facts.empty_searches(messages, REPEAT_NOTE_LINES)
    if empty:
        lines.append("These searches found nothing:")
        lines.extend(empty)
    lines.append("Do not send these calls again. Change the query, remove a filter, work on an "
                 "open item, or write your answer. If the next "
                 f"{REPEAT_STEP_LIMIT} replies repeat earlier calls again, the run must answer.")
    return "\n".join(lines)


def _bring_back(row) -> str:
    """The "Bring back" text of a sub-agent's stored briefing, or ""."""
    if row.kind != "subagent" or not row.briefing:
        return ""
    briefing = thread_facts.json_object(row.briefing) or {}
    return str(briefing.get("bring_back") or "").strip()


def final_text(row, params: ModelStepParams) -> str:
    """The human message of a `final` step: EMPTY_ANSWER_TEXT for the second final step of
    a sub-agent, else the text of the reason. A sub-agent's text ends with its "Bring back"
    text."""
    if params.empty_retry:
        text = EMPTY_ANSWER_TEXT
    else:
        text = FINAL_TEXT.get(params.final_reason) or FINAL_TEXT["step_budget"]
    bring_back = _bring_back(row)
    return text + ("\n\nBring back: " + bring_back if bring_back else "")


def _close_for_final(row, params: ModelStepParams, messages) -> list:
    """Step 5 of `model_step` in mode `final`: a `not_run` result for each unanswered call of
    the last reply, then the human message of the step (`final_text`). A retry writes
    neither twice."""
    from database import agent_runs

    out = list(messages)
    last_ai = _last_ai(messages)
    if last_ai is not None:
        for call in call_refs(last_ai):
            if _answer_of(messages, call.call_id) is not None:
                continue
            content = json.dumps({"success": False, "error": "not_run",
                                  "message": NOT_RUN_TEXT.get(params.final_reason, "")})
            _write_tool_result(row, params.turn_uuid, last_ai, call, content, "error",
                               error_class="not_run")
        out = _read_thread(row)
    text = final_text(row, params)
    last = out[-1] if out else None
    if not (last is not None and last.role == "human" and last.content == text):
        idx = max(m.idx for m in out) + 1 if out else 0
        message = agent_runs.RunMessageRow(idx=idx, role="human", content=text,
                                           run_id=row.run_id)
        agent_runs.write_message(row.username, row.session_id, row.thread_id, row.run_id,
                                 message)
        out.append(message)
    return out


def _step_tokens(row, step_no: int, usage: dict) -> dict[str, int]:
    """The token columns of the run row after this step. A retry after the run row write
    adds nothing, because the row already counts this step."""
    if row.model_steps >= step_no:
        return {}
    return {"prompt_tokens": row.prompt_tokens + int(usage.get("input_tokens") or 0),
            "completion_tokens": row.completion_tokens + int(usage.get("output_tokens") or 0)}


def _write_calls(row, params: ModelStepParams, earlier, ai, writer, stream) -> ModelStepResult:
    """Step 8 of `model_step`: the live tool rows, the result of each repeated call, and the
    run row of a reply with calls. The result lists the calls that the loop runs."""
    entries = ai.tool_calls
    if stream is not None:
        stream.tool_rows(entries)
    repeats = repeat_sources(earlier, entries, row.thread_id)
    _write_repeats(row, params, ai, repeats)
    calls_end = max([row.next_seq] + [int(e.get("seq") or 0) + 1 for e in entries])
    next_seq, next_idx = calls_end, reply_end_idx(ai)
    if ai.usage.get("note_warning"):
        # The seq after the calls is the same on a retry, so the rows are the same.
        next_seq = max(row.next_seq, _write_note_warning(row, ai, calls_end))
        next_idx += 1
    writer.write(next_seq=next_seq, model_steps=max(row.model_steps, params.step_no),
                 **_step_tokens(row, params.step_no, ai.usage))
    return ModelStepResult(outcome="calls",
                           calls=[c for c in call_refs(ai) if c.position not in repeats],
                           repeat_streak=repeat_streak(earlier, ai, repeats),
                           next_seq=next_seq, next_idx=next_idx,
                           repeat_notes=repeat_notes(earlier, row.run_id))


def keeps_answer(row, reply: str = "", earlier=()) -> bool:
    """Whether a reply with no call keeps the answer row of the turn. An earlier reply of
    the turn wrote an answer with text, and one of these is true.

    - The run is in a nag round. A nag asks for the todo marks only, so the reply that
      follows it does not answer the user.
    - The run is in the citation round (`nagging.CITATION_NOTE` in `earlier`), and the
      reply has no text. The reply of that round replaces the answer only when it writes
      one.
    """
    from tasks.P_agent import nagging

    if not (row.result or "").strip():
        return False
    if row.nags_this_turn > 0:
        return True
    return not reply.strip() and any(nagging.is_citation_note(m) for m in earlier)


def _write_answer(row, params: ModelStepParams, earlier, ai, writer,
                  seq0: Optional[int] = None) -> ModelStepResult:
    """Step 9 of `model_step`: the answer row and the run row of a reply with no call.

    `seq0` is the first free seq of the step, one after the compaction line when the step
    wrote one, and `row.next_seq` when it is None.

    `earlier` is the thread before the `ai` message. A retry after the run row write finds
    `model_steps` at this step, and writes the answer row again at the same seq. The
    result's `next_idx` is the index after the last row of the reply, so a nag written
    there replaces no `compaction` row and no `not_run` result.

    The answer row holds the text of the reply and the plan prose of the round, and never
    the reasoning. A reply with no text gets the empty-answer row, and its reasoning stays
    in the reasoning column. The answer of a turn is the last reply that answered the user,
    so a reply of a nag round writes no answer row when the turn has an answer already
    (`keeps_answer`).
    """
    from database import agent_runs
    from tasks.P_agent.stream_writer import context_window_for, round_view

    first = row.next_seq if seq0 is None else seq0
    plan_prose, round_reasoning, _ = round_view(earlier)
    answer = "\n\n".join(p for p in (plan_prose, (ai.content or "").strip()) if p)
    reasoning = "\n\n".join(p for p in (round_reasoning, (ai.reasoning or "").strip()) if p)
    if keeps_answer(row, ai.content or "", earlier):
        transcript = agent_runs.writes_transcript(row)
        if transcript:
            _finish_stream_rows_from(row.username, row.session_id, params.turn_uuid,
                                     row.start_seq)
        writer.write(next_seq=first, model_steps=max(row.model_steps, params.step_no),
                     end_reason=params.final_reason,
                     **_step_tokens(row, params.step_no, ai.usage))
        # `keeps_answer` is true in a nag round, or else in the citation round.
        round_kind = "nag" if row.nags_this_turn > 0 else "citation"
        log.info("[P_agent] run %s: the %s round reply at step %d keeps the answer row",
                 row.run_id, round_kind, params.step_no)
        return ModelStepResult(outcome="answered", next_seq=first,
                               next_idx=reply_end_idx(ai))
    empty = not (ai.content or "").strip()
    if params.mode == "tools" and empty and not ai.tool_calls and not any(
            m.role == "human" and m.content == EMPTY_REPLY_TEXT for m in earlier):
        # The workflow writes EMPTY_REPLY_TEXT at `next_idx` and asks again, once in a
        # thread, so this reply writes no answer row.
        if agent_runs.writes_transcript(row):
            _finish_stream_rows_from(row.username, row.session_id, params.turn_uuid,
                                     row.start_seq)
        writer.write(next_seq=first, model_steps=max(row.model_steps, params.step_no),
                     **_step_tokens(row, params.step_no, ai.usage))
        log.info("[P_agent] run %s: the reply at step %d has no text and no call",
                 row.run_id, params.step_no)
        return ModelStepResult(outcome="empty", next_seq=first,
                               next_idx=reply_end_idx(ai), empty_answer=True)
    start = 0
    for i, m in enumerate(earlier):
        if m.role == "human":
            start = i
    round_ai = [m for m in earlier[start:] if m.role == "ai"] + [ai]
    if any(m.usage.get("summarised") for m in round_ai):
        answer = answer + SUMMARY_NOTICE
    plan_reference = ""
    if row.plan_run_id and row.depth == 0:
        from tasks.P_agent import plan_runs

        # The organizer's final report names every failed section, whatever the model
        # wrote. The planner's answer row carries the reference that the plan card reads.
        if row.kind == "organizer":
            answer = plan_runs.final_answer(row, answer)
        elif row.kind == "planner":
            plan_reference = plan_runs.plan_reference(row)
    transcript = agent_runs.writes_transcript(row)
    written = row.model_steps >= params.step_no
    seq = row.next_seq - 1 if written and transcript else first
    if transcript:
        usage = ai.usage
        model = str(usage.get("model") or "")
        peak = max((int(m.usage.get("input_tokens") or 0) + int(m.usage.get("output_tokens") or 0)
                    for m in round_ai), default=0)
        _chat_row(row)(
            seq, "assistant",
            content=answer or "(the assistant returned an empty answer)",
            plan_reference_json=plan_reference, reasoning=reasoning, model=model,
            context_tokens=int(usage.get("input_tokens") or 0), peak_context_tokens=peak,
            context_window=context_window_for(model),
        )
        _finish_stream_rows_from(row.username, row.session_id, params.turn_uuid, row.start_seq)
        seq += 1
    writer.write(result=answer, next_seq=seq, model_steps=max(row.model_steps, params.step_no),
                 end_reason=params.final_reason, **_step_tokens(row, params.step_no, ai.usage))
    log.info("[P_agent] run %s answered at step %d: %d chars, next seq %d",
             row.run_id, params.step_no, len(answer), seq)
    return ModelStepResult(outcome="answered", next_seq=seq, next_idx=reply_end_idx(ai),
                           empty_answer=empty)


def _store_reply(row, params: ModelStepParams, turn: dict, idx: int, model: str,
                 seq0: Optional[int] = None):
    """Write the `ai` message of a reply at `idx`, with its call entries and usage.

    Each call entry gets its `position` in the reply and its transcript `seq`. The seqs
    start at `seq0`, else at the row's `next_seq`, in call order, and the delegations take
    the last ones, so the seqs of one delegation batch are consecutive.
    """
    from database import agent_runs

    entries = []
    for position, raw in enumerate(turn.get("tool_calls") or []):
        entry = dict(raw)
        entry["position"] = position
        entries.append(entry)
    seq = row.next_seq if seq0 is None else seq0
    for entry in ([e for e in entries if e.get("kind") != "delegation"]
                  + [e for e in entries if e.get("kind") == "delegation"]):
        entry["seq"] = seq
        seq += 1
    usage = dict(turn.get("usage") or {})
    usage.update(step_no=params.step_no, mode=params.mode,
                 summarised=bool(turn.get("summarised")), model=model,
                 compaction=bool(turn.get("compaction")),
                 note_warning=bool(turn.get("note_warning")))
    ai = agent_runs.RunMessageRow(
        idx=idx, role="ai", content=str(turn.get("text") or ""),
        reasoning=str(turn.get("reasoning") or ""), tool_calls_json=json.dumps(entries),
        usage_json=json.dumps(usage), is_final=1, run_id=row.run_id)
    agent_runs.write_message(row.username, row.session_id, row.thread_id, row.run_id, ai)
    return ai


#: The `server_settings` key of the thinking switch on `/admin/llm`.
THINKING_SETTING_KEY = "llm_thinking"


def thinking_setting() -> bool:
    """The thinking switch, read for each model call so a change applies to the next one.

    Only the stored value `off` turns thinking off. An absent row and a failed read mean
    on, which is the default of the switch.
    """
    from database.clickhouse import get_server_setting

    try:
        value = get_server_setting(THINKING_SETTING_KEY)
    except Exception as exc:  # noqa: BLE001, a failed read keeps the default
        log.warning("[P_agent] the thinking setting was not read, sending on: %s", exc)
        return True
    return (value or "").strip() != "off"


@activity.defn
@with_heartbeat(interval_seconds=STEP_HEARTBEAT_SECONDS)
def model_step(params: ModelStepParams) -> ModelStepResult:
    """One model call of a run, and the rows it writes.

    1. A terminal row returns `closed`.
    2. A thread whose last `ai` message has this `step_no` holds the reply of a failed
       attempt. The step writes the rest of it from the stored message and makes no model
       call.
    3. A retry marks final the stream rows that the failed attempt left open.
    4. Mode `final` stores a `not_run` result for each unanswered call, then the human
       message of the reason.
    5. `POST /model_step` streams the reply, with the earlier turns of the chat for a run
       that writes the transcript. The partial rows are written as it arrives.
    6. A `compaction` frame of a run that writes the transcript writes the compaction line
       at `row.next_seq` in its running state, and every later seq of the step moves up by
       one. The `end` frame rewrites the line in its done state (`compaction_line`).
    7. A reply with calls gets its seqs (delegations last), the `ai` message, the
       `compaction` row when the service sent one, one live tool row for each call, the
       result of each repeated call (`repeat_sources`), the note warning when the
       `model_turn` frame asks for it, and the run row. A reply with no
       call gets the `ai` message, the answer row and the run row with the result. The
       reply of a `final` step is always the answer: its calls get a `not_run` result. A
       `plan` reply with no call writes no answer. The first `tools` reply of a thread
       with no text and no call writes no answer and gives `empty`.
    """
    from database import agent_runs
    from tasks.P_agent.stream_writer import (
        KEEPALIVE_SECONDS, RUN_STREAM_IDLE_SECONDS, ModelStepWriter, round_view, run_message,
    )

    started = time.monotonic()
    row = _read_row(params)
    if agent_runs.is_terminal(row):
        return ModelStepResult(outcome="closed", next_seq=row.next_seq)
    messages = _read_thread(row)
    writer = agent_runs.RunRowWriter(row, interval=KEEPALIVE_SECONDS)
    last_ai = _last_ai(messages)
    if (last_ai is not None and last_ai.run_id == row.run_id
            and last_ai.usage.get("step_no") == params.step_no):
        earlier = [m for m in messages if m.idx < last_ai.idx]
        seq0 = row.next_seq
        if (last_ai.usage.get("compaction") and agent_runs.writes_transcript(row)
                and row.model_steps < params.step_no):
            # The run row is not written, so the line is at `row.next_seq`, and the call
            # entries hold the seqs after it.
            record = _stored_compaction(messages, last_ai)
            if record is not None:
                _chat_row(row)(row.next_seq, COMPACTION_ROLE, content=json.dumps(
                    compaction_line(record, last_ai.usage.get("input_tokens") or 0)))
            seq0 = row.next_seq + 1
        if last_ai.tool_calls and params.mode != "final":
            return _write_calls(row, params, earlier, last_ai, writer, None)
        if last_ai.tool_calls:
            _close_final_calls(row, params, messages, last_ai)
        return _write_answer(row, params, earlier, last_ai, writer, seq0)

    # A step that returned its stored result above writes no row: the earlier attempt
    # wrote it.
    with _step_event(row, "model", params.llm_model or _step_run(row, params)["llm_model"],
                     mode=params.mode) as event:
        transcript = agent_runs.writes_transcript(row)
        if activity.in_activity() and activity.info().attempt > 1 and transcript:
            _finish_stream_rows_from(row.username, row.session_id, params.turn_uuid, row.next_seq)
        if params.mode == "final":
            messages = _close_for_final(row, params, messages)
        next_idx = max(m.idx for m in messages) + 1 if messages else 0
        plan_prose, round_reasoning, in_opening = round_view(messages)
        earlier_turns = _earlier_turns(row) if transcript else []
        body = {
            **_step_run(row, params),
            "step_no": params.step_no,
            "mode": params.mode,
            "thinking": thinking_setting(),
            "messages": [run_message(m, row.thread_id) for m in messages],
            "earlier": earlier_turns,
        }
        stream = ModelStepWriter(row, params.turn_uuid, row.next_seq, next_idx, plan_prose,
                                 round_reasoning)
        writer.start_keepalive()
        try:
            stream.start()
            ai = None
            ended = False
            # 1 after the compaction line of this step, which takes `row.next_seq`.
            shift = 0
            running: dict = {}
            record: dict = {}
            prompt_tokens = 0
            for line in _lines(f"{agent_url_for(params.internet_tools)}/model_step", body,
                               RUN_STREAM_IDLE_SECONDS):
                if not line or not line.startswith("data: "):
                    continue
                try:
                    frame = json.loads(line[len("data: "):])
                except ValueError:
                    log.warning("[P_agent] unparseable step frame: %.200s", line)
                    continue
                kind = frame.get("type")
                if kind in ("reasoning", "response"):
                    stream.add(kind, str(frame.get("content") or ""))
                elif kind == COMPACTION_ROLE and transcript and ai is None and not shift:
                    running = {"state": "running",
                               "tokens_before": int(frame.get("tokens_before") or 0),
                               "target": int(frame.get("target") or 0),
                               "parts": int(frame.get("parts") or 0)}
                    content = json.dumps(running)
                    _chat_row(row)(row.next_seq, COMPACTION_ROLE, content=content)
                    shift = 1
                    stream.shift_seq(1, COMPACTION_ROLE, content)
                elif kind == "model_turn" and ai is None:
                    # Written at once, so a retry after a later failure finds the reply.
                    ai = _store_reply(row, params, frame, next_idx, body["llm_model"],
                                      seq0=row.next_seq + shift)
                    if frame.get("compaction"):
                        record = dict(frame["compaction"])
                        _write_compaction(row, ai, record)
                elif kind == "end":
                    ended = True
                    usage = frame.get("usage") or {}
                    prompt_tokens = int(usage.get("prompt_tokens") or 0)
                    event.name = str(frame.get("model") or event.name)
                    event.prompt_tokens = int(usage.get("prompt_tokens") or 0)
                    event.completion_tokens = int(usage.get("completion_tokens") or 0)
                    event.reasoning_tokens = int(usage.get("reasoning_tokens") or 0)
                elif kind == "error":
                    text = str(frame.get("content") or "unknown agent error")
                    failure = (ModelRequestRejected(text) if frame.get("retryable") is False
                               else RuntimeError(text))
                    failure.error_class = str(frame.get("error_class") or "")
                    raise failure
            if ai is None:
                raise RuntimeError("the agent stream ended without a model_turn frame")
            if not ended:
                raise RuntimeError("the agent stream ended without an end frame")
            if shift:
                _chat_row(row)(row.next_seq, COMPACTION_ROLE, content=json.dumps(
                    compaction_line(record, prompt_tokens or ai.usage.get("input_tokens") or 0,
                                    running.get("parts", 0))))
            if ai.tool_calls and params.mode != "final":
                result = _write_calls(row, params, messages, ai, writer, stream)
            else:
                if ai.tool_calls:
                    _close_final_calls(row, params, messages, ai)
                result = _write_answer(row, params, messages, ai, writer, row.next_seq + shift)
            event.ok = result.outcome in ("answered", "calls")
            return result
        finally:
            # A cancellation raises inside this thread at any line. The cleanup is shielded
            # from it, so a stop never leaves the keepalive threads writing rows.
            with (activity.shield_thread_cancel_exception() if activity.in_activity()
                  else contextlib.nullcontext()):
                stream.close()
                writer.stop_keepalive()


# ---------------------------------------------------------------------------- tool_call


@activity.defn
@with_heartbeat(interval_seconds=STEP_HEARTBEAT_SECONDS)
def tool_call(params: ToolCallParams) -> ToolCallResult:
    """One tool call of the last reply, and its `tool` message and tool row.

    A call that already has a `tool` message returns its status and runs nothing. The
    request carries the idempotency key of the call, which is the same in every attempt,
    so a plan tree tool applies one mutation once. A result that arrives after a stop, or
    after `record_step_failure` stored `tool_unavailable` for the call, is not written: the
    model already read the stored result. The run row is not written.
    """
    from database import agent_runs
    from tasks.P_agent.stream_writer import ToolCallWriter

    call = params.call
    row = _read_row(params)
    if agent_runs.is_terminal(row):
        return ToolCallResult(status="closed")
    messages = _read_thread(row)
    ai = next((m for m in messages if m.role == "ai" and m.idx == call.ai_idx), None)
    if ai is None or call.position >= len(ai.tool_calls):
        raise RuntimeError(f"run {row.run_id} has no call {call.ai_idx}:{call.position}")
    done = _answer_of(messages, call.call_id)
    if done is not None:
        return ToolCallResult(status=str(done.usage.get("status") or "ok"))
    entry = ai.tool_calls[call.position]
    key = str(uuid.uuid5(agent_runs.RUN_ID_NAMESPACE,
                         f"tool:{row.thread_id}:{call.ai_idx}:{call.position}"))
    body = {
        **_step_run(row, params),
        "call": {"id": call.call_id, "name": call.name,
                 "args": entry.get("args") if isinstance(entry.get("args"), dict) else {}},
        "page_share": entry.get("page_share"),
        "budget_exhausted": bool(entry.get("budget_exhausted")),
        "idempotency_key": key,
    }
    live = ToolCallWriter(row, params.turn_uuid, call.seq, call.name, entry.get("args"))
    with _step_event(row, "tool", call.name, tool_call_id=call.call_id) as event:
        try:
            live.start()
            result = _post_json(f"{agent_url_for(params.internet_tools)}/tool_call", body,
                                TOOL_READ_SECONDS)
            # The guard against a late write.
            done = _answer_of(_read_thread(row), call.call_id)
            if done is not None:
                status = str(done.usage.get("status") or "ok")
                event.ok = status != "error"
                event.error_class = str(done.usage.get("error_class") or "")
                return ToolCallResult(status=status)
            content = result.get("content")
            content = content if isinstance(content, str) else json.dumps(content, default=str)
            status = "error" if result.get("status") == "error" else "ok"
            error_class = str(result.get("error_class") or "")
            _write_tool_result(row, params.turn_uuid, ai, call, content, status,
                               result.get("measure"), error_class, result.get("doc_refs"))
            # A result with an error code only in its text, such as not_found, is a result.
            event.ok = status != "error"
            event.error_class = error_class
            return ToolCallResult(status=status, error_class=error_class)
        finally:
            with (activity.shield_thread_cancel_exception() if activity.in_activity()
                  else contextlib.nullcontext()):
                live.close()


@activity.defn
@with_heartbeat
def write_asked_answer(params: AskedAnswerParams) -> int:
    """Write the question as the turn answer after all calls of its step have run."""
    from database import agent_runs

    row = _read_row(params)
    if agent_runs.is_terminal(row):
        return row.next_seq
    messages = _read_thread(row)
    ai = next((m for m in messages if m.role == "ai" and m.idx == params.call.ai_idx), None)
    if ai is None or params.call.position >= len(ai.tool_calls):
        raise RuntimeError(f"run {row.run_id} has no question call")
    entry = ai.tool_calls[params.call.position]
    result = _answer_of(messages, params.call.call_id)
    if result is None or result.usage.get("status") != "ok":
        raise RuntimeError(f"run {row.run_id} has no successful question result")
    question = str((entry.get("args") or {}).get("question") or "")
    if not question:
        raise RuntimeError(f"run {row.run_id} has an empty question")
    if agent_runs.writes_transcript(row):
        from tasks.P_agent import plan_runs
        reference = plan_runs.plan_reference(row) if row.kind == "planner" else ""
        _chat_row(row)(row.next_seq, "assistant", content=question,
                       plan_reference_json=reference)
        _finish_stream_rows_from(row.username, row.session_id, params.turn_uuid, row.start_seq)
        next_seq = row.next_seq + 1
    else:
        next_seq = row.next_seq
    agent_runs.write_run(row, result=question, next_seq=next_seq)
    return next_seq


# ------------------------------------------------------------------ the short activities


#: The failures of a step that no attempt row can hold, so the workflow writes the row: a
#: step that never started, and an attempt whose worker stopped beating. An attempt that
#: passed its start-to-close limit on a live worker wrote its own row with
#: `start_to_close_timeout`, and a last attempt that raised wrote its own row with `ok` 0,
#: so a second row would count the failure twice.
WORKFLOW_ROW_CLASSES = ("schedule_to_start_timeout", "heartbeat_timeout")


def _record_timeout_row(row, params: StepFailure) -> None:
    """The `agent_step_events` row of a step that timed out, with `attempt` 0."""
    from database import agent_step_events as events

    name = params.name
    if params.step == "model" and not name:
        name = _step_run(row, params)["llm_model"]
    events.record(events.StepEvent(
        username=row.username, session_id=row.session_id, run_id=row.run_id,
        run_kind=row.kind, step=params.step, mode=params.mode, name=name,
        task_queue=params.task_queue, attempt=0, ok=False,
        tool_call_id=params.call.call_id if params.call is not None else "",
        error_class=params.error_class))


@activity.defn
@with_heartbeat
def record_step_failure(params: StepFailure) -> None:
    """Record a step that failed after its last attempt, or never started.

    A step that never started or lost its heartbeat gets its `agent_step_events` row here,
    with `attempt` 0. No attempt could write that row. Every other failure has the row of
    its last attempt, a start-to-close timeout included.

    For a tool step, store the `tool_unavailable` result at the call's index and the
    finished tool row, so the thread keeps one result for each call and the loop goes on.
    A call that already has a result keeps it.
    """
    from database import agent_runs

    row = _read_row(params)
    if params.error_class in WORKFLOW_ROW_CLASSES:
        _record_timeout_row(row, params)
    if params.step != "tool" or params.call is None:
        return
    if agent_runs.is_terminal(row):
        return
    messages = _read_thread(row)
    ai = next((m for m in messages if m.role == "ai" and m.idx == params.call.ai_idx), None)
    if ai is None or _answer_of(messages, params.call.call_id) is not None:
        return
    content = json.dumps({
        "success": False, "error": "tool_unavailable",
        "message": TOOL_UNAVAILABLE_TEXT.format(error_class=params.error_class),
    })
    _write_tool_result(row, params.turn_uuid, ai, params.call, content, "error",
                       error_class=params.error_class)


@activity.defn
@with_heartbeat
def delegate_step(params: StepRef) -> Optional[RunSummary]:
    """Write the children of the `run_subagent` calls of the last reply, and the waiting
    state. Returns None when no delegation call is left unanswered."""
    from database import agent_runs

    row = _read_row(params)
    if agent_runs.is_terminal(row):
        return RunSummary(outcome="closed", next_seq=row.next_seq)
    messages = _read_thread(row)
    last_ai = _last_ai(messages)
    if last_ai is None:
        return None
    entries = [e for e in last_ai.tool_calls
               if e.get("kind") == "delegation" and e.get("name") == DELEGATION_TOOL
               and _answer_of(messages, str(e.get("id") or "")) is None]
    if not entries:
        return None
    calls = [(str(e.get("id") or ""),
              [b for b in (e.get("briefings") or []) if isinstance(b, dict)]) for e in entries]
    seqs = [int(e.get("seq") or 0) for e in entries]
    summary = _delegate(row, calls, seqs, agent_runs.RunRowWriter(row), _chat_row(row))
    if agent_runs.writes_transcript(row):
        _finish_stream_rows_from(row.username, row.session_id, params.turn_uuid, min(seqs))
    return summary


@activity.defn
@with_heartbeat
def prepare_continuation(params: StepRef) -> int:
    """Add the result of each `run_subagent` call of the continued run to the thread.
    Returns the count of results the thread holds after it."""
    from database import agent_runs

    row = _read_row(params)
    if agent_runs.is_terminal(row) or not row.continues_run_id:
        return 0
    messages = _add_continuation_results(row, _read_thread(row), _chat_row(row))
    return sum(1 for m in messages if m.role == "tool" and m.tool_name == DELEGATION_TOOL)


@activity.defn
@with_heartbeat
def plan_has_sections(params: StepRef) -> bool:
    """Whether the newest snapshot of the planner's plan has a section, by the rule of
    `agent_plans.sections`: a node with at least one leaf child, the root included."""
    from database import agent_plans

    row = _read_row(params)
    if not row.plan_run_id:
        return False
    plan_run = agent_plans.read_plan_run(row.username, row.session_id, row.plan_run_id)
    if plan_run is None:
        return False
    snapshot = agent_plans.read_snapshot(row.username, row.session_id, plan_run.plan_id)
    return bool(snapshot is not None and agent_plans.sections(snapshot))


@activity.defn
@with_heartbeat
def needs_citations(params: StepRef) -> bool:
    """Whether the chat answer of the run gets the citation round, by the rule of
    `nagging.needs_citation_round`. A run in a nag round, a forced answer and a terminal
    run get none."""
    from database import agent_runs
    from tasks.P_agent import nagging

    row = _read_row(params)
    if agent_runs.is_terminal(row) or row.nags_this_turn > 0 or row.end_reason:
        return False
    return nagging.needs_citation_round(row.result or "", _read_thread(row))


@dataclass
class RepeatNoteParams(StepRef):
    """The input of `write_repeat_note`: the keys of the rows and the nag counters, which
    the workflow computes."""

    seq: int = 0
    idx: int = 0
    nags_this_turn: int = 0
    nags_without_progress: int = 0
    #: Write EMPTY_REPLY_TEXT in place of the repeat note.
    empty_reply: bool = False


@activity.defn
@with_heartbeat
def write_repeat_note(params: RepeatNoteParams) -> int:
    """Write the repeat note, or EMPTY_REPLY_TEXT, as a `human` row at `idx`, and for a run
    that writes the transcript, as a `nag` chat row at `seq`. Write the nag counters into
    the run row. Returns the next free seq.

    The note of a chat lead lists its open todo items. A retry writes the same rows at the
    same keys, because the thread and the todo list do not change while it runs.
    """
    from database import agent_runs, chat_todos
    from tasks.P_agent import nagging

    row = _read_row(params)
    if agent_runs.is_terminal(row):
        return params.seq
    if params.empty_reply:
        text = EMPTY_REPLY_TEXT
    else:
        todo = chat_todos.read_todo(row.username, chat_todos.key_for_run(row))
        text = repeat_note_text(_read_thread(row), todo)
    agent_runs.write_message(
        row.username, row.session_id, row.thread_id, row.run_id,
        agent_runs.RunMessageRow(idx=params.idx, role="human", content=text,
                                 run_id=row.run_id))
    changes: dict = {"nags_this_turn": params.nags_this_turn,
                     "nags_without_progress": params.nags_without_progress}
    next_seq = params.seq
    if agent_runs.writes_transcript(row):
        _insert_chat_row(row.username, row.session_id, params.seq, nagging.NAG_ROLE,
                         content=text)
        next_seq = params.seq + 1
        changes["next_seq"] = next_seq
    agent_runs.write_run(row, **changes)
    return next_seq


@dataclass
class FoundDocumentsParams(StepRef):
    #: The end reason of the run: `step_budget`, `repeated_call`, or "" for a `tools` reply.
    reason: str = ""


@activity.defn
@with_heartbeat
def write_found_documents(params: FoundDocumentsParams) -> None:
    """Write the listing of a sub-agent that answered with no text twice as its result
    (`thread_facts.found_documents_text`). The ending writes the result as its report."""
    from database import agent_runs

    row = _read_row(params)
    if agent_runs.is_terminal(row):
        return
    text = thread_facts.found_documents_text(_read_thread(row))
    agent_runs.RunRowWriter(row).write(result=text, end_reason=params.reason)


__all__ = [
    "EMPTY_ANSWER_TEXT", "EMPTY_REPLY_TEXT", "FINAL_TEXT", "FoundDocumentsParams",
    "ModelRequestRejected", "ModelStepParams", "ModelStepResult", "NOT_RUN_TEXT",
    "REPEAT_NOTE_HEAD", "RepeatNoteParams", "RepeatSource", "StepFailure", "StepRef",
    "ToolCallParams", "ToolCallResult", "args_digest", "canonical_json", "delegate_step",
    "model_step", "needs_citations", "plan_has_sections", "prepare_continuation",
    "record_step_failure", "repeat_sources", "repeat_streak", "tool_call", "tool_idx",
    "write_asked_answer", "write_found_documents", "write_repeat_note",
]
