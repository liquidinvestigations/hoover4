"""The parts of a tool call that do not depend on one request: the batch result budget,
the MCP client factory, the call measure and the argument check.

`/tool_call` (`steps.py`) runs one tool call with them, and `/model_step` computes the page
share of each call of a reply with `batch_budget`. The todo tools
(`ORDERED_TOOLS`) must run one after the other in call order, because each one reads or
changes the state that the next one reads. The worker keeps that order, and it also runs the
calls of one browser session in call order. Every other call can run in parallel.

**The batch result budget.** The result pages of all calls of one model reply share
`SAFE_MODE_BATCH_BYTES` UTF-8 bytes (`batch_budget`). The empty page of every call is
reserved first, and the rest is divided into equal parts. The count of calls and the size of
their empty pages set the shares. The length of the conversation does not: a tool call always
runs, and the next model request is sized after its result is stored (`request_size.py`).
When the empty pages alone pass the batch target, each call keeps its empty page and no
content share, and the page broker returns its next unit through a stored window. Each call
sends its share in the `X-Hoover4-Page-Share` header (`page_share_client`). The collection
server's page broker sizes each page within that share, and it divides the share of a call
that reads several documents among those documents.

**The idempotency key.** `page_share_client` also sends the key of the current call as
`X-Hoover4-Idempotency-Key`. The plan server returns the stored result for a key it has, so
a retried plan mutation changes the tree once.

**The call measure.** The broker adds the `PageMeasure` of the page it returned as an
embedded resource beside the page text, and the MCP adapter puts that block in the tool
message artifact. `split_resources` takes it out of the artifact, and `/tool_call` returns
it beside the result. The broker also adds the doc refs, the whole identity of each row of
the page, as a second embedded resource. `/tool_call` returns them as `doc_refs`. The model
reads neither.
"""

from __future__ import annotations

import contextvars
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

import jsonschema
from langchain_core.messages import ToolMessage
from mcp.shared._httpx_utils import create_mcp_http_client

from agent_common.result_pages import SAFE_MODE_BATCH_BYTES, ByteLimit, PageInput, build_page

log = logging.getLogger(__name__)

#: The calls that the worker runs in reply order, in one chain: the todo tools, because each
#: one reads or changes state that the next one reads.
#: `/model_step` gives them the kind `ordered`. The worker's copy is `STATE_TOOLS` in
#: `processing/tasks/P_agent/steps.py`, and the two lists change in one patch.
ORDERED_TOOLS = frozenset({"write_todo", "edit_todo", "mark_todo", "read_todo"})

#: The browser server's own tool, and the name prefix of every tool it routes to the
#: browser (`BROWSER_EXPOSED_TOOLS` chooses which of them it lists).
BROWSER_READ_TOOL = "read_page"
BROWSER_TOOL_PREFIX = "browser_"


def is_browser_tool(name: str) -> bool:
    """Whether a tool drives the run's one browser: `read_page` and every `browser_` tool
    of the browser server, whichever of them the server lists. A later call reads the page
    that an earlier call left, so the worker runs the calls of one reply to these tools one
    after the other in call order. Its copy is `is_browser_tool` in
    `processing/tasks/P_agent/steps.py`, and the two change in one patch."""
    return name == BROWSER_READ_TOOL or name.startswith(BROWSER_TOOL_PREFIX)

#: The request header that carries one call's page share to the page broker.
PAGE_SHARE_HEADER = "X-Hoover4-Page-Share"
#: The URI of the embedded resource in which the broker returns the call measure.
CALL_MEASURE_URI = "hoover4://call-measure"
#: The URI of the embedded resource in which the broker returns the doc refs of a page.
DOC_REFS_URI = "hoover4://doc-refs"
#: The `total_units` and artifact id with which the empty page of a call is measured. They
#: are the largest values a real empty page carries, so the reserve is never too small.
_EMPTY_PAGE_TOTAL = 10**15
_EMPTY_PAGE_ARTIFACT = "00000000-0000-0000-0000-000000000000"


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
    the current call as `X-Hoover4-Page-Share` when it is set. The adapter opens one session for each
    tool call inside the call's task, so the values it reads are those of that call."""
    share = _PAGE_SHARE.get()
    merged = dict(headers or {})
    if share is not None:
        merged[PAGE_SHARE_HEADER] = str(share)
    return create_mcp_http_client(headers=merged, timeout=timeout, auth=auth)


def empty_page_text(tool_name: str) -> str:
    """The smallest zero-content page of one call: the page that `build_page` returns when
    not one unit fits."""
    text, _ = build_page(
        PageInput(tool_name, "table", [None], None, _EMPTY_PAGE_TOTAL, {}, "", {},
                  _EMPTY_PAGE_ARTIFACT, lambda count: None),
        ByteLimit(1),
    )
    return text


@dataclass(frozen=True)
class BatchBudget:
    """The page share of each call of one batch, in bytes, in call order. `total` is the
    sum of the shares. It passes `SAFE_MODE_BATCH_BYTES` only when the empty pages of the
    calls do."""

    shares: Tuple[int, ...]
    total: int


def batch_budget(names: Sequence[str], batch_bytes: int = SAFE_MODE_BATCH_BYTES) -> BatchBudget:
    """The byte share of each call of one batch.

    Each call gets its empty page, and an equal part of what the empty pages leave of
    `batch_bytes`. The result depends on the tool names only.
    """
    empty = [len(empty_page_text(name).encode("utf-8")) for name in names]
    if not empty:
        return BatchBudget((), 0)
    content = max(0, batch_bytes - sum(empty)) // len(empty)
    shares = tuple(size + content for size in empty)
    return BatchBudget(shares, sum(shares))


def split_resources(artifact: Any) -> Tuple[Optional[Dict[str, Any]], Optional[List[Dict[str, Any]]], Any]:
    """Take the broker's call measure and doc refs out of a tool message artifact. Return
    the measure or `None`, the doc refs or `None`, and the artifact without them, or `None`
    when nothing else is left."""
    if not isinstance(artifact, list):
        return None, None, artifact
    measure = None
    doc_refs = None
    rest = []
    for block in artifact:
        resource = getattr(block, "resource", None)
        uri = str(getattr(resource, "uri", "")) if resource is not None else ""
        if uri in (CALL_MEASURE_URI, DOC_REFS_URI):
            try:
                value = json.loads(getattr(resource, "text", "") or "")
            except ValueError:
                value = None
            if uri == CALL_MEASURE_URI and measure is None and isinstance(value, dict):
                measure = value
                continue
            if uri == DOC_REFS_URI and doc_refs is None and isinstance(value, list):
                doc_refs = value
                continue
        rest.append(block)
    return measure, doc_refs, (rest or None)


def _text_of(content: Any) -> str:
    """The text of a tool result as the model reads it. The MCP adapter gives a result of
    several text blocks as a list of strings, and the blocks are joined with a newline, so
    the model reads the bytes that the server measured against its page share. A JSON
    encoding of the list would escape each newline, quote and non-ASCII character."""
    if isinstance(content, str):
        return content
    if isinstance(content, list) and content and all(isinstance(p, str) for p in content):
        return "\n".join(content)
    if isinstance(content, list) and all(
        isinstance(p, dict) and p.get("type") == "text" for p in content
    ):
        return "".join(p.get("text", "") for p in content)
    return json.dumps(content, default=str)


def _error(code: str, message: str, **extra: Any) -> str:
    return json.dumps({"success": False, "error": code, "message": message, **extra})


#: The most problems that one `invalid_arguments` message names.
MAX_PROBLEMS = 4
#: The most characters of one value that a problem quotes.
QUOTE_CHARS = 120


def _where(path: Sequence[Any]) -> str:
    return "/".join(str(p) for p in path) or "arguments"


def _clip(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= QUOTE_CHARS else text[:QUOTE_CHARS] + "..."


def _json_kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, list):
        return f"a list of {len(value)} item{'s' if len(value) != 1 else ''}"
    if isinstance(value, dict):
        return "an object"
    return type(value).__name__


def _branch_errors(error: Any) -> List[Any]:
    """The errors of the branch of a choice that the value's type matches, or the whole
    choice error when no branch matches it."""
    by_branch: Dict[Any, List[Any]] = {}
    for sub in error.context or []:
        by_branch.setdefault(sub.schema_path[0] if sub.schema_path else None, []).append(sub)
    path = list(error.absolute_path)
    for branch, errors in sorted(by_branch.items(), key=lambda item: str(item[0])):
        if not any(e.validator == "type" and list(e.absolute_path) == path for e in errors):
            return errors
    return [error]


def _problems(error: Any) -> List[str]:
    """One sentence for each problem that one validation error holds."""
    where = _where(error.absolute_path)
    if error.validator in ("anyOf", "oneOf") and error.context:
        chosen = _branch_errors(error)
        if chosen != [error]:
            out: List[str] = []
            for sub in chosen:
                out.extend(_problems(sub))
            return out
        types = sorted({str(sub.validator_value) for sub in error.context
                        if sub.validator == "type"})
        return [f"{where}: expects {' or '.join(types) or 'another value'}, and the call "
                f"gave {_json_kind(error.instance)}."]
    if error.validator == "type":
        expected = error.validator_value
        expected = " or ".join(expected) if isinstance(expected, list) else str(expected)
        if isinstance(error.instance, list) and expected in ("string", "integer", "number", "boolean"):
            return [f"{where}: takes one {expected} value, and the call gave "
                    f"{_json_kind(error.instance)}. Send one value."]
        return [f"{where}: expects {expected}, and the call gave "
                f"{_json_kind(error.instance)} {_clip(error.instance)}."]
    if error.validator == "required":
        out = [f"{where}: {error.message}."]
        properties = (error.schema or {}).get("properties") if isinstance(error.schema, dict) else None
        if isinstance(error.instance, dict) and isinstance(properties, dict):
            unknown = [k for k in error.instance if k not in properties]
            if unknown:
                out.append(f"{where}: the call gave {', '.join(repr(k) for k in unknown)}, "
                           f"which the schema does not name. The schema names "
                           f"{', '.join(properties)}.")
        return out
    if error.validator in ("minItems", "maxItems"):
        bound = "at least" if error.validator == "minItems" else "at most"
        unit = "item" if error.validator_value == 1 else "items"
        given = "item" if len(error.instance) == 1 else "items"
        return [f"{where}: accepts {bound} {error.validator_value} {unit}. "
                f"The call gave {len(error.instance)} {given}."]
    if error.validator in ("minLength", "maxLength"):
        bound = "at least" if error.validator == "minLength" else "at most"
        unit = "character" if error.validator_value == 1 else "characters"
        given = "character" if len(error.instance) == 1 else "characters"
        return [f"{where}: accepts {bound} {error.validator_value} {unit}. "
                f"The call gave {len(error.instance)} {given}."]
    message = error.message
    if len(message) > 300:
        message = message[:300] + "..."
    return [f"{where}: {message}."]


def validation_error(args: Dict[str, Any], schema: dict) -> Optional[str]:
    """Return why the arguments do not match the schema, or `None`.

    Each problem starts with its path. The branch of an `anyOf` or `oneOf` that the value's
    type matches gives the problems, so a list of objects with wrong keys names the
    missing keys and the keys that the schema does not name.
    """
    if not schema:
        return None
    try:
        validator = jsonschema.validators.validator_for(schema)(schema)
        validator.check_schema(schema)
        errors = sorted(validator.iter_errors(args), key=lambda e: list(map(str, e.absolute_path)))
    except jsonschema.SchemaError:
        return None
    if not errors:
        return None
    problems: List[str] = []
    for error in errors:
        for problem in _problems(error):
            if problem not in problems:
                problems.append(problem)
    shown = problems[:MAX_PROBLEMS]
    more = len(problems) - len(shown)
    if more:
        shown.append(f"The call has {more} more problem{'s' if more != 1 else ''}.")
    return " ".join(shown)


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
    "BROWSER_READ_TOOL", "BROWSER_TOOL_PREFIX", "BatchBudget",
    "IDEMPOTENCY_HEADER", "ORDERED_TOOLS", "PAGE_SHARE_HEADER",
    "is_browser_tool",
    "batch_budget", "empty_page_text", "page_share_client", "pending_calls",
    "split_resources", "validation_error",
]
