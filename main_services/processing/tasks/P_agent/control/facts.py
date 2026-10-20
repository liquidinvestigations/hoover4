"""Result facts: what the stored tool results of a thread hold, for the policy handlers.

Each `ResultFact` comes from one stored call and its `tool` message. The facts reuse the
typed evidence of the message (`reports.normalize`, stored in its usage) for reads and
discoveries, and the parsed result for the ranked web addresses and the hit types of a
collection search. A handler reads facts and never parses a result itself.

A read is satisfactory when its evidence status is `ok` or `partial` and it has a document
or a page reference. A `read_page` section that gave no text has the status `error`
(`reports._read_page`), so it is not a read.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

#: The file extensions of a table document.
TABLE_EXTENSIONS = (".xlsx", ".xls", ".xlsm", ".ods", ".csv", ".tsv", ".sqlite", ".db")
EMAIL_EXTENSIONS = (".eml", ".msg", ".mbox")
READ_TOOLS = ("read_page", "read_documents", "read_more", "table_page", "table_cell")
#: The workspace write and patch tools, with the names that older rows hold.
MUTATION_TOOLS = ("write_file", "patch_file", "workspace_write", "workspace_patch")


@dataclass(frozen=True)
class ResultFact:
    call_id: str
    name: str
    ai_idx: int
    idx: int
    origin: str
    status: str
    args: Any
    hit_types: tuple = ()
    paths: tuple = ()
    #: The result addresses of a `web_search`, in rank order.
    urls: tuple = ()
    #: `(address or file hash, status)` of each read of the result.
    reads: tuple = ()
    skill: str = ""
    continuation: bool = False
    item_count: int | None = None
    keyword_sources: tuple = ()
    word_counts: tuple = ()
    repeated: bool = False
    todo_closed: int = 0
    todo_goal: str = ""
    verified_citations: int = 0
    #: The error code of a failed result, such as `not_found` or `invalid_argument`. A
    #: tool validation text (`VALIDATION_TEXT`) gives `invalid_arguments`. A result with
    #: a code of `ARGUMENT_ERRORS` has the status `refused`.
    error_code: str = ""
    #: `(name, version, changed)` of a successful workspace write or patch. `changed` is
    #: false for a result that names the unchanged current version.
    file_version: tuple = ()


def _parse(content: str) -> Any:
    try:
        return json.loads(content or "")
    except (TypeError, ValueError):
        return None


def origin_of(message) -> str:
    """`policy` for an `ai` message that a policy action wrote, else `model`."""
    return "policy" if message.usage.get("origin") == "policy" else "model"


#: The error codes of a call whose arguments were wrong. The agent service writes
#: `invalid_arguments` (`research_agent.steps`), and the website agent routes write
#: `invalid_argument`.
ARGUMENT_ERRORS = ("invalid_argument", "invalid_arguments")

#: The plain text that a tool server returns when its own argument validation refuses a
#: call, for example `Error: 1 validation error for call[table_page]`.
VALIDATION_TEXT = re.compile(r"Error: \d+ validation errors? for call\[")


def result_facts(messages: Iterable) -> list[ResultFact]:
    """One fact for each answered call of the thread, in thread order."""
    messages = list(messages)
    calls: dict[str, tuple[Any, dict]] = {}
    for m in messages:
        if m.role == "ai":
            for entry in m.tool_calls:
                calls[str(entry.get("id") or "")] = (m, entry)
    out = []
    for m in messages:
        if m.role != "tool":
            continue
        ai, entry = calls.get(str(m.tool_call_id or ""), (None, {}))
        name = str(entry.get("name") or m.tool_name or "")
        args = entry.get("args") if isinstance(entry.get("args"), dict) else {}
        parsed = _parse(m.content)
        # A tool server's own argument validation answers with plain text and can leave no
        # error status in the usage. Only that exact prefix of an unparsed reply counts.
        validation = parsed is None and isinstance(m.content, str) and bool(VALIDATION_TEXT.match(m.content))
        failed = (m.usage.get("status") == "error" or validation
                  or (isinstance(parsed, dict) and (parsed.get("success") is False
                                                    or bool(parsed.get("error")))))
        evidence = [e for e in (m.usage.get("evidence") or []) if isinstance(e, dict)]
        hit_types, paths, urls, reads = [], [], [], []
        if isinstance(parsed, dict) and not failed:
            for key in ("items", "results", "documents"):
                rows = parsed.get(key)
                for row in rows if isinstance(rows, list) else []:
                    if not isinstance(row, dict):
                        continue
                    if isinstance(row.get("type"), str):
                        hit_types.append(row["type"])
                    if isinstance(row.get("path"), str):
                        paths.append(row["path"])
                    if name == "web_search" and isinstance(row.get("url"), str) and row["url"]:
                        urls.append(row["url"])
        for e in evidence:
            if e.get("kind") != "document_read":
                continue
            ref = e.get("reference") or {}
            key = ref.get("url") or ref.get("file_hash") or ""
            if key:
                reads.append((key, str(e.get("status") or "")))
        fields = parsed.get("fields", {}) if isinstance(parsed, dict) else {}
        fields = fields if isinstance(fields, dict) else {}
        def field(key, default=None):
            return parsed.get(key, fields.get(key, default)) if isinstance(parsed, dict) else default
        rows = next((parsed[k] for k in ("items", "results", "documents")
                     if isinstance(parsed, dict) and isinstance(parsed.get(k), list)), [])
        sources = list(field("keyword_sources", []))
        if name == "search_collections" and not sources and (args.get("query") or args.get("queries")):
            sources = [f"{r.get('collection', '')}/{r['file_hash']}" for r in rows
                       if isinstance(r, dict) and r.get("file_hash")]
        if name == "web_search":
            sources = urls
        error_code = str(field("error") or "") if failed and isinstance(field("error"), str) else ""
        if not error_code and validation:
            error_code = "invalid_arguments"
        # Every argument error is a refused call, whichever service wrote its code.
        refused = (field("status") == "refused"
                   or (failed and (error_code in ARGUMENT_ERRORS or error_code == "forbidden")))
        todo_items = field("todos", field("items", []))
        todo_items = todo_items if isinstance(todo_items, list) else []
        todo_closed = sum(1 for t in todo_items if isinstance(t, dict) and t.get("status") in ("completed", "done", "cancelled"))
        resolved = re.match(r"(\d+)/\d+ items resolved", str(field("summary", "")))
        if resolved:
            todo_closed = int(resolved.group(1))
        continuation = isinstance(parsed, dict) and bool(parsed.get("more") or parsed.get("continuation"))
        skill = str(args.get("name") or "") if name == "read_skill" and not failed else ""
        file_version: tuple = ()
        if name in MUTATION_TOOLS and not failed and isinstance(parsed, dict) and parsed.get("success") is True:
            if isinstance(parsed.get("name"), str) and isinstance(parsed.get("version"), int):
                file_version = (parsed["name"], parsed["version"], not parsed.get("unchanged"))
        out.append(ResultFact(
            call_id=str(m.tool_call_id or ""), name=name,
            ai_idx=ai.idx if ai is not None else -1, idx=m.idx,
            origin=origin_of(ai) if ai is not None else "model",
            status="refused" if refused else "error" if failed else "ok", args=args,
            hit_types=tuple(hit_types), paths=tuple(paths), urls=tuple(urls),
            reads=tuple(reads), skill=skill, continuation=continuation,
            item_count=len(rows) if isinstance(parsed, dict) and any(k in parsed for k in ("items", "results", "documents")) else None,
            keyword_sources=tuple(sources), word_counts=tuple(field("word_counts", [])),
            repeated=refused or (isinstance(m.content, str) and m.content.startswith("This call repeats call ")),
            todo_closed=todo_closed, todo_goal=str(args.get("goal") or field("goal", "")),
            verified_citations=sum(e.get("kind") == "citation" and e.get("status") == "ok" for e in evidence),
            error_code=error_code[:80], file_version=file_version))
    return out


def satisfactory_reads(facts: Iterable[ResultFact]) -> list[str]:
    """The addresses and file hashes with a successful read, in thread order."""
    out = []
    for fact in facts:
        for key, status in fact.reads:
            if status in ("ok", "partial") and key not in out:
                out.append(key)
    return out


def page_address(url: str) -> str:
    """Compare page addresses without a fragment or trailing sentence punctuation."""
    url = url.rstrip(".,;:!?")
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1]
    return url.split("#", 1)[0]


def is_table_hit(fact: ResultFact) -> bool:
    return ("table" in fact.hit_types
            or any(p.lower().endswith(TABLE_EXTENSIONS) for p in fact.paths))


def is_email_hit(fact: ResultFact) -> bool:
    return ("email" in fact.hit_types
            or any(p.lower().endswith(EMAIL_EXTENSIONS) for p in fact.paths))


def batch_of(facts: Iterable[ResultFact], ai_idx: int) -> list[ResultFact]:
    return [f for f in facts if f.ai_idx == ai_idx]


def fact_dict(fact: ResultFact) -> dict:
    """A small JSON form for decision records."""
    return {"call_id": fact.call_id, "name": fact.name, "idx": fact.idx, "origin": fact.origin,
            "status": fact.status}


def first(items: Iterable, default: Optional[Any] = None) -> Any:
    return next(iter(items), default)


#: The task fields of a structured task, in the order that a classifier request shows them.
TASK_FIELDS = ("objective", "corrections", "constraints", "deliverables", "allowed_sources",
               "brief", "goals")


def task_of(opening) -> dict:
    """The structured task of a turn: each field with its `text` and its `source`.

    A board explore turn stores its fields in the usage of the opening message (`task`),
    built from the stored intent before the long brief is rendered. A chat turn has the
    request of the person as its objective. A field holds original text only. A classifier
    answer never becomes a field.
    """
    task = opening.usage.get("task") if opening is not None else None
    if isinstance(task, dict) and task:
        out = {}
        for key, value in task.items():
            if isinstance(value, dict) and isinstance(value.get("text"), str):
                out[str(key)] = {"text": value["text"], "source": str(value.get("source") or "")}
            elif isinstance(value, list):
                items = [{"text": v["text"], "source": str(v.get("source") or "")}
                         for v in value if isinstance(v, dict) and isinstance(v.get("text"), str)]
                if items:
                    out[str(key)] = items
        if out:
            return out
    return {"objective": {"text": (opening.content or "") if opening is not None else "",
                          "source": "user"}}


def task_text(task: dict, limit: int) -> tuple[str, int]:
    """The text of a structured task for a classifier request, and the characters left out.

    The objective and the corrections come first, so a cut never removes the focused task.
    A cut text ends with a line that names the count of omitted characters, so the request
    never shows a cut task as complete."""
    from collections.abc import Mapping

    parts = []
    for key in TASK_FIELDS + tuple(k for k in task if k not in TASK_FIELDS):
        value = task.get(key)
        if isinstance(value, Mapping):
            parts.append(f"{key}: {value['text']}")
        elif isinstance(value, (list, tuple)) and value:
            parts.append(f"{key}:\n" + "\n".join(f"- {v['text']}" for v in value))
    text = "\n\n".join(parts)
    if len(text) <= limit:
        return text, 0
    omitted = len(text) - limit
    return text[:limit] + f"\n[{omitted} characters of the task are omitted here]", omitted


def render_steps(messages, limit: int = 5) -> str:
    """Render recent model replies and their structured result counts for the classifier."""
    replies = [m for m in messages if m.role == "ai" and origin_of(m) == "model"][-limit:]
    facts = result_facts(messages)
    lines = []
    for number, message in enumerate(replies, 1):
        calls = ", ".join(f"{c.get('name')}({json.dumps(c.get('args'), ensure_ascii=False)[:180]})"
                          for c in message.tool_calls)
        lines.append(f"Step {number}: {message.content[:300]} {calls}")
        for fact in batch_of(facts, message.idx):
            lines.append(f"  {fact.name}: status {fact.status}, {fact.item_count} items, "
                         f"{len(fact.keyword_sources)} keyword-matched sources.")
            text = next((m.content for m in messages if m.idx == fact.idx), "")
            lines.append(text[:700])
    return "\n".join(lines)[-6000:]


def justified_absence(context) -> bool:
    """An explicit absence statement with successful searches and no keyword source."""
    import re

    searches = [f for f in context.results if f.name in ("search_collections", "search_passages", "web_search")
                and f.status == "ok"]
    absent = re.search(r"\b(?:no (?:matching |relevant )?(?:documents?|sources?|results?|evidence|records?|e-?mails?)|"
                       r"(?:could not|couldn't|did not|didn't|cannot|can't) find|not found|"
                       r"(?:do not|does not|don't|doesn't) (?:contain|hold|establish)|"
                       r"(?:not|isn't|aren't) (?:available|present|in the collections))\b", context.draft, re.I)
    named = [*(context.turn.get("preparation", {}).get("absence_records") or []),
             *(context.turn.get("progress", {}).get("absence_records") or [])]
    verified_name = any(str(record.get("name") or "").casefold() in context.draft.casefold()
                        for record in named if record.get("name"))
    return bool(absent and (searches or verified_name) and not any(f.keyword_sources for f in searches))
