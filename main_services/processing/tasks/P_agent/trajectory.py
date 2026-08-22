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
    """Cut a *text* payload off. For a JSON document use `truncate_json` instead."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"


#: Headroom for the `"truncated": true` markers, added after the shrinking.
_MARK_RESERVE = 64

#: Below this a string is not worth clipping.
_MIN_CLIPPABLE = 80


def truncate_json(text: str, max_chars: int = TOOL_PAYLOAD_CHARS) -> str:
    """Fit a serialised tool result into `max_chars` **without breaking its JSON**.

    The Python twin of `truncate_tool_payload` in `website/common/src/chat_types.rs`; a
    research turn's transcript must read identically to an inline one's, and this is one
    of the places the two are the same code written twice.

    Cutting the serialised document leaves a `{` with no `}`, and every reader then treats
    a recorded result as an absent one — the card printed "the result payload was not
    recorded" about a row it had just read. So: drop whole elements off the biggest array
    (the result list, in practice), mark the object that owned it, and only clip long
    strings when there is nothing left to drop. Anything that is not JSON, or that is one
    huge scalar, falls back to `truncate`.
    """
    if len(text) <= max_chars:
        return text
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return truncate(text, max_chars)

    target = max(max_chars - _MARK_RESERVE, 0)
    marked: list[list[Any]] = []
    _shrink_to_fit(value, target, marked)
    for path in marked:
        owner = _at(value, path)
        if isinstance(owner, dict):
            owner["truncated"] = True

    out = _dumps(value)
    if len(out) <= max_chars:
        return out
    return truncate(text, max_chars)


def _at(value: Any, path: list[Any]) -> Any:
    for step in path:
        try:
            value = value[step]
        except (KeyError, IndexError, TypeError):
            return None
    return value


def _collect(value: Any, path: list[Any], out: list, want: str) -> None:
    """Every array (or long string) in the document, as (path, size)."""
    if want == "array" and isinstance(value, list) and value:
        out.append((list(path), len(_dumps(value))))
    if want == "string" and isinstance(value, str) and len(value) > _MIN_CLIPPABLE:
        out.append((list(path), len(value)))
    if isinstance(value, list):
        for i, item in enumerate(value):
            _collect(item, path + [i], out, want)
    elif isinstance(value, dict):
        for key, item in value.items():
            _collect(item, path + [key], out, want)


def _shrink_to_fit(value: Any, target: int, marked: list[list[Any]]) -> None:
    """Arrays first and biggest-first, then strings.

    Dropping the tail of a result list costs the reader the results they were least
    likely to read; clipping strings costs every result a little.
    """
    while len(_dumps(value)) > target:
        arrays: list = []
        _collect(value, [], arrays, "array")
        if not arrays:
            break
        arrays.sort(key=lambda pair: pair[1], reverse=True)
        path = arrays[0][0]
        items = _at(value, path)
        if not isinstance(items, list):
            break
        # By measured size rather than one-at-a-time: a hundred results would otherwise
        # mean a hundred serialisations of the whole document.
        over = len(_dumps(value)) - target
        freed = 0
        while items and freed <= over:
            freed += len(_dumps(items.pop())) + 1
        owner = path[:-1]
        if owner not in marked:
            marked.append(owner)

    # Every array is empty and it still does not fit: the bulk is in the strings.
    while len(_dumps(value)) > target:
        strings: list = []
        _collect(value, [], strings, "string")
        if not strings:
            return
        strings.sort(key=lambda pair: pair[1], reverse=True)
        path, length = strings[0]
        owner = _at(value, path[:-1])
        keep = max(length // 2, _MIN_CLIPPABLE // 2)
        clipped = _at(value, path)[:keep] + "…"
        if isinstance(owner, dict):
            owner[path[-1]] = clipped
        elif isinstance(owner, list):
            owner[path[-1]] = clipped
        else:
            return
        if path[:-1] not in marked:
            marked.append(path[:-1])


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
        # Inside the JSON, never across it — see `truncate_json`.
        tool_output = truncate_json(_dumps(result))

        name = _tool_name(content)
        if name == "tool":
            name = _tool_name(start)
        refs = extract_doc_refs(name, result)
        paired.append(
            PairedToolCall(
                tool_name=name,
                tool_input=truncate_json(tool_input),
                tool_output=tool_output,
                summary=truncate(tool_input, TOOL_SUMMARY_CHARS),
                doc_refs=_dumps(refs) if refs else "",
            )
        )

    return paired


#: Tools whose result is a single document rather than a result set.
#:
#: `get_document_text` is retired and no live call produces one — **the arm stays anyway**,
#: because transcripts written before the batch form still hold its rows and a card that
#: cannot render an old row loses the evidence base this design was built on.
_SINGLE_DOCUMENT_TOOLS = {"get_document_text", "show_document"}

#: Tools whose result is a list of documents under a named key.
#:
#: `list_document_entities` answered with one document object before it was batched, so a
#: row here with no list under its key falls back to the single-document shape rather than
#: rendering as nothing.
_DOCUMENT_LIST_TOOLS = {"read_documents": "documents", "list_document_entities": "documents"}


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

    if tool_name == "cite_documents":
        citations = _as_dict(result).get("citations")
        if not isinstance(citations, list):
            return []
        refs: list[dict[str, Any]] = []
        for item in citations:
            one = _doc_ref(item)
            if not one:
                continue
            if not isinstance(item, dict):
                continue
            one["handle"] = str(item.get("handle") or "")
            one["quote"] = str(item.get("quote") or "")
            one["why"] = str(item.get("why") or "")
            one["quote_verified"] = bool(item.get("quote_verified"))
            # The snippet slot carries the quote, so the card shows what was cited
            # rather than an unrelated passage of the same file.
            if not one["snippet"]:
                one["snippet"] = one["quote"]
            refs.append(one)
        return refs

    key = _DOCUMENT_LIST_TOOLS.get(tool_name)
    if key is not None:
        entries = _as_dict(result).get(key)
        if not isinstance(entries, list):
            one = _doc_ref(result)
            return [one] if one else []
        return [d for d in (_doc_ref(item) for item in entries) if d]

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
