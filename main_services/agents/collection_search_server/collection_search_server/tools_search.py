"""Collection and search tools backed by the website agent API, and `search_passages`,
the hybrid passage search of this server, paged by the same broker."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_common import batching
from agent_common.result_pages import canonical_json
from collection_search_server.backend_client import (
    AgentError, AgentSort, BackendClient, CollectionsListRequest, CollectionsListResponse,
    SearchDateHistogramRequest,
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
    max_rows: int | None = None

    def render(self, request: BaseModel, position: dict[str, Any], source: str) -> str:
        if position.get("artifact"):
            return paging._stored_page(self, request, position, paging._artifact_reader(position["artifact"]))
        result = self.produce(request)
        if result.get("success") is False:
            return canonical_json(result)
        refs = result.pop(paging.REFS_KEY, None)
        following = result.pop("__following", None)
        digest = hashlib.sha256(canonical_json(result).encode("utf-8")).hexdigest()[:32]
        if source and source != digest:
            return canonical_json({"success": False, "error": "source_changed", "message": "the source changed after the prior page"})
        items = list(result.get(self.item_key) or [])
        if refs is None:
            items, refs = paging.slim_items(self.tool_name, items)
        fields = {**{key: value for key, value in result.items() if key != self.item_key}, "source": digest}
        return paging._live_page(self, request, None, paging.Window(items, fields, None, following, len(items), refs))


class SearchPassagesRequest(BaseModel):
    """The arguments of `search_passages`."""

    model_config = ConfigDict(extra="forbid")

    queries: list[str] = Field(min_length=1, max_length=server.MAX_QUERIES_PER_CALL)
    collectionname: list[str] = Field(default_factory=list)
    max_results: int = Field(default=server.DEFAULT_MAX_RESULTS, ge=1, le=server.MAX_ALLOWED_RESULTS)


def _search_passages(request: SearchPassagesRequest) -> dict[str, Any]:
    """The rows of `search_passages` that the model reads, and `__refs`, the whole identity
    of each row. A row names the forms that found it in `q` when the call has more than one."""
    response = server.search_passages(
        queries=request.queries, collections=request.collectionname or None, max_results=request.max_results,
    )
    if not response.success:
        return {"success": False, "error": "invalid_argument", "message": response.error or "the search failed"}
    several = len(response.queries) > 1
    rows: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    for hit in response.results:
        forms = [response.queries.index(q) for q in hit.matched_queries if q in response.queries]
        row = {"file_hash": paging.hash_start(hit.file_hash), "collectionname": hit.collectionname,
               "path": hit.path or None, "page": hit.page_id, "q": forms if several else None,
               "snippet": hit.snippet}
        rows.append({key: value for key, value in row.items() if value not in (None, "", [])} | {"snippet": hit.snippet})
        refs.append(paging.doc_ref(hit.model_dump(mode="json"), page_id=hit.page_id, snippet=hit.snippet))
    return {"results": rows, "notes": [response.note] if response.note else [], paging.REFS_KEY: refs}


class SearchCollectionsRequest(SearchResultsRequest):
    """The arguments of `search_collections`: the route request, and the list of query
    forms. With `queries` empty the query is the one form."""

    queries: list[str] = Field(default_factory=list, max_length=server.MAX_QUERIES_PER_CALL)
    #: The notes of `collections_for`, for `query_notes`. Not a route argument.
    collection_notes: list[str] = Field(default_factory=list)


def collections_for(names: list[str] | None) -> tuple[list[str] | None, list[str]]:
    """The collections that `names` mean, and a note for each name that was mapped.

    A model gives a dataset name (`files`), a `collection_dataset` value (`consulate_files`)
    or the display form (`consulate/files`) where a collection name belongs. Each such name
    becomes the collection that holds the dataset, from `collections/list`. A collection
    name and a name that matches nothing stay as they are, so the route still refuses a
    collection that the user cannot read.
    """
    if not names:
        return names, []
    listing = BackendClient().post("collections/list", CollectionsListRequest(), CollectionsListResponse)
    if isinstance(listing, AgentError) or not isinstance(listing, CollectionsListResponse):
        return names, []
    known = {c.collectionname for c in listing.collections}
    owner: dict[str, str] = {}
    for collection in listing.collections:
        for dataset in collection.datasets:
            for alias in (f"{collection.collectionname}_{dataset.name}",
                          f"{collection.collectionname}/{dataset.name}", dataset.name):
                owner.setdefault(alias, collection.collectionname)
    resolved: list[str] = []
    notes: list[str] = []
    for name in names:
        target = name
        if name not in known and name in owner:
            target = owner[name]
            notes.append(
                f"{name!r} is a dataset of the collection {target!r}, not a collection, so this "
                f"search covers the collection {target!r}. Give collectionname {target!r}."
            )
        if target not in resolved:
            resolved.append(target)
    return resolved, notes


def _route_request(request: SearchResultsRequest, query: str | None = None) -> SearchResultsRequest:
    """The route request of `request`, without its `queries` and its `collection_notes`,
    for the query `query` when it is given."""
    values = request.model_dump(mode="json", exclude={"queries", "collection_notes"},
                                exclude_none=True, by_alias=True)
    if query is not None:
        values["query"] = query
    return SearchResultsRequest.model_validate(values)


def _search_date(epoch: int | None) -> str | None:
    """The UTC calendar date of an epoch in seconds, or None for no date."""
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return None


def search_row(document: dict[str, Any], forms: list[int] | None, words: list[str]) -> dict[str, Any]:
    """The row of one document that the model reads. `forms` is the numbers of the query
    forms that found it, or None when the call has one form. The title is left out when
    the path holds it, and every empty value is left out."""
    title = document.get("title") or ""
    path = document.get("path") or ""
    row = {
        "file_hash": paging.hash_start(document.get("file_hash") or ""),
        "collectionname": document.get("collectionname") or "",
        "path": path,
        "title": title if title and title not in path else None,
        "type": document.get("canonical_file_type") or None,
        "date": _search_date(document.get("document_date")),
        "q": forms or None,
        "snippet": server.centred_snippet(document.get("snippet") or "", server.SNIPPET_CHARS, words),
    }
    return {key: value for key, value in row.items() if value not in (None, "", []) or key in ("path", "snippet")}


def _search_forms(request: SearchCollectionsRequest) -> dict[str, Any]:
    """One route search for each query form, the rows merged.

    Each form keeps the first `ROWS_PER_FORM` rows of its first route page. Rows merge by
    `(collectionname, file_hash)`, first seen first. When the call has more than one form,
    each row names the forms that found it in `q`, by number from 0. A form that fails adds
    its error to `query_notes`, and the other forms still run. The notes of
    `collections_for` come first in `query_notes`. A call with no form runs the query as
    one form, so a browse with an empty query is one route search. `__refs` holds the whole
    identity of each row, which `LocalPagedTool.render` takes out of the result."""
    forms, repeats = batching.dedupe(([request.query] if request.query.strip() else []) + list(request.queries))
    notes: list[str] = list(getattr(request, "collection_notes", []))
    if not forms:
        forms = [request.query]
    if repeats:
        notes.append(batching.repeats_note(repeats, "query"))
    found: dict[tuple[str, str], tuple[dict[str, Any], list[int]]] = {}
    partial = False
    succeeded = 0
    following: list[dict[str, Any]] = []
    for number, form in enumerate(forms):
        result = BackendClient().post("search/results", _route_request(request, form), SearchResultsResponse)
        if isinstance(result, AgentError):
            notes.append(f"the query {form!r} failed: {result.message}")
            continue
        succeeded += 1
        partial |= result.partial
        notes.extend(f"the query {form!r}: {note}" for note in result.query_notes)
        if len(result.documents) > server.ROWS_PER_FORM:
            following.append({"form": number, "page": 0, "skip": server.ROWS_PER_FORM,
                              "source": result.source})
        elif result.next_position is not None:
            following.append({"form": number, "page": result.next_position.page, "skip": 0,
                              "source": result.source})
        if result.total_count > server.ROWS_PER_FORM:
            notes.append(f"{form!r}: {result.total_count} found, first {server.ROWS_PER_FORM} shown")
        for document in result.documents[:server.ROWS_PER_FORM]:
            key = (document.collectionname, document.file_hash)
            _, numbers = found.setdefault(key, (document.model_dump(mode="json"), []))
            numbers.append(number)
    if not succeeded:
        return {"success": False, "error": "invalid_argument", "message": " ".join(notes) or "no query to run"}
    several = len(forms) > 1
    rows = []
    refs = []
    for document, numbers in found.values():
        words = server.query_words([forms[n] for n in numbers])
        row = search_row(document, numbers if several else None, words)
        rows.append(row)
        refs.append(paging.doc_ref(document, snippet=row["snippet"]))
    return {"documents": rows, "query_notes": notes, "partial": partial,
            "__following": {"_forms": following} if following else None, paging.REFS_KEY: refs}


def _following_form(request: SearchCollectionsRequest, position: dict[str, Any], tool: PagedTool) -> str:
    """Read the next rows of one form from the route's page cursor."""
    forms, _ = batching.dedupe(([request.query] if request.query.strip() else []) + list(request.queries))
    forms = forms or [request.query]
    pending = deepcopy(position["_forms"])
    rows: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    while pending and len(rows) < server.ROWS_PER_FORM:
        cursor = pending[0]
        if cursor["form"] >= len(forms):
            return paging._invalid("continuation form is invalid")
        route_request = _route_request(request, forms[cursor["form"]])
        route_request = SearchResultsRequest.model_validate({
            **route_request.model_dump(mode="json", exclude_none=True),
            "position": {"kind": "Page", "page": cursor["page"]},
        })
        result = BackendClient().post("search/results", route_request, SearchResultsResponse,
                                      expected_source=cursor["source"])
        if isinstance(result, AgentError):
            return error_text(result)
        if result.source != cursor["source"]:
            return canonical_json({"success": False, "error": "source_changed",
                                   "message": "the source changed after the prior page"})
        available = result.documents[cursor["skip"]:]
        taken = available[:server.ROWS_PER_FORM - len(rows)]
        for document in taken:
            whole = document.model_dump(mode="json")
            row = search_row(whole, [cursor["form"]] if len(forms) > 1 else None,
                             server.query_words([forms[cursor["form"]]]))
            rows.append(row)
            refs.append(paging.doc_ref(whole, snippet=row["snippet"]))
        skip = cursor["skip"] + len(taken)
        if skip < len(result.documents):
            cursor["skip"] = skip
        elif result.next_position is not None:
            cursor["page"] = result.next_position.page
            cursor["skip"] = 0
        else:
            pending.pop(0)
            break
        if not taken and skip >= len(result.documents) and result.next_position is None:
            continue
        if not taken and skip >= len(result.documents) and result.next_position is not None:
            return paging._invalid("continuation route returned no rows")
    window = paging.Window(rows, {}, None, {"_forms": pending} if pending else None, len(rows), refs)
    return paging._live_page(tool, request, position, window)


SEARCH_FORMS = LocalPagedTool(SearchCollectionsRequest, "search_collections", "documents", _search_forms,
                              max_rows=server.ROWS_PER_FORM)


@dataclass(frozen=True)
class SearchCollectionsTool(PagedTool):
    """`search_collections`. Every call is the merged search of `_search_forms`. Only a
    continuation that carries a route position goes to the route, and only a page that was
    stored before every call went through `_search_forms` holds one."""

    def render(self, request: BaseModel, position: dict[str, Any], source: str) -> str:
        if position.get("artifact"):
            return super().render(request, position, source)
        if isinstance(position.get("window"), dict) and "_forms" in position["window"]:
            return _following_form(request, position["window"], self)
        if position.get("window") or position.get("next"):
            return super().render(_route_request(request), position, source)
        return SEARCH_FORMS.render(request, position, source)


LIST_COLLECTIONS = PagedTool(CollectionsListRequest, "collections/list", "list_collections", "rows", "collections")
SEARCH_COLLECTIONS = SearchCollectionsTool(SearchCollectionsRequest, "search/results", "search_collections", "rows", "documents", max_rows=server.ROWS_PER_FORM)
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

Give queries as a list of up to 12 forms of what you look for, for example the email address, the name in double quotes and the name with the surname first. Each row names the forms that found it in q, by number from 0. Do not make one call for each form.
Example: queries ["JoeBWilkinson@cs.com", "\"Joe Wilkinson\"", "\"Wilkinson, Joe\"", "JoeBWilkinson"]

Query rules:
- Words in a query must all occur: water testing
- | means either: water | sewage
- -word excludes a word: water -draft
- Double quotes find a phrase or a name: "Joe Wilkinson"
- OR, AND and NOT are ordinary words. Use | and -word. The search reads OR as | and NOT x as -x, and says so in query_notes.
- from: and to: are not fields. The search drops them, keeps the word after them, and says so in query_notes.
- An email address works as typed.

Each row gives file_hash, path and collectionname. Copy file_hash from a row to read_documents. Never write a hash yourself. When the result has more, give that value to read_more to get the other rows.

Set a filter only when the user asks for it. Dates are epoch seconds. size_min and size_max are in bytes. A facet_filters value is a term id from a facet count or search_facet_values."""

SEARCH_PASSAGES_TEXT = (
    "Search the text passages of the user's documents by keywords and by meaning together. Use "
    "it for a question in plain words, when you do not know the words that the documents use. "
    "Leave out collectionname to search every collection of this chat. Give up to 12 queries in "
    "one call. Each row names the forms that found it in q, by number from 0. Copy file_hash "
    "from a row to read_documents. For an exact name, address or phrase, "
    "use search_collections."
)


@mcp.tool(name="list_collections", description=LIST_COLLECTIONS_TEXT)
def list_collections() -> str:
    return _render(LIST_COLLECTIONS, {})


def _filters(values: dict[str, Any]) -> dict[str, Any]:
    return {**values, "collectionname": values["collectionname"] or [], "facet_filters": values["facet_filters"] or {}}


@mcp.tool(name="search_collections", description=SEARCH_COLLECTIONS_TEXT)
def search_collections(collectionname: list[str] | None = None, queries: Annotated[list[str] | None, Field(max_length=server.MAX_QUERIES_PER_CALL)] = None, query: str = "", sort: AgentSort | None = None, date_after: int | None = None, date_before: int | None = None, date_unknown_only: bool | None = None, mentioned_date_after: int | None = None, mentioned_date_before: int | None = None, size_min: int | None = None, size_max: int | None = None, folder_term_id: int | None = None, filename_only: bool | None = None, facet_filters: dict[str, list[str]] | None = None) -> str:
    collectionname, collection_notes = collections_for(collectionname)
    return _render(SEARCH_COLLECTIONS, _filters({"collectionname": collectionname, "collection_notes": collection_notes, "queries": queries or [], "query": query, "sort": sort, "date_after": date_after, "date_before": date_before, "date_unknown_only": date_unknown_only, "mentioned_date_after": mentioned_date_after, "mentioned_date_before": mentioned_date_before, "size_min": size_min, "size_max": size_max, "folder_term_id": folder_term_id, "filename_only": filename_only, "facet_filters": facet_filters}))


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
