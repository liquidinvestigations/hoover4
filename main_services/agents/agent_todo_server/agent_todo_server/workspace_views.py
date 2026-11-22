"""Read and search the stored extent of conversation files and captures."""

from __future__ import annotations

import csv
import io
import json
import operator
import os
import re

import regex
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field

from agent_common import workspace_results
from database import chat_workspace

csv.field_size_limit(chat_workspace.MAX_FILE_CHARS)


class Filter(BaseModel):
    column: str
    op: str = "eq"
    value: str | bool | int | float | None


class Sort(BaseModel):
    column: str
    descending: bool = False


def collection_access(caller, supplied):
    """Intersect the turn scope with the current permissions of its caller."""
    if not any(supplied):
        return []
    endpoint = os.getenv("AGENT_API_BASE_URL", "").rstrip("/")
    if not endpoint:
        return []
    import requests

    try:
        response = requests.post(
            f"{endpoint}/api/agent/v1/collections/list", json={},
            headers={"x-hoover4-user": caller.username, "x-hoover4-chat-session": caller.session_id,
                     "x-hoover4-collections": ",".join(supplied)},
            timeout=5,
        )
        if response.ok:
            return sorted(set(supplied).intersection(
                row["collectionname"] for row in response.json().get("collections", [])))
    except (requests.RequestException, KeyError, ValueError):
        pass
    return []


def item_access(caller, entries):
    """Recheck earlier chat and board access through the website's agent API."""
    from collections import defaultdict

    def source_items(entry):
        source = entry.source
        if source.get("item_kind"):
            return [source]
        return source.get("items", [])

    groups = defaultdict(list)
    for entry in entries:
        for source in source_items(entry):
            if source.get("item_kind") in {"chat", "board"} and source.get("item_id"):
                groups[source["item_kind"]].append(source["item_id"])
    if not groups:
        return entries
    import requests

    endpoint = os.getenv("AGENT_API_BASE_URL", "").rstrip("/")
    readable = set()
    for kind, keys in groups.items():
        if not endpoint:
            continue
        id_field = "session_id" if kind == "chat" else "board_id"
        for start in range(0, len(keys), 20):
            try:
                response = requests.post(
                    f"{endpoint}/api/agent/v1/{kind}s/list",
                    json={"ids": keys[start:start + 20], "page": 0},
                    headers={"x-hoover4-user": caller.username, "x-hoover4-chat-session": caller.session_id},
                    timeout=5,
                )
                if response.ok:
                    readable.update((kind, entry[id_field])
                                    for entry in response.json().get(f"{kind}s", []))
            except (requests.RequestException, KeyError, ValueError):
                continue
    return [entry for entry in entries if all(
        (source.get("item_kind"), source.get("item_id")) in readable for source in source_items(entry)
    )]


def listing(caller, collections, prefix="", kind="", cursor="", limit=50):
    files = [
        {"path": f["name"], "version": f["version"], "kind": "file",
         "extent": {"characters": f["chars"]}, "title": f["name"]}
        for f in chat_workspace.list_files(caller.username, caller.session_id)
    ]
    matches = [f for f in files if not cursor or f["path"] > cursor]
    # Captures are ordered by immutable artifact ID. Show files before captures.
    after = cursor[1:] if cursor.startswith("@") else ""
    if after:
        matches = []
    items = [f for f in matches if f["path"].startswith(prefix) and (not kind or f["kind"] == kind)]
    while len(items) <= limit:
        page = workspace_results.entries(caller.username, caller.session_id, collections, after=after)
        if page:
            after = page[-1].artifact_id
        for entry in item_access(caller, page):
            if entry.path.startswith(prefix) and (not kind or entry.tool == kind):
                items.append(entry.as_dict())
        if len(page) < 100:
            break
    next_cursor = None
    if len(items) > limit:
        path = items[limit - 1]["path"]
        next_cursor = path if path in {f["path"] for f in files} else "@" + path.rsplit("/", 1)[1]
    return {"entries": items[:limit], "next_cursor": next_cursor}


def body(caller, collections, path, version=None):
    if not chat_workspace.valid_name(path):
        if version is not None:
            try:
                version = int(version)
            except ValueError as exc:
                raise ToolError("A file version must be an integer.") from exc
        found = chat_workspace.read_version(caller.username, caller.session_id, path, version)
        if found is None:
            raise ToolError("The file or version is unavailable.")
        return {"path": path, "version": found.version, "kind": "file"}, found.content
    try:
        entry, text = workspace_results.read(caller.username, caller.session_id, collections, path, version)
        if not item_access(caller, [entry]):
            raise PermissionError("The source is unavailable.")
    except (ValueError, LookupError, PermissionError) as exc:
        raise ToolError(str(exc)) from exc
    return entry.as_dict(), text


def search(caller, collections, terms, paths, prefix, match, regex_mode, mode,
           case_sensitive, context_lines, cursor, limit):
    if not terms or len(terms) > 20 or any(not term or len(term) > 512 for term in terms):
        raise ToolError("Give 1 to 20 search terms of 1 to 512 characters.")
    if match not in {"any", "all"} or mode not in {"lines", "files", "count"}:
        raise ToolError("Use any or all for match, and lines, files or count for mode.")
    flags = 0 if case_sensitive else regex.IGNORECASE
    try:
        patterns = [regex.compile(t if regex_mode else re.escape(t), flags) for t in terms]
    except regex.error as exc:
        raise ToolError(f"The regular expression is invalid. {exc}") from exc
    position = int(cursor or 0)
    results = []
    scanned = 0
    if paths:
        entries = [{"path": path} for path in dict.fromkeys(paths)]
        next_page = None
    else:
        page = listing(caller, collections, prefix, limit=100)
        entries = page["entries"]
        next_page = page["next_cursor"]
    while True:
        for item in entries:
            entry, text = body(caller, collections, item["path"], item.get("version"))
            lines = text.splitlines(keepends=True)
            offset = 0
            count = 0
            for index, line in enumerate(lines):
                try:
                    hits = [list(p.finditer(line, timeout=0.05)) for p in patterns]
                except TimeoutError as exc:
                    raise ToolError("The regular expression exceeded the search time limit.") from exc
                selected = all(hits) if match == "all" else any(hits)
                if selected:
                    count += 1
                    if mode == "lines":
                        for hit in sorted({(m.start(), m.end()) for group in hits for m in group}):
                            scanned += 1
                            if scanned > position:
                                start, end = hit
                                before = "".join(lines[max(0, index - context_lines):index])[-400:]
                                after = "".join(lines[index + 1:index + context_lines + 1])[:400]
                                context = before + line[max(0, start - 600):min(len(line), end + 600)] + after
                                results.append({**entry, "start": offset + start, "end": offset + end,
                                                "text": line[start:end][:8000], "line": index + 1,
                                                "context": context[:4000]})
                            if len(results) > limit:
                                return {"matches": results[:limit], "next_cursor": str(position + limit),
                                        "exhausted": False}
                offset += len(line)
            if count and mode != "lines":
                scanned += 1
                if scanned > position:
                    results.append({**entry, "count": count})
                if len(results) > limit:
                    return {"matches": results[:limit], "next_cursor": str(position + limit),
                            "exhausted": False}
        if not next_page:
            return {"matches": results, "next_cursor": None, "exhausted": True}
        page = listing(caller, collections, prefix, cursor=next_page, limit=100)
        entries, next_page = page["entries"], page["next_cursor"]


def rows(caller, collections, path, version, columns, filters, sort, cursor, limit, row_offset=None):
    entry, text = body(caller, collections, path, version)
    envelope = {}
    try:
        if path.endswith(".csv"):
            records = list(csv.DictReader(io.StringIO(text, newline="")))
        elif path.endswith(".jsonl"):
            records = [json.loads(line) for line in text.split("\n") if line.strip()]
        else:
            data = json.loads(text)
            if isinstance(data, list):
                records = data
            else:
                envelope = data
                records = next((data[key] for key in ("rows", "items", "results", "hits", "matches", "entries")
                                if isinstance(data.get(key), list)), None)
    except (AttributeError, TypeError, ValueError, csv.Error) as exc:
        raise ToolError("This file does not contain readable structured rows.") from exc
    if records is None or any(not isinstance(record, dict) for record in records):
        raise ToolError("This file does not contain readable structured rows.")
    def fields(record):
        cells = record.get("cells")
        if not isinstance(cells, dict):
            return record
        return {**record, **{key: value.get("value", value.get("text", value))
                            if isinstance(value, dict) else value for key, value in cells.items()}}

    indexed = [(index, record, fields(record)) for index, record in enumerate(records)]
    for condition in filters:
        if condition.op not in {"eq", "ne", "lt", "le", "gt", "ge"}:
            raise ToolError("Use eq, ne, lt, le, gt or ge for a filter comparison.")
        compare = getattr(operator, condition.op)
        def selected(item):
            row = item[2]
            if condition.column not in row:
                return False
            value = row[condition.column]
            expected = condition.value
            numbers = (int, float)
            if type(value) is not type(expected) and not (type(value) in numbers and type(expected) in numbers):
                return condition.op == "ne"
            try:
                return compare(value, expected)
            except TypeError:
                return False
        indexed = [item for item in indexed if selected(item)]
    for key in reversed(sort):
        def sort_key(item):
            value = item[2].get(key.column)
            if isinstance(value, (str, int, float, bool)):
                return type(value).__name__, value
            return type(value).__name__, json.dumps(value, sort_keys=True)
        indexed.sort(key=sort_key, reverse=key.descending)
    start = int(cursor or 0)
    result = [{
        "row": index, **({"row_id": record["row_id"]} if "row_id" in record else {}),
        "values": {key: fields[key] for key in columns if key in fields} if columns else record,
    } for index, record, fields in indexed[start:start + limit]]
    if row_offset is not None and result:
        full_row = json.dumps(result[0], ensure_ascii=False, separators=(",", ":"))
        start_char = min(row_offset, len(full_row))
        end = min(len(full_row), start_char + 2000)
        return {**entry, "row_segment": full_row[start_char:end], "segment_start": start_char,
                "next_row_offset": end if end < len(full_row) else None,
                "next_cursor": str(start + 1) if start + 1 < len(indexed) else None}
    return {**entry, "rows": result, "stored_rows": len(records), "matching_rows": len(indexed),
            "next_cursor": str(start + limit) if start + limit < len(indexed) else None,
            "backend_continuation": envelope.get("more", envelope.get("continuation"))}
