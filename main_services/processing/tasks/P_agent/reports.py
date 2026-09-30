"""Typed evidence of tool results, and the report of a run thread.

**Evidence.** `_write_tool_result` stores the evidence of each tool result in the `evidence`
list of the `usage_json` of its `tool` message, at every run depth. `normalize` makes the
list from the result, the call arguments and the `doc_refs` that the collection server
sent beside the page. Each entry has this shape.

| key | value |
|---|---|
| `version` | `EVIDENCE_VERSION` |
| `source` | `{thread_id, message_idx, item_key}` |
| `kind` | `document_read`, `discovery`, `citation`, `note` or `artifact` |
| `status` | `ok`, `partial` or `error` |
| `reference` | the document, citation, note, page or artifact identity |
| `range` | the page, byte or character span of a read, when the result states it |
| `error` | the error text of a failed item |

The `source` names the logical thread and the index of the message in it, so an entry keeps
its identity when a continuation runs the thread under another run id. `item_key` names one
item of the result: several items of one message have distinct keys. A search result gives
`discovery` entries only, never `document_read`. A failed item stays `error` when its batch
succeeded. A read that the page cut is `partial`, with the span that the page states.

A tool message stored before this module has no `evidence` list. `thread_evidence` then
normalizes its stored content with no `doc_refs`, so it gives only what that content shows.

**The report.** `project` is a pure function of the committed messages and the run state.
It selects the final answer, the latest `RECENT_TEXTS` texts that the model wrote (never
its reasoning and never a note to the model), the evidence lists, the calls with no result,
and the citation check of the answer. `render` writes the text body. `materialize` writes
both as the `report` and `report_data` documents of a plan sub-agent thread, keyed by the
thread's first run. `ensure_reports` writes a missing pair from the committed messages, with
no model call, no tool call and no change of state. `read_run_report` projects the thread of
any run of the owner, and a chat run has no plan document.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable, Optional

log = logging.getLogger(__name__)

EVIDENCE_VERSION = 1
REPORT_VERSION = 1

KIND_READ = "document_read"
KIND_DISCOVERY = "discovery"
KIND_CITATION = "citation"
KIND_NOTE = "note"
KIND_ARTIFACT = "artifact"

STATUS_OK = "ok"
STATUS_PARTIAL = "partial"
STATUS_ERROR = "error"

#: The texts of the model that a report selects, newest last.
RECENT_TEXTS = 3

#: The most entries of one kind that one tool message stores. A result page holds fewer.
MAX_ENTRIES_PER_MESSAGE = 60

#: The most entries of each list of a report. The report counts the entries it left out.
MAX_REPORT_ENTRIES = 400

#: The most characters of a note, a quote or an error text in an entry.
MAX_ENTRY_TEXT = 2000

#: The tools whose result reads the text of a document.
READ_TOOLS = frozenset({"read_documents", "read_more", "read_page"})

#: The report document kinds.
REPORT_KIND = "report"
REPORT_DATA_KIND = "report_data"

#: The `cut` text of a `read_documents` item: `<shown> of <total> bytes`.
_CUT_TEXT = re.compile(r"^\s*(\d+)\s+of\s+(\d+)\s+bytes")

#: A citation label as an answer writes it.
LABEL_PATTERN = re.compile(r"\[D(\d+)\]")


def _clip(text: Any, limit: int = MAX_ENTRY_TEXT) -> str:
    value = str(text or "")
    return value if len(value) <= limit else value[:limit] + "…"


def _parse(content: str) -> Any:
    try:
        return json.loads(content or "")
    except (TypeError, ValueError):
        return content


def _call_error(parsed: Any, status: str) -> str:
    """The error text of a whole result, or "" for a result that succeeded."""
    if isinstance(parsed, dict) and (parsed.get("success") is False
                                     or (parsed.get("error") and "items" not in parsed
                                         and "citations" not in parsed)):
        return _clip(parsed.get("message") or parsed.get("error") or "the call failed")
    if status == STATUS_ERROR:
        return _clip(parsed if isinstance(parsed, str) else json.dumps(parsed, default=str))
    return ""


def _hash_start(value: Any) -> str:
    return str(value or "")[:16]


def _doc_reference(ref: dict, item: Optional[dict] = None) -> dict:
    """The document identity of a doc ref, else of a page item."""
    ref = ref or {}
    item = item or {}
    return {
        "collectionname": str(ref.get("collectionname") or item.get("collectionname") or ""),
        "collection_dataset": str(ref.get("collection_dataset")
                                  or item.get("collection_dataset") or ""),
        "file_hash": str(ref.get("file_hash") or item.get("file_hash") or ""),
        "path": str(ref.get("path") or item.get("path") or ""),
    }


def _refs_by_start(doc_refs: Any) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for ref in doc_refs if isinstance(doc_refs, list) else []:
        if isinstance(ref, dict) and ref.get("file_hash"):
            out.setdefault((str(ref.get("collectionname") or ""),
                            _hash_start(ref["file_hash"])), ref)
    return out


def _requested_hashes(args: dict) -> list[str]:
    value = args.get("file_hash")
    if isinstance(value, str):
        value = [value]
    return [str(v) for v in value or [] if str(v).strip()] if isinstance(value, list) else []


def _entry(kind: str, status: str, reference: dict, key: str, range_: Optional[dict] = None,
           error: str = "") -> dict:
    out = {"version": EVIDENCE_VERSION, "kind": kind, "status": status,
           "reference": reference, "item_key": key}
    if range_:
        out["range"] = range_
    if error:
        out["error"] = _clip(error)
    return out


def _read_documents(parsed: Any, args: dict, doc_refs: Any, error: str) -> list[dict]:
    collection = str(args.get("collectionname") or "")
    if error:
        requested = _requested_hashes(args) or [""]
        return [_entry(KIND_READ, STATUS_ERROR,
                       {"collectionname": collection, "file_hash": value, "path": ""},
                       f"read:{value}", error=error) for value in requested]
    out: list[dict] = []
    refs = _refs_by_start(doc_refs)
    items = parsed.get("items") if isinstance(parsed, dict) else None
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        ref = refs.get((str(item.get("collectionname") or collection),
                        _hash_start(item.get("file_hash"))), {})
        reference = _doc_reference(ref, item)
        page = item.get("page")
        range_: dict[str, Any] = {"page": page} if isinstance(page, int) else {}
        status = STATUS_OK
        cut = _CUT_TEXT.match(str(item.get("cut") or ""))
        if item.get("error"):
            status = STATUS_ERROR
        elif cut or item.get("more"):
            status = STATUS_PARTIAL
            if cut:
                range_.update(start_bytes=0, end_bytes=int(cut.group(1)),
                              total_bytes=int(cut.group(2)))
        out.append(_entry(KIND_READ, status, reference,
                          f"read:{_hash_start(reference['file_hash'])}:{page}", range_,
                          error=str(item.get("error") or "")))
    notes = parsed.get("file_hash_notes") if isinstance(parsed, dict) else None
    for i, note in enumerate(notes if isinstance(notes, list) else []):
        out.append(_entry(KIND_READ, STATUS_ERROR,
                          {"collectionname": collection, "file_hash": "", "path": ""},
                          f"read_note:{i}", error=str(note)))
    return out


def _read_more(parsed: Any, args: dict, error: str) -> list[dict]:
    handle = str(args.get("continuation") or "")[:64]
    reference = {"continuation": handle}
    if error:
        return [_entry(KIND_READ, STATUS_ERROR, reference, f"more:{handle}", error=error)]
    if not isinstance(parsed, dict):
        return []
    cut = parsed.get("cut")
    if isinstance(cut, dict) and isinstance(cut.get("start_bytes"), int):
        items = parsed.get("items") if isinstance(parsed.get("items"), list) else []
        shown = sum(len(str(i).encode("utf-8")) for i in items if isinstance(i, str))
        start = int(cut["start_bytes"])
        total = int(cut.get("total_bytes") or 0)
        status = STATUS_PARTIAL if not total or start + shown < total or start > 0 else STATUS_OK
        return [_entry(KIND_READ, status, reference, f"more:{handle}:{start}",
                       {"start_bytes": start, "end_bytes": start + shown,
                        "total_bytes": total, "field": str(cut.get("field") or "")})]
    return []


#: The separator between the pages of one `read_page` result. Mirrors the join of
#: `browser_use_server/read_page.py::render`.
PAGE_SEPARATOR = "\n\n---\n\n"

#: The start of the artifact marker block of a browser result. Mirrors
#: `browser_use_server/server.py::ARTIFACT_MARKER`.
BROWSER_ARTIFACT_MARKER = "[hoover4:artifacts]"

#: The lines of `read_page.render` that mean the page gave no text.
PAGE_FAILURES = ("COULD NOT READ:", "BLOCKED BY A BOT CHECK:", "[offset ")

#: The cut line of a page that `read_page.render` did not return whole.
_PAGE_CUT = re.compile(r"\[cut: this call read ([\d,]+) of the page's ([\d,]+) characters")

#: The first line of a `find` result of `read_page.render`, and the line before the text of
#: each shown match. Mirrors `browser_use_server/read_page.py::_find_block`.
_PAGE_FIND = re.compile(
    r"^\[find (\".*?\"): (?:(\d+) of (\d+) matches from offset (\d+) are shown"
    r"|no match from offset (\d+))\. The page has (\d+) matches in ([\d,]+) characters")
_FIND_MATCH = re.compile(r"^\[match at (\d+), text from (\d+) to (\d+)\]$", re.MULTILINE)


def _page_blocks(parsed: Any) -> list[str]:
    """The page sections of a `read_page` result, in order. The result is a list of text
    blocks (older rows), or one text with the marker block on its last line. A section
    starts with `## <title>` and the page URL on its second line. A `---` line inside the text of a
    page does not start a section, so that text stays with its page."""
    texts = parsed if isinstance(parsed, list) else [parsed] if isinstance(parsed, str) else []
    blocks: list[str] = []
    for text in texts:
        if not isinstance(text, str) or text.startswith(BROWSER_ARTIFACT_MARKER):
            continue
        # A result stored as one text holds the marker block on its last line.
        head, _, last = text.rstrip().rpartition("\n")
        if head and last.startswith(BROWSER_ARTIFACT_MARKER):
            text = head
        for part in text.split(PAGE_SEPARATOR):
            lines = part.split("\n", 2)
            starts_page = (part.startswith("## ") and len(lines) > 1
                           and lines[1].strip().startswith(("http://", "https://")))
            if starts_page or not blocks:
                blocks.append(part)
            else:
                blocks[-1] += PAGE_SEPARATOR + part
    return [b for b in blocks if b.startswith("## ")]


def _read_page(parsed: Any, args: dict, error: str) -> list[dict]:
    """One entry for each page section. A page that gave no text is `error`. A cut page is
    `partial` with its character span, from the `offset` argument and the cut line. A
    `find` result is `partial` with the character spans of the text that it shows."""
    urls = args.get("urls") or args.get("url") or []
    if isinstance(urls, str):
        urls = [urls]
    if error:
        return [_entry(KIND_READ, STATUS_ERROR, {"url": str(u)}, f"page:{i}:{u}", error=error)
                for i, u in enumerate(urls or [""])]
    try:
        offset = max(0, int(args.get("offset") or 0))
    except (TypeError, ValueError):
        offset = 0
    out = []
    for i, block in enumerate(_page_blocks(parsed)):
        lines = block.split("\n", 2)
        url = lines[1].strip()
        body = lines[2].strip() if len(lines) > 2 else ""
        reference = {"url": url, "title": _clip(lines[0][3:].strip(), 200)}
        key = f"page:{i}:{url}"
        if body.startswith(PAGE_FAILURES):
            out.append(_entry(KIND_READ, STATUS_ERROR, reference, key,
                              error=body.split("\n", 1)[0]))
            continue
        found = _PAGE_FIND.match(body)
        if found:
            # A search in the page shows the text around each match only.
            spans = [[int(m.group(2)), int(m.group(3))] for m in _FIND_MATCH.finditer(body)]
            try:
                literal = json.loads(found.group(1))
            except ValueError:
                literal = found.group(1)
            out.append(_entry(KIND_READ, STATUS_PARTIAL, reference, key, {
                "find": str(literal), "spans": spans,
                "matches": int(found.group(6)),
                "total_chars": int(found.group(7).replace(",", ""))}))
            continue
        cut = _PAGE_CUT.search(body)
        if cut:
            read = int(cut.group(1).replace(",", ""))
            total = int(cut.group(2).replace(",", ""))
            out.append(_entry(KIND_READ, STATUS_PARTIAL, reference, key,
                              {"start_chars": offset, "end_chars": offset + read,
                               "total_chars": total}))
        elif offset:
            out.append(_entry(KIND_READ, STATUS_PARTIAL, reference, key,
                              {"start_chars": offset}))
        else:
            out.append(_entry(KIND_READ, STATUS_OK, reference, key))
    return out


def _citations(parsed: Any, args: dict, doc_refs: Any, error: str) -> list[dict]:
    if error:
        return [_entry(KIND_CITATION, STATUS_ERROR, {}, "citation:call", error=error)]
    rows = parsed.get("citations") if isinstance(parsed, dict) else None
    rows = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    refs = [r for r in doc_refs if isinstance(r, dict)] if isinstance(doc_refs, list) else []
    aligned = len(refs) == len(rows)
    out = []
    for i, row in enumerate(rows):
        ref = refs[i] if aligned else next(
            (r for r in refs if _hash_start(r.get("file_hash")) == row.get("file_hash")), {})
        reference = _doc_reference(ref, row)
        handle = str(row.get("handle") or ref.get("handle") or "")
        reference.update(handle=handle,
                         quote_verified=bool(row.get("quote_verified")
                                             or ref.get("quote_verified")),
                         quote_reason=str(row.get("quote_reason")
                                          or ref.get("quote_reason") or ""))
        if ref.get("quote"):
            reference["quote"] = _clip(ref["quote"], 500)
        candidate = row.get("candidate") or ref.get("candidate")
        if isinstance(candidate, dict):
            reference["candidate"] = {k: candidate[k] for k in candidate
                                      if k in ("text", "extracted_by", "page_id", "start",
                                               "end")}
        failure = str(row.get("error") or "")
        if not failure and not handle:
            failure = "no handle was allocated"
        out.append(_entry(KIND_CITATION, STATUS_ERROR if failure else STATUS_OK, reference,
                          f"citation:{i}", error=failure))
    return out


def _note(parsed: Any, error: str) -> list[dict]:
    if error or not isinstance(parsed, dict) or not parsed.get("note"):
        return []
    return [_entry(KIND_NOTE, STATUS_OK, {"text": _clip(parsed["note"])}, "note")]


#: The key under which a tool result lists the artifacts it wrote. Mirrors
#: `agent_common.artifacts.ARTIFACTS_KEY`, which the worker cannot import.
ARTIFACTS_KEY = "_hoover4_artifacts"


def _artifacts(parsed: Any) -> list[dict]:
    listed = parsed.get(ARTIFACTS_KEY) if isinstance(parsed, dict) else None
    out = []
    for item in listed if isinstance(listed, list) else []:
        if isinstance(item, dict) and item.get("artifact_id"):
            reference = {k: str(item.get(k) or "") for k in ("artifact_id", "kind", "title",
                                                              "url")}
            out.append(_entry(KIND_ARTIFACT, STATUS_OK, reference,
                              f"artifact:{reference['artifact_id']}"))
    return out


def _discovery(tool_name: str, parsed: Any, args: dict, doc_refs: Any) -> list[dict]:
    from tasks.P_agent.trajectory import call_query, extract_doc_refs, response_doc_refs

    if isinstance(doc_refs, list):
        refs = response_doc_refs(tool_name, doc_refs, call_query(args))
    else:
        refs = extract_doc_refs(tool_name, parsed, call_query(args))
    out = []
    for ref in refs:
        range_ = {"page": ref["page_id"]} if isinstance(ref.get("page_id"), int) else None
        out.append(_entry(KIND_DISCOVERY, STATUS_OK, _doc_reference(ref),
                          f"found:{_hash_start(ref.get('file_hash'))}:{ref.get('page_id')}",
                          range_))
    return out


def normalize(tool_name: str, args: Any, content: str, status: str,
              doc_refs: Any = None) -> list[dict]:
    """The evidence entries of one tool result, with no `source` yet.

    `status` is the stored status of the result (`ok` or `error`). A result whose content
    holds `"success": false` fails too, whatever its status.
    """
    args = args if isinstance(args, dict) else {}
    parsed = _parse(content)
    error = _call_error(parsed, status)
    if tool_name == "read_documents":
        entries = _read_documents(parsed, args, doc_refs, error)
    elif tool_name == "read_more":
        entries = _read_more(parsed, args, error)
    elif tool_name == "read_page":
        entries = _read_page(parsed, args, error)
    elif tool_name == "cite_documents":
        entries = _citations(parsed, args, doc_refs, error)
    elif tool_name == "write_note":
        entries = _note(parsed, error)
    elif error or tool_name == "run_subagent":
        entries = []
    else:
        entries = _discovery(tool_name, parsed, args, doc_refs)
    if not error:
        entries += _artifacts(parsed)
    return _unique_keys(entries[:MAX_ENTRIES_PER_MESSAGE])


def _unique_keys(entries: list[dict]) -> list[dict]:
    seen: dict[str, int] = {}
    for entry in entries:
        key = entry["item_key"]
        count = seen.get(key, 0)
        seen[key] = count + 1
        if count:
            entry["item_key"] = f"{key}#{count}"
    return entries


def with_source(entries: Iterable[dict], thread_id: str, message_idx: int) -> list[dict]:
    """The entries with their `source`. The item key moves into the source."""
    out = []
    for entry in entries:
        entry = dict(entry)
        key = entry.pop("item_key", "")
        entry["source"] = {"thread_id": thread_id, "message_idx": int(message_idx),
                           "item_key": key}
        out.append(entry)
    return out


def _call_args(messages, message) -> dict:
    for m in messages:
        if m.role == "ai":
            for entry in m.tool_calls:
                if str(entry.get("id") or "") == message.tool_call_id:
                    args = entry.get("args")
                    return args if isinstance(args, dict) else {}
    return {}


def message_evidence(messages, message, thread_id: str) -> tuple[list[dict], bool]:
    """The evidence of one stored `tool` message, and whether it is legacy (no stored
    list)."""
    stored = message.usage.get("evidence")
    if isinstance(stored, list):
        return [e for e in stored if isinstance(e, dict)], False
    entries = normalize(message.tool_name or "", _call_args(messages, message),
                        message.content or "", str(message.usage.get("status") or "ok"))
    return with_source(entries, thread_id, message.idx), True


def thread_evidence(messages, thread_id: str) -> tuple[list[dict], int]:
    """Every evidence entry of a thread in message order, and the count of legacy tool
    messages among them."""
    out: list[dict] = []
    legacy = 0
    for message in messages:
        if message.role != "tool":
            continue
        entries, old = message_evidence(messages, message, thread_id)
        legacy += int(old)
        out.extend(entries)
    return out, legacy


# ------------------------------------------------------------------ citation labels


def answer_labels(answer: str) -> list[str]:
    """The distinct `[Dn]` labels of an answer, in order of first use."""
    seen: list[str] = []
    for match in LABEL_PATTERN.finditer(answer or ""):
        label = f"[D{match.group(1)}]"
        if label not in seen:
            seen.append(label)
    return seen


def label_bindings(entries: Iterable[dict]) -> dict[str, set[str]]:
    """The documents of each label of successful citation entries. A document is its
    16-character hash start, which a stored result of every age shows."""
    out: dict[str, set[str]] = {}
    for entry in entries:
        if entry.get("kind") != KIND_CITATION or entry.get("status") != STATUS_OK:
            continue
        reference = entry.get("reference") or {}
        handle = str(reference.get("handle") or "")
        file_hash = _hash_start(reference.get("file_hash"))
        if handle and file_hash:
            out.setdefault(handle, set()).add(file_hash)
    return out


def check_labels(answer: str, bindings: dict[str, set[str]],
                 entries: Iterable[dict] = ()) -> dict:
    """The citation check of an answer against the label bindings of the session.

    A label resolves when successful citation results bind it to one document. An
    unresolved label has no such result. A conflicting label is bound to more than one
    document, and no document is chosen for it. `unverified_quotes` lists the citations
    whose quote did not match the text, separately. The check does not verify a claim.
    """
    labels = answer_labels(answer)
    unresolved = [label for label in labels if not bindings.get(label)]
    conflicting = [label for label in labels if len(bindings.get(label) or ()) > 1]
    unverified = []
    for entry in entries:
        reference = entry.get("reference") or {}
        if (entry.get("kind") == KIND_CITATION and entry.get("status") == STATUS_OK
                and not reference.get("quote_verified")
                and reference.get("handle") in labels):
            unverified.append({"handle": reference.get("handle"),
                               "quote_reason": reference.get("quote_reason") or "",
                               "candidate": reference.get("candidate")})
    return {"labels": labels, "unresolved": unresolved, "conflicting": conflicting,
            "unverified_quotes": unverified}


def session_citation_entries(username: str, session_id: str) -> list[dict]:
    """The citation entries of every thread of a chat session."""
    from database import agent_runs

    out: list[dict] = []
    for thread_id, messages in agent_runs.read_session_tool_messages(
            username, session_id, "cite_documents").items():
        for message in messages:
            entries, _ = message_evidence([], message, thread_id)
            out.extend(e for e in entries if e.get("kind") == KIND_CITATION)
    return out


# ---------------------------------------------------------------------- projection


def _text_source(thread_id: str, idx: int) -> dict:
    return {"thread_id": thread_id, "message_idx": int(idx)}


def _final_source(messages, asked: bool) -> Optional[int]:
    """The index of the `ai` message that gave the final answer: the newest one with text
    and no call, or for a question the newest one that called `ask_user`."""
    for m in reversed(messages):
        if m.role != "ai":
            continue
        if asked and any(c.get("name") == "ask_user" for c in m.tool_calls):
            return m.idx
        if not asked and not m.tool_calls and (m.content or "").strip():
            return m.idx
    return None


def _asked(messages) -> bool:
    last = next((m for m in reversed(messages) if m.role == "ai"), None)
    if last is None:
        return False
    ids = {str(c.get("id") or "") for c in last.tool_calls if c.get("name") == "ask_user"}
    return any(m.role == "tool" and m.tool_call_id in ids
               and m.usage.get("status") == "ok" for m in messages)


def _bounded(entries: list[dict], name: str, left_out: dict) -> list[dict]:
    if len(entries) > MAX_REPORT_ENTRIES:
        left_out[name] = len(entries) - MAX_REPORT_ENTRIES
        return entries[-MAX_REPORT_ENTRIES:]
    return entries


def project(messages, *, thread_id: str, first_run_id: str, state: str, result: str = "",
            end_reason: str = "", error: str = "", plan_run_id: str = "",
            section_node_id: str = "", session_citations: Optional[list[dict]] = None) -> dict:
    """The typed report of one thread, from its committed messages and its run state.

    `messages` is the thread in index order, partials left out. `result` is the stored
    result of the newest run. `session_citations` is the citation evidence of the whole
    chat session, which the citation check reads. Without it the check reads the thread.
    """
    from database import agent_runs

    evidence, legacy = thread_evidence(messages, thread_id)
    texts = [{"source": _text_source(thread_id, m.idx), "text": (m.content or "").strip()}
             for m in messages if m.role == "ai" and (m.content or "").strip()]
    completed = state == agent_runs.COMPLETED and not end_reason
    final = None
    if completed and (result or "").strip():
        asked = _asked(messages)
        idx = _final_source(messages, asked)
        final = {"source": _text_source(thread_id, idx) if idx is not None else None,
                 "text": result, "asked": asked}
    answered = {m.tool_call_id for m in messages if m.role == "tool"}
    unanswered = []
    for m in messages:
        if m.role == "ai":
            for entry in m.tool_calls:
                if str(entry.get("id") or "") not in answered:
                    unanswered.append({"source": _text_source(thread_id, m.idx),
                                       "tool": str(entry.get("name") or "")})
    left_out: dict[str, int] = {}
    by_kind = {kind: [e for e in evidence if e.get("kind") == kind]
               for kind in (KIND_READ, KIND_DISCOVERY, KIND_CITATION, KIND_NOTE,
                            KIND_ARTIFACT)}
    citations_seen = (session_citations if session_citations is not None
                      else by_kind[KIND_CITATION])
    check = check_labels(final["text"] if final else "", label_bindings(citations_seen),
                         citations_seen)
    failed = [e for e in evidence if e.get("status") == STATUS_ERROR]
    diagnostics: dict[str, Any] = {
        "failed_items": len(failed),
        "unanswered_calls": unanswered,
        "legacy_tool_messages": legacy,
        "citation_check": check,
        "repair_round": any(is_repair_marker(m) for m in messages),
    }
    report = {
        "version": REPORT_VERSION,
        "thread_id": thread_id,
        "first_run_id": first_run_id,
        "plan_run_id": plan_run_id or "",
        "section_node_id": section_node_id or "",
        "execution": {"state": state, "end_reason": end_reason or "",
                      "incomplete": not completed, "error": error or ""},
        "final_answer": final,
        "recent_text": texts[-RECENT_TEXTS:],
        "documents_read": _bounded(by_kind[KIND_READ], "documents_read", left_out),
        "documents_found": _bounded(by_kind[KIND_DISCOVERY], "documents_found", left_out),
        "citations": _bounded(by_kind[KIND_CITATION], "citations", left_out),
        "notes": _bounded(by_kind[KIND_NOTE], "notes", left_out),
        "artifacts": _bounded(by_kind[KIND_ARTIFACT], "artifacts", left_out),
        "diagnostics": diagnostics,
    }
    diagnostics["left_out"] = left_out
    return report


def is_repair_marker(message) -> bool:
    """Whether a thread message is the note of the citation repair round."""
    from tasks.P_agent import citations

    return citations.is_citation_note(message)


# -------------------------------------------------------------------------- the body


def _document_line(entry: dict) -> str:
    reference = entry.get("reference") or {}
    name = (reference.get("path") or reference.get("url") or reference.get("continuation")
            or _hash_start(reference.get("file_hash")) or "unknown document")
    parts = [f"- {name}"]
    if reference.get("file_hash"):
        parts.append(f"({reference.get('collectionname') or ''} "
                     f"{_hash_start(reference['file_hash'])})")
    range_ = entry.get("range") or {}
    if "page" in range_:
        parts.append(f"page {range_['page']}")
    if "end_bytes" in range_:
        parts.append(f"bytes {range_.get('start_bytes', 0)} to {range_['end_bytes']} "
                     f"of {range_.get('total_bytes', 0)}")
    if "end_chars" in range_:
        parts.append(f"characters {range_.get('start_chars', 0)} to {range_['end_chars']} "
                     f"of {range_.get('total_chars', 0)}")
    elif "start_chars" in range_:
        parts.append(f"from character {range_['start_chars']}")
    if entry.get("status") == STATUS_PARTIAL:
        parts.append("partial read")
    if entry.get("status") == STATUS_ERROR:
        parts.append(f"failed: {_clip(entry.get('error') or 'unknown error', 200)}")
    return " ".join(parts)


def render(report: dict) -> str:
    """The text body of a report: the answer or the newest model text, then the
    evidence and the diagnostics that code wrote. The model text and the code text are in
    separate sections."""
    execution = report.get("execution") or {}
    lines: list[str] = []
    final = report.get("final_answer")
    if final:
        lines.append(str(final.get("text") or "").rstrip())
    else:
        state = execution.get("state") or "unknown"
        reason = execution.get("end_reason")
        lines.append(f"The run ended {state}" + (f" ({reason})" if reason else "")
                     + " with no answer.")
        if execution.get("error"):
            lines.append(f"Error: {execution['error']}")
        recent = report.get("recent_text") or []
        if recent:
            lines += ["", "## Latest model text", ""]
            lines += [str(t.get("text") or "") + "\n" for t in recent]
    # A failed citation call names no document, so the body counts those calls in the
    # diagnostics and lists the citations that have a handle.
    cited = [e for e in report.get("citations") or [] if e.get("status") == STATUS_OK]
    failed_citations = len(report.get("citations") or []) - len(cited)
    sections = [("Documents read", report.get("documents_read")),
                ("Citations", cited),
                ("Notes", report.get("notes"))]
    evidence_lines: list[str] = []
    for title, entries in sections:
        if not entries:
            continue
        evidence_lines += ["", f"### {title}", ""]
        for entry in entries:
            if entry.get("kind") == KIND_NOTE:
                evidence_lines.append(f"- {(entry.get('reference') or {}).get('text', '')}")
            elif entry.get("kind") == KIND_CITATION:
                reference = entry.get("reference") or {}
                line = _document_line(entry)
                handle = reference.get("handle")
                if handle:
                    line = f"- {handle} " + line[2:]
                if not reference.get("quote_verified"):
                    line += " (quote not verified)"
                evidence_lines.append(line)
            else:
                evidence_lines.append(_document_line(entry))
    diagnostics = report.get("diagnostics") or {}
    check = diagnostics.get("citation_check") or {}
    notes = []
    if check.get("unresolved"):
        notes.append("Labels with no citation result: " + ", ".join(check["unresolved"]))
    if check.get("conflicting"):
        notes.append("Labels bound to more than one document: "
                     + ", ".join(check["conflicting"]))
    if diagnostics.get("unanswered_calls"):
        notes.append(f"Calls with no result: {len(diagnostics['unanswered_calls'])}")
    failed_reads = sum(1 for e in report.get("documents_read") or []
                       if e.get("status") == STATUS_ERROR)
    if failed_reads:
        notes.append(f"Reads that failed: {failed_reads}")
    if failed_citations:
        notes.append(f"Citation results that failed: {failed_citations}")
    if evidence_lines or notes:
        lines += ["", "## Evidence of the run", "",
                  "This section is written from the stored tool results, not by the model."]
        lines += evidence_lines
        if notes:
            lines += ["", "### Diagnostics", ""] + [f"- {n}" for n in notes]
    return "\n".join(lines).strip() + "\n"


# ------------------------------------------------------------------ documents


def _thread_rows(username: str, session_id: str, thread_id: str):
    from tasks.P_agent.activities import _read_rows

    return _read_rows("thread_id = {t:UUID}",
                      {"u": username, "s": session_id, "t": thread_id})


def report_for_rows(rows, messages=None, session_citations=None, state: str = "",
                    error: str = "") -> dict:
    """The report of a thread from its run rows, oldest first. `state` and `error` replace
    the newest row's values, for an ending that has not written its row yet."""
    from database import agent_runs
    from tasks.P_agent.stream_writer import prepare_thread

    first, newest = rows[0], rows[-1]
    if messages is None:
        messages = prepare_thread(agent_runs.read_messages(first.username, first.session_id,
                                                           first.thread_id))
    if session_citations is None:
        session_citations = session_citation_entries(first.username, first.session_id)
    return project(messages, thread_id=first.thread_id, first_run_id=first.run_id,
                   state=state or newest.state, result=newest.result,
                   end_reason=newest.end_reason, error=error or newest.error,
                   plan_run_id=first.plan_run_id or "",
                   section_node_id=first.plan_node_id or "",
                   session_citations=session_citations)


def _report_node(first) -> str:
    from database import agent_plans

    if first.plan_node_id:
        return first.plan_node_id
    plan_run = agent_plans.read_plan_run(first.username, first.session_id, first.plan_run_id)
    return agent_plans.root_node_id(plan_run.plan_id) if plan_run else first.plan_run_id


def write_report_documents(first, report: dict) -> None:
    """Write the `report` and `report_data` documents of a plan sub-agent thread. Both ids
    come from the thread's first run, so a retry writes the same rows."""
    from database import agent_plans

    node = _report_node(first)
    attempt = 1 if first.purpose == "correct" else 0
    agent_plans.write_document(first.username, first.session_id, first.plan_run_id,
                               first.run_id, node, "executor", REPORT_KIND, render(report),
                               attempt=attempt)
    agent_plans.write_document(first.username, first.session_id, first.plan_run_id,
                               first.run_id, node, "executor", REPORT_DATA_KIND,
                               json.dumps(report, sort_keys=True, ensure_ascii=False),
                               attempt=attempt)


def materialize(x, state: str, chain: list, error: str = "") -> Optional[dict]:
    """Write the report pair of the plan sub-agent thread whose run `x` ends in `state`.
    `chain` is the earlier runs of the thread, newest first. Returns the report, or None
    for a run that is not a plan sub-agent."""
    if not x.plan_run_id or x.depth < 1:
        return None
    rows = list(reversed(chain)) + [x]
    report = report_for_rows(rows, state=state, error=error)
    write_report_documents(rows[0], report)
    return report


def ensure_reports(children) -> int:
    """Write the missing report pair of each plan sub-agent thread whose newest run is
    terminal. The report comes from the committed messages. No model runs, no tool runs,
    and no run state changes. Returns the count of pairs written."""
    from database import agent_plans, agent_runs

    written = 0
    by_plan: dict[str, set[str]] = {}
    for child in children:
        if not child.plan_run_id or child.depth < 1:
            continue
        if child.plan_run_id not in by_plan:
            by_plan[child.plan_run_id] = {
                d.document_id for d in agent_plans.read_documents(
                    child.username, child.session_id, child.plan_run_id)}
        rows = _thread_rows(child.username, child.session_id, child.thread_id)
        if not rows or not agent_runs.is_terminal(rows[-1]):
            continue
        first = rows[0]
        want = {agent_plans.document_id(first.run_id, REPORT_KIND),
                agent_plans.document_id(first.run_id, REPORT_DATA_KIND)}
        if want <= by_plan[child.plan_run_id]:
            continue
        write_report_documents(first, report_for_rows(rows))
        by_plan[child.plan_run_id] |= want
        written += 1
        log.info("[P_agent] wrote the missing report of thread %s", first.thread_id)
    return written


def read_run_report(username: str, session_id: str, run_id: str) -> Optional[dict]:
    """The report of the thread of one run of the owner, projected from the committed
    messages. None when the owner has no such run. A chat run has no plan document, so
    this is its report reader. It writes nothing."""
    from database import agent_runs

    row = agent_runs.read_run(username, session_id, run_id)
    if row is None:
        return None
    rows = _thread_rows(username, session_id, row.thread_id) or [row]
    return report_for_rows(rows)


__all__ = [
    "EVIDENCE_VERSION", "KIND_ARTIFACT", "KIND_CITATION", "KIND_DISCOVERY", "KIND_NOTE",
    "KIND_READ", "RECENT_TEXTS", "REPORT_DATA_KIND", "REPORT_KIND", "REPORT_VERSION",
    "answer_labels", "check_labels", "ensure_reports", "label_bindings", "materialize",
    "message_evidence", "normalize", "project", "read_run_report", "render",
    "report_for_rows", "session_citation_entries", "thread_evidence", "with_source",
    "write_report_documents",
]
