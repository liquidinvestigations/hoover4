"""The two step requests of the agent service: one model call, and one tool call.

The worker runs the agent loop. For each model call it sends `POST /model_step`, and for
each tool call of a reply it sends `POST /tool_call`. The service keeps no state between two
requests. Each request carries the run fields (`StepRun`), and the stored thread is the only
state of a run.

`/model_step` streams `data: {json}` frames: `reasoning` and `response` deltas, then one
`model_turn` with the classified calls of the reply (`CallEntry`), then one `end`. When the
call compacts its input, one `compaction` frame comes first, before the summary request, and
`model_turn` carries `compaction`, the version 3 record that the worker stores as a
`compaction` row of the run thread (`run_messages.apply_compactions`).

A failed call sends one `error` frame in place of `model_turn` and `end`. While no frame is ready,
the stream sends the SSE comment line `KEEPALIVE_LINE` every `KEEPALIVE_SECONDS`.

Before the model call, `/model_step` measures the whole request (`request_size.py`) with the
tool results that the worker stored after the previous reply, and gives that size to the
compaction. After a compaction it measures the request again. A request that still passes
the safe input sends one `error` frame of class `context_size` or `context_preparation`,
which the worker does not retry. When the provider refuses a request as too large before
any output, the step reads the model's window again, compacts once more, and sends the new
request only when it differs. `model_turn` carries the size in its usage as `request_size`,
the model that answered as `model`, and in `citation_tool` whether the call bound
`cite_documents`, which the worker's citation check reads. The model is bound with each
tool's schema as `tool_args.model_schema` shows it, and `model_turn` carries each call with
its arguments normalized (`classify_calls`).

`/tool_call` runs one call and returns its result as JSON. It refuses an unavailable name,
damaged arguments, and arguments that do not match the tool's schema. The length of the
conversation never refuses a call. A failed result that shows a known stumble ends with a
sentence that names the skill of the fix (`stumbles.py`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, AsyncIterator, Dict, FrozenSet, List, Literal, Optional, Sequence, Tuple

import httpx
import openai
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field, model_validator

from research_agent import compaction, llm_events, request_size, skill_store, stumbles
from research_agent.chat_model import ThinkingChatOpenAI
from research_agent.execution import (
    ORDERED_TOOLS, _IDEMPOTENCY_KEY, _PAGE_SHARE, _error, _text_of,
    batch_budget, is_browser_tool, split_resources, validation_error,
)
from research_agent.run_messages import (
    RunMessage, ToolCallRecord, apply_compactions, close_unanswered, to_langchain,
)
from research_agent import thinking
from research_agent.tool_args import DamagedArguments, model_schema, normalize_arguments, repair_json_arguments
from research_agent.tool_catalogue import SEARCH_TOOL, tool_schema

log = logging.getLogger(__name__)

#: How long the step stream may send nothing before it sends a keepalive line. It must stay
#: well under the worker's read timeout of the stream (300 s).
KEEPALIVE_SECONDS = 30.0
#: An SSE comment: a line that starts with ":", which a reader of `data: ` frames skips.
KEEPALIVE_LINE = ": keepalive\n\n"

#: The browser tools that only read the page or wait. Every other browser tool can change
#: the page, and a second attempt could repeat its action, so the worker gives it one
#: attempt only (`retries`). The browser server can list more `browser_` tools than its six
#: default ones (`BROWSER_EXPOSED_TOOLS`). A tool that is not named here gets one attempt.
BROWSER_READS = frozenset({
    "read_page", "browser_snapshot", "browser_take_screenshot", "browser_wait_for",
    "browser_console_messages", "browser_network_requests",
})


def retries(name: str) -> bool:
    """Whether the worker may run a failed call again: every call except a browser tool
    that can change the page."""
    return not is_browser_tool(name) or name in BROWSER_READS


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
    username: str
    session_id: str
    allowed_collections: List[str] = Field(default_factory=list)
    llm_model: Optional[str] = None


class ModelStepRequest(StepRun):
    step_no: int = Field(description="1 for the first model call of the run thread")
    thinking: bool = Field(
        description="The admin thinking switch, read by the worker before this call"
    )
    messages: List[RunMessage] = Field(description="The run thread. messages[0] is human")
    earlier: List[RunMessage] = Field(
        default_factory=list, description="Earlier turns of the chat"
    )

    @model_validator(mode="after")
    def _opening(self):
        if not self.messages or self.messages[0].role != "human":
            raise ValueError("messages[0] must be the opening human message")
        return self


class ToolCallRequest(StepRun):
    call: ToolCallRecord
    page_share: Optional[int] = Field(default=None, description="bytes, None: the tool's default")
    idempotency_key: str
    messages: List[RunMessage] = Field(default_factory=list)
    earlier: List[RunMessage] = Field(default_factory=list)


class CallEntry(BaseModel):
    """One call of a reply as the service classifies it."""

    id: str
    name: str
    args: Dict[str, Any]
    kind: Literal["parallel", "ordered"]
    page_share: Optional[int] = None
    retry: bool = True
    #: The changes that `tool_args.normalize_arguments` made to the model's arguments. `args`
    #: holds the arguments after them.
    argument_repairs: List[str] = Field(default_factory=list)
    #: Why the model client could not read the arguments of the call, which it lists as an
    #: invalid call. `args` is then empty, and `/tool_call` refuses the call.
    argument_error: str = ""


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


#: The name that a call with unreadable arguments and no readable name is stored under.
UNNAMED_CALL = "unnamed_call"
#: The most characters of an unreadable argument text that a stored call keeps.
UNREADABLE_CHARS = 600


def unreadable_call(call: Dict[str, Any]) -> Dict[str, Any]:
    """Repair known JSON key damage or retain the call with its damage position."""
    raw = str(call.get("args") or "")
    try:
        args, repairs = repair_json_arguments(raw)
    except DamagedArguments as exc:
        call = dict(call, error=str(exc))
    else:
        return {"id": call.get("id"), "name": call.get("name") or UNNAMED_CALL,
                "args": args, "argument_repairs": repairs}
    text = str(call.get("args") or "")
    if len(text) > UNREADABLE_CHARS:
        text = text[:UNREADABLE_CHARS] + "..."
    error = str(call.get("error") or "the text is not JSON")
    return {"id": call.get("id"), "name": call.get("name") or UNNAMED_CALL, "args": {},
            "argument_error": f"{error}. The model server sent: {text}"}


#: Tokens of the served model's call syntax. A reply text that holds one is a call that the
#: model server did not parse, whether the model or the parser failed.
CALL_SYNTAX_TOKENS = ('<|"|>', "<|tool_call>")
_CALL_NAME = re.compile(r"call:([A-Za-z_][A-Za-z0-9_]*)\{")


def leaked_call(text: str) -> Optional[Dict[str, Any]]:
    """The call that a reply with no parsed call writes as text, as one unreadable call, or
    `None` for a text with no call syntax. The name comes from `call:NAME{` when the text
    has it. No argument is rebuilt, so `/tool_call` refuses the call and quotes the text."""
    if not any(token in text for token in CALL_SYNTAX_TOKENS):
        return None
    name = _CALL_NAME.search(text)
    return unreadable_call({
        "id": None, "name": name.group(1) if name else UNNAMED_CALL, "args": text,
        "error": "the model server returned this call as text and did not parse it",
    })


def shown_tool(tool: Any) -> Dict[str, Any]:
    """The OpenAI tool definition that the model is bound with: the tool's name and
    description, and its schema as `tool_args.model_schema` shows it."""
    shown = convert_to_openai_tool(tool)
    function = shown.get("function") or {}
    function["parameters"] = model_schema(tool_schema(tool) or function.get("parameters") or {})
    return shown


def classify_calls(
    snapshot: Any,
    callable_names: Sequence[str],
    calls: Sequence[Dict[str, Any]],
    step_no: int,
    thread: Sequence[RunMessage],
) -> List[CallEntry]:
    """Classify the calls of one reply, give each its id and its page share. The shares
    depend on the calls of the reply only (`execution.batch_budget`).

    The arguments of a call to a tool of the run are normalized first
    (`tool_args.normalize_arguments`), so the stored call, the worker's readers of it, such
    as the question of `ask_user`, and `/tool_call` all see the same values. Damaged
    arguments stay as the model sent them, and `/tool_call` refuses them.
    """
    earlier_ids = {c.id for m in thread if m.role == "ai" for c in m.tool_calls}
    ids = call_ids(calls, step_no, earlier_ids)
    tools = getattr(snapshot, "tools_by_name", None) or {}
    entries: List[CallEntry] = []
    for call, call_id in zip(calls, ids):
        name = call.get("name") or ""
        args = call.get("args") or {}
        argument_error = str(call.get("argument_error") or "")
        repairs: List[str] = list(call.get("argument_repairs") or [])
        if name in tools and not argument_error:
            normalized = normalize_arguments(args, tool_schema(tools[name]))
            if not normalized.problem:
                args = normalized.args
                repairs.extend(normalized.repairs)
        entries.append(CallEntry(
            id=call_id, name=name, args=args,
            kind="ordered" if name in ORDERED_TOOLS else "parallel",
            retry=retries(name), argument_repairs=repairs, argument_error=argument_error,
        ))
    if entries:
        budget = batch_budget([e.name for e in entries])
        for entry, share in zip(entries, budget.shares):
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
    if isinstance(exc, compaction.ContextError):
        return exc.error_class, False
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
        request.llm_model, request.run_id,
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
    views = [m.model_copy(update={"content": m.model_content})
             if m.role == "tool" and m.model_content is not None else m for m in rows]
    return rows, apply_compactions(views)


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
    """The content of the `compaction` row of one report, a version 3 record. Each message
    is named by its stored key. A message with no key, such as a `not_run` result, is not
    named."""
    return dict(report.row)


def compaction_frame(plan: compaction.CompactionPlan) -> Dict[str, Any]:
    """The frame that the stream sends before the summary request of a compaction."""
    return {"type": "compaction", "state": "running", "tokens_before": plan.billed,
            "target": plan.target, "parts": plan.parts}


def _provider_status(exc: BaseException) -> Optional[int]:
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    return None


def _same_request(a: Sequence[RunMessage], b: Sequence[RunMessage]) -> bool:
    """Whether two model inputs hold the same messages."""
    return [(m.role, m.content, m.tool_call_id) for m in a] == \
        [(m.role, m.content, m.tool_call_id) for m in b]


class Prepared(BaseModel):
    """The model input of one step after the context preparation."""

    messages: List[RunMessage]
    size: Dict[str, Any]
    #: The report of this step's compaction, or None.
    report: Optional[Any] = None
    reductions: List[Dict[str, Any]] = Field(default_factory=list)


async def _prepare(request: ModelStepRequest, context: Any, system_text: str,
                   schemas_json: str, rows: List[RunMessage], applied: List[RunMessage],
                   window: int, *, force: bool = False) -> AsyncIterator[Any]:
    """Measure input, summarize older steps, and page the largest newest results.

    Raise `ContextError` when eligible reductions cannot make the request fit.
    Yield the compaction frame when planned, then yield the prepared request.
    """
    size = await asyncio.to_thread(
        request_size.measure, system_text, schemas_json, applied,
        model_id=context.model_id, window=window)
    pending = await asyncio.to_thread(
        compaction.plan_compaction, applied, rows, system_text=system_text,
        schemas_json=schemas_json, model_id=context.model_id, window=window,
        measured=size.tokens, safe_input=size.safe_input, force=force,
        allow_oversized_newest=True)
    report = None
    compacted = list(applied)
    sent_size = size.record()
    if pending is not None:
        yield compaction_frame(pending)
        compacted, report = await asyncio.to_thread(compaction.finish_compaction, pending)
        compacted = list(compacted)
        await asyncio.to_thread(
            compaction.record_compaction, report,
            username=request.username, session_id=request.session_id)
        before = size.tokens
        if report.status == "ok":
            size = await asyncio.to_thread(
                request_size.measure, system_text, schemas_json, compacted,
                model_id=context.model_id, window=window)
        sent_size = {**size.record(), "before_compaction": before}
    reductions = []
    pager = getattr(context, "result_pager", None)
    groups = compaction.step_groups(compacted)
    newest = groups[-1] if groups else []
    originals = {(m.thread_id, m.idx): m for m in rows}
    candidates = [index for index in newest if compacted[index].role == "tool"]
    budgets = {index: 24000 for index in candidates}
    while not size.fits and pager and candidates:
        index = max(candidates, key=lambda i: len(compacted[i].content.encode("utf-8")))
        message = compacted[index]
        original = originals.get((message.thread_id, message.idx), message)
        budget = min(budgets[index], max(1024, len(message.content.encode("utf-8")) // 2))
        result = await pager.ainvoke({"run_id": request.run_id,
            "call_id": str(message.tool_call_id), "content": original.content,
            "max_bytes": budget, "doc_refs": original.doc_refs})
        text = _text_of(result.content if isinstance(result, ToolMessage) else result)
        try:
            page = json.loads(text)
        except (ValueError, TypeError):
            page = {}
        if page.get("error") or isinstance(result, ToolMessage) and result.status == "error":
            raise RuntimeError(f"The complete tool result could not be paged: {text[:600]}")
        if not page.get("more") or len(text.encode("utf-8")) >= len(message.content.encode("utf-8")):
            candidates.remove(index)
            continue
        compacted[index] = message.model_copy(update={"content": text})
        reductions = [r for r in reductions if (r["thread_id"], r["idx"]) != (message.thread_id, message.idx)]
        reductions.append({"thread_id": message.thread_id, "idx": message.idx,
                           "tool_call_id": message.tool_call_id, "model_content": text})
        if budget <= 1024:
            candidates.remove(index)
        else:
            budgets[index] = max(1024, budget // 2)
        size = await asyncio.to_thread(request_size.measure, system_text, schemas_json,
            compacted, model_id=context.model_id, window=window)
    sent_size = {**sent_size, **size.record()}
    if not size.fits:
        error_class = compaction.CONTEXT_PREPARATION if report is not None and report.status != "ok" else compaction.CONTEXT_SIZE
        raise compaction.ContextError(error_class, (
            f"The next model request is {size.tokens:,} tokens ({size.method}), and the model "
            f"accepts {size.safe_input:,} tokens of input. "
            + ("The summary of the older steps failed. " if error_class == compaction.CONTEXT_PREPARATION
               else "The summary of the older steps did not make it fit. " if pending is not None
               else "No complete older step is left to summarise. ")
            + "The run stops. The transcript keeps every step."))
    yield Prepared(messages=compacted, size=sent_size, report=report, reductions=reductions)


async def _model_step_frames(agent: Any, request: ModelStepRequest) -> AsyncIterator[Dict[str, Any]]:
    context = await _context(agent, request)
    snapshot = context.snapshot
    thread = [m for m in list(request.earlier) + list(request.messages)
              if m.role != "compaction"]
    names = snapshot.callable_names()
    system_text = context.system_text_for(names)
    bound_tools = snapshot.tools_for()
    shown_tools = [shown_tool(t) for t in bound_tools]
    schemas_json = json.dumps([t["function"]["parameters"] for t in shown_tools], default=str)

    # What the compaction returns goes to the model only. The stored thread keeps every
    # tool result in full, and the `compaction` row of the reply records what was replaced.
    rows, applied = model_input_rows(request.earlier, request.messages)
    window = await asyncio.to_thread(compaction.context_window, context.model_id)

    llm: Any = ThinkingChatOpenAI(
        **context.llm_kwargs,
        streaming=llm_streaming_enabled(),
        disable_streaming=not llm_streaming_enabled(),
        extra_body=thinking_body(request),
    )
    llm = llm.bind_tools(shown_tools)
    config = _callbacks_config(agent, request)

    # A provider refusal of the size gives one more preparation, with the refreshed window
    # and a forced compaction. An identical request is not sent again.
    rejected: Optional[List[RunMessage]] = None
    for attempt in (0, 1):
        prepared: Optional[Prepared] = None
        async for item in _prepare(request, context, system_text, schemas_json, rows, applied,
                                   window, force=attempt > 0):
            if isinstance(item, Prepared):
                prepared = item
            else:
                yield item
        assert prepared is not None
        if rejected is not None and _same_request(prepared.messages, rejected):
            raise compaction.ContextError(compaction.CONTEXT_SIZE, (
                "The model provider refused the request as too large, and a new preparation "
                "gave the same request. The run stops. The transcript keeps every step."))
        compacted, report, sent_size = prepared.messages, prepared.report, prepared.size
        model_input = [SystemMessage(content=system_text)] + to_langchain(compacted)

        timer = llm_events.CallTimer()
        message: Any = None
        started = False
        try:
            if llm_streaming_enabled():
                async for chunk in llm.astream(model_input, config or None):
                    # A client with no stream of its own sends one whole `AIMessage`.
                    if not isinstance(chunk, AIMessage):
                        continue
                    started = True
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
                started = True
                reasoning = _reasoning(message)
                if reasoning:
                    yield {"type": "reasoning", "content": reasoning}
                text = _text(message.content)
                if text:
                    yield {"type": "response", "content": text}
        except Exception as exc:
            stated = compaction.size_refusal(_provider_status(exc), str(exc))
            if started or attempt > 0 or stated is None:
                raise
            log.warning("the provider refused the request of run %s step %s as too large: "
                        "%s", request.run_id, request.step_no, exc)
            compaction.forget_window(context.model_id)
            window = await asyncio.to_thread(compaction.context_window, context.model_id)
            if stated and (window <= 0 or stated < window):
                window = stated
            rejected = compacted
            continue
        break
    latency_ms = timer.elapsed_ms()

    calls = [
        {"id": c.get("id"), "name": c.get("name"), "args": c.get("args")}
        for c in (getattr(message, "tool_calls", None) or [])
    ] + [unreadable_call(c) for c in (getattr(message, "invalid_tool_calls", None) or [])]
    if not calls:
        # A reply whose text is call syntax is not an answer. The model reads why the
        # call did not run and writes it again.
        leaked = leaked_call(_text(message.content))
        if leaked is not None:
            calls = [leaked]
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
            "citation_tool": any(getattr(t, "name", "") in ("cite_documents", "cite_pages")
                                 for t in bound_tools),
        },
        # True when a summary replaced older steps. A failed summary changes no message.
        "summarised": report is not None and report.status == "ok",
        "compaction": compaction_record(report) if report is not None else None,
        "reductions": prepared.reductions,
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

    if request.call.argument_error:
        return _tool_response(request, _error(
            "invalid_arguments",
            "The call was not run, because the arguments could not be read as JSON: "
            f"{request.call.argument_error} Send the call again, with each argument as plain "
            "JSON.", tool=name,
        ), "error", "invalid_arguments")

    if name not in allowed:
        return _tool_response(request, _error(
            "tool_unavailable", f"No tool of this run is named {name!r}. "
            f"Find tools with {SEARCH_TOOL}.", tool=name,
        ), "error", "tool_unavailable")

    tool = snapshot.tools_by_name[name]
    schema = tool_schema(tool)
    normalized = normalize_arguments(dict(request.call.args or {}), schema)
    repairs = normalized.repairs
    if normalized.problem:
        log.info("tool %s: damaged arguments: %s", name, normalized.problem)
        return _tool_response(
            request, _error("invalid_arguments", normalized.problem, tool=name), "error",
            "invalid_arguments")
    if repairs:
        log.info("tool %s: %d argument repairs: %s", name, len(repairs), "; ".join(repairs))
    args = normalized.args
    problem = validation_error(args, schema)
    if problem:
        return _tool_response(
            request, _error("invalid_arguments", problem, tool=name), "error", "invalid_arguments",
            _with_repairs(None, repairs),
        )

    if name.startswith(("search_", "read_documents", "doc_", "table_", "folder_", "list_document_")):
        rows, visible = model_input_rows(request.earlier, request.messages)
        whole = {(m.thread_id, m.idx) for m in visible if m.role == "tool" and m.status == "ok"
                 and any(r.thread_id == m.thread_id and r.idx == m.idx and r.content == m.content
                         for r in rows)}
        answers = {m.tool_call_id: m for m in rows if m.role == "tool"
                   and (m.thread_id, m.idx) in whole}
        for message in rows:
            if message.role != "ai":
                continue
            for call in message.tool_calls:
                if (call.name == name and call.id in answers
                        and normalize_arguments(call.args, schema).args == args):
                    return _tool_response(request, f"This call repeats call {call.id}. Its result is above.", "ok")

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


#: The measure key that lists the argument changes that `/tool_call` made
#: (`tool_args.normalize_arguments`). A call that `/model_step` normalized holds its changes
#: in its stored call entry (`CallEntry.argument_repairs`), and `/tool_call` finds none.
ARGUMENT_REPAIRS_KEY = "argument_repairs"


def _with_repairs(measure: Optional[Dict[str, Any]], repairs: List[str]) -> Optional[Dict[str, Any]]:
    """The measure of a call with its argument repairs added. A call with no repair keeps
    its measure as it was."""
    if not repairs:
        return measure
    return {**(measure or {}), ARGUMENT_REPAIRS_KEY: list(repairs)}


__all__ = [
    "BROWSER_READS", "CallEntry", "KEEPALIVE_LINE", "KEEPALIVE_SECONDS", "ModelStepRequest",
    "StepRun", "ToolCallRequest",
    "build_model_input", "call_ids", "classify_calls", "compaction_frame",
    "compaction_record", "model_input_rows",
    "classify_error", "llm_streaming_enabled", "retries", "run_model_step", "run_tool_call",
    "shown_tool", "unreadable_call",
    "stream_frames", "thinking_body",
]
