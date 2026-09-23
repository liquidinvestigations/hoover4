"""Collection and search tools backed by the website agent API."""

from __future__ import annotations

from typing import Any

from fastmcp.server.dependencies import get_http_headers
from pydantic import ValidationError

from agent_common.result_pages import canonical_json
from collection_search_server.backend_client import (
    AgentError, AgentSort, CollectionsListRequest, SearchDateHistogramRequest,
    SearchEntityExplainerRequest, SearchFacetValuesRequest, SearchResultsRequest,
)
from collection_search_server.paging import PagedTool, error_text
from collection_search_server.server import mcp


LIST_COLLECTIONS = PagedTool(CollectionsListRequest, "collections/list", "list_collections", "rows", "collections")
SEARCH_COLLECTIONS = PagedTool(SearchResultsRequest, "search/results", "search_collections", "rows", "documents")
SEARCH_FACET_VALUES = PagedTool(SearchFacetValuesRequest, "search/facet_values", "search_facet_values", "rows", "terms")
SEARCH_DATE_HISTOGRAM = PagedTool(SearchDateHistogramRequest, "search/date_histogram", "search_date_histogram", "rows", "buckets")
SEARCH_ENTITY_EXPLAINER = PagedTool(SearchEntityExplainerRequest, "search/entity_explainer", "search_entity_explainer", "rows", "documents")
PAGED_TOOLS = {
    "list_collections": LIST_COLLECTIONS, "search_collections": SEARCH_COLLECTIONS,
    "search_facet_values": SEARCH_FACET_VALUES, "search_date_histogram": SEARCH_DATE_HISTOGRAM,
    "search_entity_explainer": SEARCH_ENTITY_EXPLAINER,
}


def _render(tool: PagedTool, values: dict[str, Any]) -> str:
    try:
        return tool.render(tool.model.model_validate(values), {}, "")
    except ValidationError as exc:
        return canonical_json({"success": False, "error": "invalid_argument", "message": str(exc)})


@mcp.tool(name="list_collections", description="List the permitted collections and their datasets. Use it to find collection names before a collection read.")
def list_collections() -> str:
    return _render(LIST_COLLECTIONS, {})


@mcp.tool(name="search_collections", description="Search permitted collections for documents. Use it to find document hashes and paths before reading documents.")
def search_collections(collectionname: list[str] | None = None, query: str = "", sort: AgentSort | None = None, date_after: int | None = None, date_before: int | None = None, date_confirmed_only: bool | None = None, size_min: int | None = None, size_max: int | None = None, folder_term_id: int | None = None, filename_only: bool | None = None, facet_filters: dict[str, list[str]] | None = None) -> str:
    return _render(SEARCH_COLLECTIONS, {"collectionname": collectionname or [], "query": query, "sort": sort, "date_after": date_after, "date_before": date_before, "date_confirmed_only": date_confirmed_only, "size_min": size_min, "size_max": size_max, "folder_term_id": folder_term_id, "filename_only": filename_only, "facet_filters": facet_filters or {}})


@mcp.tool(name="search_facet_values", description="Find facet values in permitted collections. Use it to choose values for a collection search filter.")
def search_facet_values(collectionname: list[str] | None = None, facet: str = "", query: str | None = None, ids: list[int] | None = None) -> str:
    return _render(SEARCH_FACET_VALUES, {"collectionname": collectionname or [], "facet": facet, "query": query, "ids": ids})


@mcp.tool(name="search_date_histogram", description="Return date buckets for a collection search. Use it to inspect document or mentioned dates before filtering.")
def search_date_histogram(collectionname: list[str] | None = None, query: str = "", date_field: str = "date", date_after: int | None = None, date_before: int | None = None, date_confirmed_only: bool | None = None, size_min: int | None = None, size_max: int | None = None, folder_term_id: int | None = None, filename_only: bool | None = None, facet_filters: dict[str, list[str]] | None = None) -> str:
    return _render(SEARCH_DATE_HISTOGRAM, {"collectionname": collectionname or [], "query": query, "date_field": date_field, "date_after": date_after, "date_before": date_before, "date_confirmed_only": date_confirmed_only, "size_min": size_min, "size_max": size_max, "folder_term_id": folder_term_id, "filename_only": filename_only, "facet_filters": facet_filters or {}})


@mcp.tool(name="search_entity_explainer", description="Explain one extracted entity value. Use it when a result names a rule and value that need context.")
def search_entity_explainer(collectionname: str, entity_type: str, entity_value: str) -> str:
    return _render(SEARCH_ENTITY_EXPLAINER, {"collectionname": collectionname, "entity_type": entity_type, "entity_value": entity_value})
