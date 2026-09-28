"""Facts that code reads from the stored thread of a run: the searches that found nothing,
the documents that the searches returned, and the documents that the run read.

The repeat stop reads `found_nothing` to pick the text of a refused call, the repeat note
lists the searches that found nothing, and `write_found_documents` writes the listing of a
sub-agent that answered with no text twice.

The agent service keeps its own copy of `found_nothing` and the documents read, in
`research_agent/thread_index.py`, because the two images share no module. Change both
copies together. The tests of both copies read the same literal result strings.
"""

from __future__ import annotations

import json
from typing import Any, Optional

#: The tools whose results can find nothing.
SEARCH_TOOLS = ("search_collections", "search_passages", "web_search")
READ_DOCUMENTS = "read_documents"

#: The most lines of one list in the listing of a sub-agent with no answer.
LISTING_LINES = 30

#: The first line of that listing.
LISTING_HEAD = "This researcher wrote no report. Code wrote this list from its calls."


def json_object(content: Any) -> Optional[dict]:
    """The content as a JSON object, or None when it is not one."""
    if isinstance(content, dict):
        return content
    try:
        value = json.loads(content) if isinstance(content, str) else None
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def item_count(content: Any) -> Optional[int]:
    """The count of documents in one search result, or None when the result is not a
    search page. A list key counts its items. `fields.total_count` counts when no list key
    is there. A refusal (`"success": false`) gives None."""
    body = json_object(content)
    if body is None or body.get("success") is False:
        return None
    for key in ("items", "results", "documents"):
        value = body.get(key)
        if isinstance(value, list):
            return len(value)
    fields = body.get("fields")
    if isinstance(fields, dict) and isinstance(fields.get("total_count"), int):
        return int(fields["total_count"])
    return None


def found_nothing(name: str, content: Any) -> bool:
    """Whether a result of a search tool holds no document. A refusal is not an empty
    search, so it gives false."""
    return name in SEARCH_TOOLS and item_count(content) == 0


def _failed(message) -> bool:
    if message.usage.get("status") == "error":
        return True
    body = json_object(message.content)
    return body is not None and (body.get("success") is False or bool(body.get("error")))


def _results(messages):
    """Each successful tool result of the thread, in thread order, with its call name and
    arguments."""
    calls: dict[str, tuple[str, dict]] = {}
    for m in messages:
        if m.role == "ai":
            for e in m.tool_calls:
                args = e.get("args")
                calls[str(e.get("id") or "")] = (str(e.get("name") or ""),
                                                  args if isinstance(args, dict) else {})
    for m in messages:
        if m.role != "tool" or _failed(m):
            continue
        name, args = calls.get(str(m.tool_call_id or ""), (str(m.tool_name or ""), {}))
        yield m, name, args


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _newest(lines: list[str], cap: int) -> list[str]:
    """Each line once, at its newest place, and at most `cap` of the newest."""
    seen: set[str] = set()
    out: list[str] = []
    for line in reversed(lines):
        if line not in seen:
            seen.add(line)
            out.insert(0, line)
    return out[-cap:]


def search_line(name: str, args: dict) -> str:
    """One search as a line: the tool, the queries as JSON, and the other arguments as
    filters."""
    filters = dict(args)
    queries = filters.pop("queries", None)
    query = filters.pop("query", None)
    return f"- {name} {_dumps(queries if queries is not None else query)} filters {_dumps(filters)}"


def empty_searches(messages, cap: int) -> list[str]:
    """The searches of the thread that found nothing, the newest `cap`, each once."""
    return _newest([search_line(name, args) for m, name, args in _results(messages)
                    if found_nothing(name, m.content)], cap)


def _document(item: dict) -> Optional[tuple[str, str, str]]:
    """The collection, the hash as the result gives it, and the path of one result item."""
    if not isinstance(item, dict) or not item.get("file_hash"):
        return None
    collection = str(item.get("collectionname") or item.get("collection") or "?")
    path = str(item.get("path") or item.get("file_path") or item.get("filename") or "")
    return collection, str(item["file_hash"]), path


def _doc_line(collection: str, file_hash: str, path: str) -> str:
    return f"- {collection}/{file_hash} {path}".rstrip() + "."


def documents_read(messages, cap: int) -> list[str]:
    """One line for each document that a `read_documents` result holds, with its pages,
    the newest `cap`."""
    docs: dict[tuple[str, str], tuple[str, list[str]]] = {}
    for m, name, _args in _results(messages):
        if name != READ_DOCUMENTS:
            continue
        for item in (json_object(m.content) or {}).get("items") or []:
            doc = _document(item)
            if doc is None:
                continue
            path, pages = docs.pop(doc[:2], (doc[2], []))
            page = item.get("page")
            if page is not None and str(page) not in pages:
                pages.append(str(page))
            docs[doc[:2]] = (path, pages)
    lines = []
    for (collection, file_hash), (path, pages) in docs.items():
        line = _doc_line(collection, file_hash, path)
        if pages:
            line += f" {'page' if len(pages) == 1 else 'pages'} {', '.join(pages)}"
        lines.append(line)
    return lines[-cap:]


def documents_returned(messages, cap: int) -> list[str]:
    """One line for each document that the search results returned, with the count of
    searches that returned it. The documents that more searches returned come first."""
    counts: dict[tuple[str, str], list] = {}
    for m, name, _args in _results(messages):
        if name not in SEARCH_TOOLS:
            continue
        body = json_object(m.content) or {}
        seen = set()
        for key in ("items", "results", "documents"):
            items = body.get(key)
            for item in items if isinstance(items, list) else []:
                doc = _document(item)
                if doc is None or doc[:2] in seen:
                    continue
                seen.add(doc[:2])
                entry = counts.setdefault(doc[:2], [doc[2], 0])
                entry[0] = entry[0] or doc[2]
                entry[1] += 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1][1])[:cap]
    return [_doc_line(c, h, path) + f" in {n} {'search' if n == 1 else 'searches'}"
            for (c, h), (path, n) in ranked]


def found_documents_text(messages) -> str:
    """The listing that a sub-agent's report holds when it answered with no text twice:
    the documents it read, the documents its searches returned, and the searches that
    found nothing. A list with no line is left out."""
    parts = [LISTING_HEAD]
    for title, lines in (
            ("Documents read", documents_read(messages, LISTING_LINES)),
            ("Documents that the searches returned", documents_returned(messages, LISTING_LINES)),
            ("Searches that found nothing", empty_searches(messages, LISTING_LINES))):
        if lines:
            parts.append(f"## {title}\n" + "\n".join(lines))
    if len(parts) == 1:
        parts.append("It read no document, and no search returned one.")
    return "\n".join(parts)
