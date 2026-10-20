"""Workspace files: the read format, the citation check, the write and patch rules, the
writer activities and the report of a turn.

Storage is replaced with dicts, so no ClickHouse is needed. The Hermes matcher has its own
tests in `test_hermes_fuzzy_match.py`.
"""

from __future__ import annotations

import json

import pytest

from database import chat_workspace as store
from database.agent_runs import RunMessageRow
from tasks.P_agent import citations
from tasks.P_workspace import mutations, references, selection
from tasks.P_workspace import workflows as writer


def cite(handle, file_hash="a" * 64, verified=True, **extra):
    return {"kind": "citation", "status": "ok",
            "reference": {"handle": handle, "file_hash": file_hash, "quote": "q",
                          "quote_verified": verified, "collectionname": "c", **extra}}


def command(op="write", name="report.md", **fields):
    return mutations.Command(username="ann", session_id="s1", operation_id="op-1",
                             run_id="run-1", op=op, name=name, **fields)


def head(content, version=1, **fields):
    return store.FileVersion("ann", "s1", "report.md", version, content=content, **fields)


# Store helpers -------------------------------------------------------------------------

def test_a_file_name_is_one_plain_segment():
    assert store.valid_name("report.md") == ""
    for name in ("", "../x", "a/b.md", ".hidden", "a b.md", "x" * 121):
        assert store.valid_name(name)


def test_a_read_has_the_gutter_and_the_next_offset():
    version = head("one\ntwo\nthree")
    first = store.render_read(version, 1, 2)
    assert first["content"] == "1|one\n2|two"
    assert first["next_offset"] == 3 and first["total_lines"] == 3
    rest = store.render_read(version, first["next_offset"], 2)
    assert rest["content"] == "3|three" and "next_offset" not in rest


def test_a_copy_of_a_read_result_is_recognised():
    assert store.looks_like_read_output("1|one\n2|two\n3|three")
    assert not store.looks_like_read_output("Total | 3\nItems | 4")
    assert not store.looks_like_read_output("one line")


# Citation handles ----------------------------------------------------------------------

def test_handles_follow_the_transcript_renderer():
    text = "\n".join([
        "Approved [D1] and [D2, W1].",
        "Literal \\[D9] and `[D8]` and a [D7](https://x) link.",
        "```",
        "[D6]",
        "```",
        "Plain [note] and [D3].",
    ])
    assert references.handles(text) == [("[D1]", 1), ("[D2]", 1), ("[W1]", 1), ("[D3]", 6)]


def test_check_resolves_a_verified_handle_and_reports_the_others():
    entries = [cite("[D1]"), cite("[D2]", verified=False),
               cite("[D3]", "b" * 64), cite("[D3]", "c" * 64)]
    findings, resolved = references.check("report.md", "A [D1]. B [D2]. C [D3]. D [D4].", entries)
    assert [r["handle"] for r in resolved] == ["[D1]"]
    assert resolved[0]["file_hash"] == "a" * 64
    actions = {f["handle"]: f["action"] for f in findings}
    assert set(actions) == {"[D2]", "[D3]", "[D4]"}
    assert "not found in its source" in actions["[D2]"]
    assert "more than one source" in actions["[D3]"]
    assert "cite_documents" in actions["[D4]"] and "\\[D4]" in actions["[D4]"]


def test_a_failed_citation_resolves_nothing():
    failed = {"kind": "citation", "status": "error", "reference": {"handle": "[D1]"}}
    findings, _ = references.check("report.md", "A [D1].", [failed])
    assert findings and findings[0]["line"] == 1


# Write and patch rules -----------------------------------------------------------------

def test_a_new_file_gets_version_one_with_its_citations():
    prepared = mutations.prepare(command(content="Approved [D1]."), None, [cite("[D1]")])
    assert prepared.ok and prepared.version.version == 1
    assert prepared.version.parent_version == 0
    assert prepared.result["citations"] == ["[D1]"]
    assert prepared.version.citations[0]["handle"] == "[D1]"


def test_a_write_of_an_existing_file_needs_the_current_version():
    stale = mutations.prepare(command(content="New.", expected_version=1), head("Old.", 2), [])
    missing = mutations.prepare(command(content="New."), head("Old.", 2), [])
    current = mutations.prepare(command(content="New.", expected_version=2), head("Old.", 2), [])
    assert not stale.ok and stale.result["current_version"] == 2
    assert "expected_version 2" in stale.result["error"]
    assert not missing.ok and "no expected_version" in missing.result["error"]
    assert current.ok and current.version.version == 3 and current.version.parent_version == 2


def test_a_write_of_a_read_result_is_refused():
    prepared = mutations.prepare(command(content="1|one\n2|two"), None, [])
    assert not prepared.ok and "N|" in prepared.result["error"]


def test_a_finding_leaves_the_file_unchanged():
    prepared = mutations.prepare(command(content="Claim [D5]."), None, [cite("[D1]")])
    assert not prepared.ok and prepared.version is None
    assert prepared.result["file_changed"] is False
    assert prepared.result["findings"][0]["handle"] == "[D5]"


def test_a_patch_replaces_one_region():
    prepared = mutations.prepare(
        command("patch", old_string="4 May", new_string="5 May"),
        head("Approved on 4 May [D1].", 1), [cite("[D1]")])
    assert prepared.ok and prepared.version.content == "Approved on 5 May [D1]."
    assert prepared.version.patch["strategy"] == "exact"
    assert prepared.version.operation == "patch"


def test_a_patch_that_matches_nothing_shows_our_tool_names():
    prepared = mutations.prepare(
        command("patch", old_string="nothing like this", new_string="x"), head("Text."), [])
    assert not prepared.ok
    assert "read_file" not in prepared.result["error"]
    assert "write_file" not in prepared.result["error"]


def test_a_repeated_patch_is_already_applied_and_stores_nothing():
    prepared = mutations.prepare(
        command("patch", old_string="on 4 May", new_string="on 5 May 2020"),
        head("Approved on 5 May 2020."), [])
    assert prepared.ok and prepared.version is None
    assert prepared.result["unchanged"] is True and "already applied" in prepared.result["note"]


def test_a_patch_of_a_missing_file_is_refused():
    prepared = mutations.prepare(command("patch", old_string="a", new_string="b"), None, [])
    assert not prepared.ok and "write_file" in prepared.result["error"]


def test_a_large_file_is_refused():
    prepared = mutations.prepare(command(content="x" * (store.MAX_FILE_CHARS + 1)), None, [])
    assert not prepared.ok and "limit" in prepared.result["error"]


def test_a_write_that_keeps_most_lines_gets_the_patch_hint():
    old = "\n".join(f"line {n} of the report text" for n in range(1000))
    new = old.replace("line 5 of", "line five of")
    prepared = mutations.prepare(command(content=new, expected_version=1), head(old), [])
    assert prepared.ok and "patch_file" in prepared.result["hint"]


def test_the_upstream_punctuation_is_rewritten_and_the_tool_names_stay():
    dash = " " + chr(0x2014) + " "
    assert mutations.ours(f"use read_file{dash}then write_file") == "use read_file, then write_file"


# Writer activities ---------------------------------------------------------------------

@pytest.fixture
def stored(monkeypatch):
    state = {"versions": {}, "receipts": {}, "deleted": False, "entries": []}

    def read_version(username, session_id, name, version=None):
        rows = [v for (u, s, n, _), v in state["versions"].items()
                if (u, s, n) == (username, session_id, name)]
        if version is not None:
            rows = [v for v in rows if v.version == version]
        return max(rows, key=lambda v: v.version) if rows else None

    def write_version(version):
        state["versions"][(version.username, version.session_id, version.name, version.version)] = version

    monkeypatch.setattr(store, "read_version", read_version)
    monkeypatch.setattr(store, "write_version", write_version)
    monkeypatch.setattr(store, "read_receipt", lambda u, s, o: state["receipts"].get((u, s, o)))
    monkeypatch.setattr(store, "write_receipt",
                        lambda u, s, r: state["receipts"].__setitem__((u, s, r.operation_id), r))
    monkeypatch.setattr(store, "session_deleted", lambda u, s: state["deleted"])
    from tasks.P_agent import reports
    monkeypatch.setattr(reports, "session_citation_entries", lambda u, s: state["entries"])
    return state


def run_command(cmd):
    prepared = writer.prepare_workspace_mutation(cmd)
    if not prepared.replay:
        writer.commit_workspace_mutation(writer.CommitInput(cmd, prepared))
    return prepared


def test_a_repeated_operation_returns_its_receipt_and_changes_the_file_once(stored):
    first = run_command(command(content="Text."))
    again = run_command(command(content="Text."))
    assert first.ok and first.found_version == 1
    assert again.replay and again.result == first.result
    assert list(stored["versions"]) == [("ann", "s1", "report.md", 1)]


def test_a_commit_that_stopped_after_the_version_writes_the_receipt(stored):
    cmd = command(content="Text.")
    prepared = writer.prepare_workspace_mutation(cmd)
    store.write_version(prepared.version)
    repaired = run_command(cmd)
    assert repaired.ok and repaired.version is None and repaired.found_version == 1
    assert stored["receipts"][("ann", "s1", "op-1")].version == 1
    assert len(stored["versions"]) == 1


def test_a_deleted_session_refuses_every_command(stored):
    stored["deleted"] = True
    prepared = run_command(command(content="Text."))
    assert not prepared.ok and stored["versions"] == {}
    assert stored["receipts"][("ann", "s1", "op-1")].ok is False


def test_the_writer_reads_the_session_citations(stored):
    stored["entries"] = [cite("[D1]")]
    assert run_command(command(content="Approved [D1].")).ok


# The report of a turn ------------------------------------------------------------------

def tool_row(idx, name, body, status="ok"):
    return RunMessageRow(idx=idx, role="tool", tool_name=name, content=json.dumps(body),
                         usage_json=json.dumps({"status": status}))


def test_the_report_is_the_last_successful_mutation():
    rows = [
        tool_row(3, "workspace_write", {"success": True, "name": "a.md", "version": 1, "citations": ["[D1]"]}),
        tool_row(5, "patch_file", {"success": True, "name": "b.md", "version": 2, "citations": []}),
        tool_row(7, "workspace_write", {"success": False, "name": "c.md"}, status="error"),
        tool_row(8, "workspace_read", {"name": "a.md", "version": 1}),
    ]
    assert selection.selected_report(rows) == {"name": "b.md", "version": 2, "citations": []}
    assert selection.selected_report(rows[2:]) is None


def test_a_report_sets_the_answer_metadata():
    report = {"name": "report.md", "version": 3, "citations": ["[D1]"]}
    meta = citations.answer_metadata("I wrote report.md.", [], False, report)
    assert meta == {"tool_scope": "documents_only", "citation_status": "cited",
                    "report": {"name": "report.md", "version": 3}}
    plain = citations.answer_metadata("No sources needed.", [], True, None)
    assert plain == {"tool_scope": "documents_and_web", "citation_status": "none"}


def test_the_delivered_files_keep_first_order_and_the_last_version():
    rows = [
        tool_row(2, "write_file", {"success": True, "name": "a.md", "version": 1, "citations": []}),
        tool_row(3, "write_file", {"success": True, "name": "b.md", "version": 1, "citations": ["[W1]"]}),
        tool_row(4, "read_file", {"name": "c.md", "version": 4}),
        tool_row(5, "write_file", {"success": False, "name": "d.md"}, status="error"),
        tool_row(6, "patch_file", {"success": True, "name": "a.md", "version": 3, "citations": ["[D1]"]}),
        tool_row(7, "patch_file", {"success": True, "name": "b.md", "version": 1,
                                   "unchanged": True, "citations": ["[W1]"]}),
    ]
    assert selection.delivered_reports(rows) == [
        {"name": "a.md", "version": 3, "citations": ["[D1]"]},
        {"name": "b.md", "version": 1, "citations": ["[W1]"]}]
    assert selection.manifest(rows) == {
        "report": {"name": "b.md", "version": 1},
        "reports": [{"name": "a.md", "version": 3, "citations": ["[D1]"]},
                    {"name": "b.md", "version": 1, "citations": ["[W1]"]}]}
    assert selection.manifest(rows[2:4]) == {}


def test_a_repeated_tool_message_of_one_call_counts_once():
    first = RunMessageRow(idx=2, role="tool", tool_name="write_file", tool_call_id="c1",
                          content=json.dumps({"success": True, "name": "a.md", "version": 1}),
                          usage_json=json.dumps({"status": "ok"}))
    again = RunMessageRow(idx=9, role="tool", tool_name="write_file", tool_call_id="c1",
                          content=json.dumps({"success": True, "name": "z.md", "version": 1}),
                          usage_json=json.dumps({"status": "ok"}))
    assert [r["name"] for r in selection.delivered_reports([first, again])] == ["a.md"]


def test_handles_in_code_are_literal_and_listed_apart():
    text = "Kept `Web [W1]` and\n```\nsee [D2]\n```\nand \\`x\\` and [D3]."
    assert references.code_handles(text) == ["[W1]", "[D2]"]
    assert references.code_handle_places(text) == [("[W1]", False), ("[D2]", True)]
    assert [h for h, _ in references.handles(text)] == ["[D3]"]


def test_a_file_with_only_code_formatted_handles_is_stored_with_a_note():
    prepared = mutations.prepare(command(content="The plant closed `[W1]`."), None, [])
    assert prepared.ok and prepared.result["citations"] == []
    assert "[W1] is inside code formatting" in prepared.result["note"]
    # A handle in an inline code span of the prose gets the note beside a linked handle.
    linked = mutations.prepare(command(content="Approved [D1]. The transfer `[D9]`."), None,
                               [cite("[D1]")])
    assert linked.ok and linked.result["citations"] == ["[D1]"]
    assert linked.result["note"].startswith("[D9] is inside code formatting in the text")
    assert "no linked citation" not in linked.result["note"]
    assert linked.version.content == "Approved [D1]. The transfer `[D9]`."
    # A fenced example beside a linked handle is an example and gets no note.
    example = "Approved [D1].\n\n```\nWrite [D2] beside the claim.\n```\n"
    fenced = mutations.prepare(command(content=example), None, [cite("[D1]")])
    assert fenced.ok and "note" not in fenced.result and fenced.version.content == example
    plain = mutations.prepare(command(content="No sources."), None, [])
    assert plain.ok and "note" not in plain.result


def test_answer_metadata_lists_the_delivered_files():
    report = {"name": "b.md", "version": 2, "citations": []}
    files = [{"name": "a.md", "version": 1, "citations": ["[D1]"]},
             {"name": "b.md", "version": 2, "citations": []}]
    meta = citations.answer_metadata("Two files.", [], False, report, files)
    assert meta["report"] == {"name": "b.md", "version": 2}
    assert meta["reports"] == files and meta["citation_status"] == "none"
