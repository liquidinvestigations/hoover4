"""The step activities of `AgentRun`: one model call or one tool call each.

The workflow runs the loop. Each step reads the run row and the stored thread, does one
thing, and writes its result into the thread, so a retry, a worker restart and a
continue-as-new resume from the thread. No text crosses a Temporal payload: a step input
and result hold ids, counts and tool names.

* `model_step` sends `POST /model_step` to the agent service and writes the reply. A reply
  with calls writes the `ai` message and one live tool row for each call. A reply with no
  call writes the `ai` message and the answer row.
* `tool_call` sends `POST /tool_call` for one stored call and writes its `tool` message and
  its finished tool row.
* `delegate_step` writes the children of the `run_subagent` calls of the last reply.
* `prepare_continuation` adds the children's reports to the thread of a continuation.
* `record_step_failure` stores a `tool_unavailable` result for a tool step that failed.
* `plan_has_sections` answers whether the planner wrote a plan section.

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
from tasks.P_agent.model_timeouts import STEP_HEARTBEAT_SECONDS

log = logging.getLogger(__name__)

#: The read timeout of `POST /tool_call`. The tool itself has `TOOL_CALL_TIMEOUT` (300 s),
#: and the extra 10 s lets the service answer a tool that timed out inside it.
TOOL_READ_SECONDS = 310

#: The connect timeout of both step requests. A dead agent host fails the step in seconds.
CONNECT_SECONDS = 10

#: The human message of a `final` step, for each reason.
FINAL_TEXT = {
    "step_budget": (
        "This run has used all its model steps. Stop now and write the final answer from "
        "what the results above contain. Name the documents you rely on. If they contain "
        "nothing relevant, say so."),
    "repeated_call": (
        "Your last call repeats an earlier call with the same arguments, so it was not run. "
        "Stop now and write the final answer from what the results above contain. Name the "
        "documents you rely on. If they contain nothing relevant, say so."),
}

#: The stored result of a call that a `final` step did not run: the first sentence of the
#: human message of that step.
NOT_RUN_TEXT = {
    "step_budget": "This run has used all its model steps.",
    "repeated_call": ("Your last call repeats an earlier call with the same arguments, so "
                      "it was not run."),
}

#: Reads that a model repeats on purpose. A repeat of one of them does not end the run.
REPEAT_EXEMPT = ("read_todo", "read_plan")

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
    #: `tools`, or `final` for an answer with no tool bound.
    mode: str = "tools"
    #: `step_budget` or `repeated_call`, for mode `final`.
    final_reason: str = ""


@dataclass
class ModelStepResult:
    #: `answered`, `calls` or `closed`.
    outcome: str
    calls: list[CallRef] = field(default_factory=list)
    #: A call of this reply repeats an earlier call of the thread.
    repeated: bool = False
    next_seq: int = 0
    next_idx: int = 0


@dataclass
class ToolCallParams(StepRef):
    call: Optional[CallRef] = None


@dataclass
class ToolCallResult:
    #: `ok`, `error` or `closed`.
    status: str
    error_class: str = ""


@dataclass
class StepFailure(StepRef):
    #: `model` or `tool`.
    step: str = ""
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
    order, and the delegations follow them.
    """
    entries = ai.tool_calls
    plain = [i for i, e in enumerate(entries) if e.get("kind") != "delegation"]
    if position in plain:
        return ai.idx + 1 + plain.index(position)
    delegations = [i for i, e in enumerate(entries) if e.get("kind") == "delegation"]
    return ai.idx + 1 + len(plain) + delegations.index(position)


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
        # The purpose of a plan sub-agent. `review` adds the verdict block to its prompt.
        "purpose": row.purpose or None,
        "username": row.username,
        "session_id": row.session_id,
        "allowed_collections": list(params.allowed_collections or []),
        "llm_model": params.llm_model or _chat_model(),
        "can_delegate": row.depth < 2,
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
                       measure: Any = None, error_class: str = "") -> None:
    """The `tool` message of one call, and for a run that writes the transcript, its
    finished tool row at the call's seq and the final stream row."""
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
        _chat_row(row)(call.seq, "tool", **tool_row_fields(call.name, entry.get("args"), content))
        ToolCallWriter(row, turn_uuid, call.seq, call.name, entry.get("args")).finish()


def _read_thread(row):
    from database import agent_runs
    from tasks.P_agent.stream_writer import prepare_thread

    return prepare_thread(agent_runs.read_messages(row.username, row.session_id, row.thread_id))


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
    `ok` 0 and its class, and is raised again.
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
        with (activity.shield_thread_cancel_exception() if activity.in_activity()
              else contextlib.nullcontext()):
            events.record(event)


# --------------------------------------------------------------------------- model_step


def _repeated(earlier, ai_entries: list[dict]) -> bool:
    """A call of this reply has the name and arguments of a call of an earlier `ai` message.
    `read_todo` and `read_plan` are left out."""
    seen = {(str(e.get("name") or ""), args_digest(str(e.get("name") or ""), e.get("args") or {}))
            for m in earlier if m.role == "ai" for e in m.tool_calls}
    return any(
        (str(e.get("name") or ""), args_digest(str(e.get("name") or ""), e.get("args") or {}))
        in seen
        for e in ai_entries if str(e.get("name") or "") not in REPEAT_EXEMPT)


def _close_for_final(row, params: ModelStepParams, messages) -> list:
    """Step 5 of `model_step` in mode `final`: a `not_run` result for each unanswered call of
    the last reply, then the human message of the reason. A retry writes neither twice."""
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
    text = FINAL_TEXT.get(params.final_reason) or FINAL_TEXT["step_budget"]
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
    """Step 8 of `model_step`: the live tool rows and the run row of a reply with calls."""
    entries = ai.tool_calls
    if stream is not None:
        stream.tool_rows(entries)
    next_seq = max([row.next_seq] + [int(e.get("seq") or 0) + 1 for e in entries])
    writer.write(next_seq=next_seq, model_steps=max(row.model_steps, params.step_no),
                 **_step_tokens(row, params.step_no, ai.usage))
    return ModelStepResult(outcome="calls", calls=call_refs(ai),
                           repeated=_repeated(earlier, entries), next_seq=next_seq,
                           next_idx=ai.idx + 1)


def _write_answer(row, params: ModelStepParams, earlier, ai, writer) -> ModelStepResult:
    """Step 9 of `model_step`: the answer row and the run row of a reply with no call.

    `earlier` is the thread before the `ai` message. A retry after the run row write finds
    `model_steps` at this step, and writes the answer row again at the same seq.
    """
    from database import agent_runs
    from tasks.P_agent.stream_writer import context_window_for, round_view

    plan_prose, round_reasoning, _ = round_view(earlier)
    answer = "\n\n".join(p for p in (plan_prose, (ai.content or "").strip()) if p)
    reasoning = "\n\n".join(p for p in (round_reasoning, (ai.reasoning or "").strip()) if p)
    if not answer and reasoning:
        answer, reasoning = reasoning, ""
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
    seq = row.next_seq - (1 if written and transcript else 0)
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
    return ModelStepResult(outcome="answered", next_seq=seq, next_idx=ai.idx + 1)


def _store_reply(row, params: ModelStepParams, turn: dict, idx: int, model: str):
    """Write the `ai` message of a reply at `idx`, with its call entries and usage.

    Each call entry gets its `position` in the reply and its transcript `seq`. The seqs
    start at the row's `next_seq` in call order, and the delegations take the last ones,
    so the seqs of one delegation batch are consecutive.
    """
    from database import agent_runs

    entries = []
    for position, raw in enumerate(turn.get("tool_calls") or []):
        entry = dict(raw)
        entry["position"] = position
        entries.append(entry)
    seq = row.next_seq
    for entry in ([e for e in entries if e.get("kind") != "delegation"]
                  + [e for e in entries if e.get("kind") == "delegation"]):
        entry["seq"] = seq
        seq += 1
    usage = dict(turn.get("usage") or {})
    usage.update(step_no=params.step_no, mode=params.mode,
                 bound_names=list(turn.get("bound_names") or []),
                 summarised=bool(turn.get("summarised")), model=model)
    ai = agent_runs.RunMessageRow(
        idx=idx, role="ai", content=str(turn.get("text") or ""),
        reasoning=str(turn.get("reasoning") or ""), tool_calls_json=json.dumps(entries),
        usage_json=json.dumps(usage), is_final=1, run_id=row.run_id)
    agent_runs.write_message(row.username, row.session_id, row.thread_id, row.run_id, ai)
    return ai


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
    5. `POST /model_step` streams the reply. The partial rows are written as it arrives.
    6. A reply with calls gets its seqs (delegations last), the `ai` message, one live
       tool row for each call and the run row. A reply with no call gets the `ai` message,
       the answer row and the run row with the result.
    """
    from database import agent_runs
    from tasks.P_agent.stream_writer import (
        KEEPALIVE_SECONDS, RUN_STREAM_IDLE_SECONDS, ModelStepWriter, _chat_history,
        round_view, run_message,
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
        if last_ai.tool_calls:
            return _write_calls(row, params, earlier, last_ai, writer, None)
        return _write_answer(row, params, earlier, last_ai, writer)

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
        earlier_turns = [
            {"role": h["type"], "content": h["content"]}
            for h in _chat_history(row.username, row.session_id, row.turn_seq)
        ] if transcript else []
        body = {
            **_step_run(row, params),
            "step_no": params.step_no,
            "mode": params.mode,
            "messages": [run_message(m) for m in messages],
            "earlier": earlier_turns,
        }
        stream = ModelStepWriter(row, params.turn_uuid, row.next_seq, next_idx, plan_prose,
                                 round_reasoning)
        writer.start_keepalive()
        try:
            stream.start()
            ai = None
            ended = False
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
                elif kind == "model_turn" and ai is None:
                    # Written at once, so a retry after a later failure finds the reply.
                    ai = _store_reply(row, params, frame, next_idx, body["llm_model"])
                elif kind == "end":
                    ended = True
                    usage = frame.get("usage") or {}
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
            if ai.tool_calls:
                result = _write_calls(row, params, messages, ai, writer, stream)
            else:
                result = _write_answer(row, params, messages, ai, writer)
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
        "bound_names": list(ai.usage.get("bound_names") or []),
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
                               result.get("measure"), error_class)
            # A result with an error code only in its text, such as not_found, is a result.
            event.ok = status != "error"
            event.error_class = error_class
            return ToolCallResult(status=status, error_class=error_class)
        finally:
            with (activity.shield_thread_cancel_exception() if activity.in_activity()
                  else contextlib.nullcontext()):
                live.close()


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
        run_kind=row.kind, step=params.step, name=name, task_queue=params.task_queue,
        attempt=0, ok=False,
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


__all__ = [
    "FINAL_TEXT", "ModelRequestRejected", "ModelStepParams", "ModelStepResult",
    "NOT_RUN_TEXT", "StepFailure", "StepRef", "ToolCallParams", "ToolCallResult",
    "args_digest", "canonical_json", "delegate_step", "model_step", "plan_has_sections",
    "prepare_continuation", "record_step_failure", "tool_call", "tool_idx",
]
