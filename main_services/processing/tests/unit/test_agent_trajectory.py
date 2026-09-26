"""The finished tool row of a `tool_result`: its output, its summary and its document
references, and the result page byte rule."""

import json

from types import SimpleNamespace

from tasks.P_agent.stream_writer import tool_row_fields
from tasks.P_agent.trajectory import (
    TOOL_PAYLOAD_CHARS,
    TOOL_SUMMARY_CHARS,
    _canonical_json,
    extract_doc_refs,
    is_canonical_page,
    truncate,
)


def _row(name, result, **arguments):
    """One finished tool row from a `tool_result`, whose content is text."""
    content = result if isinstance(result, str) else json.dumps(result)
    fields = tool_row_fields(name, dict(arguments), content)
    return SimpleNamespace(tool_output=fields["tool_output"], summary=fields["content"],
                           doc_refs=fields["doc_refs"])


def test_search_collections_results_become_doc_refs():
    result = {
        "success": True,
        "results": [
            {
                "collectionname": "testdata",
                "collection_dataset": "testdata_testfiles",
                "file_hash": "abc123",
                "path": "/pdf-scans/Water.pdf",
                "page_id": 0,
                "score": 2921.0,
                "snippet": "water testing",
            }
        ],
    }
    refs = extract_doc_refs("search_collections", result)
    assert len(refs) == 1
    assert refs[0]["collection_dataset"] == "testdata_testfiles"
    assert refs[0]["file_hash"] == "abc123"
    assert refs[0]["path"] == "/pdf-scans/Water.pdf"


def test_doc_refs_are_attached_to_the_paired_row():
    row = _row("search_collections",
               {"results": [{"file_hash": "h1", "collection_dataset": "d1"}]}, query="water")
    assert '"file_hash": "h1"' in row.doc_refs


def test_a_web_search_row_has_no_doc_refs():
    paired = [_row("web_search", {"results": [{"url": "https://x"}]}, query="q")]
    assert paired[0].doc_refs == ""


def test_a_document_without_a_dataset_is_still_recorded():
    # The card renders, it just is not clickable -- dropping it would lose the citation.
    refs = extract_doc_refs("get_document_text", {"file_hash": "abc", "path": "/x.pdf"})
    assert len(refs) == 1
    assert refs[0]["collection_dataset"] == ""


def test_a_batch_entity_listing_yields_one_ref_per_document():
    refs = extract_doc_refs(
        "list_document_entities",
        {"documents": [{"file_hash": "aaa"}, {"file_hash": "bbb"}]},
    )
    assert [r["file_hash"] for r in refs] == ["aaa", "bbb"]


def test_a_citation_keeps_its_reason_and_an_older_row_has_none():
    refs = extract_doc_refs(
        "cite_documents",
        {
            "citations": [
                {
                    "file_hash": "aaa",
                    "handle": "[D1]",
                    "quote": "the board approved",
                    "quote_verified": True,
                },
                {
                    "file_hash": "bbb",
                    "handle": "[D2]",
                    "quote": "the",
                    "quote_verified": False,
                    "quote_reason": "short",
                },
                {
                    "file_hash": "ccc",
                    "handle": "[D3]",
                    "quote": "older stored quote",
                    "quote_verified": False,
                },
            ]
        },
    )
    assert refs[0]["quote_verified"] is True
    assert refs[0]["quote_reason"] == ""
    assert refs[1]["quote_reason"] == "short"
    assert refs[2]["quote_reason"] == ""


def test_a_pre_batch_entities_row_still_renders():
    # The single-document shape the tool answered with before it was batched. Stored
    # transcripts still hold these rows and a card that cannot render one loses the record.
    refs = extract_doc_refs(
        "list_document_entities", {"file_hash": "abc", "collection_dataset": "d"}
    )
    assert len(refs) == 1 and refs[0]["file_hash"] == "abc"


def test_a_result_with_no_documents_yields_nothing():
    assert extract_doc_refs("search_collections", {"results": []}) == []
    assert extract_doc_refs("get_document_text", {"error": "not found"}) == []
    assert extract_doc_refs("anything", "a plain string") == []


def test_payloads_are_truncated_rather_than_stored_whole():
    # Against the constant, not a literal: it mirrors TOOL_PAYLOAD_CHARS in
    # website/common/src/chat_types.rs and the two move together. A hardcoded 12_000
    # here is what made the doubling for the richer search payload look like a
    # regression.
    long_result = {"text": "z" * (TOOL_PAYLOAD_CHARS * 4)}
    paired = [_row("get_document_text", long_result, q="x")]
    assert len(paired[0].tool_output) <= TOOL_PAYLOAD_CHARS + 1
    # And it is still a JSON document. It used to end in a bare "…", i.e. a `{` with no
    # `}`, which every reader downstream reported as "the payload was not recorded".
    stored = json.loads(paired[0].tool_output)
    assert stored["text"].endswith("…"), "the clip is inside the field, not across the doc"
    assert stored["truncated"] is True


def test_the_summary_is_the_arguments_not_the_whole_event():
    # The old behaviour dumped the entire end event into `content`, which is what made
    # transcripts render as a wall of JSON.
    paired = [_row("web_search", {"results": [1, 2, 3]}, query="water levels")]
    assert "water levels" in paired[0].summary
    assert "results" not in paired[0].summary
    assert len(paired[0].summary) <= TOOL_SUMMARY_CHARS + 1


def test_truncate_leaves_short_text_alone():
    assert truncate("short", 100) == "short"
    assert truncate("abcdef", 3) == "abc…"


# --------------------------------------------------------------------------------------
# The byte rule's store step: a broker result page is stored unchanged.
# --------------------------------------------------------------------------------------

#: A page-shaped envelope, canonical: sorted keys, compact separators, matching what
#: `agent_common.result_pages.canonical_page_bytes` would build for the same object.
_PAGE_ENVELOPE = {
    "continuation": None,
    "items": [{"path": "a.txt"}],
    "kind": "result_page",
    "raw_artifact_id": None,
    "returned_units": 1,
    "shape": "rows",
    "success": True,
    "tool_name": "search_collections",
    "total_units": 1,
}
_PAGE_TEXT = json.dumps(_PAGE_ENVELOPE, sort_keys=True, separators=(",", ":"))


def test_is_canonical_page_true_for_the_fixture_false_after_a_change():
    # Parity with `agent_common.result_pages.is_canonical_page`, which cannot be
    # imported here (`hoover4-worker` has no `agent_common` on its import path -- see
    # `_canonical_json`'s docstring). Both copies are exercised against the same shape
    # of fixture in their own suite; this asserts what this copy does with it.
    assert is_canonical_page(_PAGE_TEXT) is True
    assert is_canonical_page(_PAGE_TEXT + " ") is False
    assert is_canonical_page(json.dumps(_PAGE_ENVELOPE)) is False  # unsorted, spaced
    assert is_canonical_page("not json") is False
    assert is_canonical_page(_canonical_json({"kind": "not_a_page"})) is False


def test_a_string_result_that_is_a_canonical_page_is_stored_unchanged():
    paired = [_row("search_collections", _PAGE_TEXT, query="x")]
    assert paired[0].tool_output == _PAGE_TEXT


def test_an_ordinary_result_is_unaffected_by_the_page_guard():
    paired = [_row("web_search", {"n": 1}, query="x")]
    assert paired[0].tool_output == '{"n": 1}'


def _search_page(items):
    """A broker result page as the broker serialises it: canonical JSON text."""
    return _canonical_json({"kind": "result_page", "items": items, "success": True,
                            "tool_name": "search_collections", "total_units": len(items)})


def test_a_canonical_search_page_becomes_doc_refs_and_keeps_its_bytes():
    page = _search_page([
        {"collectionname": "enron", "collection_dataset": "enron_maildir", "dataset": "maildir",
         "file_hash": "aaa", "path": "/a.eml", "snippet": "s"},
        {"collectionname": "enron", "collection_dataset": "enron_maildir", "dataset": "maildir",
         "file_hash": "bbb", "path": "/b.eml", "snippet": "t",
         "matched_queries": ["talking points"]},
    ])
    assert is_canonical_page(page)
    row = _row("search_collections", page, query="hearings")
    assert row.tool_output == page
    refs = json.loads(row.doc_refs)
    assert [r["collection_dataset"] for r in refs] == ["enron_maildir", "enron_maildir"]
    # The first query that matched the document, else the query of the call.
    assert [r["find_query"] for r in refs] == ["hearings", "talking points"]


def test_a_search_card_takes_the_first_of_queries():
    page = _search_page([{"collection_dataset": "d", "file_hash": "aaa"}])
    refs = json.loads(_row("search_passages", page, queries=["one", "two"]).doc_refs)
    assert refs[0]["find_query"] == "one"


def test_a_read_documents_page_yields_its_items():
    page = _canonical_json({"kind": "result_page", "items": [
        {"collectionname": "enron", "collection_dataset": "enron_maildir", "file_hash": "aaa"}]})
    refs = json.loads(_row("read_documents", page).doc_refs)
    assert [(r["file_hash"], r["collection_dataset"], r["find_query"]) for r in refs] == [
        ("aaa", "enron_maildir", "")]


def test_a_citation_carries_its_find_query():
    refs = extract_doc_refs("cite_documents", {"citations": [{
        "collectionname": "enron", "collection_dataset": "enron_maildir", "file_hash": "aaa",
        "quote": "Your notes look great. Best of luck today with the Hearings.",
        "find_query": '"Your notes look great"', "quote_verified": True}]})
    assert refs[0]["find_query"] == '"Your notes look great"'


def test_a_stored_search_row_with_only_the_short_dataset_gets_the_composed_key():
    refs = extract_doc_refs("search_collections", {"kind": "result_page", "items": [
        {"collectionname": "enron", "dataset": "maildir", "file_hash": "aaa"}]})
    assert refs[0]["collection_dataset"] == "enron_maildir"
