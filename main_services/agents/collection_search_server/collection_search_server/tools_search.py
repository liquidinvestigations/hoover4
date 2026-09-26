"""Collection and search tools backed by the website agent API, and `search_passages`,
the hybrid passage search of this server, paged by the same broker."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Annotated, Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_common import batching
from agent_common.result_pages import canonical_json
from collection_search_server.backend_client import (
    AgentError, AgentSort, BackendClient, CollectionsListRequest, SearchDateHistogramRequest,
    SearchEntityExplainerRequest, SearchFacetValuesRequest, SearchResultsRequest,
    SearchResultsResponse,
)
from collection_search_server import paging
from collection_search_server.paging import PagedTool, error_text
from collection_search_server import server
from collection_search_server.server import mcp


@dataclass(frozen=True)
class LocalPagedTool:
    """A paged tool whose result this server computes, with the `model` and `render`
    interface of `PagedTool`, so `read_more` dispatches to it like to a route tool.

    `produce` returns the complete result as a JSON object. The complete result is one
    window of the route paging policy: the list under `item_key` is its rows, and the
    other keys are its fields. A result that does not fit one page is stored once, and
    its later pages read the stored window, as a route window's do. The `source` is a
    digest of the complete result, so a continuation whose result changed is refused.
    """

    model: type[BaseModel]
    tool_name: str
    item_key: str
    produce: Callable[[Any], dict[str, Any]]
    shape: str = "rows"

    def render(self, request: BaseModel, position: dict[str, Any], source: str) -> str:
        if position.get("artifact"):
            return paging._stored_page(self, request, position, paging._artifact_reader(position["artifact"]))
        result = self.produce(request)
        if result.get("success") is False:
            return canonical_json(result)
        digest = hashlib.sha256(canonical_json(result).encode("utf-8")).hexdigest()[:32]
        if source and source != digest:
            return canonical_json({"success": False, "error": "source_changed", "message": "the source changed after the prior page"})
        items = list(result.get(self.item_key) or [])
        fields = {**{key: value for key, value in result.items() if key != self.item_key}, "source": digest}
        return paging._live_page(self, request, None, paging.Window(items, fields, None, None, len(items)))


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


class SearchCollectionsRequest(SearchResultsRequest):
    """The arguments of `search_collections`: the route request, and the list of query
    forms. With `queries` empty the call is one route search, paged by the route's pages."""

    queries: list[str] = Field(default_factory=list, max_length=server.MAX_QUERIES_PER_CALL)


def _route_request(request: SearchResultsRequest, query: str | None = None) -> SearchResultsRequest:
    """The route request of `request`, without its `queries`, for the query `query` when
    it is given."""
    values = request.model_dump(mode="json", exclude={"queries"}, exclude_none=True, by_alias=True)
    if query is not None:
        values["query"] = query
    return SearchResultsRequest.model_validate(values)


def _search_forms(request: SearchCollectionsRequest) -> dict[str, Any]:
    """One route search for each query form, the rows merged.

    Rows merge by `(collectionname, file_hash)`, first seen first, and each row gets
    `matched_queries`, the forms that found it, in the order of the list. A form that
    fails adds its error to `query_notes`, and the other forms still run. Each form
    returns the first route page of its rows."""
    forms, repeats = batching.dedupe(([request.query] if request.query.strip() else []) + list(request.queries))
    notes: list[str] = []
    if repeats:
        notes.append(batching.repeats_note(repeats, "query"))
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    partial = False
    succeeded = 0
    for form in forms:
        result = BackendClient().post("search/results", _route_request(request, form), SearchResultsResponse)
        if isinstance(result, AgentError):
            notes.append(f"the query {form!r} failed: {result.message}")
            continue
        succeeded += 1
        partial |= result.partial
        notes.extend(f"the query {form!r}: {note}" for note in result.query_notes)
        if result.has_more:
            notes.append(
                f"the query {form!r} found {result.total_count} documents, and this result holds "
                f"its first {len(result.documents)}. Search with that query alone to read the others."
            )
        for document in result.documents:
            key = (document.collectionname, document.file_hash)
            row = rows.setdefault(key, {**document.model_dump(mode="json"), "matched_queries": []})
            row["matched_queries"].append(form)
    if not succeeded:
        return {"success": False, "error": "invalid_argument", "message": " ".join(notes) or "no query to run"}
    return {"documents": list(rows.values()), "total_count": len(rows), "query_notes": notes, "partial": partial}


SEARCH_FORMS = LocalPagedTool(SearchCollectionsRequest, "search_collections", "documents", _search_forms)


@dataclass(frozen=True)
class SearchCollectionsTool(PagedTool):
    """`search_collections`. A request with `queries` is the merged search of
    `_search_forms`, and a request without is one route search. A continuation of either
    carries its own input, so `read_more` reaches the same path again."""

    def render(self, request: BaseModel, position: dict[str, Any], source: str) -> str:
        if getattr(request, "queries", None):
            return SEARCH_FORMS.render(request, position, source)
        return super().render(_route_request(request), position, source)


LIST_COLLECTIONS = PagedTool(CollectionsListRequest, "collections/list", "list_collections", "rows", "collections")
SEARCH_COLLECTIONS = SearchCollectionsTool(SearchCollectionsRequest, "search/results", "search_collections", "rows", "documents")
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


LIST_COLLECTIONS_TEXT = (
    "List the collections of this chat and the datasets in each. You do not need it before a "
    "search, because a search with no collectionname covers every collection. A dataset name, "
    "for example tables/ehudx, is not a collection name. Give the collection name, tables."
)

SEARCH_COLLECTIONS_TEXT = r"""Search the user's documents. Leave out collectionname to search every collection of this chat. That is the default, and it is correct for most questions. Give collectionname only to narrow a search, with names from list_collections. A dataset is not a collection.

Give queries as a list of up to 8 forms of what you look for, for example the email address, the name in double quotes and the name with the surname first. Each row names the queries that found it. Do not make one call for each form.
Example: queries ["JoeBWilkinson@cs.com", "\"Joe Wilkinson\"", "\"Wilkinson, Joe\"", "JoeBWilkinson"]

Query rules:
- Words in a query must all occur: water testing
- | means either: water | sewage
- -word excludes a word: water -draft
- Double quotes find a phrase or a name: "Joe Wilkinson"
- OR, AND and NOT are ordinary words. Use | and -word. The search reads OR as | and NOT x as -x, and says so in query_notes.
- An email address works as typed.

Each row gives file_hash, path and collectionname. Copy file_hash from a row to read_documents. Never write a hash yourself. When the result has a continuation, call read_more to get the other rows.

Set a filter only when the user asks for it. Dates are epoch seconds. size_min and size_max are in bytes. A facet_filters value is a term id from a facet count or search_facet_values."""

SEARCH_PASSAGES_TEXT = (
    "Search the text passages of the user's documents by keywords and by meaning together. Use "
    "it for a question in plain words, when you do not know the words that the documents use. "
    "Leave out collectionname to search every collection of this chat. Give up to 8 queries in "
    "one call. Each hit names the queries that found it. For an exact name, address or phrase, "
    "use search_collections."
)


@mcp.tool(name="list_collections", description=LIST_COLLECTIONS_TEXT)
def list_collections() -> str:
    return _render(LIST_COLLECTIONS, {})


def _filters(values: dict[str, Any]) -> dict[str, Any]:
    return {**values, "collectionname": values["collectionname"] or [], "facet_filters": values["facet_filters"] or {}}


@mcp.tool(name="search_collections", description=SEARCH_COLLECTIONS_TEXT)
def search_collections(collectionname: list[str] | None = None, queries: Annotated[list[str] | None, Field(max_length=server.MAX_QUERIES_PER_CALL)] = None, query: str = "", sort: AgentSort | None = None, date_after: int | None = None, date_before: int | None = None, date_unknown_only: bool | None = None, mentioned_date_after: int | None = None, mentioned_date_before: int | None = None, size_min: int | None = None, size_max: int | None = None, folder_term_id: int | None = None, filename_only: bool | None = None, facet_filters: dict[str, list[str]] | None = None) -> str:
    return _render(SEARCH_COLLECTIONS, _filters({"collectionname": collectionname, "queries": queries or [], "query": query, "sort": sort, "date_after": date_after, "date_before": date_before, "date_unknown_only": date_unknown_only, "mentioned_date_after": mentioned_date_after, "mentioned_date_before": mentioned_date_before, "size_min": size_min, "size_max": size_max, "folder_term_id": folder_term_id, "filename_only": filename_only, "facet_filters": facet_filters}))


@mcp.tool(name="search_facet_values", description="Find facet values in permitted collections. Use it to choose values for a collection search filter.")
def search_facet_values(collectionname: list[str] | None = None, facet: str = "", query: str | None = None, ids: list[int] | None = None) -> str:
    return _render(SEARCH_FACET_VALUES, {"collectionname": collectionname or [], "facet": facet, "query": query, "ids": ids})


@mcp.tool(name="search_histogram", description="Return the buckets of a collection search by document date, mentioned date or file size. Use it to choose a date or size range before filtering. field is date, mentioned_date or size.")
def search_histogram(collectionname: list[str] | None = None, query: str = "", field: str = "date", date_after: int | None = None, date_before: int | None = None, date_unknown_only: bool | None = None, mentioned_date_after: int | None = None, mentioned_date_before: int | None = None, size_min: int | None = None, size_max: int | None = None, folder_term_id: int | None = None, filename_only: bool | None = None, facet_filters: dict[str, list[str]] | None = None) -> str:
    return _render(SEARCH_HISTOGRAM, _filters({"collectionname": collectionname, "query": query, "date_field": field, "date_after": date_after, "date_before": date_before, "date_unknown_only": date_unknown_only, "mentioned_date_after": mentioned_date_after, "mentioned_date_before": mentioned_date_before, "size_min": size_min, "size_max": size_max, "folder_term_id": folder_term_id, "filename_only": filename_only, "facet_filters": facet_filters}))


@mcp.tool(name="search_entity_explainer", description="Explain one extracted entity value. Use it when a result names a rule and value that need context.")
def search_entity_explainer(collectionname: str, entity_type: str, entity_value: str) -> str:
    return _render(SEARCH_ENTITY_EXPLAINER, {"collectionname": collectionname, "entity_type": entity_type, "entity_value": entity_value})


@mcp.tool(name="search_passages", description=SEARCH_PASSAGES_TEXT)
def search_passages(queries: list[str] | str, collectionname: list[str] | str | None = None, max_results: int = server.DEFAULT_MAX_RESULTS) -> str:
    if isinstance(queries, str):
        queries = server._as_collection_list(queries) if queries.strip().startswith("[") else [queries]
    collections = server._as_collection_list(collectionname) or []
    return _render(SEARCH_PASSAGES, {"queries": queries, "collectionname": collections, "max_results": max_results})
