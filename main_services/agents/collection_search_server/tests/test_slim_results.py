"""The search limits and the slim result page of the collection tools.

The route and the datastores are stubs. What is tested is what the model reads: how many
rows each query form keeps, the snippet cut round the first match, the slim row, the
`more` handle and its store, and the whole identity of each row beside the page.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_common import artifacts
from agent_common.result_pages import is_canonical_page
from collection_search_server import paging, server, tools_document, tools_search
from test_paging import SAMPLES, Store


def route(monkeypatch, documents_of, total_of=None, failing=()):
    """A `search/results` route that answers each query form with `documents_of(form)`
    rows and the `total_count` of `total_of(form)`. Returns the forms it was asked for."""
    from collection_search_server.backend_client import AgentError

    asked = []

    def post(self, route_name, request, response_model, expected_source=None):
        asked.append(request.query)
        if request.query in failing:
            return AgentError(error="invalid_argument", message="query has no searchable terms")
        documents = documents_of(request.query)
        total = total_of(request.query) if total_of else len(documents)
        return response_model.model_validate({
            **SAMPLES["search_collections"], "documents": documents, "total_count": total,
            "has_more": total > len(documents), "total": total, "source": "s", "query_notes": [],
        })

    monkeypatch.setattr("collection_search_server.backend_client.BackendClient.post", post)
    return asked


def document(n, snippet="text", **extra):
    base = {**SAMPLES["search_collections"]["documents"][0], "file_hash": f"{n:016x}" + "b" * 48,
            "path": f"/doc/{n}", "title": f"/doc/{n}", "snippet": snippet}
    return {**base, **extra}


def highlight(first_match=300, length=440):
    """A route highlight of `length` characters whose first `**` pair starts at
    `first_match`."""
    text = "x" * first_match + "**Raptor**"
    return text + "y" * (length - len(text))


# --------------------------------------------------------------------------------------
# The rows of a form
# --------------------------------------------------------------------------------------


def test_twelve_forms_run_twelve_route_searches(monkeypatch):
    Store(monkeypatch)
    forms = [f"form{n}" for n in range(12)]
    asked = route(monkeypatch, lambda form: [document(int(form[4:]))])
    page = json.loads(tools_search.search_collections.fn(queries=forms))
    assert asked == forms
    assert len(page["items"]) == 12


def test_thirteen_forms_are_refused_by_the_schema():
    assert server.MAX_QUERIES_PER_CALL == 12
    with pytest.raises(ValidationError, match="at most 12"):
        tools_search.SearchCollectionsRequest.model_validate({"queries": [f"f{n}" for n in range(13)]})


def test_a_form_of_20_rows_keeps_15_and_says_how_many_were_found(monkeypatch):
    Store(monkeypatch)
    route(monkeypatch, lambda form: [document(n) for n in range(20)], lambda form: 640)
    page = json.loads(tools_search.search_collections.fn(queries=["x", "y"]))
    assert len(page["items"]) == 15
    assert "'x': 640 found, first 15 shown" in page["notes"]


def test_a_form_of_15_rows_has_no_note(monkeypatch):
    Store(monkeypatch)
    route(monkeypatch, lambda form: [document(n) for n in range(15)])
    page = json.loads(tools_search.search_collections.fn(queries=["x"]))
    assert len(page["items"]) == 15
    assert "notes" not in page


def test_a_snippet_is_350_characters_round_its_first_match(monkeypatch):
    Store(monkeypatch)
    route(monkeypatch, lambda form: [document(0, highlight(300, 440))])
    snippet = json.loads(tools_search.search_collections.fn(queries=["Raptor"]))["items"][0]["snippet"]
    assert snippet.startswith("…") and snippet.endswith("…")
    assert len(snippet) == 352 and "**Raptor**" in snippet


def test_a_query_alone_is_one_form_with_15_rows(monkeypatch):
    Store(monkeypatch)
    asked = route(monkeypatch, lambda form: [document(n, highlight()) for n in range(20)], lambda form: 40)
    page = json.loads(tools_search.search_collections.fn(query="Raptor"))
    assert asked == ["Raptor"]
    assert len(page["items"]) == 15
    assert all("q" not in row and len(row["snippet"]) == 352 and "**Raptor**" in row["snippet"]
               for row in page["items"])
    assert page["notes"] == ["'Raptor': 40 found, first 15 shown"]
    assert len(page["more"]) == 12


def test_an_empty_query_alone_is_one_route_search(monkeypatch):
    Store(monkeypatch)
    asked = route(monkeypatch, lambda form: [document(n) for n in range(3)])
    page = json.loads(tools_search.search_collections.fn(query=""))
    assert asked == [""]
    assert len(page["items"]) == 3


# --------------------------------------------------------------------------------------
# The slim row and the page
# --------------------------------------------------------------------------------------


def test_an_empty_search_is_an_empty_items_list(monkeypatch):
    Store(monkeypatch)
    route(monkeypatch, lambda form: [])
    assert json.loads(tools_search.search_collections.fn(query="Raptor")) == {
        "items": [], "query_forms": [{"query": "Raptor", "total_count": 0, "word_counts": []}]}


def test_a_search_row_has_the_slim_keys(monkeypatch):
    Store(monkeypatch)
    row = document(1, "…the **Raptor** approval…", title="Raptor approval", path="/maildir/kean-s/sent/12.",
                   canonical_file_type="email", document_date=989798400)
    route(monkeypatch, lambda form: [row], lambda form: 40)
    text = tools_search.search_collections.fn(query="Raptor")
    page = json.loads(text)
    assert page == {"items": [{"collection": "c", "date": "2001-05-14", "file_hash": row["file_hash"][:16],
                               "path": "/maildir/kean-s/sent/12.", "snippet": "…the **Raptor** approval…",
                               "title": "Raptor approval", "type": "email", "size": 1}],
                    "notes": ["'Raptor': 40 found, first 15 shown"],
                    "keyword_sources": ["c/" + row["file_hash"][:16]],
                    "query_forms": [{"query": "Raptor", "total_count": 40, "word_counts": []}]}
    assert is_canonical_page(text)


def test_a_page_with_no_next_page_has_no_more_and_writes_nothing(monkeypatch):
    store = Store(monkeypatch)
    route(monkeypatch, lambda form: [document(n) for n in range(3)])
    text = tools_search.search_collections.fn(query="x")
    assert "more" not in json.loads(paging.finish(text))
    assert store.bodies == {}


@pytest.mark.parametrize("size", [0, 2681358, None])
def test_search_rows_preserve_known_sizes_and_omit_unknown_sizes(monkeypatch, size):
    Store(monkeypatch)
    route(monkeypatch, lambda form: [document(0, size=size)])
    row = json.loads(tools_search.search_collections.fn(query="pdf"))["items"][0]
    assert row.get("size") == size
    assert ("size" in row) is (size is not None)


def test_a_handle_reads_the_next_page(monkeypatch):
    store = Store(monkeypatch)
    monkeypatch.setattr(paging, "page_share", lambda: 3_000)
    route(monkeypatch, lambda form: [document(n, "s" * 300) for n in range(15)])
    first = json.loads(paging.finish(tools_search.search_collections.fn(query="x")))
    handle = first["more"]
    assert len(handle) == 12
    assert paging.handle_artifact_id(handle) in store.bodies
    # The same token gives the same handle, so a second store writes the same artifact.
    token = paging._TOKENS[handle]
    assert paging.store_handle(token) == handle
    assert len(store.bodies) == 2
    second = json.loads(paging.read_more.fn(handle))
    assert second["items"][0]["file_hash"] == document(len(first["items"]))["file_hash"][:16]


def test_an_unknown_handle_and_a_handle_of_another_session_are_not_found(monkeypatch):
    Store(monkeypatch)
    monkeypatch.setattr(paging, "page_share", lambda: 3_000)
    route(monkeypatch, lambda form: [document(n, "s" * 300) for n in range(15)])
    headers = {"x-hoover4-chat-session": "one", "x-hoover4-user": "alice"}
    monkeypatch.setattr(paging, "get_http_headers", lambda: headers)
    handle = json.loads(paging.finish(tools_search.search_collections.fn(query="x")))["more"]
    unknown = json.loads(paging.read_more.fn("0123456789ab"))
    assert unknown["error"] == "not_found"
    headers["x-hoover4-chat-session"] = "two"
    assert json.loads(paging.read_more.fn(handle))["error"] == "not_found"


def test_a_start_that_names_two_documents_is_refused_naming_both(monkeypatch):
    class Acl:
        def check(self, names):
            return names
    one, two = "abcdef0123456789" + "1" * 48, "abcdef0123456789" + "2" * 48
    monkeypatch.setattr(server, "_caller", lambda: Acl())
    monkeypatch.setattr(server, "clickhouse_query", lambda *a, **k: [{"hash": one}, {"hash": two}])
    monkeypatch.setattr(tools_document, "_readable", lambda names: True)
    answer = json.loads(tools_document.doc_metadata.fn(collection="c", file_hash="abcdef0123456789"))
    assert answer["error"] == "invalid_argument"
    assert one in answer["message"] and two in answer["message"]


def test_the_doc_refs_hold_the_whole_hash_and_the_dataset(monkeypatch):
    Store(monkeypatch)
    rows = [document(n, collection_dataset="c_d") for n in range(3)]
    route(monkeypatch, lambda form: rows)
    refs: list = []
    token = paging._CALL_REFS.set(refs)
    try:
        text = tools_search.search_collections.fn(query="x")
    finally:
        paging._CALL_REFS.reset(token)
    doc_refs = paging.page_doc_refs(text, refs)
    assert [ref["file_hash"] for ref in doc_refs] == [row["file_hash"] for row in rows]
    assert all(ref["collection_dataset"] == "c_d" and len(ref["file_hash"]) == 64 for ref in doc_refs)


# --------------------------------------------------------------------------------------
# search_passages
# --------------------------------------------------------------------------------------


class _Acl:
    username = "alice"
    collections = ["c"]

    def check(self, names):
        return names or ["c"]


def passages(monkeypatch, page_text, seen=None):
    """`search_passages` over one shard whose rows hold `page_text`, with the vector branch
    on, no vector hit, and a reranker that records the texts it scores."""
    monkeypatch.setattr(server, "_caller", lambda: _Acl())
    monkeypatch.setattr(server, "_shard_tables", lambda name: ["s_pages"])
    monkeypatch.setattr(server, "_attach_paths", lambda hits: None)
    monkeypatch.setattr(server, "manticore_query", lambda sql: [
        {"collection_dataset": "c_d", "file_hash": f"{n:064x}", "page_id": 1, "page_text": page_text(n), "score": 40 - n}
        for n in range(40)])
    monkeypatch.setattr(server.embeddings_client, "endpoint", lambda: "http://embeddings")
    monkeypatch.setattr(server.vectors, "serving_model", lambda: "m")
    monkeypatch.setattr(server.embeddings_client, "embed_query", lambda query, model: [0.0])
    monkeypatch.setattr(server.vectors, "search", lambda vector, targets: [])

    def rerank(query, texts):
        if seen is not None:
            seen.extend(texts)
        return [], 0.0
    monkeypatch.setattr(server.rerank_client, "rerank", rerank)


def test_three_forms_of_40_hits_give_at_most_45_rows(monkeypatch):
    passages(monkeypatch, lambda n: f"text {n}")
    response = server.search_passages(queries=["a", "b", "c"], max_results=200)
    assert len(response.results) <= 45


def test_a_late_match_is_inside_the_snippet_and_the_reranker_reads_the_whole_text(monkeypatch):
    seen: list = []
    text = "x" * 800 + "Raptor" + "y" * 294
    passages(monkeypatch, lambda n: text, seen)
    response = server.search_passages(queries=["Raptor"])
    assert seen[0] == text
    assert response.results[0].snippet == "…" + text[625:975].strip() + "…"
    assert "Raptor" in response.results[0].snippet


def test_the_reranker_reads_the_first_1200_characters_of_a_long_text(monkeypatch):
    seen: list = []
    text = "x" * 800 + "Raptor" + "y" * 1194
    passages(monkeypatch, lambda n: text, seen)
    server.search_passages(queries=["Raptor"])
    assert seen[0] == text[:1200]


# --------------------------------------------------------------------------------------
# centred_snippet
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("marker,words,expected", [
    (600, (), (425, 775, True)),
    (100, (), (0, 350, False)),
    (980, (), (650, 1000, True)),
])
def test_the_centred_cut(marker, words, expected):
    text = "a" * marker + "**" + "b" * (998 - marker)
    start, stop, leading = expected
    assert server.centred_snippet(text, 350, words) == ("…" if leading else "") + text[start:stop] + "…"


def test_a_short_text_is_unchanged():
    assert server.centred_snippet("a" * 300, 350) == "a" * 300


def test_with_no_marker_the_first_word_of_a_form_centres_the_cut():
    text = "a" * 700 + "barak" + "c" * 295
    assert server.centred_snippet(text, 350, ["Barak"]) == "…" + text[525:875] + "…"


def test_with_no_marker_and_no_word_the_cut_is_a_prefix():
    text = "a" * 1000
    assert server.centred_snippet(text, 350, ["zzz"]) == "a" * 350 + "…"


def test_the_words_of_a_form_drop_quotes_bars_and_a_leading_minus():
    assert server.query_words(['"Joe Wilkinson" | water -draft']) == ["Joe", "Wilkinson", "water", "draft"]


def test_the_continuation_kind_is_named():
    assert artifacts.KIND_AGENT_CONTINUATION == "agent_continuation"
