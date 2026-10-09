"""Verify collection-scoped facet matrices, argument errors and continued values."""

import asyncio
import json

import pytest
from pydantic import ValidationError

from collection_search_server import server, tools_search
from collection_search_server.backend_client import AgentError, CollectionsListResponse, SearchFacetValuesResponse
from test_paging import Store, walk


def fixture_backend(monkeypatch, count=2):
    calls = []

    def post(self, route, request, response_model=None, expected_source=None):
        calls.append((route, request))
        if route == "collections/list":
            return CollectionsListResponse(collections=[
                {"collectionname": name, "document_count": 20, "datasets": []}
                for name in ("alpha", "beta")], source="listing")
        assert route == "search/facet_values"
        assert request.collectionname in (["alpha"], ["beta"])
        if request.facet == "email_to":
            return AgentError(error="timed_out", message="The facet read timed out.")
        return SearchFacetValuesResponse(terms=[
            {"id": n + 900000, "text": f"{request.facet}-{n}", "count": n + 1}
            for n in range(count)], resolved={}, source="facet")

    monkeypatch.setattr("collection_search_server.backend_client.BackendClient.post", post)
    return calls


def test_omitted_scope_returns_permitted_rows_and_text_count_cells(monkeypatch):
    calls = fixture_backend(monkeypatch)
    page = json.loads(tools_search.search_facet_values.fn())
    assert page["columns"] == ["collection", "file_types", "language"]
    assert page["items"] == [
        [name, [["file_types-0", 1], ["file_types-1", 2]], [["language-0", 1], ["language-1", 2]]]
        for name in ("alpha", "beta")]
    assert len(calls) == 5
    assert "900000" not in json.dumps(page)


def test_one_collection_name_selects_one_row(monkeypatch):
    fixture_backend(monkeypatch)
    page = json.loads(tools_search.search_facet_values.fn(collection="beta", facets=["file_types"]))
    assert [row[0] for row in page["items"]] == ["beta"]


def test_errors_preserve_collection_and_facet_identity(monkeypatch):
    calls = fixture_backend(monkeypatch)
    page = json.loads(tools_search.search_facet_values.fn(collection=["alpha", "secret"], facets=["email_to", "language"]))
    assert page["items"][0][1] is None and page["items"][0][2]
    assert page["items"][1] == ["secret", None, None]
    assert page["errors"] == [
        {"collection": "alpha", "facet": "email_to", "error": "timed_out", "message": "The facet read timed out."},
        {"collection": "secret", "error": "forbidden", "message": "This collection is not permitted."}]
    assert len(calls) == 3


def test_an_empty_permission_listing_selects_no_collections(monkeypatch):
    calls = []

    def post(self, route, request, response_model=None, expected_source=None):
        calls.append(route)
        assert route == "collections/list"
        return CollectionsListResponse(collections=[], source="empty")

    monkeypatch.setattr("collection_search_server.backend_client.BackendClient.post", post)
    page = json.loads(tools_search.search_facet_values.fn())
    assert page["items"] == [] and calls == ["collections/list"]


def test_large_matrix_values_continue_without_loss(monkeypatch):
    Store(monkeypatch)
    fixture_backend(monkeypatch, count=1000)
    first = json.loads(tools_search.search_facet_values.fn(facets=["file_types"]))
    assert first.get("more")
    # Generic table paging must preserve the complete nested matrix cells.
    from test_paging import rebuild
    restored = rebuild(walk(first))
    assert restored == [[name, [[f"file_types-{n}", n + 1] for n in range(1000)]] for name in ("alpha", "beta")]


def test_schema_exposes_exact_facet_values_and_rejects_old_names():
    tool = asyncio.run(server.mcp.get_tools())["search_facet_values"]
    assert "facets" in tool.parameters["properties"]
    assert "collection" in tool.parameters["properties"]
    assert "facet" not in tool.parameters["properties"]
    assert "collectionname" not in tool.parameters["properties"]
    enum = tool.parameters["properties"]["facets"]["items"]["enum"]
    assert "file_types" in enum and "file_type" not in enum and "collection_dataset" not in enum
    with pytest.raises(ValidationError):
        tools_search.FacetMatrixRequest(facets=["file_type"])
    with pytest.raises(ValidationError):
        tools_search.FacetMatrixRequest(collectionname=["alpha"])


def test_mcp_rejects_old_arguments_before_any_backend_read(monkeypatch):
    monkeypatch.setattr("collection_search_server.backend_client.BackendClient.post",
                        lambda *a, **k: pytest.fail("An invalid argument reached the backend."))
    tool = asyncio.run(server.mcp.get_tools())["search_facet_values"]
    with pytest.raises(Exception):
        asyncio.run(tool.run({"collectionname": ["alpha"], "facet": "file_types"}))
