"""The two step requests of the agent service: one model call, and one tool call.

The worker runs the agent loop. For each model call it sends `POST /model_step`, and for
each tool call of a reply it sends `POST /tool_call`. The service keeps no state between two
requests. Each request carries the run fields (`StepRun`), and the stored thread is the only
state of a run.

`/model_step` streams `data: {json}` frames: `reasoning` and `response` deltas, then one
`model_turn` with the classified calls of the reply (`CallEntry`), then one `end`. When the
call compacts its input, one `compaction` frame comes first, before the summary requests, and
`model_turn` carries `compaction`, the version 2 record that the worker stores as a
`compaction` row of the run thread (`run_messages.apply_compactions`). `model_turn` also
carries `note_warning`, true when the worker writes the warning to save notes.

A failed call sends one `error` frame in place of `model_turn` and `end`. While no frame is ready,
the stream sends the SSE comment line `KEEPALIVE_LINE` every `KEEPALIVE_SECONDS`.

Before the model call, `/model_step` measures the whole request (`request_size.py`) with the
tool results that the worker stored after the previous reply, and gives that size to the
compaction. `model_turn` carries the size in its usage as `request_size`, the model that
answered as `model`, and in `citation_tool` whether the call bound `cite_documents`, which
the worker's citation check reads.

`/tool_call` runs one call and returns its result as JSON. It refuses an unavailable name,
a `run_subagent` call, and arguments that do not match the tool's schema. The length of the
conversation never refuses a call. A failed result that shows a known stumble ends with a
sentence that names the skill of the fix (`stumbles.py`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, AsyncIterator, Dict, FrozenSet, List, Literal, Optional, Sequence, Tuple

import httpx
import openai
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field, model_validator

from research_agent import compaction, llm_events, request_size, skill_store, stumbles
from research_agent.chat_model import ThinkingChatOpenAI
from research_agent.execution import (
    DELEGATION_TOOL, ORDERED_TOOLS, _IDEMPOTENCY_KEY, _PAGE_SHARE, _error, _text_of,
    batch_budget, split_resources, validation_error,
)
from research_agent.run_messages import (
    RunMessage, ToolCallRecord, apply_compactions, close_unanswered, to_langchain,
)
from research_agent.subagents import briefings_of
from research_agent import thinking
from research_agent.tool_args import decode_string_arguments, rename_aliases, repair_arguments
from research_agent.tool_catalogue import SEARCH_TOOL, tool_schema

log = logging.getLogger(__name__)

#: How long the step stream may send nothing before it sends a keepalive line. It must stay
#: well under the worker's read timeout of the stream (300 s).
KEEPALIVE_SECONDS = 30.0
#: An SSE comment: a line that starts with ":", which a reader of `data: ` frames skips.
KEEPALIVE_LINE = ": keepalive\n\n"

#: The browser tools that change the page. A second attempt could repeat the action, so
#: the worker gives these calls one attempt only.
BROWSER_ACTIONS = frozenset({
    "browser_navigate", "browser_click", "browser_type", "browser_select_option",
    "browser_press_key",
})


def llm_streaming_enabled() -> bool:
    """Whether `/model_step` streams the reply token by token.

    Token streaming follows `LLM_STREAMING`. The compose files and `deploy.py` render
    `true` for an empty key, and the code default `false` applies only when the variable
    is absent. A whole reply keeps its reasoning through
    `ThinkingChatOpenAI._create_chat_result`.
    """
    return os.getenv("LLM_STREAMING", "false").lower() in ("1", "true", "yes")


# ----------------------------------------------------------------------- request types


class StepRun(BaseModel):
    """The fields of every step request. The worker sends them from the run row."""

    run_id: str = Field(description="The agent run id. It keys the context and the browser.")
    kind: Literal["chat", "subagent", "planner", "organizer"]
    depth: int = Field(description="0 for a lead, 1 or 2 for a sub-agent")
    purpose: Optional[Literal["execute", "correct"]] = None
    username: str
    session_id: str
    allowed_collections: List[str] = Field(default_factory=list)
    llm_model: Optional[str] = None
    can_delegate: bool = True


class ModelStepRequest(StepRun):
    step_no: int = Field(description="1 for the first model call of the run thread")
    thinking: bool = Field(
        description="The admin thinking switch, read by the worker before this call"
    )
    messages: List[RunMessage] = Field(description="The run thread. messages[0] is human")
    earlier: List[RunMessage] = Field(
        default_factory=list, description="Earlier turns of the chat, depth 0 only"
    )

    @model_validator(mode="after")
    def _opening(self):
        if not self.messages or self.messages[0].role != "human":
            raise ValueError("messages[0] must be the opening human message")
        if self.depth > 0 and self.earlier:
            raise ValueError("a sub-agent gets no earlier turns")
        return self


class ToolCallRequest(StepRun):
    call: ToolCallRecord
    page_share: Optional[int] = Field(default=None, description="bytes, None: the tool's default")
    idempotency_key: str


class CallEntry(BaseModel):
    """One call of a reply as the service classifies it."""

    id: str
    name: str
    args: Dict[str, Any]
    kind: Literal["parallel", "ordered", "delegation"]
    briefings: Optional[List[Dict[str, Any]]] = None
    page_share: Optional[int] = None
    retry: bool = True


# ------------------------------------------------------------------------ model step


def thinking_body(request: ModelStepRequest) -> Dict[str, Any]:
    """The request body of the thinking switch for one model step."""
    return thinking.thinking_body(request.thinking)


def call_ids(calls: Sequence[Dict[str, Any]], step_no: int, earlier_ids: set) -> List[str]:
    """The ids of the calls of one reply. A call whose id is empty, equal to another id of
    the reply, or equal to an id of an earlier `ai` message gets `call-{step_no}-{position}`."""
    raw = [(c.get("id") or "") for c in calls]
    out = []
    for position, call_id in enumerate(raw):
        if not call_id or raw.count(call_id) > 1 or call_id in earlier_ids:
            call_id = f"call-{step_no}-{position}"
        out.append(call_id)
    return out


def classify_calls(
    snapshot: Any,
    callable_names: Sequence[str],
    calls: Sequence[Dict[str, Any]],
    step_no: int,
    thread: Sequence[RunMessage],
) -> List[CallEntry]:
    """Classify the calls of one reply, give each its id and its page share. The shares
    depend on the calls of the reply only (`execution.batch_budget`)."""
    earlier_ids = {c.id for m in thread if m.role == "ai" for c in m.tool_calls}
    ids = call_ids(calls, step_no, earlier_ids)
    entries: List[CallEntry] = []
    for call, call_id in zip(calls, ids):
        name = call.get("name") or ""
        args = call.get("args") or {}
        briefings = None
        if name == DELEGATION_TOOL and name in callable_names:
            briefings = briefings_of(args)
        if briefings is not None:
            kind = "delegation"
        elif name in ORDERED_TOOLS:
            kind = "ordered"
        else:
            kind = "parallel"
        entries.append(CallEntry(
            id=call_id, name=name, args=args, kind=kind, briefings=briefings,
            retry=name not in BROWSER_ACTIONS,
        ))
    budgeted = [e for e in entries if e.kind != "delegation"]
    if budgeted:
        budget = batch_budget([e.name for e in budgeted])
        for entry, share in zip(budgeted, budget.shares):
            entry.page_share = int(share)
    return entries


def _text(content: Any) -> str:
    if isinstance(content, list):
        return "".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
        )
    return content or ""


def _reasoning(message: Any) -> str:
    value = (getattr(message, "additional_kwargs", None) or {}).get("reasoning_content") or ""
    return value if isinstance(value, str) else json.dumps(value)


def classify_error(exc: BaseException) -> Tuple[str, bool]:
    """The class of a failed model call, and whether a retry can succeed."""
    if isinstance(exc, (openai.APITimeoutError, httpx.TimeoutException, asyncio.TimeoutError)):
        return "read_timeout", True
    if isinstance(exc, (openai.APIConnectionError, httpx.ConnectError)):
        return "connect_error", True
    status = None
    if isinstance(exc, openai.APIStatusError):
        status = exc.status_code
    elif isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
    if status is not None:
        retryable = not (400 <= status < 500 and status not in (408, 429))
        return f"http_{status}", retryable
    return "other", True


def _callbacks_config(agent: Any, request: StepRun) -> Dict[str, Any]:
    handler = getattr(agent, "langfuse_handler", None)
    if not handler:
        return {}
    return {
        "callbacks": [handler],
        "metadata": {
            "langfuse_user_id": request.username,
            "langfuse_session_id": request.session_id,
            "langfuse_tags": [getattr(agent, "name", "agent")],
        },
    }


async def _context(agent: Any, request: StepRun) -> Any:
    return await agent.context_for(
        request.username, request.allowed_collections, request.session_id,
        request.llm_model, request.run_id, request.kind, request.can_delegate,
        request.purpose,
    )


async def run_model_step(agent: Any, request: ModelStepRequest) -> AsyncIterator[Dict[str, Any]]:
    """Make one model call and yield its frames. An exception yields one `error` frame."""
    try:
        async for frame in _model_step_frames(agent, request):
            yield frame
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - the worker reads the error frame
        error_class, retryable = classify_error(exc)
        log.warning("model step %s of run %s failed: %s", request.step_no, request.run_id, exc)
        yield {"type": "error", "error_class": error_class, "retryable": retryable,
               "content": f"{type(exc).__name__}: {exc}"}


def model_input_rows(earlier: Sequence[RunMessage], messages: Sequence[RunMessage]
                     ) -> Tuple[List[RunMessage], List[RunMessage]]:
    """The stored thread of one model call, with a `not_run` result for each unanswered
    call of an earlier turn, and the list after every stored compaction."""
    rows = close_unanswered(list(earlier)) + list(messages)
    return rows, apply_compactions(rows)


def build_model_input(
    earlier: Sequence[RunMessage], messages: Sequence[RunMessage], model_id: str, *,
    system_text: str = "", schemas_json: str = "",
    summariser: Optional[compaction.Summariser] = None,
) -> Tuple[List[RunMessage], List[BaseMessage], Optional[compaction.CompactionReport]]:
    """The input of one model call: the earlier turns and the run thread, with every stored
    compaction applied, and then the compaction of this call.

    Returns the applied rows, the list to send and the report of this call's compaction.
    `system_text` and `schemas_json` are the fixed part, which the token estimate counts.
    """
    rows, applied = model_input_rows(earlier, messages)
    compacted, report = compaction.compact(
        applied, rows, system_text=system_text, schemas_json=schemas_json,
        model_id=model_id, summariser=summariser)
    return applied, to_langchain(compacted), report


def compaction_record(report: compaction.CompactionReport,
                      applied: Sequence[RunMessage] = ()) -> Dict[str, Any]:
    """The content of the `compaction` row of one report, a version 2 record. Each message
    is named by its stored key. A message with no key, such as a `not_run` result, is not
    named."""
    return dict(report.row)


def compaction_frame(plan: compaction.CompactionPlan) -> Dict[str, Any]:
    """The frame that the stream sends before the summary requests of a compaction."""
    return {"type": "compaction", "state": "running", "tokens_before": plan.billed,
            "target": plan.target, "parts": plan.parts}


async def _model_step_frames(agent: Any, request: ModelStepRequest) -> AsyncIterator[Dict[str, Any]]:
    context = await _context(agent, request)
    snapshot = context.snapshot
    thread = [m for m in list(request.earlier) + list(request.messages)
              if m.role != "compaction"]
    names = snapshot.callable_names()
    system_text = context.system_text_for(names)
    bound_tools = snapshot.tools_for()
    schemas_json = json.dumps([tool_schema(t) for t in bound_tools], default=str)

    # What the compaction returns goes to the model only. The stored thread keeps every
    # tool result in full, and the `compaction` row of the reply records what was replaced.
    rows, applied = model_input_rows(request.earlier, request.messages)
    window = await asyncio.to_thread(compaction.context_window, context.model_id)
    if request.step_no <= 1 and compaction.fixed_part_passes_target(
            applied, system_text, schemas_json, window):
        log.warning("the system text, the tool schemas and the user messages of run %s pass "
                    "the compaction target", request.run_id)
    # The size of this request, with the results that the worker stored after the previous
    # reply. The billed tokens of that reply do not include them.
    size = await asyncio.to_thread(
        request_size.measure, system_text, schemas_json, applied,
        model_id=context.model_id, window=window)
    pending = await asyncio.to_thread(
        compaction.plan_compaction, applied, rows, system_text=system_text,
        schemas_json=schemas_json, model_id=context.model_id, window=window,
        measured=size.tokens, safe_input=size.safe_input)
    report = None
    compacted = applied
    if pending is not None:
        yield compaction_frame(pending)
        compacted, report = await asyncio.to_thread(compaction.finish_compaction, pending)
        before = size.tokens
        size = await asyncio.to_thread(
            request_size.measure, system_text, schemas_json, compacted,
            model_id=context.model_id, window=window)
        sent_size = {**size.record(), "before_compaction": before}
    else:
        sent_size = size.record()
    if not size.fits:
        log.warning("the request of run %s step %s is %d tokens (%s), above the safe input "
                    "of %d tokens", request.run_id, request.step_no, size.tokens, size.method,
                    size.safe_input)
    record = compaction_record(report) if report is not None else None
    if report is not None:
        await asyncio.to_thread(
            compaction.record_compaction, report,
            username=request.username, session_id=request.session_id,
        )
    model_input = [SystemMessage(content=system_text)] + to_langchain(compacted)

    llm: Any = ThinkingChatOpenAI(
        **context.llm_kwargs,
        streaming=llm_streaming_enabled(),
        disable_streaming=not llm_streaming_enabled(),
        extra_body=thinking_body(request),
    )
    llm = llm.bind_tools(bound_tools)
    config = _callbacks_config(agent, request)

    timer = llm_events.CallTimer()
    message: Any = None
    if llm_streaming_enabled():
        async for chunk in llm.astream(model_input, config or None):
            # A client with no stream of its own sends one whole `AIMessage`.
            if not isinstance(chunk, AIMessage):
                continue
            reasoning = _reasoning(chunk)
            if reasoning:
                yield {"type": "reasoning", "content": reasoning}
            text = _text(chunk.content)
            if text:
                yield {"type": "response", "content": text}
            message = chunk if message is None else message + chunk
        if message is None:
            message = AIMessage(content="")
    else:
        message = await llm.ainvoke(model_input, config or None)
        reasoning = _reasoning(message)
        if reasoning:
            yield {"type": "reasoning", "content": reasoning}
        text = _text(message.content)
        if text:
            yield {"type": "response", "content": text}
    latency_ms = timer.elapsed_ms()

    calls = [
        {"id": c.get("id"), "name": c.get("name"), "args": c.get("args")}
        for c in (getattr(message, "tool_calls", None) or [])
    ]
    entries = await asyncio.to_thread(
        classify_calls, snapshot, names, calls, request.step_no, thread
    )

    provider = llm_events.provider_from_base_url()
    try:
        stats = llm_events.stats_from_message(
            message, model_id=context.model_id, provider=provider, latency_ms=latency_ms,
            kind="chat",
        )
    except Exception as exc:  # noqa: BLE001 - a lost number never loses the answer
        log.warning("could not read usage off a model step: %s", exc)
        stats = llm_events.LlmCallStats(
            provider=provider, model_id=context.model_id, latency_ms=latency_ms
        )
    if report is not None and stats.prompt_tokens:
        # The "after" of a compaction is the prompt of the call made on the shortened
        # list. The second insert under the same id replaces the first row.
        report.tokens_after = stats.prompt_tokens
        await asyncio.to_thread(
            compaction.record_compaction, report,
            username=request.username, session_id=request.session_id,
        )
    try:
        # In a thread, because these are synchronous POSTs to ClickHouse, and on the
        # event loop they stall the frames of every other step.
        await asyncio.to_thread(
            llm_events.record_llm_call, stats,
            username=request.username, session_id=request.session_id,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("failed to record llm_call_events: %s", exc)

    usage = getattr(message, "usage_metadata", None) or {}
    yield {
        "type": "model_turn",
        "model": context.model_id,
        "text": _text(message.content),
        "reasoning": _reasoning(message),
        "tool_calls": [e.model_dump() for e in entries],
        "usage": {
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
            "reasoning_tokens": int(stats.reasoning_tokens or 0),
            "request_size": sent_size,
            # The worker's citation check runs only for a model that had the tool.
            "citation_tool": any(getattr(t, "name", "") == "cite_documents"
                                 for t in bound_tools),
        },
        "summarised": report is not None,
        "compaction": record,
        # The worker writes the warning to save notes before the next compaction.
        "note_warning": compaction.note_warning_due(
            rows, usage, bool(calls), window),
    }
    yield {
        "type": "end",
        "model": context.model_id,
        "latency_ms": latency_ms,
        "usage": {
            "prompt_tokens": int(stats.prompt_tokens or 0),
            "completion_tokens": int(stats.completion_tokens or 0),
            "reasoning_tokens": int(stats.reasoning_tokens or 0),
        },
    }


async def stream_frames(frames: AsyncIterator[Dict[str, Any]]) -> AsyncIterator[str]:
    """Send each frame as a `data: {json}` line, and a keepalive line while none is ready.

    The frames run in a task of their own. A client that closes the request cancels it.
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def produce():
        try:
            async for frame in frames:
                await queue.put(("data", frame))
        except Exception as exc:  # noqa: BLE001 - run_model_step sends its own error frame
            await queue.put(("data", {"type": "error", "error_class": "other",
                                      "retryable": True, "content": str(exc)}))
        finally:
            await queue.put(("done", None))

    task = asyncio.create_task(produce())
    try:
        while True:
            try:
                # A cancelled get() removes no item, so a timeout loses no frame.
                kind, item = await asyncio.wait_for(queue.get(), KEEPALIVE_SECONDS)
            except asyncio.TimeoutError:
                yield KEEPALIVE_LINE
                continue
            if kind == "done":
                break
            yield f"data: {json.dumps(item, default=str)}\n\n"
    finally:
        task.cancel()


# ------------------------------------------------------------------------- tool call


def _tool_response(request: ToolCallRequest, content: str, status: str = "ok",
                   error_class: str = "", measure: Optional[Dict[str, Any]] = None,
                   matched: Optional[List[str]] = None,
                   doc_refs: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """The `/tool_call` response. `doc_refs` is the whole identity of each row of a
    result page, or None when the tool sent none."""
    return {
        "tool_call_id": request.call.id,
        "name": request.call.name,
        "content": content,
        "status": status,
        "error_class": error_class,
        "measure": measure,
        "matched_names": matched or [],
        "doc_refs": doc_refs,
    }


def _listed_skill_names(context: Any) -> FrozenSet[str]:
    """The names of the skills that the run lists, for the skill line of an error."""
    ctx = getattr(context, "skill_context", None) \
        or getattr(getattr(context, "snapshot", None), "skill_context", None)
    if ctx is None:
        return frozenset()
    return frozenset(skill.name for skill in skill_store.listed_skills(ctx))


async def run_tool_call(agent: Any, request: ToolCallRequest) -> Dict[str, Any]:
    """Run one tool call and return its result. A failed result that shows a known stumble
    ends with the sentence that names its skill (`stumbles.with_skill_line`)."""
    context = await _context(agent, request)
    response = await _run_tool_call(context, request)
    return stumbles.with_skill_line(response, dict(request.call.args or {}),
                                    _listed_skill_names(context))


async def _run_tool_call(context: Any, request: ToolCallRequest) -> Dict[str, Any]:
    snapshot = context.snapshot
    name = request.call.name
    allowed = snapshot.callable_names()

    if name == DELEGATION_TOOL and name in allowed:
        # A readable delegation never reaches this endpoint, because the worker delegates it.
        return _tool_response(request, _error(
            "invalid_arguments",
            "tasks must be a list of 1 to 5 briefings, each with an objective",
            tool=name,
        ), "error", "invalid_arguments")
    if name not in allowed:
        return _tool_response(request, _error(
            "tool_unavailable", f"No tool of this run is named {name!r}. "
            f"Find tools with {SEARCH_TOOL}.", tool=name,
        ), "error", "tool_unavailable")

    tool = snapshot.tools_by_name[name]
    schema = tool_schema(tool)
    repaired, repairs = repair_arguments(dict(request.call.args))
    repaired, renames = rename_aliases(repaired, schema)
    repairs += renames
    if repairs:
        log.info("tool %s: %d argument repairs: %s", name, len(repairs), "; ".join(repairs))
    args = decode_string_arguments(repaired, schema)
    problem = validation_error(args, schema)
    if problem:
        return _tool_response(
            request, _error("invalid_arguments", problem, tool=name), "error", "invalid_arguments",
            _with_repairs(None, repairs),
        )

    share_token = _PAGE_SHARE.set(request.page_share)
    key_token = _IDEMPOTENCY_KEY.set(request.idempotency_key or None)
    try:
        result = await tool.ainvoke(
            {"type": "tool_call", "id": request.call.id, "name": name, "args": args}
        )
    except Exception as exc:  # noqa: BLE001 - the model reads the error
        log.warning("tool %s raised: %s", name, exc)
        return _tool_response(request, f"Error: {exc}", "error", "tool_error")
    finally:
        _PAGE_SHARE.reset(share_token)
        _IDEMPOTENCY_KEY.reset(key_token)

    measure = None
    doc_refs = None
    status = "ok"
    if isinstance(result, ToolMessage):
        content = _text_of(result.content)
        measure, doc_refs, _ = split_resources(result.artifact)
        if result.status == "error":
            status = "error"
    else:
        content = _text_of(result)
    return _tool_response(
        request, content, status, "tool_error" if status == "error" else "",
        _with_repairs(measure, repairs), [], doc_refs
    )


#: The measure key that lists the argument repairs of a call (`tool_args.repair_arguments`).
ARGUMENT_REPAIRS_KEY = "argument_repairs"


def _with_repairs(measure: Optional[Dict[str, Any]], repairs: List[str]) -> Optional[Dict[str, Any]]:
    """The measure of a call with its argument repairs added. A call with no repair keeps
    its measure as it was."""
    if not repairs:
        return measure
    return {**(measure or {}), ARGUMENT_REPAIRS_KEY: list(repairs)}


__all__ = [
    "BROWSER_ACTIONS", "CallEntry", "KEEPALIVE_LINE", "KEEPALIVE_SECONDS", "ModelStepRequest",
    "StepRun", "ToolCallRequest",
    "build_model_input", "call_ids", "classify_calls", "compaction_frame",
    "compaction_record", "model_input_rows",
    "classify_error", "llm_streaming_enabled", "run_model_step", "run_tool_call",
    "stream_frames", "thinking_body",
]
