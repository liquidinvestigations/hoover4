"""The document tool arguments that reach the website routes, and the tools this server
pages itself through the broker: `search_passages` and `list_document_entities`."""

import inspect
import json

import pytest

from agent_common.result_pages import decode_continuation
from collection_search_server import server, tools_document, tools_search
from collection_search_server.paging import _read_more_response
from test_paging import Store


@pytest.fixture
def sent(monkeypatch):
    """Records the route and body of each website call, and answers with a route error."""
    calls = []

    def fake_post(self, route, request, response_model=None, expected_source=None):
        calls.append((route, request.model_dump(mode="json", exclude_none=True, by_alias=True)))
        from collection_search_server.backend_client import AgentError
        return AgentError(error="not_found", message="recorded")

    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", fake_post)
    return calls


def test_read_documents_sends_the_page_id(sent):
    tools_document.read_documents.fn(collectionname="c", file_hash=["h"], query="q", page=7)
    assert sent == [("documents/read", {"collectionname": "c", "file_hash": ["h"], "query": "q", "page": 7})]


def test_read_documents_refuses_more_than_twenty_hashes(sent):
    page = json.loads(tools_document.read_documents.fn(collectionname="c", file_hash=[str(n) for n in range(21)]))
    assert page["error"] == "invalid_argument" and sent == []


def test_doc_search_text_calls_its_route(sent):
    tools_document.doc_search_text.fn(collectionname="c", file_hash="h", query="needle", source="raw_text")
    assert sent == [("documents/search_text", {"collectionname": "c", "file_hash": "h", "query": "needle", "source": "raw_text"})]


def test_doc_email_sends_the_graph_centre(sent):
    tools_document.doc_email.fn(collectionname="c", file_hash="h", node="other")
    assert sent == [("documents/email", {"collectionname": "c", "file_hash": "h", "node": "other"})]


def test_doc_diff_sources_sends_the_pages(sent):
    tools_document.doc_diff_sources.fn(collectionname="c", file_hash="h", source_a="a", source_b="b", page_a=2, page_b=3)
    assert sent[0][1]["page_a"] == 2 and sent[0][1]["page_b"] == 3


def test_pdf_search_sends_the_page_range(sent):
    tools_document.pdf_search.fn(collectionname="c", file_hash="h", query="q", page_from=2, page_to=4)
    assert sent[0] == ("documents/pdf_search", {"collectionname": "c", "file_hash": "h", "query": "q", "source": "", "page_from": 2, "page_to": 4})


def test_search_histogram_takes_the_field_and_no_confirmed_date_flag(sent):
    parameters = inspect.signature(tools_search.search_histogram.fn).parameters
    assert "date_confirmed_only" not in parameters
    assert "date_confirmed_only" not in inspect.signature(tools_search.search_collections.fn).parameters
    tools_search.search_histogram.fn(collectionname=["c"], field="size", date_unknown_only=True, mentioned_date_after=5)
    route, body = sent[0]
    assert route == "search/histogram"
    assert body["date_field"] == "size" and body["date_unknown_only"] is True and body["mentioned_date_after"] == 5


def test_the_renamed_tools_are_registered():
    names = set(server.mcp._tool_manager._tools)
    assert {"search_histogram", "search_passages", "doc_search_text", "list_document_entities", "cite_documents"} <= names
    assert "search_date_histogram" not in names


def _hits(count):
    return server.SearchResponse(
        success=True,
        query="q",
        queries=["q"],
        collections_searched=["c"],
        results=[
            server.SearchHit(collectionname="c", collection_dataset="c_d", file_hash=f"{n:064x}", page_id=1, score=1.0, snippet="s" * 300)
            for n in range(count)
        ],
    )


def test_search_passages_pages_its_hits_through_the_broker(monkeypatch):
    asked = []

    def fake_search(queries=None, collections=None, max_results=50, query=None):
        asked.append((queries, collections, max_results))
        return _hits(120)

    monkeypatch.setattr(server, "search_passages", fake_search)
    store = Store(monkeypatch)
    page = json.loads(tools_search.search_passages.fn(queries='["q", "r"]', collectionname="c", max_results=120))
    assert asked[0] == (["q", "r"], ["c"], 120)
    assert page["tool_name"] == "search_passages" and page["shape"] == "rows"
    assert page["total_units"] == 120 and 0 < page["returned_units"] < 120
    seen = [item["file_hash"] for item in page["items"]]
    while page["continuation"]:
        token = decode_continuation(page["continuation"])
        assert token["tool"] == "search_passages"
        page = json.loads(_read_more_response(token))
        seen += [item["file_hash"] for item in page["items"]]
    assert seen == [f"{n:064x}" for n in range(120)]
    # The complete result is one window, stored once, and every later page reads it.
    assert len(store.bodies) == 1


def test_a_changed_local_result_refuses_the_continuation(monkeypatch):
    monkeypatch.setattr(server, "search_passages", lambda **kwargs: _hits(1))
    page = json.loads(tools_search.search_passages.fn(queries=["q"]))
    changed = tools_search.SEARCH_PASSAGES.render(
        tools_search.SearchPassagesRequest(queries=["q"]), {"page": 0, "offset": 0}, "stale"
    )
    assert json.loads(changed)["error"] == "source_changed"
    assert page["fields"]["source"] != "stale"


def test_list_document_entities_pages_documents_through_the_broker(monkeypatch):
    def fake_entities(documents=None, collectionname=None, file_hash=None):
        return server.DocumentsEntities(
            success=True,
            documents=[server.DocumentEntities(success=True, collectionname="c", file_hash=f"{n:064x}", entities={"PER": ["Ana"]}) for n in range(3)],
            note="three documents",
        )

    monkeypatch.setattr(server, "list_document_entities", fake_entities)
    page = json.loads(tools_document.list_document_entities.fn(documents=[{"collectionname": "c", "file_hash": "0" * 64}]))
    assert page["tool_name"] == "list_document_entities" and page["total_units"] == 3
    assert [item["file_hash"] for item in page["items"]] == [f"{n:064x}" for n in range(3)]
    assert page["fields"]["note"] == "three documents"


def test_a_failed_entity_listing_is_returned_as_is(monkeypatch):
    monkeypatch.setattr(
        server, "list_document_entities",
        lambda **kwargs: server.DocumentsEntities(success=False, error="no document was named"),
    )
    page = json.loads(tools_document.list_document_entities.fn(documents=[]))
    assert page["success"] is False and page["error"] == "no document was named"
