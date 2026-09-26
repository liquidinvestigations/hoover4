"""Page construction and the `read_more` collection MCP tool.

The route decides paging. Every paged route returns `next_position`, `total` and
`partial` beside its units, and the broker applies one route paging policy
(:meth:`PagedTool.window`) to every route: it sends the route's `next_position` back as
the next request's `position`, and computes no position of its own.

A backend window that fits one page is returned whole. A window that does not fit is
stored once, as one raw artifact, on its first page. The later pages of that window
read byte ranges of the artifact with `artifacts.read_range`, and call no route. The
artifact holds a header line with the window's fields and columns, then one canonical
JSON line for each unit. The store target of a unit is the page share less the measured
envelope of this window: the bytes of a zero-unit page with the window fields and columns,
and a continuation that holds the largest position values. A unit whose page does not fit
that target is stored with string fields moved out of the line, largest first, until the
unit with its cut marker fits. The line carries `{"__cut": [{"field", "bytes"}, ...]}`,
one entry for each moved field in the order moved, and the raw bytes of each field follow
the line, each on its own line. The page cuts such a unit inside its first moved field with
the marker `{"cut": {"field", "returned_bytes", "total_bytes", "next_fields"}}`, where
`next_fields` lists the other moved fields. Its continuations read the rest of each moved
field in order, and then the next unit. A blob window (a text page, a diff, a cell) is
stored as the header line and the raw text.

The page share is the byte limit of one page. The agent's execution node gives the calls
of one model step one shared budget, and sends each call its share in the
`X-Hoover4-Page-Share` header. A call with no header gets `PAGE_LIMIT`. The header line of
a stored window records the share it was stored with. Every page is built within the
current share of its call, and never within a larger one. A page keeps the window fields
when a unit fits with them, and leaves them out when not one unit fits with them.

When not one unit fits the current share, the page returns the next unit as its canonical
JSON text, cut by UTF-8 bytes, with the marker `{"cut": {"field": "", "start_bytes",
"total_bytes"}}` in the page fields. The empty `field` is the JSON pointer of the whole
unit. For a unit stored with moved fields, that text is the unit as its cut page shows it,
with zero bytes of the first moved field, and the continuations then read the moved fields.
So every stored unit is readable at every share that holds this text page with one byte of
text. Below that share the page is an `invalid_argument` answer, and the same continuation
can be sent again in a step with fewer calls.

The call measure is the `PageMeasure` that `build_page` returned for the page a tool call
returns. `measure_middleware` adds it to the tool result as one embedded resource with the
URI `CALL_MEASURE_URI`, beside the page text. The page text stays the only text content
block, so the page bytes do not change. The MCP adapter of the agent puts a non-text block
in the tool message artifact, which the model does not read.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Callable

from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware, MiddlewareContext
from mcp.types import EmbeddedResource, TextResourceContents
from pydantic import BaseModel, ValidationError

from agent_common import artifacts
from agent_common.result_pages import (
    ByteLimit, ContinuationInvalid, PageInput, PageMeasure, build_page, canonical_json, cut_unit,
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
#: Stands in for a byte position while the broker measures a page envelope. No stored
#: window has a position with more digits.
LARGEST_POSITION = 10**15
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
#: The fields of a unit that the broker never moves out of a stored unit, as JSON
#: pointers. A row without them cannot be read on or cited, so a cut row keeps them and
#: loses its snippet or its text.
IDENTITY_FIELDS = frozenset({"/file_hash", "/path", "/collectionname", "/dataset", "/collection_dataset"})
#: The keys a route tool's continuation position may hold.
POSITION_KEYS = frozenset({"window", "next", "artifact", "head", "start", "total", "cut", "blob", "part"})


#: The request header that carries the page share of one call, in UTF-8 bytes.
PAGE_SHARE_HEADER = "x-hoover4-page-share"
#: The largest page share the header can set. A larger value is cut to this.
MAX_PAGE_SHARE = 1_048_576
#: The largest stored header line a later page reads.
MAX_HEADER_BYTES = 4 * MAX_PAGE_SHARE
#: The URI of the embedded resource that carries the call measure.
CALL_MEASURE_URI = "hoover4://call-measure"


def page_share() -> int:
    """The bytes one page of this call may take: the `X-Hoover4-Page-Share` header, cut to
    `MAX_PAGE_SHARE`, or `PAGE_LIMIT` when the header is absent or is not a positive
    integer."""
    raw = get_http_headers().get(PAGE_SHARE_HEADER, "").strip()
    try:
        value = int(raw)
    except ValueError:
        return PAGE_LIMIT.max_bytes
    if value <= 0:
        return PAGE_LIMIT.max_bytes
    return min(value, MAX_PAGE_SHARE)


#: The measures that `build_page` returned during the current tool call, or `None`
#: outside a call that `measure_middleware` wraps.
_CALL_MEASURES: contextvars.ContextVar[list[PageMeasure] | None] = contextvars.ContextVar(
    "call_measures", default=None,
)


def _build(p: PageInput, limit: ByteLimit) -> tuple[str, PageMeasure]:
    """`build_page`, with the measure kept for the call measure of the current call."""
    text, measure = build_page(p, limit)
    kept = _CALL_MEASURES.get()
    if kept is not None:
        kept.append(measure)
    return text, measure


def _build_fitting(make: Callable[[dict[str, Any] | None], PageInput], fields: dict[str, Any] | None) -> str | None:
    """The page of `make(fields)` within the current share. When not one unit fits with
    `fields`, the page without `facet_counts`, and then the page with no fields. `None`
    when not one unit fits in any of them. The facets are the large field, so the rewrite
    note and the `partial` flag stay on a page that cannot also hold the facets."""
    candidates: list[dict[str, Any] | None] = [fields]
    if fields and "facet_counts" in fields and len(fields) > 1:
        candidates.append({key: value for key, value in fields.items() if key != "facet_counts"})
    if fields:
        candidates.append(None)
    for page_fields in candidates:
        text, measure = _build(make(page_fields), _page_limit())
        if measure.returned_units > 0:
            return text
    return None


def call_measure(text: str, measures: list[PageMeasure]) -> dict[str, Any] | None:
    """The measure of the page `text`, found by its digest, or `None` when no measure
    of the call has that digest."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    for measure in reversed(measures):
        if measure.page_sha256 == digest:
            return asdict(measure)
    return None


class MeasureMiddleware(Middleware):
    """Adds the call measure of a paged tool call to its result, as one embedded
    resource after the page text."""

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        measures: list[PageMeasure] = []
        token = _CALL_MEASURES.set(measures)
        try:
            result = await call_next(context)
        finally:
            _CALL_MEASURES.reset(token)
        content = list(getattr(result, "content", None) or [])
        if len(content) != 1 or getattr(content[0], "type", "") != "text" or not measures:
            return result
        measure = call_measure(content[0].text, measures)
        if measure is None:
            return result
        measure["page_share"] = page_share()
        content.append(EmbeddedResource(type="resource", resource=TextResourceContents(
            uri=CALL_MEASURE_URI, mimeType="application/json", text=canonical_json(measure),
        )))
        result.content = content
        return result


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
    page, measure = _build(
        PageInput(tool.tool_name, tool.shape, window.items, window.columns, total, {"window": window_position},
                  source, _input(request), None, after, window.fields),
        _page_limit(),
    )
    if measure.returned_units >= units:
        return page
    try:
        artifact_id, body, head = _store_window(tool, window, _input(request), window_position)
    except artifacts.ArtifactWriteFailed as exc:
        return canonical_json({"success": False, "error": "artifact_write_failed", "message": str(exc)})
    position = {"window": window_position, "next": window.next, "artifact": artifact_id, "head": head,
                "start": head, "total": window.total}
    if tool.shape == "blob":
        position["blob"] = 1
    return _stored_page(tool, request, position, _memory_reader(body), fields=window.fields, columns=window.columns)


def _envelope_bytes(tool: PagedTool, window: Window, request_input: dict[str, Any],
                    window_position: dict | None, cut_field: str | None) -> int:
    """The bytes of a page of this stored window less its units. That is a zero-unit page
    with the window columns, and a continuation that holds the largest position values,
    with a `cut` position into the field `cut_field` when it is not `None`.

    The window fields, the facets among them, are not measured. A page that cannot hold
    the fields and its first unit leaves the fields for a later page (`_build_fitting`),
    so the fields move to the continuation before a field of a unit is cut."""
    position: dict[str, Any] = {
        "window": window_position, "next": window.next, "artifact": PENDING_ARTIFACT_ID,
        "head": LARGEST_POSITION, "total": window.total, "start": LARGEST_POSITION,
    }
    if cut_field is not None:
        position["cut"] = {"field": cut_field, "base": LARGEST_POSITION, "end": LARGEST_POSITION, "line": LARGEST_POSITION}
    text, _ = build_page(
        PageInput(tool.tool_name, tool.shape, [None], window.columns, window.total, {},
                  window.fields.get("source", ""), request_input, PENDING_ARTIFACT_ID,
                  lambda count: position, None),
        ByteLimit(MAX_HEADER_BYTES),
    )
    return len(text.encode("utf-8")) - len(canonical_json(None))


def _store_window(tool: PagedTool, window: Window, request_input: dict[str, Any],
                  window_position: dict | None) -> tuple[str, bytes, int]:
    """Write the window as one artifact, and return its id, its body and the header length.
    The header records the page share that the lines were stored with."""
    share = page_share()
    head = (canonical_json({"fields": window.fields, "columns": window.columns, "share": share}) + "\n").encode("utf-8")
    parts = [head]
    if tool.shape == "blob":
        parts.append((window.items[0] if window.items else "").encode("utf-8"))
    else:
        envelope = lambda cut_field: _envelope_bytes(tool, window, request_input, window_position, cut_field)
        whole_target = share - envelope(None)
        for unit in window.items:
            parts.extend(_stored_unit(unit, share, whole_target, envelope))
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


def _stored_unit(unit: Any, share: int, whole_target: int, envelope: Callable[[str], int]) -> list[bytes]:
    """The stored lines of one unit. A unit whose line is longer than `whole_target` has
    string fields moved out, largest first, until the unit as its cut page shows it fits
    `share` less `envelope(first moved field)`. The fields of `IDENTITY_FIELDS` never move.
    Each moved field follows the line as a raw segment, in the order of its `__cut` entry.
    A unit that still does not fit is read as unit text pages."""
    line = canonical_json(unit).encode("utf-8")
    if len(line) <= whole_target or not isinstance(unit, dict):
        return [line, b"\n"]
    stripped: Any = unit
    moved: list[tuple[str, bytes]] = []
    cut_target = 0
    while True:
        found = largest_string_field(stripped, exclude=IDENTITY_FIELDS)
        if found is None or not found[0] or not found[1]:
            break
        pointer, text = found
        stripped = replace_at_pointer(stripped, pointer, "")
        moved.append((pointer, text.encode("utf-8")))
        if len(moved) == 1:
            cut_target = share - envelope(pointer)
        shown = _shown_cut_unit(stripped, [field for field, _ in moved], len(moved[0][1]))
        if len(canonical_json(shown).encode("utf-8")) <= cut_target:
            break
    if not moved:
        return [line, b"\n"]
    parts = [_cut_line(stripped, moved), b"\n"]
    for _, raw in moved:
        parts.extend([raw, b"\n"])
    return parts


def _shown_cut_unit(stripped: dict, fields: list[str], first_bytes: int, kept: bytes = b"") -> dict:
    """A unit stored with the moved `fields` as its cut page shows it: `kept` bytes of the
    first moved field, and the marker that names the other moved fields."""
    unit = cut_unit(stripped, fields[0], kept, first_bytes)
    if len(fields) > 1:
        unit["cut"]["next_fields"] = fields[1:]
    return unit


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


def _read_line(read: Reader, start: int, length: int) -> tuple[bytes, int]:
    """The stored line that starts at `start`, without its newline, and the artifact size.
    It reads `length` bytes, and up to `MAX_HEADER_BYTES` when the line is longer."""
    data, size = read(start, length)
    newline = data.find(b"\n")
    if newline < 0 and len(data) < size - start:
        data, size = read(start, MAX_HEADER_BYTES)
        newline = data.find(b"\n")
    if newline < 0:
        raise ValueError(f"the stored unit at byte {start} has no complete line")
    return data[:newline], size


def _following_segment(read: Reader, cut: dict[str, Any], length: int) -> dict[str, Any] | None:
    """The moved field stored after the one `cut` names, read from the unit's stored line,
    or `None` after the last moved field."""
    if "line" not in cut:
        return None
    line_start = int(cut["line"])
    line, _ = _read_line(read, line_start, length)
    record = json.loads(line.decode("utf-8"))
    segments = _cut_segments(record["__cut"], line_start, line_start + len(line) + 1)
    for index, segment in enumerate(segments):
        if segment["base"] == int(cut["base"]):
            return segments[index + 1] if index + 1 < len(segments) else None
    raise ValueError("the continuation names no moved field of the stored unit")


Reader = Callable[[int, int], tuple[bytes, int]]


def _memory_reader(body: bytes) -> Reader:
    """Reads the stored window that this call has just written, with the clamp of
    `artifacts.read_range`. The caller gives the length, which is the header length, the
    larger of the stored share and the current share, or `MAX_HEADER_BYTES` for a stored
    line longer than that. `MAX_HEADER_BYTES` cuts it."""
    def read(start: int, length: int) -> tuple[bytes, int]:
        if start >= len(body):
            raise artifacts.ArtifactRangeRefused(f"start {start} is past the end of the artifact")
        return body[start:start + min(length, MAX_HEADER_BYTES)], len(body)
    return read


def _artifact_reader(artifact_id: str) -> Reader:
    headers = {key.lower(): value for key, value in get_http_headers().items()}
    username = headers.get("x-hoover4-user", "")
    session_id = headers.get("x-hoover4-chat-session", "")

    def read(start: int, length: int) -> tuple[bytes, int]:
        return artifacts.read_range(username, session_id, artifact_id, start, min(length, MAX_HEADER_BYTES))
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
    # The header is read whole whatever the current share, so that a later page keeps the
    # window's fields and its source. A window stored before the header held its share was
    # stored with `PAGE_LIMIT`.
    header = json.loads(read(0, head)[0].decode("utf-8"))
    first_page = fields is not None
    if fields is None:
        fields, columns = header.get("fields") or {}, header.get("columns")
    # A read takes the larger of the stored share and the current share. Every page is
    # then built within the current share.
    length = max(int(header.get("share") or PAGE_LIMIT.max_bytes), page_share())
    fields = fields or {}
    source = fields.get("source", "")
    page_input = lambda shape, items, total, after, page_fields, cols=None: PageInput(
        tool.tool_name, shape, items, cols, total, {**base, "start": start}, source, _input(request),
        position["artifact"], after, page_fields,
    )
    too_small = lambda: _share_too_small(start, first_page)

    if position.get("blob"):
        data, size = read(start, length)
        text = utf8_prefix(data, len(data)).decode("utf-8")
        after = lambda count: {**base, "blob": 1, "start": start + count} if start + count < size else source_end
        return _build_fitting(lambda page_fields: page_input("blob", [text], size - head, after, page_fields), fields) or too_small()

    cut = position.get("cut")
    if cut:
        end = int(cut["end"])
        data, size = read(start, min(length, end - start))
        text = utf8_prefix(data, len(data)).decode("utf-8")
        marker = {"cut": {"field": cut["field"], "start_bytes": start - int(cut["base"]), "total_bytes": end - int(cut["base"])}}
        following: list[dict[str, Any] | None] = []

        def after_cut(count: int) -> dict | None:
            if start + count < end:
                return {**base, "start": start + count, "cut": cut}
            if not following:
                following.append(_following_segment(read, cut, length))
            return _after_segment(base, following[0], end, size, source_end)
        return _build_fitting(lambda _: page_input("blob", [text], end - int(cut["base"]), after_cut, marker), None) or too_small()

    text_page = lambda line, size, offset: _unit_text_page(base, start, line, size, offset, source_end, page_input, fields) or too_small()
    if "part" in position:
        line, size = _read_line(read, start, length)
        return text_page(line, size, int(position["part"]))

    data, size = read(start, length)
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
            return _cut_unit_page(tool, base, start, newline + 1, data, size, record, source_end, page_input, fields, columns) \
                or text_page(data[:newline], size, 0)
        units.append(record)
        offset = newline + 1
        ends.append(start + offset)
    if not units:
        line, size = _read_line(read, start, length)
        return text_page(line, size, 0)

    def after_units(count: int) -> dict | None:
        following = ends[count - 1] if count else start
        return {**base, "start": following} if following < size else source_end
    total = int(position.get("total", len(units)))
    page = _build_fitting(lambda page_fields: page_input(tool.shape, units, total, after_units, page_fields, columns), fields)
    return page or text_page(data[:ends[0] - start - 1], size, 0)


def _unit_text_page(base, line_start, line, size, offset, source_end, page_input, fields) -> str | None:
    """A page of the unit whose stored line starts at `line_start`, as its canonical JSON
    text from byte `offset`. A unit stored with moved fields is the unit as its cut page
    shows it, with zero bytes of the first moved field, and the page after the text reads
    that field. `None` when not one byte fits the current share."""
    record = json.loads(line.decode("utf-8"))
    if isinstance(record, dict) and "__cut" in record:
        segments = _cut_segments(record.pop("__cut"), line_start, line_start + len(line) + 1)
        first = segments[0]
        unit = _shown_cut_unit(record, [segment["field"] for segment in segments], first["end"] - first["base"])
        done = {**base, "start": first["base"], "cut": first}
    else:
        unit = record
        end = line_start + len(line) + 1
        done = {**base, "start": end} if end < size else source_end
    whole = canonical_json(unit).encode("utf-8")
    if offset >= len(whole):
        raise ValueError(f"byte {offset} is past the end of the unit text")
    text = utf8_prefix(whole[offset:], len(whole)).decode("utf-8")
    after = lambda count: {**base, "start": line_start, "part": offset + count} if offset + count < len(whole) else done
    marker = {"cut": {"field": "", "start_bytes": offset, "total_bytes": len(whole)}}
    return _build_fitting(lambda page_fields: page_input("blob", [text], len(whole), after, {**(page_fields or {}), **marker}), fields)


def _share_too_small(start: int, first_page: bool) -> str:
    """The answer when a page of the current share cannot hold one byte of the next unit,
    because the page envelope alone is larger than the share."""
    again = ("Call the tool again" if first_page else "Send the same continuation again") + " in a step with fewer tool calls."
    return _invalid(
        f"a page of {page_share()} bytes cannot hold one byte of the unit stored at byte {start} "
        f"of this result, because the page envelope is larger. {again}"
    )


def _after_segment(base: dict[str, Any], segment: dict[str, Any] | None, end: int, size: int, source_end: dict | None) -> dict | None:
    """The position after a moved field that ends at `end`: the next moved field of the
    same unit, the next stored unit, or the next backend window."""
    if segment is not None:
        return {**base, "start": segment["base"], "cut": segment}
    return {**base, "start": end + 1} if end + 1 < size else source_end


def _cut_unit_page(tool, base, start, raw_offset, data, size, record, source_end, page_input, fields, columns) -> str | None:
    """The page of one unit too large for a page, cut inside its first moved field. The
    marker lists the other moved fields, which the continuations read in order. `None`
    when the unit with zero bytes of that field does not fit the current share."""
    segments = _cut_segments(record.pop("__cut"), start, start + raw_offset)
    first = segments[0]
    raw_start, raw_end = first["base"], first["end"]
    total_bytes = raw_end - raw_start
    available = data[raw_offset:raw_offset + total_bytes]
    following = segments[1] if len(segments) > 1 else None
    moved = [segment["field"] for segment in segments]

    def attempt(keep: int, page_fields: dict | None) -> tuple[str, int]:
        kept = utf8_prefix(available, keep)
        position_after = raw_start + len(kept)
        after = lambda count: (
            {**base, "start": position_after, "cut": first} if position_after < raw_end
            else _after_segment(base, following, raw_end, size, source_end)
        )
        unit = _shown_cut_unit(record, moved, total_bytes, kept)
        text, measure = _build(page_input(tool.shape, [unit], int(base.get("total", 1)), after, page_fields, columns), _page_limit())
        return text, measure.returned_units

    for page_fields in ([fields, None] if fields else [fields]):
        best = attempt(0, page_fields)
        if best[1]:
            break
    else:
        return None
    low, high = 0, len(available)
    while low <= high:
        middle = (low + high) // 2
        text, returned = attempt(middle, page_fields)
        if returned:
            best, low = (text, returned), middle + 1
        else:
            high = middle - 1
    return best[0]


def error_text(error: AgentError) -> str:
    return canonical_json(error.model_dump())


def _position_is_valid(handler: Any, position: dict[str, Any]) -> bool:
    """The shape check of a continuation position. A position is checked here for its
    types only: the route checks the window position, and `read_range`
    clamps the byte range and checks the artifact owner."""
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
    if "part" in position and (type(position["part"]) is not int or position["part"] < 0
                               or "cut" in position or position.get("blob")):
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

mcp.add_middleware(MeasureMiddleware())


@mcp.tool(name="read_more", description="Read the next page from a prior paged tool result. Use it when that result contains a continuation token.")
def read_more(continuation: str) -> str:
    """Read only a continuation issued by this server."""
    try:
        return _read_more_response(decode_continuation(continuation))
    except ContinuationInvalid as exc:
        return canonical_json({"success": False, "error": "invalid_argument", "message": str(exc)})
