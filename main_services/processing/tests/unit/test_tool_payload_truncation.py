"""Fitting a research turn's tool payload into the transcript column.

The Python half of a rule the Rust side states too (`truncate_tool_payload` in
`website/common/src/chat_types.rs`): a tool result is a JSON document, and you truncate a
document *inside* it. Cutting the serialised text leaves a `{` with no `}`, and every
reader downstream then treats a recorded result as an absent one. The card printed "the
result payload was not recorded" about a row it had just read.

A research transcript must read identically to an inline one, so the two implementations
are tested against the same claims.
"""

import json

from tasks.P_agent.trajectory import TOOL_PAYLOAD_CHARS, truncate, truncate_json


def _search_payload(results: int, snippet_chars: int) -> str:
    return json.dumps({
        "output": {
            "name": "web_search",
            "content": {
                "success": True,
                "query": "danube water level",
                "sources_used": ["ddg_api", "yahoo", "wikipedia"],
                "results": [
                    {
                        "title": f"Result {i}",
                        "url": f"https://example.com/{i}",
                        "snippet": "x" * snippet_chars,
                        "sources": ["ddg_api", "yahoo"],
                    }
                    for i in range(results)
                ],
            },
        }
    })


def test_a_truncated_payload_is_still_parseable_json():
    raw = _search_payload(60, 400)
    assert len(raw) > 4_000
    out = truncate_json(raw, 4_000)
    assert len(out) <= 4_000
    parsed = json.loads(out)  # the truncated payload must still parse
    assert parsed["output"]["content"]["query"] == "danube water level"


def test_whole_results_are_dropped_rather_than_the_document_being_cut():
    out = json.loads(truncate_json(_search_payload(60, 400), 4_000))
    results = out["output"]["content"]["results"]
    assert results, "some results must survive"
    assert len(results) < 60, "and some must have been dropped"
    # Best-first order: what is kept is what the reader was going to read.
    assert results[0]["title"] == "Result 0"
    for row in results:
        assert isinstance(row["url"], str) and isinstance(row["snippet"], str)


def test_the_object_that_lost_rows_says_so():
    out = json.loads(truncate_json(_search_payload(60, 400), 4_000))
    assert out["output"]["content"]["truncated"] is True


def test_a_payload_that_already_fits_is_returned_byte_for_byte():
    raw = _search_payload(2, 40)
    assert truncate_json(raw, TOOL_PAYLOAD_CHARS) == raw


def test_a_document_whose_bulk_is_one_string_clips_the_string():
    # Nothing to drop: a get_document_text result is one enormous field.
    raw = json.dumps({"path": "/a.pdf", "text": "y" * 50_000})
    out = truncate_json(raw, 2_000)
    assert len(out) <= 2_000
    parsed = json.loads(out)
    assert parsed["path"] == "/a.pdf", "the fields that identify it survive"
    assert parsed["text"].endswith("…")


def test_a_payload_that_is_not_json_falls_back_to_cutting_it():
    raw = "z" * 500
    out = truncate_json(raw, 100)
    assert out == truncate(raw, 100)
    assert len(out) == 101 and out.endswith("…")
