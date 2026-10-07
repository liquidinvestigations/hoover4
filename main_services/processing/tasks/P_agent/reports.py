"""Store typed evidence from tool results.

Each entry records its source, kind, status, reference, span, and error.
Search results record discovery. Document text and table cells record reads.
The worker stores these entries in each tool message's usage.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable, Optional

log = logging.getLogger(__name__)

EVIDENCE_VERSION = 1

KIND_READ = "document_read"
KIND_DISCOVERY = "discovery"
KIND_CITATION = "citation"
KIND_NOTE = "note"
KIND_ARTIFACT = "artifact"

STATUS_OK = "ok"
STATUS_PARTIAL = "partial"
STATUS_ERROR = "error"

#: The most entries of one kind that one tool message stores. A result page holds fewer.
MAX_ENTRIES_PER_MESSAGE = 60

#: The most characters of a note, a quote or an error text in an entry.
MAX_ENTRY_TEXT = 2000

#: The `cut` text of a `read_documents` item: `<shown> of <total> bytes`.
_CUT_TEXT = re.compile(r"^\s*(\d+)\s+of\s+(\d+)\s+bytes")

#: A citation label as an answer writes it.
LABEL_PATTERN = re.compile(r"\[([DW]\d+)\]")


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


def _read_more(parsed: Any, args: dict, error: str, doc_refs: Any = None) -> list[dict]:
    handle = str(args.get("continuation") or "")[:64]
    reference = {"continuation": handle}
    if error:
        return [_entry(KIND_READ, STATUS_ERROR, reference, f"more:{handle}", error=error)]
    if not isinstance(parsed, dict):
        return []
    refs = [ref for ref in doc_refs or [] if isinstance(ref, dict)
            and ref.get("evidence_kind") == KIND_READ and ref.get("file_hash")]
    items = parsed.get("items") or []
    if refs and any(isinstance(item, dict) and item.get("file_hash") and item.get("text") for item in items):
        return _read_documents(parsed, {}, refs, error)
    if refs and items:
        return [_entry(KIND_READ, STATUS_PARTIAL if parsed.get("more") or parsed.get("cut") else STATUS_OK,
                       _doc_reference(ref), f"more:{handle}:{index}", {"continuation": handle})
                for index, ref in enumerate(refs)]
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


def _table_content(tool_name: str, parsed: Any, args: dict, error: str) -> list[dict]:
    """A table row window or cell with content is a read of its source document."""
    if error or not isinstance(parsed, dict) or not args.get("file_hash"):
        return []
    if tool_name == "table_page":
        items = parsed.get("items")
        if not isinstance(items, list) or not any(isinstance(item, dict) and item.get("cells")
                                                     for item in items):
            return []
        range_ = {"sheet": args.get("sheet"), "row_start": parsed.get("row_start")}
    else:
        if not str(parsed.get("text") or ""):
            return []
        range_ = {"sheet": args.get("sheet"), "row": args.get("row"),
                  "column": args.get("column"), "offset": parsed.get("offset")}
    reference = {"collectionname": str(args.get("collectionname") or ""),
                 "file_hash": str(args["file_hash"]), "path": ""}
    location = (f"{range_.get('row_start')}" if tool_name == "table_page"
                else f"{range_.get('row')}:{range_.get('column')}:{range_.get('offset')}")
    return [_entry(KIND_READ, STATUS_OK, reference,
                   f"table:{tool_name}:{_hash_start(args['file_hash'])}:{args.get('sheet')}:{location}",
                   {key: value for key, value in range_.items() if value is not None})]


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
_PAGE_VERSION = re.compile(r"\b[Vv]ersion ([0-9a-f]{16})\b")
_FIND_MORE = re.compile(r"\[more: \d+ matches from offset (\d+)\. Call read_page")


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
            if not found.group(2):
                continue
            # A search in the page shows the text around each match only.
            spans = [[int(m.group(2)), int(m.group(3))] for m in _FIND_MATCH.finditer(body)]
            try:
                literal = json.loads(found.group(1))
            except ValueError:
                literal = found.group(1)
            range_ = {
                "find": str(literal), "spans": spans,
                "matches": int(found.group(6)),
                "total_chars": int(found.group(7).replace(",", ""))}
            version = _PAGE_VERSION.search(body)
            more = _FIND_MORE.search(body)
            if version:
                range_["version"] = version.group(1)
            if more:
                range_["next_offset"] = int(more.group(1))
            out.append(_entry(KIND_READ, STATUS_PARTIAL, reference, key, range_))
            continue
        cut = _PAGE_CUT.search(body)
        if cut:
            read = int(cut.group(1).replace(",", ""))
            total = int(cut.group(2).replace(",", ""))
            range_ = {"start_chars": offset, "end_chars": offset + read,
                      "total_chars": total}
            version = _PAGE_VERSION.search(body)
            if version:
                range_["version"] = version.group(1)
            out.append(_entry(KIND_READ, STATUS_PARTIAL, reference, key, range_))
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

    if tool_name == "web_search" and isinstance(parsed, dict):
        rows = parsed.get("items", parsed.get("results", []))
        return [_entry(KIND_DISCOVERY, STATUS_OK, {"url": row["url"]}, f"web-found:{i}")
                for i, row in enumerate(rows if isinstance(rows, list) else [])
                if isinstance(row, dict) and isinstance(row.get("url"), str) and row["url"]]
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
        entries = _read_more(parsed, args, error, doc_refs)
    elif tool_name == "read_page":
        entries = _read_page(parsed, args, error)
    elif tool_name in ("table_page", "table_cell"):
        entries = _table_content(tool_name, parsed, args, error)
    elif tool_name == "cite_pages":
        entries = _page_citations(parsed, error)
    elif tool_name == "cite_documents":
        entries = _citations(parsed, args, doc_refs, error)
    elif tool_name == "write_note":
        entries = _note(parsed, error)
    elif error:
        entries = []
    else:
        entries = _discovery(tool_name, parsed, args, doc_refs)
    if not error:
        entries += _artifacts(parsed)
    return _unique_keys(entries[:MAX_ENTRIES_PER_MESSAGE])


def _page_citations(parsed: Any, error: str) -> list[dict]:
    if error or not isinstance(parsed, dict):
        return [_entry(KIND_CITATION, STATUS_ERROR, {}, "web-citation:call", error=error)]
    out = []
    for i, row in enumerate(parsed.get("citations") or []):
        if not isinstance(row, dict):
            continue
        ref = {key: row[key] for key in ("url", "final_url", "version", "artifact_id", "handle",
                                       "quote_verified", "terms", "quotes", "spans") if key in row}
        valid = (all(ref.get(key) for key in ("url", "version", "artifact_id"))
                 and re.fullmatch(r"\[W[1-9]\d*\]", str(ref.get("handle") or ""))
                 and ref.get("quote_verified") is True)
        out.append(_entry(KIND_CITATION, STATUS_OK if valid else STATUS_ERROR, ref,
                          f"web-citation:{i}", error="" if valid else "Invalid web citation evidence."))
    for i, row in enumerate(parsed.get("errors") or []):
        if isinstance(row, dict):
            out.append(_entry(KIND_CITATION, STATUS_ERROR, {"url": row.get("url", "")},
                              f"web-citation-error:{i}", error=_clip(row.get("error"))))
    return out


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




def message_evidence(message) -> list[dict]:
    """Read the stored evidence of one tool message."""
    stored = message.usage.get("evidence")
    return [entry for entry in stored if isinstance(entry, dict)] if isinstance(stored, list) else []


# ------------------------------------------------------------------ citation labels


def answer_labels(answer: str) -> list[str]:
    """Return distinct document and web citation labels in their answer order."""
    seen: list[str] = []
    for match in LABEL_PATTERN.finditer(answer or ""):
        label = f"[{match.group(1)}]"
        if label not in seen:
            seen.append(label)
    return seen


def label_bindings(entries: Iterable[dict]) -> dict[str, set[str]]:
    """Bind successful labels to document hash starts or captured page versions."""
    out: dict[str, set[str]] = {}
    for entry in entries:
        if entry.get("kind") != KIND_CITATION or entry.get("status") != STATUS_OK:
            continue
        reference = entry.get("reference") or {}
        handle = str(reference.get("handle") or "")
        file_hash = _hash_start(reference.get("file_hash"))
        source = ("web:" + str(reference["url"]) + ":" + str(reference["version"])) if (
            reference.get("url") and reference.get("version")) else file_hash
        if handle and source:
            out.setdefault(handle, set()).add(source)
    return out


def one_citation_per_document(entries: Iterable[dict]) -> list[dict]:
    """The citation entries with one successful entry for each document, in the order of
    first citation. A later entry with a verified quote replaces one without, as the
    transcript's source list does (`merge_citations`). A citation repair round cites a
    document again, and the report shows the stronger result once. Failed entries and
    other kinds stay unchanged."""
    out: list[dict] = []
    kept: dict[tuple[str, str], int] = {}
    for entry in entries:
        reference = entry.get("reference") or {}
        key = (str(reference.get("collectionname") or ""),
               _hash_start(reference.get("file_hash")) or "")
        if (entry.get("kind") != KIND_CITATION or entry.get("status") != STATUS_OK
                or not key[1]):
            out.append(entry)
            continue
        if key not in kept:
            kept[key] = len(out)
            out.append(entry)
        elif (reference.get("quote_verified")
              and not (out[kept[key]].get("reference") or {}).get("quote_verified")):
            out[kept[key]] = entry
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
    for entry in one_citation_per_document(entries):
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
    for tool_name in ("cite_documents", "cite_pages"):
        for messages in agent_runs.read_session_tool_messages(username, session_id, tool_name).values():
            for message in messages:
                entries = message_evidence(message)
                out.extend(e for e in entries if e.get("kind") == KIND_CITATION)
    return out
