"""Turn a research agent's raw event list into transcript rows.

This is the Python twin of `pair_tool_calls` / `extract_doc_refs` in
`website/backend/src/api/chat/agent_client.rs` and `website/common/src/chat_types.rs`.
Two implementations of one format is not ideal, but the alternative is worse: the
synchronous chat path is Rust in the website and the research path is Python in a
Temporal worker, and neither can call the other. **They must agree** -- a transcript
should look the same whether it was produced inline or by a research task, and it did
not: this path used to store `json.dumps(event)[:400]` as the message body with the tool
type hardcoded to "tool", so research answers rendered as raw JSON in a card whose
expand panel was empty.

The event shapes, confirmed against a live run of `hoover4-full-research-agent`:

    start: {"input": {...arguments...}}
    end:   {"input": {...arguments...},
            "output": {"content": <tool result>, "name": "web_search",
                       "type": "tool", "tool_call_id": "..."}}

Note there is no tool name on a start event -- it only appears under `output.name` on
the end event, which is why pairing is required to label a call at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

#: Mirrors TOOL_PAYLOAD_CHARS in website/common/src/chat_types.rs.
TOOL_PAYLOAD_CHARS = 24_000

#: Mirrors TOOL_SUMMARY_CHARS in website/backend/src/api/chat/mod.rs.
TOOL_SUMMARY_CHARS = 400


@dataclass
class PairedToolCall:
    tool_name: str
    tool_input: str
    tool_output: str
    summary: str
    doc_refs: str = ""


@dataclass
class _Pending:
    tool_call_id: str | None
    content: dict[str, Any] = field(default_factory=dict)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _tool_name(content: dict[str, Any]) -> str:
    """Best-effort tool name. Matches the Rust `AgentToolCall::tool_name` order."""
    output = _as_dict(content.get("output"))
    for candidate in (content.get("name"), content.get("tool"), output.get("name")):
        if isinstance(candidate, str) and candidate:
            return candidate
    return "tool"


def _tool_call_id(content: dict[str, Any]) -> str | None:
    output = _as_dict(content.get("output"))
    for candidate in (output.get("tool_call_id"), content.get("tool_call_id")):
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def truncate(text: str, max_chars: int = TOOL_PAYLOAD_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"


def _dumps(value: Any) -> str:
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)


def pair_tool_calls(tool_calls: list[dict[str, Any]]) -> list[PairedToolCall]:
    """Pair start events with their end events, one row per completed call.

    Prefers `tool_call_id` when the end event carries one, and falls back to FIFO
    order when it does not -- the same rule as the Rust implementation. A start with
    no matching end is dropped: the call did not complete, and a row claiming a result
    that never arrived would be a lie.
    """
    pending: list[_Pending] = []
    paired: list[PairedToolCall] = []

    for call in tool_calls or []:
        phase = call.get("phase")
        content = _as_dict(call.get("content"))

        if phase == "start":
            pending.append(_Pending(_tool_call_id(content), content))
            continue
        if phase != "end":
            continue

        end_id = _tool_call_id(content)
        start: dict[str, Any] = {}
        if end_id is not None:
            match = next((i for i, p in enumerate(pending) if p.tool_call_id == end_id), None)
            if match is not None:
                start = pending.pop(match).content
            elif pending:
                start = pending.pop().content
        elif pending:
            start = pending.pop().content

        # Arguments are on both events in practice; prefer the start, which is where
        # they are guaranteed to be.
        arguments = start.get("input")
        if not isinstance(arguments, dict) or not arguments:
            arguments = content.get("input")
        tool_input = _dumps(arguments if arguments is not None else {})

        # Unwrap the tool's actual result out of the LangChain envelope, so the output
        # pane shows the result rather than a second copy of the arguments.
        output = _as_dict(content.get("output"))
        result = output.get("content", content)
        tool_output = truncate(_dumps(result))

        name = _tool_name(content)
        if name == "tool":
            name = _tool_name(start)
        refs = extract_doc_refs(name, result)
        paired.append(
            PairedToolCall(
                tool_name=name,
                tool_input=truncate(tool_input),
                tool_output=tool_output,
                summary=truncate(tool_input, TOOL_SUMMARY_CHARS),
                doc_refs=_dumps(refs) if refs else "",
            )
        )

    return paired


#: Tools whose result is a single document rather than a result set.
_SINGLE_DOCUMENT_TOOLS = {"get_document_text", "list_document_entities", "show_document"}


def extract_doc_refs(tool_name: str, result: Any) -> list[dict[str, Any]]:
    """Pull document references out of a tool result, for the result cards.

    Mirrors `extract_doc_refs` in `website/common/src/chat_types.rs`, including the
    rule that a document with no `collection_dataset` is still recorded -- the card
    renders, it just is not clickable.
    """
    if tool_name == "search_collections":
        results = _as_dict(result).get("results")
        if not isinstance(results, list):
            return []
        return [d for d in (_doc_ref(item) for item in results) if d]

    if tool_name in _SINGLE_DOCUMENT_TOOLS:
        one = _doc_ref(result)
        return [one] if one else []

    found: list[dict[str, Any]] = []
    _collect_document_shaped(result, found)
    return found


def _doc_ref(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    file_hash = value.get("file_hash")
    if not isinstance(file_hash, str) or not file_hash:
        return None
    page_id = value.get("page_id")
    score = value.get("score")
    return {
        "collection_dataset": str(value.get("collection_dataset") or ""),
        "file_hash": file_hash,
        "collectionname": str(value.get("collectionname") or ""),
        "path": str(value.get("path") or ""),
        "page_id": page_id if isinstance(page_id, int) else None,
        "score": score if isinstance(score, (int, float)) else None,
        "snippet": str(value.get("snippet") or ""),
    }


def _collect_document_shaped(value: Any, out: list[dict[str, Any]]) -> None:
    one = _doc_ref(value)
    if one:
        out.append(one)
        return
    if isinstance(value, list):
        for item in value:
            _collect_document_shaped(item, out)
    elif isinstance(value, dict):
        for item in value.values():
            _collect_document_shaped(item, out)
