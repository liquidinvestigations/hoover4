"""Trajectory parsing for research-task transcripts.

The shapes here are copied from a live run of `hoover4-full-research-agent`, not
invented: the bug these guard against was code that assumed the tool name sits at the
top level of the event when it actually only appears under `output.name` on the end
event.
"""

import json

from tasks.P_agent.trajectory import (
    TOOL_PAYLOAD_CHARS,
    TOOL_SUMMARY_CHARS,
    extract_doc_refs,
    pair_tool_calls,
    truncate,
)


def _start(**arguments):
    return {"phase": "start", "content": {"input": dict(arguments)}}


def _end(name, result, tool_call_id="call-1", **arguments):
    return {
        "phase": "end",
        "content": {
            "input": dict(arguments),
            "output": {
                "content": result,
                "type": "tool",
                "name": name,
                "tool_call_id": tool_call_id,
            },
        },
    }


def test_a_completed_call_is_one_row_with_name_arguments_and_result():
    paired = pair_tool_calls(
        [
            _start(query="danube level", max_results=5),
            _end("web_search", {"success": True, "results": []}, query="danube level"),
        ]
    )
    assert len(paired) == 1
    call = paired[0]
    # The regression: this used to come back as "tool" because the name was looked for
    # at the top level of the event rather than under output.
    assert call.tool_name == "web_search"
    assert "danube level" in call.tool_input
    assert "max_results" in call.tool_input
    # The result is unwrapped out of the LangChain envelope.
    assert call.tool_output == '{"success": true, "results": []}'


def test_calls_are_paired_by_tool_call_id_not_only_by_order():
    paired = pair_tool_calls(
        [
            {"phase": "start", "content": {"input": {"query": "first"}, "tool_call_id": "a"}},
            {"phase": "start", "content": {"input": {"query": "second"}, "tool_call_id": "b"}},
            _end("web_search", {"n": 2}, tool_call_id="b"),
            _end("web_search", {"n": 1}, tool_call_id="a"),
        ]
    )
    assert [c.tool_output for c in paired] == ['{"n": 2}', '{"n": 1}']
    assert "second" in paired[0].tool_input
    assert "first" in paired[1].tool_input


def test_an_end_event_with_no_matching_id_still_pairs_by_order():
    # vLLM's streamed deltas can mangle tool_call_id, so FIFO has to keep working.
    paired = pair_tool_calls(
        [
            _start(query="x"),
            {"phase": "end", "content": {"output": {"content": {"ok": 1}, "name": "web_search"}}},
        ]
    )
    assert len(paired) == 1
    assert paired[0].tool_name == "web_search"
    assert "x" in paired[0].tool_input


def test_a_start_without_an_end_is_dropped():
    # The call never completed; a row claiming a result would be a lie.
    assert pair_tool_calls([_start(query="orphan")]) == []


def test_events_that_are_neither_start_nor_end_are_ignored():
    assert pair_tool_calls([{"phase": "other", "content": {}}]) == []
    assert pair_tool_calls([]) == []
    assert pair_tool_calls(None) == []


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
    paired = pair_tool_calls(
        [
            _start(query="water"),
            _end(
                "search_collections",
                {"results": [{"file_hash": "h1", "collection_dataset": "d1"}]},
            ),
        ]
    )
    assert '"file_hash": "h1"' in paired[0].doc_refs


def test_a_web_search_row_has_no_doc_refs():
    paired = pair_tool_calls(
        [_start(query="q"), _end("web_search", {"results": [{"url": "https://x"}]})]
    )
    assert paired[0].doc_refs == ""


def test_a_document_without_a_dataset_is_still_recorded():
    # The card renders, it just is not clickable -- dropping it would lose the citation.
    refs = extract_doc_refs("get_document_text", {"file_hash": "abc", "path": "/x.pdf"})
    assert len(refs) == 1
    assert refs[0]["collection_dataset"] == ""


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
    paired = pair_tool_calls([_start(q="x"), _end("get_document_text", long_result)])
    assert len(paired[0].tool_output) <= TOOL_PAYLOAD_CHARS + 1
    # And it is still a JSON document. It used to end in a bare "…", i.e. a `{` with no
    # `}`, which every reader downstream reported as "the payload was not recorded".
    stored = json.loads(paired[0].tool_output)
    assert stored["text"].endswith("…"), "the clip is inside the field, not across the doc"
    assert stored["truncated"] is True


def test_the_summary_is_the_arguments_not_the_whole_event():
    # The old behaviour dumped the entire end event into `content`, which is what made
    # transcripts render as a wall of JSON.
    paired = pair_tool_calls(
        [_start(query="water levels"), _end("web_search", {"results": [1, 2, 3]})]
    )
    assert "water levels" in paired[0].summary
    assert "results" not in paired[0].summary
    assert len(paired[0].summary) <= TOOL_SUMMARY_CHARS + 1


def test_truncate_leaves_short_text_alone():
    assert truncate("short", 100) == "short"
    assert truncate("abcdef", 3) == "abc…"
