"""Typed evidence stored with tool results.

No service runs. The storage readers and writers are replaced with lists.
"""

import json

import pytest

from database import agent_runs
from tasks.P_agent import reports, steps

THREAD = "7a1d2c3b-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
FIRST = THREAD
HASH_A = "a" * 64
HASH_B = "b" * 64


def _message(idx, role, content="", **fields):
    return agent_runs.RunMessageRow(idx=idx, role=role, content=content, **fields)




def _tool(idx, name, content, call_id, doc_refs=None, status="ok", args=None,
          run_id=FIRST, evidence=True):
    usage = {"status": status}
    if evidence:
        usage["evidence"] = reports.with_source(
            reports.normalize(name, args or {}, content, status, doc_refs), THREAD, idx)
    return _message(idx, "tool", content, tool_name=name, tool_call_id=call_id,
                    run_id=run_id, usage_json=json.dumps(usage))


def _read_page(*items, notes=None):
    page = {"items": list(items)}
    if notes:
        page["file_hash_notes"] = notes
    return json.dumps(page)


def _item(file_hash, page=1, text="x", **extra):
    return {"collectionname": "c", "file_hash": file_hash[:16], "page": page, "text": text,
            **extra}


def test_web_discovery_and_citations_keep_distinct_evidence():
    found = reports.normalize("web_search", {}, json.dumps({"results": [
        {"url": "https://example.org/source", "title": "Source"}]}), "ok")
    assert found[0]["kind"] == "discovery"
    assert found[0]["reference"]["url"] == "https://example.org/source"
    cited = reports.normalize("cite_pages", {}, json.dumps({"citations": [{
        "handle": "[W1]", "url": "https://example.org/source", "version": "v1",
        "artifact_id": "captured-source", "quote_verified": True,
        "quotes": ["The result is 5."], "terms": ["result is 5"]}],
        "errors": [{"url": "https://unread.example.org/", "error": "Unread page"}]}), "ok")
    assert [entry["status"] for entry in cited] == ["ok", "error"]
    assert reports.check_labels("The result is 5 [W1].", reports.label_bindings(cited))["unresolved"] == []
    changed = dict(cited[0], reference=dict(cited[0]["reference"], version="v2"))
    assert reports.check_labels("The result is 5 [W1].", reports.label_bindings([cited[0], changed]))["conflicting"] == ["[W1]"]


# ------------------------------------------------------------------------ evidence


def test_several_items_of_one_message_have_distinct_stable_keys():
    content = _read_page(_item(HASH_A), _item(HASH_A, text="y"), _item(HASH_B, page=2))
    refs = [{"collectionname": "c", "file_hash": HASH_A, "path": "/a.txt"},
            {"collectionname": "c", "file_hash": HASH_B, "path": "/b.txt"}]
    first = reports.with_source(reports.normalize("read_documents", {}, content, "ok", refs),
                                THREAD, 4)
    again = reports.with_source(reports.normalize("read_documents", {}, content, "ok", refs),
                                THREAD, 4)
    keys = [e["source"]["item_key"] for e in first]
    assert len(set(keys)) == 3
    assert keys == [e["source"]["item_key"] for e in again]
    assert {e["source"]["message_idx"] for e in first} == {4}
    assert first[0]["reference"]["file_hash"] == HASH_A
    assert first[2]["reference"]["path"] == "/b.txt"


def test_a_batch_keeps_a_successful_read_and_a_failed_read_apart():
    content = _read_page(_item(HASH_A),
                         notes=["no document of collection c matches 'missing.txt'"])
    entries = reports.normalize("read_documents", {"collectionname": "c"}, content, "ok", None)
    assert [(e["kind"], e["status"]) for e in entries] == [
        ("document_read", "ok"), ("document_read", "error")]
    assert "missing.txt" in entries[1]["error"]


def test_a_failed_batch_marks_each_requested_document_failed_with_status_ok():
    """A result can carry `success: false` while the call status is `ok`."""
    content = json.dumps({"success": False, "error": "unauthenticated", "message": "unknown user"})
    entries = reports.normalize("read_documents",
                                {"collectionname": "c", "file_hash": [HASH_A[:16], HASH_B[:16]]},
                                content, "ok")
    assert [e["status"] for e in entries] == ["error", "error"]
    assert all(e["error"] == "unknown user" for e in entries)


def test_an_excerpt_records_its_actual_span():
    content = _read_page(_item(HASH_A, page=3, text="part", cut="4000 of 33798 bytes",
                               more="abc123abc123"))
    [entry] = reports.normalize("read_documents", {}, content, "ok")
    assert entry["status"] == "partial"
    assert entry["range"] == {"page": 3, "start_bytes": 0, "end_bytes": 4000,
                              "total_bytes": 33798}


def test_a_continuation_page_records_its_byte_span():
    content = json.dumps({"cut": {"field": "/text", "start_bytes": 100, "total_bytes": 1000},
                          "items": ["x" * 50]})
    [entry] = reports.normalize("read_more", {"continuation": "abc123abc123"}, content, "ok")
    assert entry["status"] == "partial"
    assert entry["range"]["start_bytes"] == 100 and entry["range"]["end_bytes"] == 150
    assert entry["reference"] == {"continuation": "abc123abc123"}


def test_notes_citations_and_artifacts_are_typed():
    note = reports.normalize("write_note", {},
                             json.dumps({"saved": 1, "note": "The lease is 2019."}), "ok")
    assert [(e["kind"], e["reference"]["text"]) for e in note] == [("note", "The lease is 2019.")]
    cited = reports.normalize(
        "cite_documents", {},
        json.dumps({"citations": [{"file_hash": HASH_A[:16], "handle": "[D1]"},
                                  {"file_hash": HASH_B[:16], "error": "no extracted text"}]}),
        "ok", [{"collectionname": "c", "file_hash": HASH_A, "handle": "[D1]",
                "quote_verified": False, "quote_reason": "absent",
                "candidate": {"text": "exact", "page_id": 2, "start": 5, "end": 10}},
               {"collectionname": "c", "file_hash": HASH_B, "handle": ""}])
    assert [(e["status"], e["reference"]["handle"]) for e in cited] == [("ok", "[D1]"),
                                                                         ("error", "")]
    assert cited[0]["reference"]["candidate"]["text"] == "exact"
    shown = reports.normalize("web_search", {}, json.dumps({
        "results": [], "_hoover4_artifacts": [{"artifact_id": "art-1", "kind": "search_detail"}]}),
        "ok")
    assert [(e["kind"], e["reference"]["artifact_id"]) for e in shown] == [("artifact", "art-1")]


def _cite(idx, call_id, verified, reason=""):
    return _tool(idx, "cite_documents",
                 json.dumps({"citations": [{"file_hash": HASH_A[:16], "handle": "[D1]"}]}),
                 call_id, doc_refs=[{"collectionname": "c", "file_hash": HASH_A,
                                     "handle": "[D1]", "quote_verified": verified,
                                     "quote_reason": reason}])


# ---------------------------------------------------------------------- projection


# ------------------------------------------------------------------- documents


class _FakeS3:
    def __init__(self):
        self.stored = {}

    def bucket_exists(self, bucket):
        return True

    def put_object(self, bucket, key, data, length, content_type):
        self.stored[key] = data.read()


def test_a_read_page_result_gives_one_entry_for_each_page():
    """One cut page and one failed page in one result. The text of the cut page holds a
    `---` line, which does not start a page."""
    text = (
        "## Lease terms\nhttps://example.org/lease\n\nFirst part.\n\n---\n\nStill the lease."
        "\n\n[cut: this call read 1,200 of the page's 5,000 characters. Call read_page with "
        "offset 1300 for the next part, with version 0123456789abcdef]"
        "\n\n---\n\n## https://example.org/down\nhttps://example.org/down\n\n"
        "COULD NOT READ: net::ERR_NAME_NOT_RESOLVED"
        "\n\n---\n\n## Check\nhttps://example.org/check\n\nBLOCKED BY A BOT CHECK: "
        "https://example.org/check. The page stayed on its bot check for 10 s."
    )
    content = json.dumps([text, '[hoover4:artifacts] {"artifacts": []}'])
    entries = reports.normalize("read_page", {"urls": ["https://example.org/lease"],
                                              "offset": 100}, content, "ok")
    assert [(e["reference"]["url"], e["status"]) for e in entries] == [
        ("https://example.org/lease", "partial"), ("https://example.org/down", "error"),
        ("https://example.org/check", "error")]
    assert entries[0]["range"] == {"start_chars": 100, "end_chars": 1300,
                                    "total_chars": 5000, "version": "0123456789abcdef"}
    assert entries[1]["error"] == "COULD NOT READ: net::ERR_NAME_NOT_RESOLVED"
    assert entries[2]["error"].startswith("BLOCKED BY A BOT CHECK")
    assert len({e["item_key"] for e in entries}) == 3


def test_a_find_in_a_page_is_a_partial_read_with_the_spans_it_shows():
    """The shape of `read_page.render` for a `find`, which the browser test fixes too."""
    text = (
        '## people.json\nhttps://example.org/people.json\n\n[find "Staff Engineer": 2 of 5 '
        "matches from offset 0 are shown. The page has 5 matches in 2,115,365 characters. "
        "Version 0123456789abcdef.]\n\n[match at 1200, text from 1000 to 1414]\nabc\n\n"
        "[match at 9000, text from 8800 to 9214]\ndef\n\n[more: 3 matches from offset 20000. "
        "Call read_page with this URL, find, offset 20000 and version 0123456789abcdef for "
        "the next matches]"
        '\n\n---\n\n## b\nhttps://example.org/b\n\n[find "x": no match from offset 0. '
        "The page has 0 matches in 12 characters. Version fedcba9876543210.]"
    )
    entries = reports.normalize("read_page", {"urls": ["https://example.org/people.json"],
                                              "find": "Staff Engineer"},
                                json.dumps([text, '[hoover4:artifacts] {"artifacts": []}']),
                                "ok")
    assert [e["status"] for e in entries] == ["partial"]
    assert entries[0]["range"] == {"find": "Staff Engineer", "spans": [[1000, 1414], [8800, 9214]],
                                   "matches": 5, "total_chars": 2115365,
                                   "version": "0123456789abcdef", "next_offset": 20000}


def test_table_rows_and_cells_count_as_document_content_reads():
    args = {"collectionname": "c", "file_hash": HASH_A, "sheet": 0}
    rows = json.dumps({"items": [{"row_id": 2, "cells": {"name": "A"}}], "row_start": 0})
    [entry] = reports.normalize("table_page", args, rows, "ok")
    assert entry["kind"] == "document_read" and entry["reference"]["file_hash"] == HASH_A
    assert entry["range"] == {"sheet": 0, "row_start": 0}
    assert reports.normalize("table_page", args, '{"items":[]}', "ok") == []
    assert reports.normalize("table_overview", args, rows, "ok") == []
    [cell] = reports.normalize("table_cell", {**args, "row": 2, "column": 1},
                               '{"text":"A","offset":0}', "ok")
    assert cell["kind"] == "document_read" and cell["range"]["row"] == 2
    [other_cell] = reports.normalize("table_cell", {**args, "row": 2, "column": 2},
                                     '{"text":"B","offset":0}', "ok")
    [later_part] = reports.normalize("table_cell", {**args, "row": 2, "column": 1},
                                     '{"text":"C","offset":2000}', "ok")
    assert len({cell["item_key"], other_cell["item_key"], later_part["item_key"]}) == 3


def test_a_read_page_result_stored_as_one_text_ends_with_its_marker_line():
    """The agent service joins the text blocks of a result with a newline, so the marker
    block is the last line of the last page."""
    text = ("## A\nhttps://example.org/a\n\nbody\n\n[cut: this call read 4 of the page's 9 "
            "characters. Call read_page with offset 4 for the next part, with version "
            '0123456789abcdef]\n[hoover4:artifacts] {"artifacts": []}')
    [entry] = reports.normalize("read_page", {"urls": ["https://example.org/a"]}, text, "ok")
    assert entry["status"] == "partial"
    assert entry["range"] == {"start_chars": 0, "end_chars": 4, "total_chars": 9,
                              "version": "0123456789abcdef"}


def test_stored_evidence_keeps_its_source_and_error():
    from database.agent_runs import RunMessageRow

    entry = {"kind": "document_read", "status": "error", "error": "missing page",
             "source": {"thread_id": "source", "message_idx": 8}}
    message = RunMessageRow(idx=1, role="tool", usage_json=json.dumps({"evidence": [entry]}))
    assert reports.message_evidence(message) == [entry]


def test_stored_evidence_ignores_invalid_entries():
    from database.agent_runs import RunMessageRow

    message = RunMessageRow(idx=1, role="tool", usage_json=json.dumps({"evidence": [None, "text", {}]}))
    assert reports.message_evidence(message) == [{}]


def test_missing_evidence_does_not_reconstruct_tool_content():
    from database.agent_runs import RunMessageRow

    message = RunMessageRow(idx=1, role="tool", tool_name="read_documents",
                            content='{"documents":[{"file_hash":"abc","text":"body"}]}')
    assert reports.message_evidence(message) == []


def test_invalid_evidence_does_not_reconstruct_tool_content():
    from database.agent_runs import RunMessageRow

    message = RunMessageRow(idx=1, role="tool", usage_json='{"evidence":{"kind":"document_read"}}')
    assert reports.message_evidence(message) == []


@pytest.mark.parametrize("items", [[{"collectionname": "c", "file_hash": HASH_A[:16], "text": "The budget is 5."}], ["continued table text"]])
def test_document_continuations_keep_the_full_document_reference(items):
    refs = [{"collectionname": "c", "file_hash": HASH_A, "evidence_kind": "document_read"}]
    entries = reports.normalize("read_more", {"continuation": "abc"},
                                json.dumps({"items": items}), "ok", refs)
    assert entries[0]["kind"] == "document_read"
    assert entries[0]["reference"]["file_hash"] == HASH_A
    assert entries[0]["status"] == "ok"


def test_search_continuation_references_do_not_establish_a_document_read():
    entries = reports.normalize("read_more", {"continuation": "abc"},
        json.dumps({"items": [{"file_hash": HASH_A[:16], "snippet": "5"}]}), "ok",
        [{"collectionname": "c", "file_hash": HASH_A}])
    assert not any(entry.get("reference", {}).get("file_hash") for entry in entries)
