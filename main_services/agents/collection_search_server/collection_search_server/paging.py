"""Page construction and the `read_more` collection MCP tool."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable

from fastmcp.server.dependencies import get_http_headers
from pydantic import BaseModel, ValidationError

from agent_common import artifacts
from agent_common.result_pages import ByteLimit, ContinuationInvalid, PageInput, build_page, canonical_json, decode_continuation
from collection_search_server.backend_client import (
    AgentError, AgentModel, AgentPosition, BackendClient, CollectionsListResponse,
    SearchResultsResponse, SearchFacetValuesResponse, SearchDateHistogramResponse,
    SearchEntityExplainerResponse, DocumentsReadResponse, DocumentsSourcesResponse,
    DocumentsMetadataResponse, DocumentsEmailResponse, DocumentsDiffSourcesResponse,
    DocumentsPdfSearchResponse, TablesOverviewResponse, TablesPageResponse,
    TablesColumnValuesResponse, TablesSearchCellsResponse, FoldersOverviewResponse,
    FoldersListResponse, FoldersSearchResponse,
)

PAGE_LIMIT = ByteLimit(24_000)
RESPONSE_MODELS: dict[str, type[AgentModel]] = {
    "collections/list": CollectionsListResponse,
    "search/results": SearchResultsResponse,
    "search/facet_values": SearchFacetValuesResponse,
    "search/date_histogram": SearchDateHistogramResponse,
    "search/entity_explainer": SearchEntityExplainerResponse,
    "documents/read": DocumentsReadResponse,
    "documents/sources": DocumentsSourcesResponse,
    "documents/metadata": DocumentsMetadataResponse,
    "documents/email": DocumentsEmailResponse,
    "documents/diff_sources": DocumentsDiffSourcesResponse,
    "documents/pdf_search": DocumentsPdfSearchResponse,
    "tables/overview": TablesOverviewResponse,
    "tables/page": TablesPageResponse,
    "tables/column_values": TablesColumnValuesResponse,
    "tables/search_cells": TablesSearchCellsResponse,
    "folders/overview": FoldersOverviewResponse,
    "folders/list": FoldersListResponse,
    "folders/search": FoldersSearchResponse,
}


@dataclass(frozen=True)
class PagedTool:
    """The route and page adapter for one continuation-capable tool."""

    model: type[AgentModel]
    route: str
    tool_name: str
    shape: str
    item_key: str
    columns_key: str | None = None

    def render(self, request: AgentModel, position: dict[str, int], source: str) -> str:
        page = int(position.get("page", 0))
        offset = int(position.get("offset", 0))
        if page < 0 or offset < 0:
            return canonical_json({"success": False, "error": "invalid_argument", "message": "continuation position is invalid"})
        if "position" in type(request).model_fields:
            request = request.model_copy(update={"position": AgentPosition(page=page)})
        result = BackendClient().post(self.route, request, RESPONSE_MODELS[self.route], expected_source=source or None)
        if isinstance(result, AgentError):
            return error_text(result)
        result = result.model_dump(mode="json", by_alias=True)
        if source and result.get("source", "") != source:
            return canonical_json({"success": False, "error": "source_changed", "message": "the source changed after the prior page"})
        encoded = canonical_json(result).encode("utf-8")
        if len(encoded) > 20_000 or position.get("blob") == 1:
            text = encoded[offset:].decode("utf-8")
            if self.route == "search/results":
                has_more = result["has_more"]
            elif self.route == "tables/page":
                has_more = (page + 1) * 50 < result["total_rows"]
            elif self.route == "folders/list":
                has_more = len({value["node_id"] for value in [*result["children"], *result["files"]]}) >= 200
            else:
                has_more = False
            def after_blob(count: int):
                if offset + count < len(encoded):
                    return {"page": page, "offset": offset + count, "blob": 1}
                if has_more:
                    return {"page": page + 1, "offset": 0, "blob": 1}
                return None
            return page_result(
                self.tool_name, request, result, "blob", [text],
                position={"page": page, "offset": offset, "blob": 1},
                total_units=len(encoded) + (1 if has_more else 0), position_after=after_blob,
            )
        if self.item_key == "__folder_items":
            folder_node_count = len({value["node_id"] for value in [*result["children"], *result["files"]]})
            items = [
                *({"field": "children", "value": value} for value in result["children"]),
                *({"field": "files", "value": value} for value in result["files"]),
            ]
        elif self.item_key == "__metadata_entries":
            items = [{"field": "raw_metadata", "key": key, "value": value} for key, value in result["raw_metadata"].items()]
        else:
            raw_items = result.get(self.item_key, [])
            items = raw_items if isinstance(raw_items, list) else [raw_items]
        excluded = {self.item_key}
        if self.item_key == "__folder_items":
            excluded.update(("children", "files"))
        if self.item_key == "__metadata_entries":
            excluded.add("raw_metadata")
        if self.columns_key:
            excluded.add(self.columns_key)
        fields = {key: value for key, value in result.items() if key not in excluded}
        if self.shape == "blob":
            text = items[0] if items else ""
            if not isinstance(text, str):
                text = canonical_json(text)
            items = [text.encode("utf-8")[offset:].decode("utf-8")]
            total = len(text.encode("utf-8"))
            start = {"page": page, "offset": offset}
            after = lambda count: None if offset + count >= total else {"page": page, "offset": offset + count}
        else:
            items = items[offset:]
            total = int(result.get("total_count", result.get("total_rows", offset + len(items))))
            start = {"page": page, "offset": offset}
            has_more = bool(result.get("has_more"))
            if self.route == "tables/page":
                has_more = (page * 50 + offset + len(items)) < total
            if self.route == "folders/list":
                has_more = folder_node_count >= 200
                if has_more:
                    total += 1
            next_page = page + 1 if has_more else None
            def after(count: int):
                if count < len(items):
                    return {"page": page, "offset": offset + count}
                if next_page is not None:
                    return {"page": next_page, "offset": 0}
                return None
        columns = result.get(self.columns_key) if self.columns_key else None
        return page_result(self.tool_name, request, result, self.shape, items, columns=columns, fields=fields, position=start, total_units=total, position_after=after)


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
    if (
        "page" not in position
        or "offset" not in position
        or any(
            key not in ("page", "offset", "blob") or type(value) is not int or value < 0
            for key, value in position.items()
        )
        or position.get("blob", 0) not in (0, 1)
    ):
        return canonical_json({"success": False, "error": "invalid_argument", "message": "continuation position is invalid"})
    handler = handlers.get(tool_name)
    if handler is None:
        return canonical_json({"success": False, "error": "invalid_argument", "message": "continuation names an unavailable paged tool"})
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
