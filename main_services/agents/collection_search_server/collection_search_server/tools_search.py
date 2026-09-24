"""Collection and search tools backed by the website agent API, and `search_passages`,
the hybrid passage search of this server, paged by the same broker."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_common.result_pages import canonical_json
from collection_search_server.backend_client import (
    AgentError, AgentSort, CollectionsListRequest, SearchDateHistogramRequest,
    SearchEntityExplainerRequest, SearchFacetValuesRequest, SearchResultsRequest,
)
from collection_search_server.paging import PagedTool, error_text, page_result
from collection_search_server import server
from collection_search_server.server import mcp


@dataclass(frozen=True)
class LocalPagedTool:
    """A paged tool whose result this server computes, with the `model` and `render`
    interface of `PagedTool`, so `read_more` dispatches to it like to a route tool.

    `produce` returns the complete result as a JSON object. The broker pages the list
    under `item_key` as rows, and the other keys go into the page fields. The `source` is
    a digest of the complete result, so a continuation whose result changed is refused.
    """

    model: type[BaseModel]
    tool_name: str
    item_key: str
    produce: Callable[[Any], dict[str, Any]]

    def render(self, request: BaseModel, position: dict[str, int], source: str) -> str:
        offset = int(position.get("offset", 0))
        if offset < 0 or int(position.get("page", 0)) != 0:
            return canonical_json({"success": False, "error": "invalid_argument", "message": "continuation position is invalid"})
        result = self.produce(request)
        if result.get("success") is False:
            return canonical_json(result)
        digest = hashlib.sha256(canonical_json(result).encode("utf-8")).hexdigest()[:32]
        if source and source != digest:
            return canonical_json({"success": False, "error": "source_changed", "message": "the source changed after the prior page"})
        result = {**result, "source": digest}
        items = list(result.get(self.item_key) or [])
        fields = {key: value for key, value in result.items() if key != self.item_key}
        return page_result(
            self.tool_name, request, result, "rows", items[offset:], fields=fields,
            position={"page": 0, "offset": offset}, total_units=len(items),
            position_after=lambda count: None if offset + count >= len(items) else {"page": 0, "offset": offset + count},
        )


class SearchPassagesRequest(BaseModel):
    """The arguments of `search_passages`."""

    model_config = ConfigDict(extra="forbid")

    queries: list[str] = Field(min_length=1, max_length=server.MAX_QUERIES_PER_CALL)
    collectionname: list[str] = Field(default_factory=list)
    max_results: int = Field(default=server.DEFAULT_MAX_RESULTS, ge=1, le=server.MAX_ALLOWED_RESULTS)


def _search_passages(request: SearchPassagesRequest) -> dict[str, Any]:
    response = server.search_passages(
        queries=request.queries, collections=request.collectionname or None, max_results=request.max_results,
    )
    return response.model_dump(mode="json")


LIST_COLLECTIONS = PagedTool(CollectionsListRequest, "collections/list", "list_collections", "rows", "collections")
SEARCH_COLLECTIONS = PagedTool(SearchResultsRequest, "search/results", "search_collections", "rows", "documents")
SEARCH_FACET_VALUES = PagedTool(SearchFacetValuesRequest, "search/facet_values", "search_facet_values", "rows", "terms")
SEARCH_HISTOGRAM = PagedTool(SearchDateHistogramRequest, "search/histogram", "search_histogram", "rows", "buckets")
SEARCH_ENTITY_EXPLAINER = PagedTool(SearchEntityExplainerRequest, "search/entity_explainer", "search_entity_explainer", "rows", "documents")
SEARCH_PASSAGES = LocalPagedTool(SearchPassagesRequest, "search_passages", "results", _search_passages)
PAGED_TOOLS = {
    "list_collections": LIST_COLLECTIONS, "search_collections": SEARCH_COLLECTIONS,
    "search_facet_values": SEARCH_FACET_VALUES, "search_histogram": SEARCH_HISTOGRAM,
    "search_entity_explainer": SEARCH_ENTITY_EXPLAINER, "search_passages": SEARCH_PASSAGES,
}


def _render(tool: PagedTool | LocalPagedTool, values: dict[str, Any]) -> str:
    try:
        return tool.render(tool.model.model_validate(values), {}, "")
    except ValidationError as exc:
        return canonical_json({"success": False, "error": "invalid_argument", "message": str(exc)})


@mcp.tool(name="list_collections", description="List the permitted collections and their datasets. Use it to find collection names before a collection read.")
def list_collections() -> str:
    return _render(LIST_COLLECTIONS, {})


def _filters(values: dict[str, Any]) -> dict[str, Any]:
    return {**values, "collectionname": values["collectionname"] or [], "facet_filters": values["facet_filters"] or {}}


@mcp.tool(name="search_collections", description="Search permitted collections for documents. Use it to find document hashes and paths before reading documents. A facet_filters value is a term id that a facet count or search_facet_values returns. Dates are epoch seconds.")
def search_collections(collectionname: list[str] | None = None, query: str = "", sort: AgentSort | None = None, date_after: int | None = None, date_before: int | None = None, date_unknown_only: bool | None = None, mentioned_date_after: int | None = None, mentioned_date_before: int | None = None, size_min: int | None = None, size_max: int | None = None, folder_term_id: int | None = None, filename_only: bool | None = None, facet_filters: dict[str, list[str]] | None = None) -> str:
    return _render(SEARCH_COLLECTIONS, _filters({"collectionname": collectionname, "query": query, "sort": sort, "date_after": date_after, "date_before": date_before, "date_unknown_only": date_unknown_only, "mentioned_date_after": mentioned_date_after, "mentioned_date_before": mentioned_date_before, "size_min": size_min, "size_max": size_max, "folder_term_id": folder_term_id, "filename_only": filename_only, "facet_filters": facet_filters}))


@mcp.tool(name="search_facet_values", description="Find facet values in permitted collections. Use it to choose values for a collection search filter.")
def search_facet_values(collectionname: list[str] | None = None, facet: str = "", query: str | None = None, ids: list[int] | None = None) -> str:
    return _render(SEARCH_FACET_VALUES, {"collectionname": collectionname or [], "facet": facet, "query": query, "ids": ids})


@mcp.tool(name="search_histogram", description="Return the buckets of a collection search by document date, mentioned date or file size. Use it to choose a date or size range before filtering. field is date, mentioned_date or size.")
def search_histogram(collectionname: list[str] | None = None, query: str = "", field: str = "date", date_after: int | None = None, date_before: int | None = None, date_unknown_only: bool | None = None, mentioned_date_after: int | None = None, mentioned_date_before: int | None = None, size_min: int | None = None, size_max: int | None = None, folder_term_id: int | None = None, filename_only: bool | None = None, facet_filters: dict[str, list[str]] | None = None) -> str:
    return _render(SEARCH_HISTOGRAM, _filters({"collectionname": collectionname, "query": query, "date_field": field, "date_after": date_after, "date_before": date_before, "date_unknown_only": date_unknown_only, "mentioned_date_after": mentioned_date_after, "mentioned_date_before": mentioned_date_before, "size_min": size_min, "size_max": size_max, "folder_term_id": folder_term_id, "filename_only": filename_only, "facet_filters": facet_filters}))


@mcp.tool(name="search_entity_explainer", description="Explain one extracted entity value. Use it when a result names a rule and value that need context.")
def search_entity_explainer(collectionname: str, entity_type: str, entity_value: str) -> str:
    return _render(SEARCH_ENTITY_EXPLAINER, {"collectionname": collectionname, "entity_type": entity_type, "entity_value": entity_value})


@mcp.tool(name="search_passages", description="Search the text passages of permitted collections with keyword and vector ranking together. Use it for a question in plain words, when the exact words in the documents are not known. Give up to 8 queries; each hit names the queries that found it.")
def search_passages(queries: list[str] | str, collectionname: list[str] | str | None = None, max_results: int = server.DEFAULT_MAX_RESULTS) -> str:
    if isinstance(queries, str):
        queries = server._as_collection_list(queries) if queries.strip().startswith("[") else [queries]
    collections = server._as_collection_list(collectionname) or []
    return _render(SEARCH_PASSAGES, {"queries": queries, "collectionname": collections, "max_results": max_results})
