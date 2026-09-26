"""The parts of a tool call that do not depend on one request: the batch result budget,
the MCP client factory, the call measure and the argument check.

`/tool_call` (`steps.py`) runs one tool call with them, and `/model_step` computes the page
share of each call of a reply with `batch_budget`. Plan mutations (`PLAN_MUTATIONS`) must
run one after the other in call order, because each one changes the tree that the next one
reads. The worker keeps that order. Every other call can run in parallel.

**The batch result budget.** The result pages of all calls of one model reply share one
budget (`batch_budget`). The empty page of every call is reserved first, and the rest is
divided equally. Each call sends its share in the `X-Hoover4-Page-Share` header
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

**The idempotency key.** `page_share_client` also sends the key of the current call as
`X-Hoover4-Idempotency-Key`. The plan server returns the stored result for a key it has, so
a retried plan mutation changes the tree once.

**The call measure.** The broker adds the `PageMeasure` of the page it returned as an
embedded resource beside the page text, and the MCP adapter puts that block in the tool
message artifact. `split_measure` takes it out of the artifact, and `/tool_call` returns it
beside the result. The model never reads it.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

import jsonschema
from langchain_core.messages import ToolMessage
from mcp.shared._httpx_utils import create_mcp_http_client

from agent_common.result_pages import (
    SAFE_MODE_BATCH_BYTES, ByteLimit, PageInput, TokenCounter, allocate, build_page,
)
from research_agent import compaction

log = logging.getLogger(__name__)

#: The plan mutations. They run one after the other in call order, because each one
#: changes the tree that the next one reads.
PLAN_MUTATIONS = frozenset({"append_node", "append_child", "move_node", "edit_node", "remove_node"})

#: The delegation tool. The worker delegates a readable call, and `/tool_call` refuses it.
DELEGATION_TOOL = "run_subagent"

#: The request header that carries one call's page share to the page broker.
PAGE_SHARE_HEADER = "X-Hoover4-Page-Share"
#: The request header that carries one call's idempotency key to the MCP server.
IDEMPOTENCY_HEADER = "X-Hoover4-Idempotency-Key"
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
#: The idempotency key of the tool call that runs in the current task.
_IDEMPOTENCY_KEY: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "idempotency_key", default=None
)


def page_share_client(
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[httpx.Timeout] = None,
    auth: Optional[httpx.Auth] = None,
) -> httpx.AsyncClient:
    """The MCP HTTP client factory of the agent's connections. It adds the page share of
    the current call as `X-Hoover4-Page-Share`, and its idempotency key as
    `X-Hoover4-Idempotency-Key`, when they are set. The adapter opens one session for each
    tool call inside the call's task, so the values it reads are those of that call."""
    share = _PAGE_SHARE.get()
    key = _IDEMPOTENCY_KEY.get()
    merged = dict(headers or {})
    if share is not None:
        merged[PAGE_SHARE_HEADER] = str(share)
    if key:
        merged[IDEMPOTENCY_HEADER] = key
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


__all__ = [
    "BatchBudget", "DELEGATION_TOOL", "IDEMPOTENCY_HEADER", "PAGE_SHARE_HEADER", "PLAN_MUTATIONS",
    "batch_budget", "empty_page_text", "page_share_client", "pending_calls", "safe_budget",
    "split_measure", "token_budget", "validation_error",
]
