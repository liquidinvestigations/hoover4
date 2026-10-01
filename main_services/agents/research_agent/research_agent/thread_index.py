"""The code-written index of a compaction record.

A compaction replaces the older steps of a run with one summary (`compaction.py`). The
summary starts with lists that code writes from the stored thread, because a summary model
copies file hashes with errors. This module writes those lists.

- "Searches that found nothing": each search call whose result holds no document.
- "Searches that found documents": each other successful search call, with its count.
- "Documents read": each document of a `read_documents` result, with its pages.
- "Citation labels": each label of a `cite_documents` result, with its file hash.
- "Pages read": each page of a `read_page` result, with its source version and any unread
  continuation. A find with no match does not count as a content read.
- "Results that continue": each result page with a `more` handle, with its call.
- One line that names the skill and tool texts that left the list.

Each list covers only the tool results that are not in the list after the compaction. The worker keeps its own copy of `found_nothing` and the documents read, because
the two images share no module. Change both copies together.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

#: The tools whose results the two search sections list.
SEARCH_TOOLS = ("search_collections", "search_passages", "web_search")
READ_DOCUMENTS = "read_documents"
READ_SKILL = "read_skill"
READ_TOOL = "read_tool"
CITE_DOCUMENTS = "cite_documents"
READ_PAGE = "read_page"
#: The cut line of a `read_page` result, which names the offset of the next part.
NEXT_OFFSET = re.compile(r"Call read_page with offset (\d+) for the next part")
PAGE_VERSION = re.compile(r"\b[Vv]ersion ([0-9a-f]{16})\b")
FIND_RESULT = re.compile(r'^\[find .*?: (?:\d+ of \d+ matches|no match) from offset')
FIND_MORE = re.compile(r"\[more: \d+ matches from offset (\d+)\. Call read_page")
#: The separator of the pages of one `read_page` result.
PAGE_SEPARATOR = "\n\n---\n\n"

NOTHING_LINES = 60
FOUND_LINES = 40
DOCUMENT_LINES = 60
CITATION_LINES = 80
PAGE_LINES = 40
MORE_LINES = 40

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


def citation_lines(rows: Sequence[Any], hidden: Set[Key]) -> List[str]:
    """One line for each label that a hidden `cite_documents` result allocated: the label
    and the file hash as the result gives it. The label stays valid for the chat session."""
    labels: Dict[str, str] = {}
    for m, name, _args in _results(rows):
        if name != CITE_DOCUMENTS or _key(m) not in hidden:
            continue
        body = _json_object(m.content) or {}
        for item in body.get("citations") or []:
            if isinstance(item, dict) and item.get("handle") and item.get("file_hash"):
                labels.pop(str(item["handle"]), None)
                labels[str(item["handle"])] = str(item["file_hash"])
    return [f"- {label} {file_hash}" for label, file_hash in labels.items()][-CITATION_LINES:]


def page_blocks(content: str) -> List[str]:
    """The page sections of one `read_page` result text, in order. A section starts with
    `## <title>` and the page URL on its second line. A `---` line and a `## ` heading inside
    the text of a page do not start a section, so that text stays with its page. The worker's
    `reports._page_blocks` splits the same way."""
    blocks: List[str] = []
    for part in content.split(PAGE_SEPARATOR):
        lines = part.split("\n", 2)
        starts_page = (part.startswith("## ") and len(lines) > 1
                       and lines[1].strip().startswith(("http://", "https://")))
        if starts_page or not blocks:
            blocks.append(part)
        else:
            blocks[-1] += PAGE_SEPARATOR + part
    return [b for b in blocks if b.startswith("## ")]


def pages_read(rows: Sequence[Any], hidden: Set[Key]) -> List[str]:
    """List pages with text, their version, and any unread continuation."""
    pages: Dict[str, str] = {}
    for m, name, _args in _results(rows):
        if name != READ_PAGE or _key(m) not in hidden or not isinstance(m.content, str):
            continue
        for block in page_blocks(m.content):
            url = block.split("\n", 2)[1].strip()
            body = block.split("\n", 2)[2].strip() if block.count("\n") >= 2 else ""
            if body.startswith(("COULD NOT READ:", "BLOCKED BY A BOT CHECK:", "[offset ")):
                continue
            if FIND_RESULT.match(body) and "no match from offset" in body.split("\n", 1)[0]:
                continue
            match = FIND_MORE.search(body) if FIND_RESULT.match(body) else NEXT_OFFSET.search(body)
            version = PAGE_VERSION.search(body)
            pages.pop(url, None)
            detail = (f". version {version.group(1)}" if version else "") + (
                f". unread continuation at offset {match.group(1)}" if match else "")
            pages[url] = detail
    return [f"- {url}{detail}" for url, detail in pages.items()][-PAGE_LINES:]


def continued_results(rows: Sequence[Any], hidden: Set[Key]) -> List[str]:
    """One line for each hidden result page that has a `more` handle: the call and the
    handle that reads the next page."""
    lines: List[str] = []
    for m, name, args in _results(rows):
        if _key(m) not in hidden:
            continue
        body = _json_object(m.content) or {}
        more = body.get("more")
        if isinstance(more, str) and more:
            lines.append(f"- {name} {_dumps(args)}: more {more}")
    return _newest(lines, MORE_LINES)


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


def render(rows: Sequence[Any], *, visible_after: Set[Key]) -> str:
    """The index of one compaction record.

    `rows` is the stored thread. `visible_after` holds the keys of the tool results that
    stay in the list after the compaction.
    """
    hidden = {k for m in rows if getattr(m, "role", "") == "tool"
              for k in [_key(m)] if k is not None and k not in visible_after}
    nothing, found = search_lines(rows, hidden)
    docs = documents_read(rows, hidden)
    labels = citation_lines(rows, hidden)
    pages = pages_read(rows, hidden)
    more = continued_results(rows, hidden)
    sections = []
    if nothing:
        sections.append("## Searches that found nothing\n" + "\n".join(nothing))
    if found:
        sections.append("## Searches that found documents\n" + "\n".join(found))
    if docs:
        sections.append("## Documents read\n" + "\n".join(docs))
    if labels:
        sections.append("## Citation labels\n" + "\n".join(labels))
    if pages:
        sections.append("## Pages read\n" + "\n".join(pages))
    if more:
        sections.append("## Results that continue\n" + "\n".join(more))
    removed = removed_texts(rows, visible_after)
    if removed:
        sections.append(
            f"Texts removed: {', '.join(removed)}. Read one again with `read_skill` "
            "or `read_tool` when you need it."
        )
    return "\n\n".join(sections)


__all__ = [
    "SEARCH_TOOLS", "citation_lines", "continued_results", "documents_read", "found_nothing",
    "item_count", "page_blocks", "pages_read", "removed_texts", "render", "search_lines",
]
