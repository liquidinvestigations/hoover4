"""Bound model views without changing the structured results used by the broker."""

from __future__ import annotations

import json

from agent_common.workspace_results import DISPLAY_LIMIT, display, public_reference


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def call(tool, args):
    if len(encode(args)) <= 1000:
        return {"tool": tool, "arguments": args}
    keys = ("cursor", "limit", "row_offset", "schema_offset", "offset", "line_offset")
    return {"tool": tool, "reuse_previous_arguments": True,
            "argument_updates": {key: args[key] for key in keys if key in args}}


def bounded_json_prefix(text, limit):
    """Return the longest prefix that can fit when encoded as a JSON string."""
    low, high = 0, min(limit, len(text))
    while low < high:
        middle = (low + high + 1) // 2
        if len(encode(text[:middle])) <= limit:
            low = middle
        else:
            high = middle - 1
    return text[:low]


def _file_view(payload, args):
    path = args.get("path") or args.get("name")
    if not path:
        return encode({"next_call": call("workspace_list", {"kind": "file"})})
    text = payload.get("text", payload.get("content", ""))
    version = payload.get("version")
    if args.get("path"):
        start = int(payload.get("start", 0))
    else:
        return encode({
            "next_call": call("read_file", {"path": path, "version": version,
                                           "line_offset": args.get("offset", 1)}),
            "note": "Read this file by character range to recover long lines.",
        })
    first = bounded_json_prefix(text, DISPLAY_LIMIT - 1500)
    args = {"path": path, "version": version, "offset": start + len(first) + 1}
    return encode({"path": path, "version": version, "text": first, "start": start,
                   "end": start + len(first), "next_call": call("read_file", args)
                   if len(first) < len(text) or payload.get("next_offset") else None})


def workspace_view(name, content, args):
    if len(content) <= DISPLAY_LIMIT:
        return None
    try:
        payload = json.loads(content)
        if not isinstance(payload, dict):
            return display(content, None, DISPLAY_LIMIT)
    except ValueError:
        return display(content, None, DISPLAY_LIMIT)
    if name == "read_file":
        return _file_view(payload, args)
    key = {"workspace_list": "entries", "workspace_search": "matches",
           "workspace_rows": "rows"}[name]
    items = payload.get(key)
    if not isinstance(items, list) or not items:
        # A single row segment may itself contain heavily escaped text.
        segment = payload.get("row_segment")
        if isinstance(segment, str) and segment:
            part = bounded_json_prefix(segment, DISPLAY_LIMIT - 1500)
            next_call = call(name, {**args, "row_offset": payload.get("segment_start", 0) + len(part)})
            return encode({"row_segment": part, "segment_start": payload.get("segment_start", 0),
                           "next_call": next_call})
        return display(content, None, DISPLAY_LIMIT)
    preview = None
    for count in range(1, len(items) + 1):
        last = items[count - 1]
        if count == len(items):
            next_cursor = payload.get("next_cursor")
        elif name == "workspace_list":
            path = last["path"]
            next_cursor = path if last["kind"] == "file" else "@" + path.rsplit("/", 1)[-1]
        else:
            next_cursor = int(args.get("cursor", 0)) + count
        if next_cursor is not None and name != "workspace_list":
            next_cursor = int(next_cursor)
        next_call = call(name, {**args, "cursor": next_cursor}) if next_cursor is not None else None
        shown = encode({key: items[:count], "next_cursor": next_cursor, "next_call": next_call})
        if len(shown) > DISPLAY_LIMIT:
            break
        preview = shown
    if preview is not None:
        return preview
    item = items[0]
    if name == "workspace_rows":
        return encode({"note": "This row exceeds the display limit.",
                       "next_call": call(name, {**args, "limit": 1, "row_offset": 0})})
    compact = {key: item[key] for key in ("path", "version", "kind", "line", "start", "end", "count")
               if key in item}
    compact["next_call"] = call("read_file", {
        "path": item.get("path"), "version": item.get("version"), "offset": item.get("start", 0) + 1,
    })
    if len(items) > 1:
        if name == "workspace_list":
            path = item["path"]
            cursor = path if item["kind"] == "file" else "@" + path.rsplit("/", 1)[-1]
        else:
            cursor = int(args.get("cursor", 0)) + 1
    else:
        cursor = payload.get("next_cursor")
    return encode({key: [compact], "next_cursor": cursor})


def execution_view(result, reference):
    """Keep essential write receipts and citation handles within the display limit."""
    receipts = []
    for receipt in result["receipts"]:
        compact = {key: receipt[key] for key in ("tool", "status", "name", "version")
                   if key in receipt and isinstance(receipt[key], (str, int))}
        if isinstance(compact.get("name"), str):
            compact["name"] = compact["name"][:120]
        if isinstance(receipt.get("error"), str):
            compact["error"] = receipt["error"][:60]
        citations = receipt.get("citations")
        if isinstance(citations, list):
            compact["handles"] = [
                value["handle"] for value in citations if isinstance(value, dict)
                and isinstance(value.get("handle"), str) and len(value["handle"]) <= 8
            ][:12]
        receipts.append(compact)
    envelope = {"success": result["success"], "receipts": receipts}
    if isinstance(result.get("error"), str):
        envelope["error"] = result["error"][:200]
    if reference:
        envelope["result_ref"] = public_reference(reference)

    room = DISPLAY_LIMIT - len(encode(envelope)) - 65
    if room < 0:
        important = [receipt for receipt in receipts if receipt.get("tool") in {"write_file", "patch_file"}]
        envelope["receipts"] = kept = []
        for receipt in [*important, *(item for item in receipts if item not in important)]:
            kept.append(receipt)
            if len(encode(envelope)) > DISPLAY_LIMIT - 80:
                kept.pop()
        envelope["omitted_receipts"] = len(receipts) - len(kept)
        room = DISPLAY_LIMIT - len(encode(envelope)) - 65
    output = encode(result.get("output"))
    if room > 0:
        first = bounded_json_prefix(output, room // 2)
        tail = bounded_json_prefix(output[::-1], room // 2)[::-1]
        envelope["output_preview"] = output if len(encode(output)) <= room else first + "\n…\n" + tail
    return encode(envelope)


def earlier_items(value):
    """Find earlier-item identities on scoped results before retaining program output."""
    if not isinstance(value, dict):
        return ()
    result = []
    for entry in [value, *(item for key in ("entries", "matches", "source_refs")
                           for item in (value.get(key) or []) if isinstance(item, dict))]:
        source = entry.get("source") or {}
        sources = source.get("items", []) if isinstance(source, dict) else []
        if isinstance(source, dict) and source.get("item_kind"):
            sources = [source, *sources]
        result.extend((item["item_kind"], item["item_id"]) for item in sources
                      if isinstance(item, dict) and item.get("item_kind") and item.get("item_id"))
    return result
