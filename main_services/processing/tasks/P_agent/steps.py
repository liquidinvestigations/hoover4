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
* `record_step_failure` stores a `tool_unavailable` result for a tool step that failed.
* The policy hooks of the run, which check answers and write their notes, are in
  `control_steps.py`.
* `write_empty_note` writes the note after the first reply with no text and no call. The
  note is the stored marker of the one retry of a thread.
* `write_incomplete` ends a run that stopped before an answer, at the step limit or after a
  second empty reply, with a result that code writes from the stored thread.

A stored write has a fixed key (`(thread_id, idx)`, `(username, session_id, seq)`), so a
retry writes the same rows. The `ai` message of a step carries `step_no` in its usage, and a
retry that finds it makes no second model call.
"""

from __future__ import annotations

import contextlib
import json
import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Iterator, Optional

import requests
from temporalio import activity
from temporalio.exceptions import CancelledError

from tasks.heartbeat import with_heartbeat
from tasks.P_agent.activities import (
    CallRef, _finish_stream_rows_from, _insert_chat_row, agent_url_for,
    call_refs,
)
from tasks.P_agent import thread_facts
from tasks.P_agent.model_timeouts import STEP_HEARTBEAT_SECONDS

log = logging.getLogger(__name__)

#: The read timeout of `POST /tool_call`. The tool itself has `TOOL_CALL_TIMEOUT` (300 s),
#: and the extra 10 s lets the service answer a tool that timed out inside it.
TOOL_READ_SECONDS = 310

#: The connect timeout of both step requests. A dead agent host fails the step in seconds.
CONNECT_SECONDS = 10

#: The human message after a reply with no text and no call, once in a thread.
EMPTY_REPLY_TEXT = ("Your last reply had no text and no tool call. Make the call you planned, "
                    "or write your answer now from the results above.")

#: The usage key and value that mark the EMPTY_REPLY_TEXT message of a thread. The marker
#: holds the one retry of a thread. A thread from before the marker has the text only.
RETRY_MARKER_KEY = "retry_marker"
EMPTY_RETRY_MARKER = "empty_reply"

#: The chat role of a note to the model that the transcript shows: the empty-reply note,
#: and the citation note. It is not
#: the user speaking. Mirrored as `ChatRole::Nag` in `website/common/src/chat_types.rs`.
NOTE_ROLE = "nag"

#: The `tool_name` of the note row of the citation repair round. The transcript shows the
#: answer before that note as replaced when the round gives a new answer. Mirrored as
#: `CITATION_NOTE_NAME` in `website/common/src/chat_types.rs`.
CITATION_NOTE_NAME = "citation_check"

#: The tools that read or change the todo list. The calls of one reply to
#: these tools run one after the other, in the order of the reply, because each one reads
#: the state that the call before it wrote.
STATE_TOOLS = frozenset({
    "write_todo", "edit_todo", "mark_todo", "read_todo",
})


#: The tools whose identical calls in one batch share one execution (`share_key`). Each is a
#: repeatable search or read whose result depends on its arguments and the caller's scope.
#: State-changing tools stay outside, and so do the todo tools.
SHARED_TOOLS = frozenset({
    "web_search", "search_collections", "search_passages", "read_documents", "doc_metadata",
    "doc_email", "read_page",
})


def share_key(name: str, args: Any) -> str:
    """The key of a call that an identical call of its batch can share, else empty. The
    arguments are the normalized arguments that the agent service stored with the call."""
    if name not in SHARED_TOOLS or not isinstance(args, dict):
        return ""
    import hashlib

    text = json.dumps([name, args], sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


#: The browser server's own tool, and the name prefix of every tool it routes to the
#: browser. `BROWSER_EXPOSED_TOOLS` of the server chooses which of them it lists.
BROWSER_READ_TOOL = "read_page"
BROWSER_TOOL_PREFIX = "browser_"


def is_browser_tool(name: str) -> bool:
    """Whether a tool drives the run's one browser: `read_page` and every `browser_` tool,
    `browser_take_screenshot` and `browser_wait_for` included when the server lists them.
    A later call reads the page that an earlier call left. Mirrors `is_browser_tool` in
    the research agent's `execution.py`."""
    return name == BROWSER_READ_TOOL or name.startswith(BROWSER_TOOL_PREFIX)


def runs_in_order(call) -> bool:
    """Whether a call of a reply runs in the ordered chain of its reply: a call that the
    agent service classed `ordered`, or a call to one of `STATE_TOOLS`."""
    return call.kind == "ordered" or call.name in STATE_TOOLS


def runs_in_browser(call) -> bool:
    """Whether a call of a reply runs in the browser chain of its reply."""
    return not runs_in_order(call) and is_browser_tool(call.name)

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


#: The `mode` of every model step in `agent_step_events`. Each model step binds the run's
#: tools. The column keeps `final` and `plan` in older rows.
MODEL_STEP_MODE = "tools"


@dataclass
class ModelStepParams(StepRef):
    #: 1 for the first model call of the run thread.
    step_no: int = 1


@dataclass
class ModelStepResult:
    #: `answered`, `calls`, `closed`, `empty` or `empty_again`. A reply with no text and no
    #: call writes no answer. It gives `empty` in a thread with no retry marker, and
    #: `empty_again` in a thread that has one.
    outcome: str
    #: The calls of the reply that the loop runs.
    calls: list[CallRef] = field(default_factory=list)
    next_seq: int = 0
    #: The thread index after the last row of the reply (`reply_end_idx`). A `closed`
    #: result gives 0.
    next_idx: int = 0


@dataclass
class ToolCallParams(StepRef):
    call: Optional[CallRef] = None
    #: An earlier call of the same batch with the same `share_key`.
    shared_from: Optional[CallRef] = None


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
    #: MODEL_STEP_MODE for a model step, empty for a tool step.
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


def tool_idx(ai, position: int) -> int:
    """The thread index of the `tool` message of call `position` of the `ai` message.

    The calls take the indexes after the `ai` message in reply order. When the reply has a
    `compaction` row, the row takes the index after the `ai` message, and the results start
    one index later.
    """
    return ai.idx + 1 + (1 if ai.usage.get("compaction") else 0) + position


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
        "username": row.username,
        "session_id": row.session_id,
        "allowed_collections": list(params.allowed_collections or []),
        "llm_model": params.llm_model or _chat_model(),
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
                       measure: Any = None, error_class: str = "", doc_refs: Any = None,
                       shared_from: str = "") -> None:
    """The `tool` message of one call, and for a run that writes the transcript, its
    finished tool row at the call's seq and the final stream row. `doc_refs` is the list
    that the `/tool_call` response carried beside the result, or None.

    The usage of the message holds the typed evidence of the result (`reports.normalize`)
    at every run depth. The evidence is metadata: the model reads the content only. A call
    of a policy batch gets `origin` in the usage of its transcript row, and a shared result
    names the call whose result it shares."""
    from database import agent_runs
    from tasks.P_agent import reports
    from tasks.P_agent.stream_writer import ToolCallWriter, tool_row_fields

    entry = ai.tool_calls[call.position]
    idx = tool_idx(ai, call.position)
    evidence = reports.with_source(
        reports.normalize(call.name, entry.get("args"), content, status, doc_refs),
        row.thread_id, idx)
    usage = {"chat_seq": call.seq, "status": status, "measure": measure,
             "error_class": error_class, "evidence": evidence, "doc_refs": doc_refs or []}
    if shared_from:
        usage["shared_from"] = shared_from
    agent_runs.write_message(
        row.username, row.session_id, row.thread_id, row.run_id,
        agent_runs.RunMessageRow(
            idx=idx, role="tool", content=content,
            tool_call_id=call.call_id, tool_name=call.name, run_id=row.run_id,
            usage_json=json.dumps(usage, default=str)))
    origin = {}
    if ai.usage.get("origin") == "policy" or shared_from:
        origin = {"usage_json": json.dumps({k: v for k, v in (
            ("origin", ai.usage.get("origin") or "model"), ("shared_from", shared_from)) if v})}
    _chat_row(row)(call.seq, "tool", **tool_row_fields(call.name, entry.get("args"), content, doc_refs),
                   **origin)
    ToolCallWriter(row, turn_uuid, call.seq, call.name, entry.get("args")).finish()


def pinned_control(messages) -> Optional[dict]:
    """The pinned assets of the turn for a step request, from the opening row: the system
    prompt, the text of each listed skill, and their revision. None for a turn that has none,
    and the agent service then renders its current defaults."""
    if not messages:
        return None
    control = messages[0].usage.get("control") if messages[0].role == "human" else None
    assets = (control or {}).get("assets") if isinstance(control, dict) else None
    if not isinstance(assets, dict) or not assets.get("system_prompt"):
        return None
    return {"revision": str(control.get("revision") or assets.get("revision") or ""),
            "system_prompt": assets["system_prompt"],
            "skills": {name: (skill or {}).get("text") or ""
                       for name, skill in (assets.get("skills") or {}).items()}}


def _read_thread(row):
    from database import agent_runs
    from tasks.P_agent.stream_writer import prepare_thread

    return prepare_thread(agent_runs.read_messages(row.username, row.session_id, row.thread_id))


def _citation_messages(row, messages):
    """Include earlier tool evidence without earlier turns' repair markers."""
    from database import agent_runs
    from tasks.P_agent.stream_writer import prepare_thread

    earlier = []
    for thread_id in agent_runs.read_earlier_threads(row.username, row.session_id,
                                                     row.turn_seq):
        previous = prepare_thread(agent_runs.read_messages(row.username, row.session_id,
                                                           thread_id))
        earlier.extend(message for message in previous if message.role == "tool")
    return earlier + list(messages)


def _earlier_turns(row) -> list[dict[str, Any]]:
    """The stored threads of the earlier chat turns of the session, in turn order, as
    `RunMessage` rows. Each thread is sent whole, with its tool calls and results.
    """
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

    A version 3 record gives `summary_state`, `ok` or `failed`, and its summary as `record`.
    A version 2 record gives `part_states`, `ok` or `failed` for each summary part, and its
    handoff as `record`. `parts` is the count of summary requests that the `compaction`
    frame gave.
    """
    states = [str(s) for s in record.get("parts") or []]
    return {"state": "done", "tokens_before": int(record.get("tokens_before") or 0),
            "target": int(record.get("target") or 0), "parts": int(parts or len(states)),
            "tokens_after": int(tokens_after or 0),
            "steps_summarised": int(record.get("steps_summarised") or 0),
            "target_reached": bool(record.get("target_reached")),
            "record": str(record.get("summary") or record.get("handoff") or ""),
            "part_states": states, "summary_state": str(record.get("status") or "")}


def _stored_compaction(messages, ai) -> Optional[dict]:
    """The record of the `compaction` row that follows `ai`, or None."""
    for m in messages:
        if m.idx == ai.idx + 1 and m.role == "compaction":
            try:
                return json.loads(m.content or "{}")
            except ValueError:
                return None
    return None


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
        run_kind="chat", step=step, name=name, task_queue=task_queue, attempt=attempt,
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


def _step_tokens(row, step_no: int, usage: dict) -> dict[str, int]:
    """The token columns of the run row after this step. A retry after the run row write
    adds nothing, because the row already counts this step."""
    if row.model_steps >= step_no:
        return {}
    return {"prompt_tokens": row.prompt_tokens + int(usage.get("input_tokens") or 0),
            "completion_tokens": row.completion_tokens + int(usage.get("output_tokens") or 0)}


def _write_calls(row, params: ModelStepParams, ai, writer, stream) -> ModelStepResult:
    """Step 6 of `model_step`: the live tool rows and the run row of a reply with calls.
    The result lists every call of the reply, and the loop runs each one."""
    entries = ai.tool_calls
    if stream is not None:
        stream.tool_rows(entries)
    calls_end = max([row.next_seq] + [int(e.get("seq") or 0) + 1 for e in entries])
    next_seq, next_idx = calls_end, reply_end_idx(ai)
    writer.write(next_seq=next_seq, model_steps=max(row.model_steps, params.step_no),
                 **_step_tokens(row, params.step_no, ai.usage))
    return ModelStepResult(outcome="calls", calls=call_refs(ai), next_seq=next_seq,
                           next_idx=next_idx)


def keeps_answer(row, reply: str = "", earlier=()) -> bool:
    """Whether a reply with no call keeps the answer row of the turn: an earlier reply of
    the turn wrote an answer with text, the run is in the citation round
    (`citations.CITATION_NOTE` in `earlier`), and the reply has no text. The reply of that
    round replaces the answer only when it writes one."""
    from tasks.P_agent import citations

    if not (row.result or "").strip():
        return False
    return not reply.strip() and any(citations.is_citation_note(m) for m in earlier)


def is_retry_marker(message) -> bool:
    """Whether a thread message is the note after the thread's first empty reply."""
    return message.role == "human" and (
        message.usage.get(RETRY_MARKER_KEY) == EMPTY_RETRY_MARKER
        or (message.content or "") == EMPTY_REPLY_TEXT)


def _write_answer(row, params: ModelStepParams, earlier, ai, writer,
                  seq0: Optional[int] = None) -> ModelStepResult:
    """Step 9 of `model_step`: the answer row and the run row of a reply with no call.

    `seq0` is the first free seq of the step, one after the compaction line when the step
    wrote one, and `row.next_seq` when it is None.

    `earlier` is the thread before the `ai` message. A retry after the run row write finds
    `model_steps` at this step, and writes the answer row again at the same seq. The
    result's `next_idx` is the index after the last row of the reply, so a note written
    there replaces no `compaction` row.

    The answer row holds the text of the reply and the plan prose of the round, and never
    the reasoning. A reply with no text and no call writes no answer row: it gives `empty`,
    or `empty_again` when the thread holds the retry marker (`is_retry_marker`). A reply of
    the citation round with no text keeps the answer row of the turn (`keeps_answer`).
    """
    from tasks.P_agent.stream_writer import context_window_for, round_view

    first = row.next_seq if seq0 is None else seq0
    plan_prose, round_reasoning, _ = round_view(earlier)
    answer = "\n\n".join(p for p in (plan_prose, (ai.content or "").strip()) if p)
    reasoning = "\n\n".join(p for p in (round_reasoning, (ai.reasoning or "").strip()) if p)
    from tasks.P_agent import citations, reports

    repair_round = any(citations.is_citation_note(m) for m in earlier)
    if keeps_answer(row, ai.content or "", earlier):
        transcript = True
        if transcript:
            _finish_stream_rows_from(row.username, row.session_id, params.turn_uuid,
                                     row.start_seq)
        writer.write(next_seq=first, model_steps=max(row.model_steps, params.step_no),
                     **_step_tokens(row, params.step_no, ai.usage))
        log.info("[P_agent] run %s: the citation round reply at step %d keeps the answer row",
                 row.run_id, params.step_no)
        return ModelStepResult(outcome="answered", next_seq=first,
                               next_idx=reply_end_idx(ai))
    if not (ai.content or "").strip() and not ai.tool_calls:
        # The workflow writes the retry marker at `next_idx` and asks again, once in a
        # thread. A second empty reply ends the run through `write_incomplete`.
        again = any(is_retry_marker(m) for m in earlier)
        if True:
            _finish_stream_rows_from(row.username, row.session_id, params.turn_uuid,
                                     row.start_seq)
        writer.write(next_seq=first, model_steps=max(row.model_steps, params.step_no),
                     **_step_tokens(row, params.step_no, ai.usage))
        log.info("[P_agent] run %s: the reply at step %d has no text and no call%s",
                 row.run_id, params.step_no, " again" if again else "")
        return ModelStepResult(outcome="empty_again" if again else "empty", next_seq=first,
                               next_idx=reply_end_idx(ai))
    if repair_round:
        entries = reports.session_citation_entries(row.username, row.session_id)
        problem = citations.repair_reply_problem(ai.content or "", entries)
        if problem:
            detail = {
                "raw_call": "It contains a tool call as text.",
                "unresolved_label": "It uses a label that no successful citation gives.",
                "conflicting_label": "It uses a label for more than one document.",
                "page_zero": "It names page 0 instead of the verified page.",
            }[problem]
            notice = "The citation reply could not replace the earlier answer. " + detail
            if (row.result or "").strip():
                answer = (row.result if row.result.startswith(notice + "\n\n")
                          else notice + "\n\n" + row.result)
            else:
                answer = ("The citation reply could not be used. " + detail
                          + " No earlier answer is available.")
    from tasks.P_agent.stream_writer import starts_round

    start = 0
    for i, m in enumerate(earlier):
        if starts_round(m):
            start = i
    round_ai = [m for m in earlier[start:] if m.role == "ai"
                and m.usage.get("origin") != "policy"] + [ai]
    from database import agent_runs

    entries = reports.session_citation_entries(row.username, row.session_id)
    metadata = citations.answer_metadata(answer, _citation_messages(row, earlier),
                                         entries, params.internet_tools)
    if any(m.usage.get("summarised") for m in round_ai):
        answer = answer + SUMMARY_NOTICE
    ai = replace(ai, usage_json=json.dumps({**ai.usage, **metadata}))
    agent_runs.write_message(row.username, row.session_id, row.thread_id, row.run_id, ai)
    transcript = True
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
            reasoning=reasoning, model=model, usage_json=json.dumps(metadata),
            context_tokens=int(usage.get("input_tokens") or 0), peak_context_tokens=peak,
            context_window=context_window_for(model),
        )
        _finish_stream_rows_from(row.username, row.session_id, params.turn_uuid, row.start_seq)
        seq += 1
    writer.write(result=answer, next_seq=seq, model_steps=max(row.model_steps, params.step_no),
                 **_step_tokens(row, params.step_no, ai.usage))
    log.info("[P_agent] run %s answered at step %d: %d chars, next seq %d",
             row.run_id, params.step_no, len(answer), seq)
    return ModelStepResult(outcome="answered", next_seq=seq, next_idx=reply_end_idx(ai))


def _store_reply(row, params: ModelStepParams, turn: dict, idx: int, model: str,
                 seq0: Optional[int] = None):
    """Write the `ai` message of a reply at `idx`, with its call entries and usage.
    `model` is the model that the service answered with, or the model of the request.

    Each call entry gets its `position` in the reply and its transcript `seq`. The seqs
    start at `seq0`, else at the row's `next_seq`, in call order.
    """
    from database import agent_runs

    entries = []
    for position, raw in enumerate(turn.get("tool_calls") or []):
        entry = dict(raw)
        entry["position"] = position
        key = share_key(str(entry.get("name") or ""), entry.get("args"))
        if key and not entry.get("argument_error"):
            entry["share_key"] = key
        entries.append(entry)
    seq = row.next_seq if seq0 is None else seq0
    for entry in entries:
        entry["seq"] = seq
        seq += 1
    usage = dict(turn.get("usage") or {})
    usage.update(step_no=params.step_no,
                 tool_scope="documents_and_web" if params.internet_tools else "documents_only",
                 summarised=bool(turn.get("summarised")), model=model,
                 compaction=bool(turn.get("compaction")))
    ai = agent_runs.RunMessageRow(
        idx=idx, role="ai", content=str(turn.get("text") or ""),
        reasoning=str(turn.get("reasoning") or ""), tool_calls_json=json.dumps(entries),
        usage_json=json.dumps(usage), is_final=1, run_id=row.run_id)
    agent_runs.write_message(row.username, row.session_id, row.thread_id, row.run_id, ai)
    return ai


def _store_reductions(row, reductions: list[dict]) -> None:
    """Persist model views before the reply while retaining complete tool evidence."""
    from dataclasses import replace
    from database import agent_runs

    for reduction in reductions:
        thread_id = str(reduction.get("thread_id") or "")
        if not thread_id:
            raise ValueError("The reduced result has no thread identity.")
        messages = agent_runs.read_messages(row.username, row.session_id, thread_id)
        message = next((m for m in messages if m.idx == reduction.get("idx")
                        and m.role == "tool" and m.tool_call_id == reduction.get("tool_call_id")), None)
        if message is None or not isinstance(reduction.get("model_content"), str):
            raise ValueError("The reduced result does not match a stored tool message.")
        usage = {**message.usage, "model_content": reduction["model_content"]}
        agent_runs.write_message(row.username, row.session_id, thread_id, message.run_id,
                                 replace(message, usage_json=json.dumps(usage)))


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
    4. `POST /model_step` streams the reply, with the earlier turns of the chat for a run
       that writes the transcript. The partial rows are written as it arrives. The request
       binds every tool of the run.
    5. A `compaction` frame of a run that writes the transcript writes the compaction line
       at `row.next_seq` in its running state, and every later seq of the step moves up by
       one. The `end` frame rewrites the line in its done state (`compaction_line`).
    6. A reply with calls gets its seqs, the `ai` message, the
       `compaction` row when the service sent one, one live tool row for each call, and the
       run row. Every call
       of the reply runs. A reply with no call gets the `ai` message, the answer row and
       the run row with the result. A reply with no text and no call writes no answer and
       gives `empty` or `empty_again`.
    """
    from database import agent_runs
    from tasks.P_agent.stream_writer import (
        KEEPALIVE_SECONDS, RUN_STREAM_IDLE_SECONDS, ModelStepWriter, round_view, run_message,
    )

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
        if (last_ai.usage.get("compaction") and True
                and row.model_steps < params.step_no):
            # The run row is not written, so the line is at `row.next_seq`, and the call
            # entries hold the seqs after it.
            record = _stored_compaction(messages, last_ai)
            if record is not None:
                _chat_row(row)(row.next_seq, COMPACTION_ROLE, content=json.dumps(
                    compaction_line(record, last_ai.usage.get("input_tokens") or 0)))
            seq0 = row.next_seq + 1
        if last_ai.tool_calls:
            return _write_calls(row, params, last_ai, writer, None)
        return _write_answer(row, params, earlier, last_ai, writer, seq0)

    # A step that returned its stored result above writes no row: the earlier attempt
    # wrote it.
    with _step_event(row, "model", params.llm_model or _step_run(row, params)["llm_model"],
                     mode=MODEL_STEP_MODE) as event:
        transcript = True
        if activity.in_activity() and activity.info().attempt > 1 and transcript:
            _finish_stream_rows_from(row.username, row.session_id, params.turn_uuid, row.next_seq)
        next_idx = max(m.idx for m in messages) + 1 if messages else 0
        plan_prose, round_reasoning, in_opening = round_view(messages)
        earlier_turns = _earlier_turns(row) if transcript else []
        body = {
            **_step_run(row, params),
            "step_no": params.step_no,
            "thinking": thinking_setting(),
            "messages": [run_message(m, row.thread_id) for m in messages],
            "earlier": earlier_turns,
            "control": pinned_control(messages),
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
                    _store_reductions(row, frame.get("reductions") or [])
                    ai = _store_reply(row, params, frame, next_idx,
                                      str(frame.get("model") or body["llm_model"]),
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
            if ai.tool_calls:
                result = _write_calls(row, params, ai, writer, stream)
            else:
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


#: The `mode` of the `agent_step_events` row of a call that shared an earlier result.
SHARED_MODE = "shared"
#: The result of a call that shares the result of an identical earlier call of its batch.
SHARED_TEXT = "This call repeats call {call_id} of the same reply. Its result is above."


def complete_result(message) -> bool:
    """Whether a stored result can be shared: a successful result whose evidence holds no
    failed or partial entry."""
    if message.usage.get("status") != "ok" or message.usage.get("shared_from"):
        return False
    try:
        parsed = json.loads(message.content or "")
    except ValueError:
        parsed = None
    if isinstance(parsed, dict) and (parsed.get("success") is False or parsed.get("error")):
        return False
    return not any(isinstance(e, dict) and e.get("status") in ("error", "partial")
                   for e in message.usage.get("evidence") or [])


@activity.defn
@with_heartbeat(interval_seconds=STEP_HEARTBEAT_SECONDS)
def tool_call(params: ToolCallParams) -> ToolCallResult:
    """One tool call of the last reply, and its `tool` message and tool row.

    A call that already has a `tool` message returns its status and runs nothing. The
    request carries the idempotency key of the call, which is the same in every attempt,
    so a retried note write keeps its identity. A result that arrives after a stop, or
    after `record_step_failure` stored `tool_unavailable` for the call, is not written: the
    model already read the stored result. The run row is not written.
    """
    from database import agent_runs
    from tasks.P_agent.stream_writer import ToolCallWriter, run_message

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
    if params.shared_from is not None:
        leader = _answer_of(messages, params.shared_from.call_id)
        if leader is not None and complete_result(leader):
            with _step_event(row, "tool", call.name, mode=SHARED_MODE,
                             tool_call_id=call.call_id) as event:
                _write_tool_result(row, params.turn_uuid, ai, call,
                                   SHARED_TEXT.format(call_id=params.shared_from.call_id), "ok",
                                   shared_from=params.shared_from.call_id)
                event.ok = True
            return ToolCallResult(status="ok")
    key = str(uuid.uuid5(agent_runs.RUN_ID_NAMESPACE,
                         f"tool:{row.thread_id}:{call.ai_idx}:{call.position}"))
    body = {
        **_step_run(row, params),
        "call": {"id": call.call_id, "name": call.name,
                 "args": entry.get("args") if isinstance(entry.get("args"), dict) else {},
                 # Set when the model client could not read the arguments. The agent
                 # service refuses such a call and says why.
                 "argument_error": str(entry.get("argument_error") or "") or None},
        "page_share": entry.get("page_share"),
        "idempotency_key": key,
        "messages": [run_message(m, row.thread_id) for m in messages],
        "earlier": _earlier_turns(row),
        "control": pinned_control(messages),
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
    if True:
        # The model that asked, from the usage of the reply, as `write_incomplete` does.
        metadata = {"citation_status": "none", "tool_scope": ai.usage.get("tool_scope", "documents_only")}
        ai = replace(ai, usage_json=json.dumps({**ai.usage, **metadata}))
        agent_runs.write_message(row.username, row.session_id, row.thread_id, row.run_id, ai)
        _chat_row(row)(row.next_seq, "assistant", content=question,
                       model=str(ai.usage.get("model") or ""), usage_json=json.dumps(metadata))
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
        run_kind="chat", step=params.step, mode=params.mode, name=name,
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


@dataclass
class EmptyNoteParams(StepRef):
    """The input of `write_empty_note`: the keys of its rows."""

    seq: int = 0
    idx: int = 0


@activity.defn
@with_heartbeat
def write_empty_note(params: EmptyNoteParams) -> int:
    """Write EMPTY_REPLY_TEXT as a `human` row at `idx` with the retry marker in its usage,
    and for a run that writes the transcript, as a note row at `seq`. Returns the next free
    seq. A retry writes the same rows at the same keys. No counter is written."""
    from database import agent_runs

    row = _read_row(params)
    if agent_runs.is_terminal(row):
        return params.seq
    agent_runs.write_message(
        row.username, row.session_id, row.thread_id, row.run_id,
        agent_runs.RunMessageRow(idx=params.idx, role="human", content=EMPTY_REPLY_TEXT,
                                 usage_json=json.dumps({RETRY_MARKER_KEY: EMPTY_RETRY_MARKER}),
                                 run_id=row.run_id))
    if not True:
        return params.seq
    _insert_chat_row(row.username, row.session_id, params.seq, NOTE_ROLE,
                     content=EMPTY_REPLY_TEXT)
    agent_runs.write_run(row, next_seq=params.seq + 1)
    return params.seq + 1


#: The `end_reason` values of a run that stopped before an answer.
STEP_BUDGET = "step_budget"
EMPTY_RESPONSE = "empty_response"
INCOMPLETE_REASONS = (STEP_BUDGET, EMPTY_RESPONSE, "no_progress")


@dataclass
class IncompleteParams(StepRef):
    #: `step_budget`, `empty_response` or `no_progress`.
    reason: str = ""
    #: The step limit of the workflow, which the text of `step_budget` names.
    limit: int = 0


@activity.defn
@with_heartbeat
def write_incomplete(params: IncompleteParams) -> int:
    """End the model steps of a run that stopped before an answer, with no model call.

    The result is `thread_facts.incomplete_text`: the reason, the newest text that the
    model wrote in the thread, and the documents and searches of the stored results. The
    result is the assistant row at `row.next_seq`. The run row gets the result and `end_reason`. A retry
    after the run row write finds `end_reason` and writes nothing. Returns the next free seq.
    """
    from database import agent_runs

    row = _read_row(params)
    if agent_runs.is_terminal(row) or row.end_reason == params.reason:
        return row.next_seq
    messages = _read_thread(row)
    ending = next((decision.get("end_turn") for message in reversed(messages)
                   for decision in (message.usage.get("control", {}).get("decisions") or {}).values()
                   if decision.get("end_turn")), "") if params.reason == "no_progress" else ""
    text = ending or thread_facts.incomplete_text(messages, params.reason, params.limit)
    seq = row.next_seq
    if True:
        last = _last_ai(messages)
        model = str(last.usage.get("model") or "") if last is not None else ""
        _chat_row(row)(seq, "assistant", content=text, model=model)
        _finish_stream_rows_from(row.username, row.session_id, params.turn_uuid,
                                 row.start_seq)
        seq += 1
    agent_runs.RunRowWriter(row).write(result=text, next_seq=seq, end_reason=params.reason)
    log.info("[P_agent] run %s stopped before an answer: %s", row.run_id, params.reason)
    return seq


__all__ = [
    "BROWSER_READ_TOOL", "BROWSER_TOOL_PREFIX", "EMPTY_REPLY_TEXT", "EMPTY_RESPONSE", "EmptyNoteParams",
    "INCOMPLETE_REASONS", "IncompleteParams", "ModelRequestRejected", "ModelStepParams",
    "CITATION_NOTE_NAME", "ModelStepResult", "NOTE_ROLE", "STEP_BUDGET", "StepFailure", "StepRef",
    "SHARED_MODE", "SHARED_TOOLS", "SHARED_TEXT", "ToolCallParams", "ToolCallResult",
    "complete_result", "pinned_control", "share_key",
    "is_browser_tool", "is_retry_marker", "model_step", "record_step_failure", "runs_in_browser", "runs_in_order",
    "tool_call", "tool_idx", "write_asked_answer", "write_empty_note", "write_incomplete",
]
