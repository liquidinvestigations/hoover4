"""Verify source ownership, exact quotes, and stable web citation handles."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from browser_use_server import page_citations as citations


@pytest.fixture
def store(monkeypatch):
    rows, bodies, committed = {}, {}, []

    def write(request, artifact_id, key, body, content_type):
        rows[artifact_id] = {"artifact_id": artifact_id, "title": request.title,
                             "url": request.url, "detail": request.detail,
                             "kind": request.kind, "owner": request.username,
                             "session": request.session_id}
        bodies[artifact_id] = body
        return artifact_id

    def query(sql, owner, session, **params):
        if "UNION ALL" in sql:
            return [{"result": json.dumps(value)} for value in committed]
        return [row for row in reversed(list(rows.values())) if row["owner"] == owner
                and row["session"] == session and row["kind"] == params["kind"]]

    def read(owner, session, artifact_id, start, length):
        row = rows[artifact_id]
        if (row["owner"], row["session"]) != (owner, session):
            raise citations.artifacts.ArtifactForbidden("The source belongs to another caller.")
        body = bodies[artifact_id]
        return body[start:start + length], len(body)

    monkeypatch.setattr(citations.artifacts, "write_required", write)
    monkeypatch.setattr(citations.artifacts, "read_range", read)
    monkeypatch.setattr(citations, "_query", query)
    return SimpleNamespace(rows=rows, bodies=bodies, committed=committed)


def read_source(text="Source α contains a verified statement.", version="version-1",
                owner="owner", session="chat", **extra):
    page = SimpleNamespace(url="https://source.example/page", final_url="https://source.example/page",
                           title="Source title", full_text=text, version=version,
                           error="", blocked=False)
    for key, value in extra.items():
        setattr(page, key, value)
    return citations.store_read(owner, session, page)


def cite(terms=None, owner="owner", session="chat", **extra):
    return asyncio.run(citations.cite(owner, session, [
        {"url": "https://source.example/page", "terms": terms or ["verified statement"], **extra}
    ]))


def test_quotes_retain_exact_unicode_text_and_source_offsets(store):
    artifact_id = read_source()
    result = cite()["citations"][0]
    assert result["artifact_id"] == artifact_id
    assert result["quotes"] == ["Source α contains a verified statement."]
    span = result["spans"][0]
    source = json.loads(store.bodies[artifact_id])["markdown"]
    assert source[span["start"]:span["end"]] == span["text"] == "verified statement"
    assert result["handle"] == "[W1]" and result["quote_verified"] is True


@pytest.mark.parametrize("count", [7, 12])
def test_source_lists_fit_the_document_citation_batch_size(store, count):
    pages = []
    for index in range(count):
        url = f"https://source.example/page-{index}"
        read_source(url=url, final_url=url)
        pages.append({"url": url, "terms": ["verified statement"]})
    result = asyncio.run(citations.cite("owner", "chat", pages))
    assert not result["errors"] and len(result["citations"]) == count
    assert [row["handle"] for row in result["citations"]] == [f"[W{n}]" for n in range(1, count + 1)]


def test_oversized_citation_list_allocates_no_handles(store):
    read_source()
    result = asyncio.run(citations.cite("owner", "chat", [
        {"url": "https://source.example/page", "terms": ["verified statement"]}
    ] * 13))
    assert not result["citations"] and result["errors"]
    assert not any(row["kind"] == citations.KIND_PAGE_CITATION for row in store.rows.values())


def test_absent_wording_returns_source_context_without_allocating_a_handle(store):
    exact = "The report describes starvation as a weapon of war."
    read_source("Opening text. " * 100 + "\n\n" + exact + "\n\n" + "Other text. " * 100)
    result = cite(terms=["The report states that starvation was a weapon of war."])
    assert not result["citations"]
    error = result["errors"][0]
    assert exact in error["candidate"] and len(error["candidate"]) <= 600
    assert error["version"] == "version-1"
    assert not any(row["kind"] == citations.KIND_PAGE_CITATION for row in store.rows.values())
    assert cite(terms=[exact])["citations"][0]["handle"] == "[W1]"


def test_repeat_and_new_versions_keep_distinct_stable_handles(store):
    first_id = read_source()
    assert cite()["citations"][0]["handle"] == "[W1]"
    read_source(version="version-2")
    assert cite()["citations"][0]["handle"] == "[W2]"
    old = cite(version="version-1")["citations"][0]
    assert old["handle"] == "[W1]" and old["artifact_id"] == first_id
    assert cite()["citations"][0]["handle"] == "[W2]"


def test_committed_handles_remain_reserved_after_binding_retention(store):
    read_source()
    old = cite()["citations"][0]
    store.committed.append({"citations": [old]})
    for key, row in list(store.rows.items()):
        if row["kind"] == citations.KIND_PAGE_CITATION:
            del store.rows[key]
    read_source(version="version-2")
    assert cite()["citations"][0]["handle"] == "[W2]"
    assert cite(version="version-1")["citations"][0]["handle"] == "[W1]"


@pytest.mark.parametrize("owner,session", [("other", "chat"), ("owner", "other"), ("", "chat")])
def test_another_owner_or_chat_cannot_cite_the_source(store, owner, session):
    read_source()
    result = cite(owner=owner, session=session)
    assert not result["citations"] and result["errors"]


@pytest.mark.parametrize("extra", [{"blocked": True}, {"error": "HTTP 403"}, {"full_text": ""}])
def test_failed_or_empty_reads_cannot_create_citations(store, extra):
    assert not read_source(**extra)
    assert not cite()["citations"]


def test_absent_or_wrong_case_terms_do_not_allocate_a_handle(store):
    read_source()
    for terms in (["invented words"], ["Verified Statement"]):
        result = cite(terms)
        assert not result["citations"] and "exact text" in result["errors"][0]["error"]
    assert cite()["citations"][0]["handle"] == "[W1]"


def test_case_mismatch_suggests_literal_source_terms_for_an_explicit_retry(store):
    read_source("Genocide as colonial erasure. Report [1] includes 4.2 points.")
    result = cite(terms=["genocide as colonial erasure", "report [1] includes 4.2"])
    assert not result["citations"]
    terms = result["errors"][0]["suggested_terms"]
    assert terms == ["Genocide as colonial erasure", "Report [1] includes 4.2"]
    assert not any(row["kind"] == citations.KIND_PAGE_CITATION for row in store.rows.values())
    ref = cite(terms=terms)["citations"][0]
    assert ref["handle"] == "[W1]" and ref["quote_verified"]
    assert [span["text"] for span in ref["spans"]] == terms


def test_absent_wording_does_not_suggest_a_partial_term_list(store):
    read_source()
    result = cite(terms=["Verified Statement", "absent wording"])
    assert not result["citations"]
    assert "suggested_terms" not in result["errors"][0]


def test_unknown_source_version_is_refused(store):
    read_source()
    result = cite(version="not-read")
    assert not result["citations"] and result["errors"]


def test_a_failed_binding_write_returns_no_citation(store, monkeypatch):
    read_source()
    def fail(*args):
        raise citations.artifacts.ArtifactWriteFailed("The source binding could not be stored.")
    monkeypatch.setattr(citations.artifacts, "write_required", fail)
    result = cite()
    assert not result["citations"] and "binding" in result["errors"][0]["error"]


def test_foreign_artifact_metadata_is_not_sufficient_to_read_it(store, monkeypatch):
    read_source(owner="other")
    original = citations._rows
    monkeypatch.setattr(citations, "_rows", lambda owner, session, kind:
                        original("other", session, kind))
    result = cite()
    assert not result["citations"] and "another caller" in result["errors"][0]["error"]


def test_one_invalid_page_does_not_discard_a_valid_citation(store):
    read_source()
    result = asyncio.run(citations.cite("owner", "chat", [
        {"url": "https://unread.example", "terms": ["Unseen text"]},
        {"url": "https://source.example/page", "terms": ["verified statement"]},
    ]))
    assert len(result["errors"]) == 1 and len(result["citations"]) == 1
    assert "partial success" in result["next_action"]
    assert "read_page, then call cite_pages again" in result["next_action"]
    assert '{"url":"COPY_READ_URL","terms":["COPY_EXACT_PHRASE"]}' in result["next_action"]


def test_conflicting_committed_handles_fail_before_allocation(store):
    read_source()
    store.committed.extend([{"handle": "[W1]", "url": "https://a.example", "version": "1"},
                            {"handle": "[W1]", "url": "https://b.example", "version": "1"}])
    with pytest.raises(ValueError, match="different source versions"):
        cite()


def test_parallel_calls_allocate_one_handle_for_one_version(store, monkeypatch):
    read_source()
    async def run():
        monkeypatch.setattr(citations, "_lock", asyncio.Lock())
        result = await asyncio.gather(*[
            citations.cite("owner", "chat", [{"url": "https://source.example/page",
                                             "terms": ["verified statement"]}])
            for _ in range(4)
        ])
        assert [item["citations"][0]["handle"] for item in result] == ["[W1]"] * 4
    asyncio.run(run())


def test_cancelled_allocation_keeps_its_lock_until_storage_finishes(monkeypatch):
    import threading
    started, release = threading.Event(), threading.Event()
    def blocked(*args):
        started.set()
        assert release.wait(2)
        raise ValueError("The storage operation failed after cancellation.")
    monkeypatch.setattr(citations, "_cite", blocked)
    async def run():
        monkeypatch.setattr(citations, "_lock", asyncio.Lock())
        task = asyncio.create_task(citations.cite("owner", "chat", [{}]))
        await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert citations._lock.locked() and not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not citations._lock.locked()
    asyncio.run(run())


@pytest.mark.parametrize("nested", [False, True])
def test_tool_accepts_flat_and_list_arguments_with_reasons(store, monkeypatch, nested):
    from browser_use_server import server
    read_source()
    monkeypatch.setattr(server, "_header", lambda name: "owner" if name == server.USER_HEADER else "chat")
    page = {"url": "https://source.example/page", "terms": ["verified statement"], "why": "Supports the statement."}
    tool = server.CitePagesTool(name="cite_pages", description=server.CITE_PAGES_DESCRIPTION,
                                parameters=server.CITE_PAGES_SCHEMA)
    result = asyncio.run(tool.run({"pages": [page]} if nested else page))
    payload = json.loads(result.content[0].text)
    assert payload["citations"][0]["why"] == page["why"]
    assert payload["citations"][0]["handle"] == "[W1]"
