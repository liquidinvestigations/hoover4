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



def _listing(monkeypatch):
    """A caller who reads `consulate` only, and a website whose `collections/list` gives the
    `consulate` collection with the dataset `files`. Returns the routes called, with the
    `collectionname` each document route received."""
    from collection_search_server.acl import CallerAcl
    from collection_search_server.backend_client import AgentError, CollectionsListResponse

    monkeypatch.setattr(server, "_caller", lambda: CallerAcl(username="u", collections=("consulate",)))
    monkeypatch.setattr(server, "full_hashes", lambda c, v: v)
    listing = CollectionsListResponse.model_validate({"collections": [
        {"collectionname": "consulate", "document_count": 1,
         "datasets": [{"name": "files", "document_count": 1}]}], "source": "s"})
    calls = []

    def fake_post(self, route, request, response_model=None, expected_source=None):
        if route == "collections/list":
            calls.append((route, None))
            return listing
        calls.append((route, request.model_dump(mode="json", exclude_none=True).get("collectionname")))
        return AgentError(error="not_found", message="recorded")

    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", fake_post)
    return calls


def test_a_dataset_name_in_a_document_tool_reads_its_collection(monkeypatch):
    calls = _listing(monkeypatch)
    for name in ("consulate_files", "files", "consulate/files"):
        calls.clear()
        tools_document.read_documents.fn(collectionname=name, file_hash=["h"])
        assert calls == [("collections/list", None), ("documents/read", "consulate")], name


def test_a_readable_collection_costs_no_listing(monkeypatch):
    calls = _listing(monkeypatch)
    tools_document.doc_metadata.fn(collectionname="consulate", file_hash="h")
    assert calls == [("documents/metadata", "consulate")]


def test_a_mapped_collection_is_named_in_the_result():
    body = json.loads(tools_document._with_notes('{"rows": []}', ["'files' is a dataset"]))
    assert body["collection_notes"] == ["'files' is a dataset"]
    assert tools_document._with_notes("plain", ["n"]) == "plain"


def test_a_hash_one_character_too_long_is_refused_with_its_length():
    with pytest.raises(server.HashPrefixError, match="has 65 characters, and a file hash has 64"):
        server.full_hash("testdata", "a" * 65)


GOOD = "1c34013565c314e2fcf93953929f2d10e622558009112e9495be315efcd7f92c"
MEANT = "b0df945ee5dfa8180541b6f7a496d0a96c3dd97ecc80fa5a4a5d9680552ac0d0"


def _collection_of(monkeypatch, hashes, paths=None):
    """A readable collection `epstein` whose `vfs_files` holds `hashes`, and `paths`, a
    map of path to hash."""
    from collection_search_server.acl import CallerAcl

    monkeypatch.setattr(server, "_caller", lambda: CallerAcl(username="u", collections=("epstein",)))

    def fake_query(sql, database, params=None):
        params = params or {}
        if "hash IN" in sql:
            wanted = params["hashes"].strip("[]").replace("'", "").split(",")
            return [{"hash": h} for h in hashes if h in wanted]
        if "startsWith" in sql:
            return [{"hash": h} for h in hashes if h.startswith(params["prefix"])][:2]
        if "endsWith" in sql:
            return [{"hash": h} for p, h in (paths or {}).items()
                    if p == params["name"] or p.endswith(params["tail"])][:2]
        raise AssertionError(sql)

    monkeypatch.setattr(server, "clickhouse_query", fake_query)


def test_a_hash_with_one_changed_character_reads_the_document_it_starts_like(monkeypatch):
    _collection_of(monkeypatch, [GOOD, MEANT])
    changed = MEANT[:41] + "e" + MEANT[41:]
    hashes, notes = server.resolve_hashes("epstein", [GOOD, changed])
    assert hashes == [GOOD, MEANT]
    assert len(notes) == 1 and MEANT[:16] in notes[0] and MEANT in notes[0]


def test_a_hash_that_matches_nothing_is_left_out_and_the_others_are_read(monkeypatch):
    _collection_of(monkeypatch, [GOOD])
    hashes, notes = server.resolve_hashes("epstein", [GOOD, "f" * 64])
    assert hashes == [GOOD]
    assert "leaves it out" in notes[0]


def test_read_documents_with_only_unknown_hashes_is_refused_with_the_notes(monkeypatch, sent):
    _collection_of(monkeypatch, [GOOD])
    body = json.loads(tools_document.read_documents.fn(collectionname="epstein", file_hash=["f" * 64]))
    assert body["error"] == "not_found" and "leaves it out" in body["message"]
    assert sent == []


def test_a_hash_with_a_dropped_character_reads_the_document_it_starts_like(monkeypatch):
    _collection_of(monkeypatch, [GOOD, MEANT])
    dropped = MEANT[:40] + MEANT[41:]
    hashes, notes = server.resolve_hashes("epstein", [dropped, GOOD[:12]])
    assert hashes == [MEANT, GOOD]
    assert len(notes) == 1 and MEANT in notes[0]


def test_a_short_start_that_matches_nothing_is_left_out(monkeypatch):
    _collection_of(monkeypatch, [GOOD])
    hashes, notes = server.resolve_hashes("epstein", ["abcdefabcdef", GOOD])
    assert hashes == [GOOD] and "leaves it out" in notes[0]


def test_a_file_name_in_file_hash_reads_the_one_document_with_that_name(monkeypatch):
    _collection_of(monkeypatch, [GOOD, MEANT], {"/oversight/HOUSE_OVERSIGHT_031227.txt": GOOD,
                                               "/a/copy.txt": MEANT, "/b/copy.txt": GOOD})
    hashes, notes = server.resolve_hashes(
        "epstein", ["HOUSE_OVERSIGHT_031227.txt", "copy.txt", MEANT])
    assert hashes == [GOOD, MEANT]
    assert "is a file name" in notes[0] and "no single document" in notes[1]
