"""Exercise owner scope, pinned versions, thread identities, and snapshot races."""

from dataclasses import replace
import json
import pytest
from database.agent_runs import RunRow, RunMessageRow
from database.chat_workspace import FileVersion
from scripts.chat_review.export import export_turn
from scripts.chat_review.packets import computed_table_facts
from scripts.chat_review.schema import Incomplete, Invalid


class FakeStore:
    def __init__(self):
        self.run = RunRow("run", "owner", "session", turn_seq=1, thread_id="answer", state="completed",
                          result="Ready.", start_seq=1, next_seq=10)
        self.reads = []
        self.deletion_checks = 0
        self.deleted_after = 99
        self.rows = {
            "earlier": [RunMessageRow(0, "human", "Earlier question", run_id="earlier-run"),
                        RunMessageRow(1, "tool", '{"source":"original evidence"}', tool_name="read_documents",
                                      usage_json=json.dumps({"model_content": "shortened", "evidence": []}), run_id="earlier-run")],
            "answer": [RunMessageRow(0, "human", "Write report.md.", run_id="run"),
                       RunMessageRow(1, "tool", json.dumps({"success": False, "name": "bad.md", "version": 9}),
                                     tool_name="write_file", tool_call_id="bad", run_id="run"),
                       RunMessageRow(2, "tool", json.dumps({"success": True, "name": "report.md", "version": 2}),
                                     tool_name="patch_file", tool_call_id="ok", run_id="run"),
                       RunMessageRow(3, "tool", json.dumps({"success": True, "name": "report.md", "version": 4}),
                                     tool_name="patch_file", tool_call_id="ok", run_id="run"),
                       RunMessageRow(4, "ai", "Ready.", reasoning="private reasoning", run_id="run")]}
        self.file = FileVersion("owner", "session", "report.md", 2, content="Pinned version two.")

    def deleted(self, owner, session):
        self.deletion_checks += 1
        return self.deletion_checks >= self.deleted_after

    def turn_runs(self, owner, session, turn):
        return [self.run] if (owner, session) == ("owner", "session") else []

    def earlier_threads(self, *args):
        return ["earlier"]

    def messages(self, owner, session, thread):
        self.reads.append((owner, session, thread))
        return self.rows[thread]

    def version(self, owner, session, name, version):
        self.reads.append((owner, session, name, version))
        assert version == 2
        return self.file

    def answer(self, run):
        return {"content": "Ready.", "seq": 9, "usage_json": json.dumps({
            "report": {"name": "report.md", "version": 2},
            "reports": [{"name": "report.md", "version": 2, "citations": []}]})}


def test_export_reads_delivered_version_not_current_head():
    store = FakeStore()
    packet, manifest = export_turn("owner", "session", 1, store)
    assert packet["delivery"]["files"] == [{"name": "report.md", "version": 2,
        "content": "Pinned version two.", "digest": packet["delivery"]["files"][0]["digest"]}]
    assert ("owner", "session", "report.md", 2) in store.reads
    assert not manifest["writes"]


def test_export_keeps_thread_identity_when_indexes_repeat():
    packet, _ = export_turn("owner", "session", 1, FakeStore())
    assert [m["thread_id"] for m in packet["history"]["messages"] if m["idx"] == 0] == ["earlier", "answer"]
    assert "private reasoning" not in json.dumps(packet)


def test_reduced_tool_view_does_not_replace_original_bytes():
    packet, _ = export_turn("owner", "session", 1, FakeStore())
    evidence = next(e for e in packet["evidence"] if e["id"] == "earlier:1")
    assert evidence["content"] == '{"source":"original evidence"}'
    assert evidence["complete"] is False


@pytest.mark.parametrize("when", [1, 2])
def test_deleted_session_cannot_export(when):
    store = FakeStore()
    store.deleted_after = when
    with pytest.raises(Incomplete):
        export_turn("owner", "session", 1, store)


def test_owner_mismatch_rejected_before_file_read():
    store = FakeStore()
    with pytest.raises(Incomplete):
        export_turn("different-owner", "session", 1, store)
    assert store.reads == []


def test_storage_returning_wrong_owner_fails():
    store = FakeStore()
    store.file.username = "another-owner"
    with pytest.raises(Invalid):
        export_turn("owner", "session", 1, store)


def test_deleted_source_remains_missing_evidence():
    store = FakeStore()
    store.rows["earlier"][1].usage_json = json.dumps({"evidence": [{"kind": "document_read", "status": "error"}]})
    packet, _ = export_turn("owner", "session", 1, store)
    assert any(m["target"] == "earlier:1" for m in packet["coverage"]["missing"])


def test_partial_message_cannot_enter_completed_visible_history():
    store = FakeStore()
    store.rows["answer"].append(RunMessageRow(5, "ai", "unfinished", is_final=0, run_id="run"))
    packet, manifest = export_turn("owner", "session", 1, store)
    assert manifest["partial_messages"] == [["answer", 5]]
    assert not packet["history"]["complete"]
    assert "unfinished" not in json.dumps(packet)


def test_published_manifest_disagreement_stays_incomplete():
    store = FakeStore()
    store.rows["answer"][2].content = json.dumps({"success": True, "name": "report.md", "version": 3})
    with pytest.raises(Incomplete):
        export_turn("owner", "session", 1, store)


def test_source_quote_reason_is_only_metadata():
    store = FakeStore()
    store.rows["earlier"][1].usage_json = json.dumps({"evidence": [{"kind": "citation", "status": "ok",
        "reference": {"handle": "[D1]", "file_hash": "a" * 64, "quote": "source", "why": "Unsupported allegation"}}]})
    packet, _ = export_turn("owner", "session", 1, store)
    assert packet["citations"][0]["reference"]["why"] == "Unsupported allegation"
    assert "Unsupported allegation" not in packet["evidence"][0]["content"]
    assert any("Citation body" in m["reason"] for m in packet["coverage"]["missing"])


def test_partial_table_cannot_produce_exact_population_count():
    cells = [{"id": "a", "city": "Rome"}, {"id": "b", "city": "Rome"}, {"id": "c", "city": ""}]
    reading = {"id_column": "id", "group_column": "city", "interpretation": "header"}
    pop = {"complete": False, "row_count": 3, "source_digest": "a" * 64, "extent": "rows 1-3", "filters": []}
    assert computed_table_facts(cells, reading, pop)["state"] == "incomplete"
    pop["complete"] = True
    result = computed_table_facts(cells, reading, pop)
    assert result["operations"]["distinct_nonempty"] == 1
    assert result["operations"]["empty_ids"] == ["c"]
    assert result["operations"]["two_row_groups"] == ["Rome"]
    pop["row_count"] = 4
    assert computed_table_facts(cells, reading, pop)["state"] == "incomplete"


def test_complete_office_fixture_has_independent_counts_and_memberships():
    from website.tools.prepare_table_fixtures import office_rows, _csv, EXPECTED
    import hashlib
    source = _csv(office_rows(), ['case_id', 'office', 'amount'])
    assert hashlib.sha3_256(source).hexdigest() == EXPECTED['p65-tables/office_values_250.csv']
    cells = [dict(zip(('case_id', 'office', 'amount'), row)) for row in office_rows()]
    result = computed_table_facts(cells, {'id_column': 'case_id', 'group_column': 'office', 'interpretation': 'header'},
        {'complete': True, 'row_count': 250, 'source_digest': hashlib.sha256(source).hexdigest(), 'extent': 'all rows', 'filters': []})
    facts = result['operations']
    assert facts['distinct_nonempty'] == 214
    assert len(facts['empty_ids']) == 9
    assert facts['two_row_group_count'] == 27
    assert facts['groups']['Office 025'] == ['C-245']
    assert facts['row_to_group']['C-250'] == 'Harbour Annex'


def test_ambiguous_readings_keep_different_populations():
    from website.tools.prepare_table_fixtures import PEOPLE
    from scripts.chat_review.schema import digest
    cells = [{'id': str(i), 'city': row[1]} for i, row in enumerate(PEOPLE)]
    results = []
    for start, reading in ((0, 'all_rows'), (1, 'first_row_header')):
        selected = cells[start:]
        results.append(computed_table_facts(selected, {'id_column': 'id', 'group_column': 'city', 'interpretation': reading},
            {'complete': True, 'row_count': len(selected), 'source_digest': digest(PEOPLE), 'extent': [start, len(cells)], 'filters': []}))
    assert [r['operations']['row_count'] for r in results] == [12, 11]
    assert [len(r['operations']['groups']['Paris']) for r in results] == [3, 2]
    assert results[0]['input_digest'] != results[1]['input_digest']
