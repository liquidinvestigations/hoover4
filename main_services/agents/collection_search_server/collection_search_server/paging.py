"""Page construction and the `read_more` collection MCP tool.

The route decides paging. Every paged route returns `next_position`, `total` and
`partial` beside its units, and the broker applies one route paging policy
(:meth:`PagedTool.window`) to every route: it sends the route's `next_position` back as
the next request's `position`, and computes no position of its own.

A backend window that fits one page is returned whole. A window that does not fit is
stored once, as one raw artifact, on its first page. The later pages of that window
read byte ranges of the artifact with `artifacts.read_range`, and call no route. The
artifact holds a header line with the window's fields and columns, then one canonical
JSON line for each unit. A unit too large for a page is stored with string fields moved
out of the line, largest first, until the line fits the page share less
`ENVELOPE_RESERVE`. The line carries `{"__cut": [{"field", "bytes"}, ...]}`, one entry
for each moved field in the order moved, and the raw bytes of each field follow the line,
each on its own line. The page cuts such a unit inside its first moved field with the
marker `{"cut": {"field", "returned_bytes", "total_bytes", "next_fields"}}`, where
`next_fields` lists the other moved fields. Its continuations read the rest of each moved
field in order, and then the next unit. A blob window (a text page, a diff, a cell) is
stored as the header line and the raw text.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from fastmcp.server.dependencies import get_http_headers
from pydantic import BaseModel, ValidationError

from agent_common import artifacts
from agent_common.result_pages import (
    ByteLimit, ContinuationInvalid, PageInput, build_page, canonical_json, cut_unit,
    decode_continuation, largest_string_field, replace_at_pointer, utf8_prefix,
)
from collection_search_server.backend_client import (
    AgentError, AgentModel, BackendClient, CollectionsListResponse,
    SearchResultsResponse, SearchFacetValuesResponse, SearchDateHistogramResponse,
    SearchEntityExplainerResponse, DocumentsReadResponse, DocumentsSearchTextResponse, DocumentsSourcesResponse,
    DocumentsMetadataResponse, DocumentsEmailResponse, DocumentsDiffSourcesResponse,
    DocumentsPdfSearchResponse, TablesOverviewResponse, TablesPageResponse, TablesCellResponse,
    TablesColumnValuesResponse, TablesSearchCellsResponse, FoldersOverviewResponse,
    FoldersListResponse, FoldersSearchResponse,
)

PAGE_LIMIT = ByteLimit(24_000)
#: Bytes of a page kept for the envelope and the continuation. A unit larger than the
#: page share less this reserve is stored with string fields moved out, largest first,
#: until its line is not.
ENVELOPE_RESERVE = 8_192
#: Stands in for the artifact id while the broker measures a page, and has its length.
PENDING_ARTIFACT_ID = "00000000-0000-0000-0000-000000000000"
ARTIFACT_CONTENT_TYPE = "application/x-ndjson"
RESPONSE_MODELS: dict[str, type[AgentModel]] = {
    "collections/list": CollectionsListResponse,
    "search/results": SearchResultsResponse,
    "search/facet_values": SearchFacetValuesResponse,
    "search/histogram": SearchDateHistogramResponse,
    "search/entity_explainer": SearchEntityExplainerResponse,
    "documents/read": DocumentsReadResponse,
    "documents/search_text": DocumentsSearchTextResponse,
    "documents/sources": DocumentsSourcesResponse,
    "documents/metadata": DocumentsMetadataResponse,
    "documents/email": DocumentsEmailResponse,
    "documents/diff_sources": DocumentsDiffSourcesResponse,
    "documents/pdf_search": DocumentsPdfSearchResponse,
    "tables/overview": TablesOverviewResponse,
    "tables/page": TablesPageResponse,
    "tables/cell": TablesCellResponse,
    "tables/column_values": TablesColumnValuesResponse,
    "tables/search_cells": TablesSearchCellsResponse,
    "folders/overview": FoldersOverviewResponse,
    "folders/list": FoldersListResponse,
    "folders/search": FoldersSearchResponse,
}
#: The keys a route tool's continuation position may hold.
POSITION_KEYS = frozenset({"window", "next", "artifact", "head", "start", "total", "cut", "blob"})


def page_share() -> int:
    """The bytes one page may take, which is `PAGE_LIMIT`."""
    return PAGE_LIMIT.max_bytes


def _page_limit() -> ByteLimit:
    """The page limit of a route page, which is the page share."""
    return ByteLimit(page_share())


@dataclass(frozen=True)
class Window:
    """One backend window, split by the route paging policy."""

    items: list[Any]
    fields: dict[str, Any]
    columns: list[Any] | None
    next: dict[str, Any] | None
    total: int


@dataclass(frozen=True)
class PagedTool:
    """The route and page adapter for one continuation-capable tool."""

    model: type[AgentModel]
    route: str
    tool_name: str
    shape: str
    item_key: str
    columns_key: str | None = None

    def window(self, result: dict[str, Any]) -> Window:
        """The route paging policy. The units are the list under `item_key`, the rest of
        the response is the page fields, and the route's `next_position` and `total`
        decide what follows."""
        excluded = {self.item_key}
        if self.item_key == "__folder_items":
            items = [
                *({"field": "children", "value": value} for value in result["children"]),
                *({"field": "files", "value": value} for value in result["files"]),
            ]
            excluded.update(("children", "files"))
        elif self.item_key == "__metadata_entries":
            items = [{"field": "raw_metadata", "key": key, "value": value} for key, value in result["raw_metadata"].items()]
            excluded.add("raw_metadata")
        else:
            raw_items = result.get(self.item_key, [])
            items = raw_items if isinstance(raw_items, list) else [raw_items]
        if self.shape == "blob":
            text = items[0] if items else ""
            items = [text if isinstance(text, str) else canonical_json(text)]
        if self.columns_key:
            excluded.add(self.columns_key)
        fields = {key: value for key, value in result.items() if key not in excluded}
        columns = result.get(self.columns_key) if self.columns_key else None
        next_position = result.get("next_position")
        total = result.get("total")
        if not isinstance(total, int):
            total = len(items)
        return Window(items, fields, columns, next_position, total)

    def render(self, request: BaseModel, position: dict[str, Any], source: str) -> str:
        if position.get("artifact"):
            return _stored_page(self, request, position, _artifact_reader(position["artifact"]))
        window = position.get("window")
        send = request
        if window is not None:
            if "position" not in type(request).model_fields:
                return _invalid("this tool has one backend window")
            try:
                send = type(request).model_validate({**request.model_dump(mode="json", exclude_none=True, by_alias=True), "position": window})
            except ValidationError as exc:
                return _invalid(f"continuation position is invalid: {exc}")
        result = BackendClient().post(self.route, send, RESPONSE_MODELS[self.route], expected_source=source or None)
        if isinstance(result, AgentError):
            return error_text(result)
        result = result.model_dump(mode="json", by_alias=True)
        if source and result.get("source", "") != source:
            return canonical_json({"success": False, "error": "source_changed", "message": "the source changed after the prior page"})
        return _live_page(self, request, window, self.window(result))


def _invalid(message: str) -> str:
    return canonical_json({"success": False, "error": "invalid_argument", "message": message})


def _input(request: BaseModel) -> dict[str, Any]:
    return request.model_dump(mode="json", exclude_none=True)


def _after_window(window: Window) -> dict[str, Any] | None:
    return {"window": window.next} if window.next else None


def _live_page(tool: PagedTool, request: BaseModel, window_position: dict | None, window: Window) -> str:
    """The first page of a window read from the route. A window that fits is returned
    whole. Otherwise the window is stored, and its first page is read from the stored
    bytes the way `read_more` reads the later ones."""
    source = window.fields.get("source", "")
    units = len(window.items[0].encode("utf-8")) if tool.shape == "blob" and window.items else len(window.items)
    pending = {"artifact": PENDING_ARTIFACT_ID, "start": 0}
    after = lambda count: _after_window(window) if count >= units else pending
    total = units if tool.shape == "blob" else window.total
    page, measure = build_page(
        PageInput(tool.tool_name, tool.shape, window.items, window.columns, total, {"window": window_position},
                  source, _input(request), None, after, window.fields),
        _page_limit(),
    )
    if measure.returned_units >= units:
        return page
    try:
        artifact_id, body, head = _store_window(tool, window)
    except artifacts.ArtifactWriteFailed as exc:
        return canonical_json({"success": False, "error": "artifact_write_failed", "message": str(exc)})
    position = {"window": window_position, "next": window.next, "artifact": artifact_id, "head": head,
                "start": head, "total": window.total}
    if tool.shape == "blob":
        position["blob"] = 1
    return _stored_page(tool, request, position, _memory_reader(body), fields=window.fields, columns=window.columns)


def _store_window(tool: PagedTool, window: Window) -> tuple[str, bytes, int]:
    """Write the window as one artifact, and return its id, its body and the header length."""
    head = (canonical_json({"fields": window.fields, "columns": window.columns}) + "\n").encode("utf-8")
    parts = [head]
    if tool.shape == "blob":
        parts.append((window.items[0] if window.items else "").encode("utf-8"))
    else:
        for unit in window.items:
            parts.extend(_stored_unit(unit))
    body = b"".join(parts)
    headers = {key.lower(): value for key, value in get_http_headers().items()}
    request = artifacts.ArtifactRequest(
        session_id=headers.get("x-hoover4-chat-session", ""),
        username=headers.get("x-hoover4-user", ""),
        kind=artifacts.KIND_AGENT_RAW_RESULT,
        tool_name=tool.tool_name,
    )
    artifact_id = str(uuid.uuid4())
    artifacts.write_required(request, artifact_id, artifact_id, body, ARTIFACT_CONTENT_TYPE)
    return artifact_id, body, len(head)


def _stored_unit(unit: Any) -> list[bytes]:
    """The stored lines of one unit. A unit whose line is longer than the page share less
    `ENVELOPE_RESERVE` has string fields moved out, largest first, until its line is not.
    Each moved field follows the line as a raw segment, in the order of its `__cut` entry.
    A unit with no string left to move keeps its line, and the reader refuses it."""
    line = canonical_json(unit).encode("utf-8")
    target = max(page_share() - ENVELOPE_RESERVE, 0)
    if len(line) <= target or not isinstance(unit, dict):
        return [line, b"\n"]
    stripped: Any = unit
    moved: list[tuple[str, bytes]] = []
    while True:
        found = largest_string_field(stripped)
        if found is None or not found[0] or not found[1]:
            break
        pointer, text = found
        stripped = replace_at_pointer(stripped, pointer, "")
        moved.append((pointer, text.encode("utf-8")))
        line = _cut_line(stripped, moved)
        if len(line) <= target:
            break
    if not moved:
        return [line, b"\n"]
    parts = [line, b"\n"]
    for _, raw in moved:
        parts.extend([raw, b"\n"])
    return parts


def _cut_line(stripped: dict, moved: list[tuple[str, bytes]]) -> bytes:
    cuts = [{"field": pointer, "bytes": len(raw)} for pointer, raw in moved]
    return canonical_json({**stripped, "__cut": cuts}).encode("utf-8")


def _cut_segments(entries: Any, line_start: int, raw_start: int) -> list[dict[str, Any]]:
    """The `cut` position of each moved field of a stored unit, in stored order. The
    first raw segment starts at `raw_start`, and each segment ends with a newline."""
    if isinstance(entries, dict):
        entries = [entries]
    segments = []
    base = raw_start
    for entry in entries:
        end = base + int(entry["bytes"])
        segments.append({"field": str(entry["field"]), "base": base, "end": end, "line": line_start})
        base = end + 1
    return segments


def _following_segment(read: Reader, cut: dict[str, Any]) -> dict[str, Any] | None:
    """The moved field stored after the one `cut` names, read from the unit's stored line,
    or `None` after the last moved field."""
    if "line" not in cut:
        return None
    line_start = int(cut["line"])
    data, _ = read(line_start, page_share())
    newline = data.find(b"\n")
    if newline < 0:
        raise ValueError(f"the stored unit at byte {line_start} has no complete line")
    record = json.loads(data[:newline].decode("utf-8"))
    segments = _cut_segments(record["__cut"], line_start, line_start + newline + 1)
    for index, segment in enumerate(segments):
        if segment["base"] == int(cut["base"]):
            return segments[index + 1] if index + 1 < len(segments) else None
    raise ValueError("the continuation names no moved field of the stored unit")


Reader = Callable[[int, int], tuple[bytes, int]]


def _memory_reader(body: bytes) -> Reader:
    """Reads the stored window that this call has just written, with the clamp of
    `artifacts.read_range`."""
    def read(start: int, length: int) -> tuple[bytes, int]:
        if start >= len(body):
            raise artifacts.ArtifactRangeRefused(f"start {start} is past the end of the artifact")
        return body[start:start + min(length, page_share())], len(body)
    return read


def _artifact_reader(artifact_id: str) -> Reader:
    headers = {key.lower(): value for key, value in get_http_headers().items()}
    username = headers.get("x-hoover4-user", "")
    session_id = headers.get("x-hoover4-chat-session", "")

    def read(start: int, length: int) -> tuple[bytes, int]:
        return artifacts.read_range(username, session_id, artifact_id, start, min(length, page_share()))
    return read


def _stored_page(
    tool: PagedTool, request: BaseModel, position: dict[str, Any], read: Reader,
    *, fields: dict[str, Any] | None = None, columns: list[Any] | None = None,
) -> str:
    """One page of a stored window, read from `position["start"]`."""
    try:
        return _stored_page_unchecked(tool, request, position, read, fields, columns)
    except artifacts.ArtifactNotFound as exc:
        return canonical_json({"success": False, "error": "not_found", "message": str(exc)})
    except artifacts.ArtifactForbidden as exc:
        return canonical_json({"success": False, "error": "permission_denied", "message": str(exc)})
    except artifacts.ArtifactRangeRefused as exc:
        return _invalid(str(exc))
    except (ValueError, KeyError, TypeError) as exc:
        return _invalid(f"the stored window does not match the continuation: {exc}")
    except Exception as exc:  # noqa: BLE001 - the object store or the index failed
        return canonical_json({"success": False, "error": "backend_unavailable", "message": f"could not read the stored window: {exc}"})


def _stored_page_unchecked(tool, request, position, read, fields, columns) -> str:
    start = int(position["start"])
    head = int(position["head"])
    base = {key: position[key] for key in ("window", "next", "artifact", "head", "total") if key in position}
    source_end = {"window": position["next"]} if position.get("next") else None
    if fields is None and head <= page_share():
        header = json.loads(read(0, head)[0].decode("utf-8"))
        fields, columns = header.get("fields") or {}, header.get("columns")
    fields = fields or {}
    source = fields.get("source", "")
    page_input = lambda shape, items, total, after, page_fields, cols=None: PageInput(
        tool.tool_name, shape, items, cols, total, {**base, "start": start}, source, _input(request),
        position["artifact"], after, page_fields,
    )

    if position.get("blob"):
        data, size = read(start, page_share())
        text = utf8_prefix(data, len(data)).decode("utf-8")
        after = lambda count: {**base, "blob": 1, "start": start + count} if start + count < size else source_end
        return build_page(page_input("blob", [text], size - head, after, fields), _page_limit())[0]

    cut = position.get("cut")
    if cut:
        end = int(cut["end"])
        data, size = read(start, min(page_share(), end - start))
        text = utf8_prefix(data, len(data)).decode("utf-8")
        marker = {"cut": {"field": cut["field"], "start_bytes": start - int(cut["base"]), "total_bytes": end - int(cut["base"])}}
        following: list[dict[str, Any] | None] = []

        def after_cut(count: int) -> dict | None:
            if start + count < end:
                return {**base, "start": start + count, "cut": cut}
            if not following:
                following.append(_following_segment(read, cut))
            return _after_segment(base, following[0], end, size, source_end)
        return build_page(page_input("blob", [text], end - int(cut["base"]), after_cut, marker), _page_limit())[0]

    data, size = read(start, page_share())
    units: list[Any] = []
    ends: list[int] = []
    offset = 0
    while offset < len(data):
        newline = data.find(b"\n", offset)
        if newline < 0:
            break
        record = json.loads(data[offset:newline].decode("utf-8"))
        if isinstance(record, dict) and "__cut" in record:
            if units:
                break
            return _cut_unit_page(tool, request, base, start, newline + 1, data, size, record, source_end, page_input, fields, columns)
        units.append(record)
        offset = newline + 1
        ends.append(start + offset)
    if not units:
        return _unreadable_unit(start, len(data))

    def after_units(count: int) -> dict | None:
        following = ends[count - 1] if count else start
        return {**base, "start": following} if following < size else source_end
    page, measure = build_page(page_input(tool.shape, units, int(position.get("total", len(units))), after_units, fields, columns), _page_limit())
    if measure.returned_units <= 0:
        return _unreadable_unit(start, ends[0] - start)
    return page


def _unreadable_unit(start: int, length: int) -> str:
    """The answer for a stored unit that no page can hold. It never happens for a unit
    with a string field, because the store moves string fields out until the line fits."""
    return _invalid(
        f"the unit stored at byte {start} of this window is at least {length} bytes with no string field "
        f"left to move out, and a page holds {page_share()} bytes"
    )


def _after_segment(base: dict[str, Any], segment: dict[str, Any] | None, end: int, size: int, source_end: dict | None) -> dict | None:
    """The position after a moved field that ends at `end`: the next moved field of the
    same unit, the next stored unit, or the next backend window."""
    if segment is not None:
        return {**base, "start": segment["base"], "cut": segment}
    return {**base, "start": end + 1} if end + 1 < size else source_end


def _cut_unit_page(tool, request, base, start, raw_offset, data, size, record, source_end, page_input, fields, columns) -> str:
    """The page of one unit too large for a page, cut inside its first moved field. The
    marker lists the other moved fields, which the continuations read in order."""
    segments = _cut_segments(record.pop("__cut"), start, start + raw_offset)
    first = segments[0]
    pointer, raw_start, raw_end = first["field"], first["base"], first["end"]
    total_bytes = raw_end - raw_start
    available = data[raw_offset:raw_offset + total_bytes]
    following = segments[1] if len(segments) > 1 else None

    def attempt(keep: int) -> tuple[str, int]:
        kept = utf8_prefix(available, keep)
        position_after = raw_start + len(kept)
        after = lambda count: (
            {**base, "start": position_after, "cut": first} if position_after < raw_end
            else _after_segment(base, following, raw_end, size, source_end)
        )
        unit = cut_unit(record, pointer, kept, total_bytes)
        if following is not None:
            unit["cut"]["next_fields"] = [segment["field"] for segment in segments[1:]]
        text, measure = build_page(page_input(tool.shape, [unit], int(base.get("total", 1)), after, fields, columns), _page_limit())
        return text, measure.returned_units

    low, high = 0, len(available)
    best = attempt(0)
    if not best[1]:
        return _unreadable_unit(start, raw_offset)
    while low <= high:
        middle = (low + high) // 2
        text, returned = attempt(middle)
        if returned:
            best, low = (text, returned), middle + 1
        else:
            high = middle - 1
    return best[0]


def error_text(error: AgentError) -> str:
    return canonical_json(error.model_dump())


def _artifact(tool_name: str, complete: dict[str, Any]) -> str | None:
    headers = {key.lower(): value for key, value in get_http_headers().items()}
    request = artifacts.ArtifactRequest(
        session_id=headers.get("x-hoover4-chat-session", ""),
        username=headers.get("x-hoover4-user", ""),
        kind=artifacts.KIND_AGENT_RAW_RESULT,
        tool_name=tool_name,
    )
    artifact_id = str(uuid.uuid4())
    artifacts.write_required(
        request, artifact_id, artifact_id, canonical_json(complete).encode("utf-8"), "application/json"
    )
    return artifact_id


def page_result(
    tool_name: str, request: AgentModel, response: dict[str, Any], shape: str, items: list[Any],
    *, columns: list[Any] | None = None, fields: dict[str, Any] | None = None, position: dict[str, int] | None = None,
    total_units: int | None = None, position_after: Callable[[int], dict[str, int] | None] | None = None,
) -> str:
    """Build one canonical page and store the complete response when it needs paging."""
    current = position or {"page": 0, "offset": 0}
    total = total_units if total_units is not None else len(items)
    after = position_after or (lambda count: None if count >= len(items) else {"page": current.get("page", 0), "offset": current.get("offset", 0) + count})
    try:
        provisional, measure = build_page(PageInput(tool_name, shape, items, columns, total, current, response.get("source", ""), request.model_dump(mode="json", exclude_none=True), None, after, fields), PAGE_LIMIT)
        artifact_id = _artifact(tool_name, response) if measure.truncated else None
        if artifact_id is None:
            return provisional
        page, _ = build_page(PageInput(tool_name, shape, items, columns, total, current, response.get("source", ""), request.model_dump(mode="json", exclude_none=True), artifact_id, after, fields), PAGE_LIMIT)
        return page
    except artifacts.ArtifactWriteFailed as exc:
        return canonical_json({"success": False, "error": "artifact_write_failed", "message": str(exc)})


def _position_is_valid(handler: Any, position: dict[str, Any]) -> bool:
    """The shape check of a continuation position. A route tool's position is checked
    here for its types only: the route checks the window position, and `read_range`
    clamps the byte range and checks the artifact owner."""
    if not isinstance(handler, PagedTool):
        return (
            "page" in position and "offset" in position
            and all(key in ("page", "offset", "blob") and type(value) is int and value >= 0 for key, value in position.items())
            and position.get("blob", 0) in (0, 1)
        )
    if any(key not in POSITION_KEYS for key in position):
        return False
    if any(position.get(key) is not None and not isinstance(position[key], dict) for key in ("window", "next")):
        return False
    if any(key in position and (type(position[key]) is not int or position[key] < 0) for key in ("head", "start", "total")):
        return False
    if "artifact" in position:
        if not isinstance(position["artifact"], str) or "start" not in position or "head" not in position:
            return False
    if position.get("blob", 0) not in (0, 1):
        return False
    cut = position.get("cut")
    if cut is not None:
        if not isinstance(cut, dict) or not isinstance(cut.get("field"), str):
            return False
        if any(type(cut.get(key)) is not int or cut[key] < 0 for key in ("base", "end")):
            return False
        if "line" in cut and (type(cut["line"]) is not int or cut["line"] < 0):
            return False
    return True


def _read_more_response(token: dict[str, Any]) -> str:
    from collection_search_server import tools_document, tools_folder, tools_search, tools_table

    handlers = {**tools_search.PAGED_TOOLS, **tools_document.PAGED_TOOLS, **tools_table.PAGED_TOOLS, **tools_folder.PAGED_TOOLS}
    tool_name = token.get("tool")
    input_values = token.get("input")
    position = token.get("position")
    source = token.get("source")
    if (
        not isinstance(tool_name, str)
        or not isinstance(input_values, dict)
        or not isinstance(position, dict)
        or not isinstance(source, str)
    ):
        return canonical_json({"success": False, "error": "invalid_argument", "message": "continuation fields are invalid"})
    handler = handlers.get(tool_name)
    if handler is None:
        return canonical_json({"success": False, "error": "invalid_argument", "message": "continuation names an unavailable paged tool"})
    if not _position_is_valid(handler, position):
        return _invalid("continuation position is invalid")
    try:
        request = handler.model.model_validate(input_values)
    except (KeyError, ValidationError) as exc:
        return canonical_json({"success": False, "error": "invalid_argument", "message": f"invalid continuation input: {exc}"})
    return handler.render(request, position, source)


from collection_search_server.server import mcp


@mcp.tool(name="read_more", description="Read the next page from a prior paged tool result. Use it when that result contains a continuation token.")
def read_more(continuation: str) -> str:
    """Read only a continuation issued by this server."""
    try:
        return _read_more_response(decode_continuation(continuation))
    except ContinuationInvalid as exc:
        return canonical_json({"success": False, "error": "invalid_argument", "message": str(exc)})
