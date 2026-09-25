"""The execution node: it runs the tool calls of one model turn.

It replaces langgraph's `ToolNode` in the lead's graph and in the in-process worker graph.
For each call of the last model turn it does these steps:

1. It sends a `tool_start` event.
2. It refuses a name outside `core_names + bound_names` with a `tool_unavailable` error. The
   model node binds the same names from the same state value, so a refused call is a name
   the model was not given.
3. It decodes JSON-string arguments against the tool's schema (`tool_args.py`), and then
   validates the arguments against that schema.
4. It runs the tool. A call that raises becomes an error `ToolMessage`, so the model reads
   the error and the thread keeps one result for each call.
5. It sends a `tool_result` event with `status` `ok` or `error`.

Plan mutations run one after the other in call order. Every other call runs in parallel, as
`ToolNode` ran them. After the batch, the bind step sets `bound_names` from the
`search_agent_tools` results of the batch. Nothing else changes `bound_names`.

**The batch result budget.** The result pages of all calls of one model turn share one
budget (`batch_budget`). The node reserves the empty page of every call first, then divides
the rest equally, and sends each call its share in the `X-Hoover4-Page-Share` header
(`page_share_client`). The collection server's page broker sizes each page within that
share before it serializes the page, a later page of a stored window included, so no page
is cut after it leaves the broker.

- Safe mode is the default. One batch receives `SAFE_MODE_BATCH_BYTES` UTF-8 bytes, or less
  when the request bytes plus the completion reserve leave less of the context window.
- Token mode runs only when `AGENT_MAX_PAGE_TOKENS` and `AGENT_COMPLETION_RESERVE_TOKENS`
  are both set and the served model's context window is known. It counts the request and
  the empty pages with the served tokenizer and applies `allocate`. The share it sends is a
  byte count equal to the token share, because a token covers at least one byte. A failed
  count falls back to safe mode.

**The call measure.** The broker adds the `PageMeasure` of the page it returned as an
embedded resource beside the page text, and the MCP adapter puts that block in the tool
message artifact. The node takes it out of the artifact, adds the share and the mode, and
puts it in the `tool_result` event and in the tool message's `response_metadata` under
`call_measure`. The model never reads it.

**The calls it runs.** The node runs the calls of the last `ai` message that have no `tool`
message after it. For a new model turn that is every call. A retry whose stored thread ends
with some calls unanswered starts the graph at this node, so it runs only the missing calls.

**The stop at `run_subagent`.** With `stop_at_delegation` true, which is the `/run/stream`
graph, a `run_subagent` call does not run in process. The node runs every other call of the
turn first, with the batch budget. It then sends a `tool_start` and one `delegate` event for
each `run_subagent` call, in call order, and sets `delegated` in the state, so the graph ends.
The thread keeps the `ai` message with those calls and no `tool` message for them. The worker
writes the sub-agent runs, and the continuation adds their results. A `run_subagent` call
whose briefings cannot be read gets an `invalid_arguments` result and does not delegate.

The events are langchain custom events, so `agent.stream` receives them from
`astream_events` as `on_custom_event` with the event type as the name.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import math
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

import jsonschema
from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from mcp.shared._httpx_utils import create_mcp_http_client

from agent_common.result_pages import (
    SAFE_MODE_BATCH_BYTES, ByteLimit, PageInput, TokenCounter, allocate, build_page,
)
from research_agent import compaction

from research_agent.tool_args import decode_string_arguments
from research_agent.tool_catalogue import (
    SEARCH_TOOL,
    CatalogueSnapshot,
    bind_names,
    matched_names,
    tool_schema,
)

log = logging.getLogger(__name__)

#: The plan mutations. They run one after the other in call order, because each one
#: changes the tree that the next one reads.
PLAN_MUTATIONS = frozenset({"append_node", "append_child", "move_node", "edit_node", "remove_node"})

TOOL_START = "tool_start"
TOOL_RESULT = "tool_result"
MODEL_TURN = "model_turn"
DELEGATE = "delegate"

#: The delegation tool. On the `/run/stream` graph the node stops at it.
DELEGATION_TOOL = "run_subagent"

#: The request header that carries one call's page share to the page broker.
PAGE_SHARE_HEADER = "X-Hoover4-Page-Share"
#: The URI of the embedded resource in which the broker returns the call measure.
CALL_MEASURE_URI = "hoover4://call-measure"
#: The completion reserve of safe mode when `AGENT_COMPLETION_RESERVE_TOKENS` is not set.
SAFE_MODE_COMPLETION_RESERVE = 8192
#: The `total_units` and artifact id with which the empty page of a call is measured. They
#: are the largest values a real empty page carries, so the reserve is never too small.
_EMPTY_PAGE_TOTAL = 10**15
_EMPTY_PAGE_ARTIFACT = "00000000-0000-0000-0000-000000000000"


def _positive_env(name: str) -> Optional[int]:
    """Read a positive integer setting. Unset or empty is `None`. Any other value that is
    not a positive integer raises, so a wrong setting stops the service at import."""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{name} is {value}, and it must be a positive integer")
    return value


#: The largest content share of one result page in token mode. Unset keeps safe mode.
MAX_PAGE_TOKENS = _positive_env("AGENT_MAX_PAGE_TOKENS")
#: The completion allowance `R` of the allocation. Unset keeps safe mode.
COMPLETION_RESERVE_TOKENS = _positive_env("AGENT_COMPLETION_RESERVE_TOKENS")

#: The page share of the tool call that runs in the current task, in bytes.
_PAGE_SHARE: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar("page_share", default=None)


def page_share_client(
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[httpx.Timeout] = None,
    auth: Optional[httpx.Auth] = None,
) -> httpx.AsyncClient:
    """The MCP HTTP client factory of the agent's connections. It adds the page share of
    the current call as `X-Hoover4-Page-Share`. The adapter opens one session for each
    tool call inside the call's task, so the share it reads is the share of that call."""
    share = _PAGE_SHARE.get()
    merged = dict(headers or {})
    if share is not None:
        merged[PAGE_SHARE_HEADER] = str(share)
    return create_mcp_http_client(headers=merged, timeout=timeout, auth=auth)


def empty_page_text(tool_name: str) -> str:
    """The smallest zero-content page of one call: the `budget_exhausted` page that
    `build_page` returns when not one unit fits."""
    text, _ = build_page(
        PageInput(tool_name, "table", [None], None, _EMPTY_PAGE_TOTAL, {}, "", {},
                  _EMPTY_PAGE_ARTIFACT, lambda count: None),
        ByteLimit(1),
    )
    return text


@dataclass(frozen=True)
class BatchBudget:
    """The page share of each call of one batch, in bytes, in call order.

    `mode` is `bytes` (safe mode) or `tokens`. `exhausted` is true when not even the empty
    pages and the completion reserve fit, and then no call runs.
    """

    mode: str
    shares: Tuple[int, ...]
    total: int
    counter: Optional[TokenCounter] = None
    exhausted: bool = False


def _request_text(messages: Sequence[Any]) -> str:
    return "\n".join(_text_of(getattr(m, "content", "")) for m in messages)


def _last_billed(messages: Sequence[Any]) -> int:
    for message in reversed(messages):
        usage = getattr(message, "usage_metadata", None)
        if usage:
            return int(usage.get("total_tokens") or 0)
    return 0


def _read_api_key() -> str:
    value = (os.getenv("LLM_API_KEY") or "").strip()
    path = (os.getenv("LLM_API_KEY_FILE") or "").strip()
    if not value and path and os.path.exists(path):
        with open(path) as handle:
            value = handle.read().strip()
    return value


def safe_budget(
    names: Sequence[str], request_bytes: int, window: int, reserve: int,
    batch_bytes: int = SAFE_MODE_BATCH_BYTES,
) -> BatchBudget:
    """The byte budget of one batch. The batch receives `batch_bytes`, cut to what the
    request bytes plus `reserve` leave of the context window when the window is known.
    The empty page of every call is reserved first, and the rest is divided equally."""
    empty = [len(empty_page_text(name).encode("utf-8")) for name in names]
    total = batch_bytes
    if window > 0:
        total = min(total, max(0, window - reserve - request_bytes))
    spare = max(0, total - sum(empty))
    return BatchBudget("bytes", tuple(e + spare // len(names) for e in empty), total)


def token_budget(
    names: Sequence[str], messages: Sequence[Any], window: int, counter: TokenCounter,
    reserve: int, max_page_tokens: int, fraction: Optional[float] = None,
) -> BatchBudget:
    """The token budget of one batch, from `allocate`. Each share is the empty page plus
    its content share. It raises `TokenCountFailed` when a count fails."""
    threshold = compaction.threshold_tokens(window, fraction)
    empty = [counter.count(empty_page_text(name)) for name in names]
    fixed = max(_last_billed(messages), counter.count(_request_text(messages)))
    shares = allocate(fixed, empty, threshold, reserve, max_page_tokens)
    if shares is None:
        return BatchBudget("tokens", tuple(empty), sum(empty), counter, exhausted=True)
    pages = tuple(e + s for e, s in zip(empty, shares))
    return BatchBudget("tokens", pages, sum(pages), counter)


def batch_budget(names: Sequence[str], messages: Sequence[Any]) -> BatchBudget:
    """The budget of one batch: token mode when the settings and the model permit it,
    and safe mode otherwise."""
    model = (os.getenv("LLM_MODEL") or "").strip()
    window = compaction.context_window(model) if model else 0
    reserve = COMPLETION_RESERVE_TOKENS or SAFE_MODE_COMPLETION_RESERVE
    if MAX_PAGE_TOKENS and COMPLETION_RESERVE_TOKENS and window > 0:
        counter = TokenCounter(os.getenv("LLM_BASE_URL") or "", model, _read_api_key() or None)
        try:
            return token_budget(names, messages, window, counter, reserve, MAX_PAGE_TOKENS)
        except Exception as exc:  # noqa: BLE001 - every count failure keeps safe mode
            log.warning("token count failed, the batch uses safe mode: %s", exc)
    request_bytes = len(_request_text(messages).encode("utf-8"))
    return safe_budget(names, request_bytes, window, reserve)


def split_measure(artifact: Any) -> Tuple[Optional[Dict[str, Any]], Any]:
    """Take the broker's call measure out of a tool message artifact. Return the measure,
    or `None`, and the artifact without it, or `None` when nothing else is left."""
    if not isinstance(artifact, list):
        return None, artifact
    measure = None
    rest = []
    for block in artifact:
        resource = getattr(block, "resource", None)
        if measure is None and resource is not None and str(getattr(resource, "uri", "")) == CALL_MEASURE_URI:
            try:
                measure = json.loads(getattr(resource, "text", "") or "")
            except ValueError:
                measure = None
            if isinstance(measure, dict):
                continue
            measure = None
        rest.append(block)
    return measure, (rest or None)


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list) and all(
        isinstance(p, dict) and p.get("type") == "text" for p in content
    ):
        return "".join(p.get("text", "") for p in content)
    return json.dumps(content, default=str)


def _error(code: str, message: str, **extra: Any) -> str:
    return json.dumps({"success": False, "error": code, "message": message, **extra})


def validation_error(args: Dict[str, Any], schema: dict) -> Optional[str]:
    """Return the first reason the arguments do not match the schema, or `None`."""
    if not schema:
        return None
    try:
        jsonschema.validate(args, schema)
    except jsonschema.ValidationError as exc:
        where = "/".join(str(p) for p in exc.absolute_path) or "arguments"
        return f"{where}: {exc.message}"
    except jsonschema.SchemaError:
        return None
    return None


async def _emit(name: str, data: Dict[str, Any], config: Optional[RunnableConfig]) -> None:
    try:
        await adispatch_custom_event(name, data, config=config)
    except RuntimeError:
        # No parent run to attach the event to, which is the case for a direct call in a
        # test. The event has no reader then.
        pass


def pending_calls(messages: Sequence[Any]) -> Tuple[List[Dict[str, Any]], int]:
    """The calls of the last `ai` message that have no `tool` message after it, in call
    order, and the position of that `ai` message. `([], -1)` when the thread ends with no
    unanswered call."""
    answered = set()
    for position in range(len(messages) - 1, -1, -1):
        message = messages[position]
        if isinstance(message, ToolMessage):
            answered.add(message.tool_call_id)
            continue
        calls = list(getattr(message, "tool_calls", None) or [])
        missing = [c for c in calls if (c.get("id") or "") not in answered]
        return (missing, position) if missing else ([], -1)
    return [], -1


def _briefings_of(args: Any) -> Optional[List[Dict[str, Any]]]:
    """The briefings of one `run_subagent` call as dicts, or `None` when they cannot be
    read. The same coercion as the in-process tool."""
    from research_agent.subagents import _as_briefings

    raw = args.get("tasks") if isinstance(args, dict) else None
    briefings = _as_briefings(raw)
    if not briefings:
        return None
    return [b.model_dump() for b in briefings]


def make_execution_node(
    snapshot: CatalogueSnapshot, emit_events: bool = True, stop_at_delegation: bool = False,
):
    """Return the execution node of a graph over one catalogue snapshot.

    `emit_events` false sends no `tool_start` or `tool_result` event. The in-process worker
    graph sets it, because its calls are not calls of the run that streams the events.
    `stop_at_delegation` true ends the run at a `run_subagent` call (module docstring).
    """

    async def emit(name: str, data: Dict[str, Any], config: Optional[RunnableConfig]) -> None:
        if emit_events:
            await _emit(name, data, config)

    async def execute(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
        messages = state["messages"]
        calls, _ = pending_calls(messages)
        bound = tuple(state.get("bound_names") or ())
        allowed = set(snapshot.callable_names(bound))
        base_index = len(messages) - int(state.get("thread_offset") or 0)
        delegations: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
        if stop_at_delegation and DELEGATION_TOOL in allowed:
            kept = []
            for call in calls:
                briefings = (
                    _briefings_of(call.get("args")) if call.get("name") == DELEGATION_TOOL else None
                )
                if briefings is None:
                    kept.append(call)
                else:
                    delegations.append((call, briefings))
            calls = kept
        budget = (
            await asyncio.to_thread(batch_budget, [c.get("name") or "" for c in calls], messages)
            if calls else None
        )
        if budget is not None and budget.exhausted:
            log.warning("the empty pages of %d calls and the completion reserve do not fit", len(calls))

        async def run_one(position: int, call: Dict[str, Any]) -> ToolMessage:
            name = call.get("name") or ""
            call_id = call.get("id") or ""
            args = call.get("args") or {}
            index = base_index + position
            await emit(
                TOOL_START,
                {"index": index, "tool_call_id": call_id, "name": name, "args": args},
                config,
            )
            status = "ok"
            artifact = None
            measure = None
            share = budget.shares[position] if budget is not None else None
            _PAGE_SHARE.set(share)
            if budget is not None and budget.exhausted:
                status = "error"
                content = empty_page_text(name)
            elif stop_at_delegation and name == DELEGATION_TOOL and name in allowed:
                status = "error"
                content = _error(
                    "invalid_arguments",
                    "tasks must be a list of 1 to 5 briefings, each with an objective",
                    tool=name,
                )
            elif name not in allowed:
                status = "error"
                content = _error(
                    "tool_unavailable",
                    f"The tool {name!r} is not available in this run. Call only the tools "
                    f"you were given, or find more with {SEARCH_TOOL}.",
                    tool=name,
                )
            else:
                tool = snapshot.tools_by_name[name]
                schema = tool_schema(tool)
                args = decode_string_arguments(args, schema)
                problem = validation_error(args, schema)
                if problem:
                    status = "error"
                    content = _error("invalid_arguments", problem, tool=name)
                else:
                    try:
                        result = await tool.ainvoke(
                            {"type": "tool_call", "id": call_id, "name": name, "args": args},
                            config,
                        )
                    except Exception as exc:  # noqa: BLE001 - the model reads the error
                        log.warning("tool %s raised: %s", name, exc)
                        status = "error"
                        content = f"Error: {exc}"
                    else:
                        if isinstance(result, ToolMessage):
                            content = _text_of(result.content)
                            measure, artifact = split_measure(result.artifact)
                            if result.status == "error":
                                status = "error"
                        else:
                            content = _text_of(result)
            if measure is not None:
                measure["budget_mode"] = budget.mode if budget is not None else "bytes"
                measure["batch_total"] = budget.total if budget is not None else None
                if budget is not None and budget.counter is not None and measure.get("page_tokens") is None:
                    try:
                        measure["page_tokens"] = await asyncio.to_thread(budget.counter.count, content)
                    except Exception as exc:  # noqa: BLE001 - the measure keeps no count
                        log.warning("could not count the page tokens of %s: %s", name, exc)
            message = ToolMessage(
                content=content,
                tool_call_id=call_id,
                name=name,
                status="error" if status == "error" else "success",
                artifact=artifact,
                response_metadata={"call_measure": measure} if measure is not None else {},
            )
            await emit(
                TOOL_RESULT,
                {
                    "index": index,
                    "tool_call_id": call_id,
                    "name": name,
                    "content": content,
                    "measure": measure,
                    "status": status,
                },
                config,
            )
            return message

        ordered = [(i, c) for i, c in enumerate(calls) if c.get("name") in PLAN_MUTATIONS]
        parallel = [(i, c) for i, c in enumerate(calls) if c.get("name") not in PLAN_MUTATIONS]

        async def run_in_order() -> List[Tuple[int, ToolMessage]]:
            return [(i, await run_one(i, c)) for i, c in ordered]

        async def run_indexed(i: int, c: Dict[str, Any]) -> List[Tuple[int, ToolMessage]]:
            return [(i, await run_one(i, c))]

        groups = await asyncio.gather(
            run_in_order(), *(run_indexed(i, c) for i, c in parallel)
        )
        results = sorted((pair for group in groups for pair in group), key=lambda p: p[0])
        out = [message for _, message in results]

        newest: List[str] = []
        for call, message in zip(calls, out):
            if call.get("name") == SEARCH_TOOL and message.status != "error":
                newest.extend(matched_names(message.content))
        update: Dict[str, Any] = {"messages": out, "bound_names": bind_names(snapshot, bound, newest)}
        if delegations:
            # The continuation writes the results of these calls at the next indexes.
            index = base_index + len(out)
            for position, (call, briefings) in enumerate(delegations):
                event = {
                    "index": index + position,
                    "tool_call_id": call.get("id") or "",
                    "name": DELEGATION_TOOL,
                    "args": call.get("args") or {},
                }
                await emit(TOOL_START, event, config)
            for position, (call, briefings) in enumerate(delegations):
                await emit(
                    DELEGATE,
                    {"index": index + position, "tool_call_id": call.get("id") or "",
                     "briefings": briefings},
                    config,
                )
            update["delegated"] = True
        return update

    return execute


def model_turn_event(index: int, message: Any) -> Dict[str, Any]:
    """Return the content of a `model_turn` event for one model reply."""
    content = getattr(message, "content", "") or ""
    if isinstance(content, list):
        content = "".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
        )
    extra = getattr(message, "additional_kwargs", None) or {}
    reasoning = extra.get("reasoning_content") or ""
    usage = getattr(message, "usage_metadata", None) or {}
    return {
        "index": index,
        "text": content,
        "reasoning": reasoning if isinstance(reasoning, str) else json.dumps(reasoning),
        "tool_calls": [
            {"id": c.get("id"), "name": c.get("name"), "args": c.get("args")}
            for c in (getattr(message, "tool_calls", None) or [])
        ],
        "usage": {
            k: int(usage.get(k) or 0)
            for k in ("input_tokens", "output_tokens", "total_tokens")
        },
    }


__all__ = [
    "BatchBudget", "DELEGATE", "DELEGATION_TOOL", "MODEL_TURN", "PAGE_SHARE_HEADER", "PLAN_MUTATIONS", "TOOL_RESULT",
    "TOOL_START", "batch_budget", "empty_page_text", "make_execution_node", "model_turn_event",
    "page_share_client", "pending_calls", "safe_budget", "split_measure", "token_budget", "validation_error",
]
