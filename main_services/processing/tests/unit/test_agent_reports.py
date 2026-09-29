"""Typed evidence, the report projection, the report documents and their recovery.

No service runs. The storage readers and writers are replaced with lists.
"""

import hashlib
import json

import pytest

from database import agent_plans, agent_runs
from tasks.P_agent import reports, steps
from tasks.P_agent.activities import CallRef

THREAD = "7a1d2c3b-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
FIRST = THREAD
CONTINUATION = "8b2e3d4c-5f6a-4b7c-9d8e-0f1a2b3c4d5e"
PLAN_RUN = "9c3f4e5d-6a7b-4c8d-8e9f-1a2b3c4d5e6f"
NODE = "0d4a5f6e-7b8c-4d9e-8f0a-2b3c4d5e6f7a"
HASH_A = "a" * 64
HASH_B = "b" * 64


def _message(idx, role, content="", **fields):
    return agent_runs.RunMessageRow(idx=idx, role=role, content=content, **fields)


def _ai(idx, text="", calls=(), reasoning="", run_id=FIRST):
    return _message(idx, "ai", text, reasoning=reasoning, run_id=run_id,
                    tool_calls_json=json.dumps(list(calls)))


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


def test_a_continuation_keeps_the_logical_source_of_its_evidence():
    """Two runs of one thread write messages under different run ids. The evidence keys
    name the thread and the index, never the run."""
    content = _read_page(_item(HASH_A))
    messages = [
        _message(0, "human", "q", run_id=FIRST),
        _ai(1, calls=[{"id": "r1", "name": "read_documents", "args": {}}]),
        _tool(2, "read_documents", content, "r1", run_id=FIRST),
        _ai(3, calls=[{"id": "r2", "name": "read_documents", "args": {}}], run_id=CONTINUATION),
        _tool(4, "read_documents", content, "r2", run_id=CONTINUATION),
    ]
    report = reports.project(messages, thread_id=THREAD, first_run_id=FIRST, state="completed",
                             session_citations=[])
    sources = [e["source"] for e in report["documents_read"]]
    assert [s["thread_id"] for s in sources] == [THREAD, THREAD]
    assert [s["message_idx"] for s in sources] == [2, 4]
    assert report["first_run_id"] == FIRST


def test_a_search_result_is_discovery_and_never_a_read():
    content = json.dumps({"items": [{"collectionname": "c", "file_hash": HASH_A[:16],
                                     "path": "/a.txt", "snippet": "s"}]})
    refs = [{"collectionname": "c", "file_hash": HASH_A, "path": "/a.txt"}]
    entries = reports.normalize("search_collections", {"query": "lease"}, content, "ok", refs)
    assert [e["kind"] for e in entries] == ["discovery"]
    messages = [_message(0, "human", "q"),
                _ai(1, calls=[{"id": "s1", "name": "search_collections", "args": {}}]),
                _tool(2, "search_collections", content, "s1", doc_refs=refs)]
    report = reports.project(messages, thread_id=THREAD, first_run_id=FIRST,
                             state="completed", session_citations=[])
    assert report["documents_read"] == []
    assert [e["reference"]["file_hash"] for e in report["documents_found"]] == [HASH_A]


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


def test_the_tool_result_write_stores_the_evidence_in_its_usage(monkeypatch):
    written = []
    monkeypatch.setattr(agent_runs, "write_message", lambda *args: written.append(args[-1]))
    row = agent_runs.RunRow(run_id=CONTINUATION, username="u", session_id="s",
                            thread_id=THREAD, depth=1, kind="subagent")
    ai = _ai(5, calls=[{"id": "r1", "name": "read_documents", "args": {"collectionname": "c"},
                        "position": 0, "seq": 0}])
    content = _read_page(_item(HASH_A))
    steps._write_tool_result(row, "", ai, CallRef(call_id="r1", name="read_documents",
                                                  ai_idx=5, position=0, seq=0,
                                                  kind="parallel"),
                             content, "ok", doc_refs=[{"collectionname": "c",
                                                       "file_hash": HASH_A}])
    [message] = written
    assert message.content == content
    [entry] = message.usage["evidence"]
    assert entry["source"]["thread_id"] == THREAD and entry["source"]["message_idx"] == 6
    assert entry["reference"]["file_hash"] == HASH_A


def test_a_legacy_tool_message_gives_only_what_its_content_shows():
    content = _read_page(_item(HASH_A))
    messages = [_message(0, "human", "q"),
                _ai(1, calls=[{"id": "r1", "name": "read_documents", "args": {}}]),
                _tool(2, "read_documents", content, "r1", evidence=False)]
    report = reports.project(messages, thread_id=THREAD, first_run_id=FIRST,
                             state="completed", session_citations=[])
    assert report["diagnostics"]["legacy_tool_messages"] == 1
    [entry] = report["documents_read"]
    assert entry["reference"]["file_hash"] == HASH_A[:16]


# ---------------------------------------------------------------------- projection


def _corrected_thread():
    return [
        _message(0, "human", "Who signed the lease?"),
        _ai(1, "The tenant signed it.", reasoning="Maybe the tenant.",
            calls=[{"id": "r1", "name": "read_documents", "args": {}}]),
        _tool(2, "read_documents", _read_page(_item(HASH_A, text="Signed by the owner.")),
              "r1"),
        _message(3, "human", "Your context is at 80 percent of its limit."),
        _ai(4, "Correction: the owner signed it [D1]."),
    ]


def test_a_correction_and_the_final_answer_stay_distinct():
    report = reports.project(_corrected_thread(), thread_id=THREAD, first_run_id=FIRST,
                             state="completed", result="Correction: the owner signed it [D1].",
                             session_citations=[])
    assert [t["text"] for t in report["recent_text"]] == [
        "The tenant signed it.", "Correction: the owner signed it [D1]."]
    assert [t["source"]["message_idx"] for t in report["recent_text"]] == [1, 4]
    assert report["final_answer"]["source"]["message_idx"] == 4


def test_model_text_and_metadata_stay_separate():
    report = reports.project(_corrected_thread(), thread_id=THREAD, first_run_id=FIRST,
                             state="completed", result="Correction: the owner signed it [D1].",
                             session_citations=[])
    texts = " ".join(t["text"] for t in report["recent_text"])
    assert "Maybe the tenant" not in texts and "percent of its limit" not in texts
    assert "Signed by the owner" not in texts
    assert report["documents_read"][0]["kind"] == "document_read"
    assert report["diagnostics"]["citation_check"]["unresolved"] == ["[D1]"]
    body = reports.render(report)
    answer, _, evidence = body.partition("## Evidence of the run")
    assert "the owner signed it" in answer and "Documents read" not in answer
    assert "Documents read" in evidence and "[D1]" in evidence


def test_the_latest_three_texts_are_selected():
    messages = [_message(0, "human", "q")] + [_ai(i, f"text {i}") for i in range(1, 6)]
    report = reports.project(messages, thread_id=THREAD, first_run_id=FIRST,
                             state="completed", result="text 5", session_citations=[])
    assert [t["text"] for t in report["recent_text"]] == ["text 3", "text 4", "text 5"]


def test_a_researcher_that_fails_before_prose_keeps_its_evidence_and_reason():
    messages = [_message(0, "human", "Read the lease."),
                _ai(1, calls=[{"id": "r1", "name": "read_documents", "args": {}},
                              {"id": "r2", "name": "read_documents", "args": {}}]),
                _tool(2, "read_documents", _read_page(_item(HASH_A)), "r1")]
    report = reports.project(messages, thread_id=THREAD, first_run_id=FIRST, state="failed",
                             error="the model service did not answer", session_citations=[])
    assert report["execution"] == {"state": "failed", "end_reason": "",
                                   "incomplete": True,
                                   "error": "the model service did not answer"}
    assert report["final_answer"] is None and report["recent_text"] == []
    assert len(report["documents_read"]) == 1
    assert report["diagnostics"]["unanswered_calls"] == [
        {"source": {"thread_id": THREAD, "message_idx": 1}, "tool": "read_documents"}]
    body = reports.render(report)
    assert "ended failed" in body and "did not answer" in body and "Documents read" in body


def test_a_step_limited_thread_has_no_final_answer():
    messages = [_message(0, "human", "q"), _ai(1, "Partial finding.")]
    report = reports.project(messages, thread_id=THREAD, first_run_id=FIRST,
                             state="completed", end_reason="step_budget",
                             result="The run stopped at 600 model steps.", session_citations=[])
    assert report["final_answer"] is None
    assert report["execution"]["incomplete"] is True
    assert report["recent_text"][-1]["text"] == "Partial finding."


def test_a_question_is_the_final_answer_of_its_ask_user_step():
    messages = [_message(0, "human", "q"),
                _ai(1, calls=[{"id": "a1", "name": "ask_user", "args": {"question": "Which?"}}]),
                _message(2, "tool", "{}", tool_name="ask_user", tool_call_id="a1",
                         usage_json=json.dumps({"status": "ok"}))]
    report = reports.project(messages, thread_id=THREAD, first_run_id=FIRST,
                             state="completed", result="Which?", session_citations=[])
    assert report["final_answer"] == {"source": {"thread_id": THREAD, "message_idx": 1},
                                      "text": "Which?", "asked": True}


# ------------------------------------------------------------------- documents


@pytest.fixture
def plan_store(monkeypatch):
    """Report documents and run rows of one plan in lists."""
    store = {"documents": [], "rows": [], "messages": [], "run_writes": []}

    def write_document(username, session_id, plan_run_id, agent_run_id, node_id, role, kind,
                       body, attempt=0):
        doc_id = agent_plans.document_id(agent_run_id, kind)
        store["documents"] = [d for d in store["documents"] if d.document_id != doc_id]
        store["documents"].append(agent_plans.PlanDocument(doc_id, node_id, role, kind,
                                                           attempt, body))
        return doc_id

    monkeypatch.setattr(agent_plans, "write_document", write_document)
    monkeypatch.setattr(agent_plans, "read_documents", lambda *a: list(store["documents"]))
    monkeypatch.setattr(agent_runs, "read_messages", lambda *a: list(store["messages"]))
    monkeypatch.setattr(agent_runs, "read_session_tool_messages", lambda *a: {})
    monkeypatch.setattr(agent_runs, "write_run", lambda *a, **k: store["run_writes"].append(k))
    monkeypatch.setattr(reports, "_thread_rows", lambda u, s, t: [
        r for r in store["rows"] if r.thread_id == t])
    return store


def _sub_agent(state="completed", run_id=FIRST, continues=None, result="The lease is 2019."):
    return agent_runs.RunRow(run_id=run_id, username="u", session_id="s", thread_id=THREAD,
                             depth=1, kind="subagent", plan_run_id=PLAN_RUN,
                             plan_node_id=NODE, purpose="execute", state=state,
                             result=result, continues_run_id=continues)


def test_every_ending_writes_the_report_pair_under_the_first_run(plan_store):
    plan_store["messages"] = _corrected_thread()
    first = _sub_agent(state="completed")
    last = _sub_agent(state="running", run_id=CONTINUATION, continues=FIRST)
    reports.materialize(last, "cancelled", [first])
    kinds = {d.kind: d for d in plan_store["documents"]}
    assert set(kinds) == {"report", "report_data"}
    assert kinds["report_data"].document_id == agent_plans.document_id(FIRST, "report_data")
    assert kinds["report"].node_id == NODE
    data = json.loads(kinds["report_data"].body)
    assert data["execution"]["state"] == "cancelled" and data["first_run_id"] == FIRST
    # A retry writes the same two rows.
    reports.materialize(last, "cancelled", [first])
    assert len(plan_store["documents"]) == 2


def test_recovery_writes_one_report_from_committed_evidence(plan_store):
    """The worker stopped after the terminal row and before the report documents."""
    plan_store["messages"] = _corrected_thread()
    row = _sub_agent(state="failed", result="")
    plan_store["rows"] = [row]
    assert reports.ensure_reports([row]) == 1
    assert sorted(d.kind for d in plan_store["documents"]) == ["report", "report_data"]
    assert reports.ensure_reports([row]) == 0
    assert len(plan_store["documents"]) == 2
    assert plan_store["run_writes"] == []
    data = json.loads(next(d.body for d in plan_store["documents"] if d.kind == "report_data"))
    assert data["execution"]["state"] == "failed"
    assert len(data["documents_read"]) == 1


def test_recovery_skips_a_thread_that_is_still_running(plan_store):
    row = _sub_agent(state="running")
    plan_store["rows"] = [row]
    assert reports.ensure_reports([row]) == 0
    assert plan_store["documents"] == []


class _FakeS3:
    def __init__(self):
        self.stored = {}

    def bucket_exists(self, bucket):
        return True

    def put_object(self, bucket, key, data, length, content_type):
        self.stored[key] = data.read()


def test_a_large_body_is_stored_as_a_required_artifact(monkeypatch):
    import database.s3 as s3

    fake = _FakeS3()
    inserts = []
    monkeypatch.setattr(s3, "get_s3_client", lambda: fake)
    monkeypatch.setattr(agent_plans, "_insert", lambda table, rows, cols: inserts.append(
        (table, dict(zip(cols, rows[0])))))
    body = "x" * (agent_plans.INLINE_BODY_BYTES + 1)
    digest = hashlib.sha256(body.encode()).hexdigest()
    monkeypatch.setattr(agent_plans, "_artifact_digest", lambda *a: digest)
    doc_id = agent_plans.write_document("u", "s", PLAN_RUN, FIRST, NODE, "executor",
                                        "report_data", body)
    (artifact_table, artifact), (doc_table, doc) = inserts
    assert artifact_table == "chat_artifacts" and artifact["artifact_id"] == doc_id
    assert artifact["body_sha256"] == digest and artifact["username"] == "u"
    assert doc_table == "agent_plan_documents"
    assert doc["body_inline"] == "" and doc["artifact_id"] == doc_id
    assert doc["body_sha256"] == digest
    assert fake.stored[agent_plans.artifact_key("s", doc_id)] == body.encode()


def test_a_large_body_whose_digest_does_not_read_back_is_not_written(monkeypatch):
    import database.s3 as s3

    inserts = []
    monkeypatch.setattr(s3, "get_s3_client", lambda: _FakeS3())
    monkeypatch.setattr(agent_plans, "_insert", lambda table, rows, cols: inserts.append(table))
    monkeypatch.setattr(agent_plans, "_artifact_digest", lambda *a: None)
    with pytest.raises(agent_plans.DocumentBodyError):
        agent_plans.write_document("u", "s", PLAN_RUN, FIRST, NODE, "executor", "report",
                                   "y" * (agent_plans.INLINE_BODY_BYTES + 1))
    assert inserts == ["chat_artifacts"]


def test_the_artifact_key_matches_the_shared_copy():
    """Mirrors `agent_common.s3_store.artifact_key(session, id, "detail.json")`. The shared
    package's test compares the same literal."""
    assert agent_plans.artifact_key("s-1", "doc-1") == "derived/chat-artifacts/s-1/doc-1/detail.json"


def test_a_read_page_result_gives_one_entry_for_each_page():
    """One cut page and one failed page in one result. The text of the cut page holds a
    `---` line, which does not start a page."""
    text = (
        "## Lease terms\nhttps://example.org/lease\n\nFirst part.\n\n---\n\nStill the lease."
        "\n\n[cut: this call read 1,200 of the page's 5,000 characters. Call read_page with "
        "offset 1300 for the next part]"
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
    assert entries[0]["range"] == {"start_chars": 100, "end_chars": 1300, "total_chars": 5000}
    assert entries[1]["error"] == "COULD NOT READ: net::ERR_NAME_NOT_RESOLVED"
    assert entries[2]["error"].startswith("BLOCKED BY A BOT CHECK")
    assert len({e["item_key"] for e in entries}) == 3


@pytest.mark.parametrize("failure", [agent_plans.DocumentBodyError("no artifact row"),
                                     RuntimeError("the object store did not answer")])
def test_an_unreadable_typed_report_reads_as_absent(monkeypatch, failure):
    doc = agent_plans.PlanDocument(agent_plans.document_id(FIRST, "report_data"), NODE,
                                   "executor", "report_data", 0, "", artifact_id="a1")
    monkeypatch.setattr(agent_plans, "read_documents", lambda *a: [doc])

    def broken(*args):
        raise failure

    monkeypatch.setattr(agent_plans, "document_body", broken)
    assert agent_plans.read_report_data("u", "s", PLAN_RUN, FIRST) is None
