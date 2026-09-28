"""The code-written index of a compaction record.

A compaction replaces the older steps of a run with a record (`compaction.compact`). The
record starts with lists that code writes from the stored thread, because a summary model
copies file hashes with errors. This module writes those lists.

- "Searches that found nothing": each search call whose result holds no document.
- "Searches that found documents": each other successful search call, with its count.
- "Documents read": each document of a `read_documents` result, with its pages.
- One line that names the skill and tool texts that left the list whole.

Each list covers only the tool results that are not visible whole in the list after the
compaction. The worker keeps its own copy of `found_nothing` and the documents read, because
the two images share no module. Change both copies together.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

#: The tools whose results the two search sections list.
SEARCH_TOOLS = ("search_collections", "search_passages", "web_search")
READ_DOCUMENTS = "read_documents"
READ_SKILL = "read_skill"
READ_TOOL = "read_tool"

NOTHING_LINES = 60
FOUND_LINES = 40
DOCUMENT_LINES = 60

Key = Tuple[str, int]


def _json_object(content: Any) -> Optional[Dict[str, Any]]:
    """The content as a JSON object, or `None` when it is not one."""
    if isinstance(content, dict):
        return content
    try:
        value = json.loads(content) if isinstance(content, str) else None
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def item_count(content: Any) -> Optional[int]:
    """The count of documents in one search result, or `None` when the result is not a
    search page. A list key counts its items. `fields.total_count` counts when no list
    key is there."""
    body = _json_object(content)
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


def _key(message: Any) -> Optional[Key]:
    if getattr(message, "thread_id", None) is None or getattr(message, "idx", None) is None:
        return None
    return (str(message.thread_id), int(message.idx))


def _calls(rows: Sequence[Any]) -> Dict[str, Tuple[str, Dict[str, Any]]]:
    """Each call id of the thread with its tool name and arguments."""
    out: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for m in rows:
        if getattr(m, "role", "") != "ai":
            continue
        for c in m.tool_calls:
            out[str(c.id)] = (str(c.name), dict(c.args or {}))
    return out


def _results(rows: Sequence[Any]) -> Iterable[Tuple[Any, str, Dict[str, Any]]]:
    """Each successful tool result of the thread, with its call name and arguments."""
    calls = _calls(rows)
    for m in rows:
        if getattr(m, "role", "") != "tool" or m.status == "error":
            continue
        name, args = calls.get(str(m.tool_call_id or ""), (str(m.name or ""), {}))
        yield m, name, args


def _queries_and_filters(args: Dict[str, Any]) -> Tuple[Any, Dict[str, Any]]:
    filters = dict(args)
    queries = filters.pop("queries", None)
    query = filters.pop("query", None)
    return (queries if queries is not None else query), filters


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _newest(lines: List[str], cap: int) -> List[str]:
    """Each line once, at its newest place, and at most `cap` of the newest."""
    seen: Set[str] = set()
    out: List[str] = []
    for line in reversed(lines):
        if line not in seen:
            seen.add(line)
            out.insert(0, line)
    return out[-cap:]


def search_lines(rows: Sequence[Any], hidden: Set[Key]) -> Tuple[List[str], List[str]]:
    """The lines of the two search sections, from the results whose key is in `hidden`."""
    nothing: List[str] = []
    found: List[str] = []
    for m, name, args in _results(rows):
        if name not in SEARCH_TOOLS or _key(m) not in hidden:
            continue
        count = item_count(m.content)
        if count is None:
            continue
        queries, filters = _queries_and_filters(args)
        if count == 0:
            nothing.append(f"- {name} {_dumps(queries)} filters {_dumps(filters)}")
        else:
            noun = "document" if count == 1 else "documents"
            found.append(f"- {name} {_dumps(queries)}: {count} {noun}")
    return _newest(nothing, NOTHING_LINES), _newest(found, FOUND_LINES)


def documents_read(rows: Sequence[Any], hidden: Set[Key]) -> List[str]:
    """One line for each document that a hidden `read_documents` result holds: the
    collection, the hash as the result gives it, the path and the pages."""
    docs: Dict[Tuple[str, str], Tuple[str, List[str]]] = {}
    for m, name, _args in _results(rows):
        if name != READ_DOCUMENTS or _key(m) not in hidden:
            continue
        body = _json_object(m.content) or {}
        for item in body.get("items") or []:
            if not isinstance(item, dict) or not item.get("file_hash"):
                continue
            key = (str(item.get("collectionname") or "?"), str(item["file_hash"]))
            path, pages = docs.pop(key, (str(item.get("path") or ""), []))
            page = item.get("page")
            if page is not None and str(page) not in pages:
                pages.append(str(page))
            docs[key] = (path, pages)
    lines = []
    for (collection, file_hash), (path, pages) in docs.items():
        line = f"- {collection}/{file_hash} {path}".rstrip() + "."
        if pages:
            line += f" {'page' if len(pages) == 1 else 'pages'} {', '.join(pages)}"
        lines.append(line)
    return lines[-DOCUMENT_LINES:]


def removed_texts(rows: Sequence[Any], present: Set[Key]) -> List[str]:
    """The skills and tools that the thread read with status ok and whose newest read is
    not in the list after the compaction, in thread order, each name once."""
    newest: Dict[str, Optional[Key]] = {}
    order: List[str] = []
    for m, name, args in _results(rows):
        if name not in (READ_SKILL, READ_TOOL):
            continue
        target = str(args.get("name") or "").strip()
        if not target:
            continue
        label = f"{'skill' if name == READ_SKILL else 'tool'} `{target}`"
        if label not in newest:
            order.append(label)
        newest[label] = _key(m)
    return [label for label in order if newest[label] not in present]


def render(rows: Sequence[Any], *, visible_after: Set[Key],
           present_after: Optional[Set[Key]] = None) -> str:
    """The index of one compaction record.

    `rows` is the stored thread. `visible_after` holds the keys of the tool results that
    stay whole in the list after the compaction. `present_after` holds the keys of every
    tool result that stays, whole or cut, and defaults to `visible_after`.
    """
    present = visible_after if present_after is None else present_after
    hidden = {k for m in rows if getattr(m, "role", "") == "tool"
              for k in [_key(m)] if k is not None and k not in visible_after}
    nothing, found = search_lines(rows, hidden)
    docs = documents_read(rows, hidden)
    sections = []
    if nothing:
        sections.append("## Searches that found nothing\n" + "\n".join(nothing))
    if found:
        sections.append("## Searches that found documents\n" + "\n".join(found))
    if docs:
        sections.append("## Documents read\n" + "\n".join(docs))
    removed = removed_texts(rows, present)
    if removed:
        sections.append(
            f"Texts removed whole: {', '.join(removed)}. Read one again with `read_skill` "
            "or `read_tool` when you need it."
        )
    return "\n\n".join(sections)


__all__ = [
    "SEARCH_TOOLS", "documents_read", "found_nothing", "item_count", "removed_texts",
    "render", "search_lines",
]
