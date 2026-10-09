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
URI `CALL_MEASURE_URI`, beside the page text. It adds the doc refs as a second embedded
resource with the URI `DOC_REFS_URI`: the whole identity of each row of the page, in page
order, which the page itself names by a 16-character hash start. The page text stays the
only text content block, so the page bytes do not change. The MCP adapter of the agent puts
a non-text block in the tool message artifact, which the model does not read.

A page with more units carries `more`, a 12-character handle. `finish`, which the
middleware runs on every tool result, stores the encoded continuation that the handle names once, as a chat artifact of the kind
`agent_continuation` whose id is a UUID of the chat session and the handle. `read_more`
reads the continuation of a handle, and still decodes an encoded continuation.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import re
import uuid
from collections import OrderedDict
from dataclasses import asdict, dataclass, replace
from typing import Any, Callable

from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware, MiddlewareContext
from mcp.types import EmbeddedResource, TextResourceContents
from pydantic import BaseModel, ValidationError

from agent_common import artifacts
from agent_common.result_pages import (
    ByteLimit, ContinuationInvalid, PageInput, PageMeasure, build_page, canonical_json, continuation_handle,
    cut_unit, decode_continuation, largest_string_field, replace_at_pointer, utf8_prefix,
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
POSITION_KEYS = frozenset({"window", "next", "artifact", "head", "start", "stop", "total", "cut", "blob", "part"})


#: The request header that carries the page share of one call, in UTF-8 bytes.
PAGE_SHARE_HEADER = "x-hoover4-page-share"
#: The largest page share the header can set. A larger value is cut to this.
MAX_PAGE_SHARE = 1_048_576
#: The largest stored header line a later page reads.
MAX_HEADER_BYTES = 4 * MAX_PAGE_SHARE
#: The URI of the embedded resource that carries the call measure.
CALL_MEASURE_URI = "hoover4://call-measure"
#: The URI of the embedded resource that carries the whole identity of each row of a page.
DOC_REFS_URI = "hoover4://doc-refs"
#: The characters of a file hash that a page shows.
HASH_START = 16
#: The key under which a local tool's result carries the doc refs of its rows.
REFS_KEY = "__refs"
#: The row keys of `read_documents` that a page does not show.
READ_DROPPED_KEYS = frozenset({"collection_dataset", "title", "source_used", "count_state", "next_position"})
#: The namespace of the artifact ids of stored continuations.
MORE_NAMESPACE = uuid.UUID("5f0c8a4e-2b7d-4c61-9e3a-7d1f0b6c2a95")
_HANDLE_RE = re.compile(r"^[0-9a-f]{12}$")
#: The continuations of the pages that `build_page` returned lately, by handle. `finish`
#: stores the one that the returned page names. A candidate page that was not returned
#: writes nothing, and its entry leaves this map when newer entries arrive.
_TOKENS: OrderedDict[str, str] = OrderedDict()
_TOKENS_KEPT = 4096
_UNIT_SHARE: contextvars.ContextVar[int | None] = contextvars.ContextVar("unit_share", default=None)


def hash_start(value: str) -> str:
    """The first `HASH_START` characters of a file hash."""
    return value[:HASH_START] if isinstance(value, str) else value


def doc_ref(row: dict[str, Any], page_id: int | None = None, snippet: str | None = None) -> dict[str, Any]:
    """The whole identity of one row: collection, dataset, 64-character hash, path, page and
    snippet."""
    return {
        "collectionname": row.get("collectionname") or "",
        "collection_dataset": row.get("collection_dataset") or "",
        "file_hash": row.get("file_hash") or "",
        "path": row.get("path") or "",
        "page_id": page_id if page_id is not None else row.get("page_id", row.get("page")),
        "snippet": snippet if snippet is not None else (row.get("snippet") or ""),
    }


def slim_items(tool_name: str, items: list[Any]) -> tuple[list[Any], list[dict[str, Any]]]:
    """The units of a page as the model reads them, and the doc ref of each unit that names a
    document. A unit's `file_hash` becomes its first `HASH_START` characters. A
    `read_documents` unit also loses the keys of `READ_DROPPED_KEYS` and every empty value."""
    out: list[Any] = []
    refs: list[dict[str, Any]] = []
    for item in items:
        if tool_name == "list_collections" and isinstance(item, dict):
            out.append({"collectionname": item.get("collectionname") or "",
                        "documents": item.get("document_count") or 0,
                        "datasets": {row.get("name") or "": row.get("document_count") or 0
                                     for row in item.get("datasets") or []}})
            continue
        if not isinstance(item, dict) or not isinstance(item.get("file_hash"), str):
            out.append(item)
            continue
        ref = doc_ref(item)
        if tool_name == "read_documents":
            ref["evidence_kind"] = "document_read"
        refs.append(ref)
        slim = {**item, "file_hash": hash_start(item["file_hash"])}
        if tool_name == "read_documents":
            slim = {key: value for key, value in slim.items()
                    if key not in READ_DROPPED_KEYS and (key == "text" or value not in (None, False, "", [], {}))}
        out.append(slim)
    return out, refs


#: The doc refs that the current tool call read, or `None` outside a call that
#: `measure_middleware` wraps.
_CALL_REFS: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar(
    "call_refs", default=None,
)


def _note_refs(refs: list[dict[str, Any]] | None) -> None:
    kept = _CALL_REFS.get()
    if kept is not None and refs:
        kept.extend(refs)


def page_doc_refs(text: str, refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The doc ref of each row of the page `text`, in page order. A row is matched by its
    collection and its hash start. A row with no doc ref is left out."""
    try:
        page = json.loads(text)
    except ValueError:
        return []
    items = page.get("items") if isinstance(page, dict) else None
    if isinstance(page, dict) and isinstance(page.get("citations"), list):
        return refs
    if not isinstance(items, list):
        return []
    content_refs = [ref for ref in refs if ref.get("evidence_kind") == "document_read"]
    if content_refs and items and not any(isinstance(item, dict) and item.get("file_hash") for item in items):
        return content_refs
    by_start: dict[tuple[str, str], dict[str, Any]] = {}
    for ref in refs:
        key = (ref.get("collectionname") or "", hash_start(ref.get("file_hash") or ""))
        by_start.setdefault(key, ref)
    out = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("file_hash"), str):
            ref = by_start.get((item.get("collectionname") or "", item["file_hash"]))
            if ref is not None:
                out.append(ref)
    return out


def _session_and_user() -> tuple[str, str]:
    headers = {key.lower(): value for key, value in get_http_headers().items()}
    return headers.get("x-hoover4-chat-session", ""), headers.get("x-hoover4-user", "")


def handle_artifact_id(handle: str) -> str:
    """The artifact id of the continuation that `handle` names in this chat session."""
    session, _ = _session_and_user()
    return str(uuid.uuid5(MORE_NAMESPACE, f"{session}:{handle}"))


def store_handle(token: str) -> str:
    """Store the encoded continuation `token` under its handle, and return the handle. The
    same token gives the same artifact id, so a retried call writes the same row."""
    handle = continuation_handle(token)
    session, user = _session_and_user()
    artifact_id = handle_artifact_id(handle)
    artifacts.write_required(
        artifacts.ArtifactRequest(session_id=session, username=user,
                                  kind=artifacts.KIND_AGENT_CONTINUATION, tool_name="read_more",
                                  title=handle, detail={key.lower(): value for key, value in get_http_headers().items()}.get("x-hoover4-agent-run", "")),
        artifact_id, artifact_id, token.encode("utf-8"), "text/plain",
    )
    return handle


def finish(text: str) -> str:
    """The page `text` as a tool returns it, after the continuation of its `more` handle is
    stored. A page with no `more` writes nothing. A failed store is an
    `artifact_write_failed` answer, because the handle would name nothing."""
    if '"more":"' not in text:
        return text
    try:
        page = json.loads(text)
    except ValueError:
        return text
    handle = page.get("more") if isinstance(page, dict) else None
    token = _TOKENS.get(handle) if isinstance(handle, str) else None
    if token is None:
        return text
    try:
        store_handle(token)
    except artifacts.ArtifactWriteFailed as exc:
        return canonical_json({"success": False, "error": "artifact_write_failed", "message": str(exc)})
    return text


def page_share() -> int:
    """The bytes one page of this call may take: the `X-Hoover4-Page-Share` header, cut to
    `MAX_PAGE_SHARE`, or `PAGE_LIMIT` when the header is absent or is not a positive
    integer."""
    override = _UNIT_SHARE.get()
    if override is not None:
        return override
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
    if measure.continuation_token is not None:
        _TOKENS[continuation_handle(measure.continuation_token)] = measure.continuation_token
        while len(_TOKENS) > _TOKENS_KEPT:
            _TOKENS.popitem(last=False)
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
    resource after the page text, and the doc refs of the page's rows as a second one."""

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        measures: list[PageMeasure] = []
        refs: list[dict[str, Any]] = []
        token = _CALL_MEASURES.set(measures)
        refs_token = _CALL_REFS.set(refs)
        try:
            result = await call_next(context)
        finally:
            _CALL_MEASURES.reset(token)
            _CALL_REFS.reset(refs_token)
        content = list(getattr(result, "content", None) or [])
        if len(content) != 1 or getattr(content[0], "type", "") != "text":
            return result
        text = finish(content[0].text)
        if text != content[0].text:
            content[0] = content[0].model_copy(update={"text": text})
            result.content = content
        if not measures and not refs:
            return result
        if measures:
            measure = call_measure(content[0].text, measures)
            if measure is None:
                return result
            measure["page_share"] = page_share()
            measure.pop("continuation_token", None)
            content.append(EmbeddedResource(type="resource", resource=TextResourceContents(
                uri=CALL_MEASURE_URI, mimeType="application/json", text=canonical_json(measure),
            )))
        doc_refs = page_doc_refs(content[0].text, refs)
        if doc_refs:
            content.append(EmbeddedResource(type="resource", resource=TextResourceContents(
                uri=DOC_REFS_URI, mimeType="application/json", text=canonical_json(doc_refs),
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
    #: The doc ref of each unit that names a document, which the page shows by hash start.
    refs: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class PagedTool:
    """The route and page adapter for one continuation-capable tool."""

    model: type[AgentModel]
    route: str
    tool_name: str
    shape: str
    item_key: str
    columns_key: str | None = None
    max_rows: int | None = None

    def window(self, result: dict[str, Any], request: BaseModel | None = None) -> Window:
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
        elif self.item_key == "__email_entries":
            graph = result.get("graph") or {}
            items = [*({"field": "attachments", "value": value} for value in result.get("attachments", [])),
                     *({"field": "graph_nodes", "value": value} for value in graph.get("nodes", [])),
                     *({"field": "graph_edges", "value": value} for value in graph.get("edges", []))]
            excluded.update(("attachments", "graph", "total"))
        else:
            raw_items = result.get(self.item_key, [])
            items = raw_items if isinstance(raw_items, list) else [raw_items]
        refs: list[dict[str, Any]] = []
        if self.shape == "blob":
            text = items[0] if items else ""
            items = [text if isinstance(text, str) else canonical_json(text)]
        else:
            items, refs = slim_items(self.tool_name, items)
        if self.columns_key:
            excluded.add(self.columns_key)
        fields = {key: value for key, value in result.items() if key not in excluded}
        if self.item_key == "__email_entries":
            fields["graph_counts"] = {"nodes": len(graph.get("nodes", [])), "edges": len(graph.get("edges", [])),
                                      "cluster_size": graph.get("cluster_size", 0), "truncated": graph.get("truncated", False)}
        columns = result.get(self.columns_key) if self.columns_key else None
        next_position = result.get("next_position")
        total = result.get("total")
        if not isinstance(total, int) or self.item_key == "__email_entries":
            total = len(items)
        return Window(items, fields, columns, next_position, total, refs)

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
        prepared = self.window(result, request)
        values = _input(request)
        has_content = bool(prepared.items) and (self.tool_name != "table_cell" or bool(result.get("text")))
        if self.tool_name in ("table_page", "table_cell") and has_content and values.get("file_hash"):
            prepared = replace(prepared, refs=[{"collectionname": values["collectionname"], "file_hash": values["file_hash"],
                                               "evidence_kind": "document_read"}])
        return _live_page(self, request, window, prepared)


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
    _note_refs(window.refs)
    units = len(window.items[0].encode("utf-8")) if tool.shape == "blob" and window.items else len(window.items)
    pending = {"artifact": PENDING_ARTIFACT_ID, "start": 0}
    after = lambda count: _after_window(window) if count >= units else pending
    total = units if tool.shape == "blob" else window.total
    page, measure = _build(
        PageInput(tool.tool_name, tool.shape, window.items, window.columns, total, {"window": window_position},
                  source, _input(request), None, after, window.fields, tool.max_rows),
        _page_limit(),
    )
    if measure.returned_units >= units:
        return page
    try:
        artifact_id, body, head, _ = _store_window(tool, window, _input(request), window_position)
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
                  window_position: dict | None, *, artifact_id: str | None = None,
                  stored_share: int | None = None) -> tuple[str, bytes, int, list[int]]:
    """Write the window as one artifact, and return its id, its body and the header length.
    The header records the page share that the lines were stored with."""
    share = stored_share or page_share()
    header = {"fields": window.fields, "columns": window.columns, "share": share}
    if window.refs:
        header["refs"] = window.refs
    head = (canonical_json(header) + "\n").encode("utf-8")
    parts = [head]
    ends: list[int] = []
    offset = len(head)
    if tool.shape == "blob":
        parts.append((window.items[0] if window.items else "").encode("utf-8"))
    else:
        envelope = lambda cut_field: _envelope_bytes(tool, window, request_input, window_position, cut_field)
        whole_target = share - envelope(None)
        for unit in window.items:
            segments = _stored_unit(unit, share, whole_target, envelope)
            parts.extend(segments)
            offset += sum(len(segment) for segment in segments)
            ends.append(offset)
    body = b"".join(parts)
    headers = {key.lower(): value for key, value in get_http_headers().items()}
    request = artifacts.ArtifactRequest(
        session_id=headers.get("x-hoover4-chat-session", ""),
        username=headers.get("x-hoover4-user", ""),
        kind=artifacts.KIND_AGENT_RAW_RESULT,
        tool_name=tool.tool_name,
    )
    artifact_id = artifact_id or str(uuid.uuid4())
    artifacts.write_required(request, artifact_id, artifact_id, body, ARTIFACT_CONTENT_TYPE)
    return artifact_id, body, len(head), ends


def unit_limits(share: int, envelope: int, n: int) -> list[int]:
    """Give each document an equal part of the page content bytes."""
    if n <= 0:
        return []
    return [max(0, (share - envelope) // n)] * n


def render_document_reads(tool: PagedTool, request: BaseModel) -> str:
    """Return one read item per document, with a continuation on each cut item."""
    result = BackendClient().post(tool.route, request, RESPONSE_MODELS[tool.route])
    if isinstance(result, AgentError):
        return error_text(result)
    window = tool.window(result.model_dump(mode="json", by_alias=True))
    n = len(window.items)
    if n == 0:
        return _live_page(tool, request, None, window)
    share = page_share()
    envelope = len(canonical_json({"items": [], **window.fields}).encode("utf-8")) + n * 70
    per = unit_limits(share, envelope, n)[0]
    if per < 1:
        return _invalid("the page share cannot hold one byte of each document")
    if all(len(canonical_json(item).encode("utf-8")) <= per for item in window.items):
        preview, measured = _build(
            PageInput(tool.tool_name, "rows", window.items, None, window.total, {},
                      window.fields.get("source", ""), _input(request), None,
                      lambda count: _after_window(window) if count >= n else None,
                      window.fields), _page_limit()
        )
        if measured.returned_units == n:
            _note_refs(window.refs)
            return preview
    _note_refs(window.refs)
    token = _UNIT_SHARE.set(per)
    try:
        artifact_id, body, head, ends = _store_window(tool, window, _input(request), None)
    except artifacts.ArtifactWriteFailed as exc:
        return canonical_json({"success": False, "error": "artifact_write_failed", "message": str(exc)})
    finally:
        _UNIT_SHARE.reset(token)
    for _ in range(8):
        items: list[dict[str, Any]] = []
        start = head
        for original, end in zip(window.items, ends):
            position = {"artifact": artifact_id, "head": head, "start": start,
                        "stop": end, "total": 1}
            token = _UNIT_SHARE.set(per)
            try:
                page = json.loads(_stored_page(tool, request, position, _memory_reader(body)))
            finally:
                _UNIT_SHARE.reset(token)
            if not page.get("items"):
                return _invalid("the page share cannot hold one byte of each document")
            item = page["items"][0]
            if page.get("more"):
                item["more"] = page["more"]
                shown = len(str(item.get("text") or "").encode("utf-8"))
                total = len(str(original.get("text") or "").encode("utf-8"))
                item["cut"] = f"{shown} of {total} bytes"
            items.append(item)
            start = end
        text, measure = _build(PageInput(tool.tool_name, "rows", items, None, window.total, {},
                                         window.fields.get("source", ""), _input(request), None,
                                         lambda count: _after_window(window) if count >= n else None,
                                         window.fields), _page_limit())
        if measure.returned_units == n:
            try:
                for item in items:
                    if item.get("more"):
                        store_handle(_TOKENS[item["more"]])
            except artifacts.ArtifactWriteFailed as exc:
                return canonical_json({"success": False, "error": "artifact_write_failed", "message": str(exc)})
            return text
        per = per * 3 // 4
        if per < 1:
            break
    return _invalid("the page share cannot hold one byte of each document")


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
    if "stop" in position:
        stop = int(position["stop"])
        original_read = read

        def read(start: int, length: int) -> tuple[bytes, int]:
            data, _ = original_read(start, min(length, max(0, stop - start)))
            return data, stop

    start = int(position["start"])
    head = int(position["head"])
    base = {key: position[key] for key in ("window", "next", "artifact", "head", "stop", "total") if key in position}
    source_end = {"window": position["next"]} if position.get("next") and "stop" not in position else None
    # The header is read whole whatever the current share, so that a later page keeps the
    # window's fields and its source. A window stored before the header held its share was
    # stored with `PAGE_LIMIT`.
    header = json.loads(read(0, head)[0].decode("utf-8"))
    first_page = fields is not None
    if not first_page:
        _note_refs(header.get("refs"))
    if fields is None:
        fields, columns = header.get("fields") or {}, header.get("columns")
    # A read takes the larger of the stored share and the current share. Every page is
    # then built within the current share.
    length = max(int(header.get("share") or PAGE_LIMIT.max_bytes), page_share())
    fields = fields or {}
    source = fields.get("source", "")
    page_input = lambda shape, items, total, after, page_fields, cols=None: PageInput(
        tool.tool_name, shape, items, cols, total, {**base, "start": start}, source, _input(request),
        position["artifact"], after, page_fields, tool.max_rows,
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
        # The stored line is longer than one read. A unit stored with moved fields can be:
        # its `__cut` entries are longer than the cut marker that its page shows.
        line, size = _read_line(read, start, length)
        record = json.loads(line.decode("utf-8"))
        if isinstance(record, dict) and "__cut" in record:
            data, size = read(start, len(line) + 1 + length)
            return _cut_unit_page(tool, base, start, len(line) + 1, data, size, record, source_end, page_input, fields, columns) \
                or text_page(line, size, 0)
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
    if any(key in position and (type(position[key]) is not int or position[key] < 0) for key in ("head", "start", "stop", "total")):
        return False
    if "stop" in position and position["stop"] <= position.get("start", 0):
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

    handlers = {**tools_search.PAGED_TOOLS, **tools_document.PAGED_TOOLS, **tools_table.PAGED_TOOLS, **tools_folder.PAGED_TOOLS,
                RUNTIME_RESULT.tool_name: RUNTIME_RESULT}
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
    if handler is RUNTIME_RESULT and not position.get("artifact"):
        return _invalid("The runtime continuation must name a stored artifact.")
    if not _position_is_valid(handler, position):
        return _invalid("continuation position is invalid")
    try:
        request = handler.model.model_validate(input_values)
    except (KeyError, ValidationError) as exc:
        return canonical_json({"success": False, "error": "invalid_argument", "message": f"invalid continuation input: {exc}"})
    return handler.render(request, position, source)


from collection_search_server.server import mcp

mcp.add_middleware(MeasureMiddleware())


def _handle_token(handle: str) -> str | None:
    """The encoded continuation that `handle` names in this chat session, or None."""
    try:
        data, _ = _artifact_reader(handle_artifact_id(handle))(0, MAX_HEADER_BYTES)
    except (artifacts.ArtifactNotFound, artifacts.ArtifactForbidden, artifacts.ArtifactRangeRefused):
        return None
    return data.decode("utf-8")


READ_MORE_TEXT = "Read the rest of a result. Give the more value of that result or item as continuation."


class RuntimeResultRequest(BaseModel):
    run_id: str
    call_id: str


RUNTIME_RESULT = PagedTool(RuntimeResultRequest, "", "_page_tool_result", "blob", "text")
RUNTIME_RESULT_NAMESPACE = uuid.UUID("8ce209a8-d594-5aa2-9bb0-f482f46d38b0")


@mcp.tool(name="_page_tool_result", description="Store a complete result and return its first page for the agent runtime.")
def page_tool_result(run_id: str, call_id: str, content: str, max_bytes: int,
                     doc_refs: list[dict[str, Any]] | None = None) -> str:
    """Store the complete result under a stable run and call identity."""
    from collection_search_server import server

    server._caller()
    headers = {key.lower(): value for key, value in get_http_headers().items()}
    if not run_id or headers.get("x-hoover4-agent-run") != run_id:
        return _invalid("The result run does not match the caller run.")
    if not call_id or not 1024 <= max_bytes <= PAGE_LIMIT.max_bytes:
        return _invalid("The result page size or call identity is invalid.")
    request = RuntimeResultRequest(run_id=run_id, call_id=call_id)
    artifact_id = str(uuid.uuid5(RUNTIME_RESULT_NAMESPACE, f"{run_id}:{call_id}"))
    window = Window([content], {"source": f"{run_id}:{call_id}"}, None, None,
                    len(content.encode("utf-8")), doc_refs)
    artifact_id, body, head, _ = _store_window(
        RUNTIME_RESULT, window, _input(request), None, artifact_id=artifact_id,
        stored_share=PAGE_LIMIT.max_bytes)
    token = _UNIT_SHARE.set(max_bytes)
    try:
        return finish(_stored_page(RUNTIME_RESULT, request,
            {"artifact": artifact_id, "head": head, "start": head, "blob": 1}, _memory_reader(body)))
    finally:
        _UNIT_SHARE.reset(token)


def _issued_handles() -> list[str]:
    """Return continuation handles owned by the caller in this chat session."""
    from collection_search_server import backends

    session, user = _session_and_user()
    run = {key.lower(): value for key, value in get_http_headers().items()}.get("x-hoover4-agent-run", "")
    if not session or not user or not run:
        return []
    rows = backends.clickhouse_query(
        "SELECT title FROM chat_artifacts FINAL WHERE username = {user:String} "
        "AND session_id = {session:String} AND kind = {kind:String} "
        "AND detail = {run:String} AND is_deleted = 0 AND status = 'ok' ORDER BY artifact_id",
        backends.GLOBAL_DB, {"user": user, "session": session, "kind": artifacts.KIND_AGENT_CONTINUATION,
                            "run": run})
    return list(dict.fromkeys(row["title"] for row in rows if _HANDLE_RE.fullmatch(row.get("title", ""))))


def _one_character_damage(value: str, candidate: str) -> bool:
    if len(value) != len(candidate) or value == candidate:
        return False
    positions = [i for i, (a, b) in enumerate(zip(value, candidate)) if a != b]
    if len(positions) == 1:
        return True
    return (len(positions) == 2 and positions[1] == positions[0] + 1
            and value[positions[0]] == candidate[positions[1]]
            and value[positions[1]] == candidate[positions[0]])


@mcp.tool(name="read_more", description=READ_MORE_TEXT)
def read_more(continuation: str) -> str:
    """Read only a continuation issued by this server, given as its `more` handle or as the
    encoded continuation of a page stored before the handles."""
    value = (continuation or "").strip()
    repaired = None
    if len(value) == 12:
        token = _handle_token(value)
        if token is None:
            issued = _issued_handles()
            matches = [handle for handle in issued if _one_character_damage(value, handle)]
            if len(matches) == 1:
                repaired = matches[0]
                token = _handle_token(repaired)
            if token is None:
                return canonical_json({"success": False, "error": "not_found", "available_handles": issued[:5],
                                       "message": "No result has this more handle in this chat. Copy more from the result."})
        value = token
    try:
        text = _read_more_response(decode_continuation(value))
        if repaired:
            body = json.loads(text)
            body["continuation_note"] = f"The continuation was corrected to {repaired}."
            return canonical_json(body)
        return text
    except ContinuationInvalid as exc:
        return canonical_json({"success": False, "error": "invalid_argument", "message": str(exc)})
