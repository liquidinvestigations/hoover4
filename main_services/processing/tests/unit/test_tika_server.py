"""Verify Tika response classes, type hints, and metadata persistence."""

from contextlib import nullcontext
from types import SimpleNamespace
import pytest
import requests
from temporalio.exceptions import ApplicationError

from tasks.P3_parse_files import parse_tika as tika
from tasks.remote import RemoteBusy


def response(status=200, metadata=None, body="server failure", headers=None):
    return SimpleNamespace(status_code=status, text=body, headers=headers or {},
                           json=lambda: metadata or {"Content-Type": "text/plain", "tk:content": "body"})


@pytest.mark.parametrize("status,error,retryable", [
    (422, "TikaParseFailed", False), (413, "TikaOutputTooLarge", False),
    (503, "TikaServiceFailed", False), (500, "TikaServiceFailed", True),
])
def test_http_failures(status, error, retryable):
    answer = tika._answer(response(status, headers={"Retry-After": "5"}))
    assert answer.error.type == error
    assert answer.error.non_retryable is not retryable
    assert "server failure" in answer.error.message


def test_busy_response():
    with pytest.raises(RemoteBusy) as caught:
        tika._answer(response(429, headers={"Retry-After": "45"}))
    assert caught.value.retry_after_seconds == 45


def test_json_document_type_and_cut_text():
    answer = tika._answer(response(metadata={
        "Content-Type": "text/x-vcard; charset=windows-1252", "tk:content": "cut body",
        "tk:exception:write-limit-reached": "true",
        "tk:exception:container-exception": "org.apache.tika.exception.WriteLimitReachedException",
    }, headers={"Content-Type": "application/json"}))
    assert tika.document_type(answer.metadata) == "text/x-vcard"
    assert answer.text == "cut body" and answer.error is None
    assert answer.metadata["tk:exception:write-limit-reached"] == "true"


def test_java_exception_is_retained_and_bounded():
    answer = tika._answer(response(metadata={"tk:exception:container-exception": "java exception" * 1000}))
    assert answer.error.type == "TikaParseFailed" and answer.error.non_retryable
    assert len(answer.error.message) == 4000
    assert len(answer.metadata["tk:exception:container-exception"]) > 4000


@pytest.mark.parametrize("types,routes,endpoint", [
    (["application/x-hoover-pst"], ["archive"], None),
    (["application/vnd.ms-outlook-pst"], ["archive"], None),
    (["application/mbox"], ["archive"], None),
    (["text/vcard"], ["text"], "/meta"), (["text/calendar"], ["text"], "/meta"),
    (["message/rfc822"], ["email", "text"], "/meta"),
    (["application/zip"], ["archive"], "/meta"), (["image/png"], ["image"], "/meta"),
    (["image/svg+xml"], ["image"], "/tika/json/text"),
    (["application/pdf"], ["pdf"], "/tika/json/text"),
])
def test_endpoint(types, routes, endpoint):
    assert tika.endpoint_for(tika.RunTikaParams("c", "ds", "h", "path", 1900,
                                             mime_types=types, routes=routes)) == endpoint


def test_stream_and_one_type_retry(tmp_path, monkeypatch):
    path = tmp_path / "hash"
    path.write_bytes(b"document")
    answers = [response(metadata={"Content-Type": "application/octet-stream",
                                 "tk:exception:container-exception": "java parse error"}),
               response(metadata={"Content-Type": "application/pdf", "tk:content": "text"})]
    calls = []
    def put(url, *, data, headers, timeout):
        calls.append((url, data.read(), dict(headers), timeout))
        return answers.pop(0)
    monkeypatch.setattr(tika.requests, "put", put)
    monkeypatch.setattr(tika, "heartbeat_pump", lambda *a: nullcontext())
    params = tika.RunTikaParams("c", "ds", "h", str(path), 1900,
                                file_mime_type="application/pdf", file_name='folder/naïve\n.pdf')
    answer = tika.parse_document(params)
    assert answer.error is None and answer.text == "text"
    assert len(calls) == 2 and calls[0][1] == calls[1][1] == b"document"
    assert "Content-Type" not in calls[0][2]
    assert calls[1][2]["Content-Type"] == "application/pdf"
    assert "%0A" in calls[0][2]["Content-Disposition"]
    assert calls[0][3][1] + 10 < params.timeout_seconds


def test_retry_names_both_attempts(tmp_path, monkeypatch):
    path = tmp_path / "hash"
    path.write_bytes(b"broken")
    monkeypatch.setattr(tika.requests, "put", lambda *a, **k: response(metadata={
        "Content-Type": "text/plain", "tk:exception:container-exception": "java parse error"}))
    monkeypatch.setattr(tika, "heartbeat_pump", lambda *a: nullcontext())
    answer = tika.parse_document(tika.RunTikaParams("c", "ds", "h", str(path), 1900,
                                                  file_mime_type="application/pdf"))
    assert "detected type 'text/plain'" in answer.error.message
    assert "requested type 'application/pdf'" in answer.error.message


def test_http_500_retries_once(tmp_path, monkeypatch):
    path = tmp_path / "hash"
    path.write_bytes(b"document")
    calls = []
    monkeypatch.setattr(tika.requests, "put", lambda *a, **k: calls.append(k) or response(500))
    monkeypatch.setattr(tika, "heartbeat_pump", lambda *a: nullcontext())
    answer = tika.parse_document(tika.RunTikaParams("c", "ds", "h", str(path), 1900))
    assert len(calls) == 2 and answer.error.non_retryable
    assert "Content-Disposition" not in calls[0]["headers"]


def test_connection_failure_stays_retryable(tmp_path, monkeypatch):
    path = tmp_path / "hash"
    path.write_bytes(b"document")
    def fail(*a, **k):
        raise requests.ConnectionError("connection failed")
    monkeypatch.setattr(tika.requests, "put", fail)
    monkeypatch.setattr(tika, "heartbeat_pump", lambda *a: nullcontext())
    with pytest.raises(requests.ConnectionError):
        tika.parse_document(tika.RunTikaParams("c", "ds", "h", str(path), 1900))


def test_metadata_and_type_are_stored_before_failure(monkeypatch):
    import database.clickhouse as db
    from tasks.P3_parse_files import word_binary, parse_common, temp_dirs
    metadata = {"Content-Type": "text/x-vcard; charset=windows-1252",
                "tk:exception:container-exception": "java parse error"}
    answer = tika._answer(response(metadata=metadata))
    stored = []
    monkeypatch.setattr(temp_dirs, "require_input_file", lambda p: None)
    monkeypatch.setattr(word_binary, "extract_binary_word_text", lambda p: "Word text")
    monkeypatch.setattr(parse_common, "insert_text_chunks", lambda *a: stored.append(("text", a)))
    monkeypatch.setattr(tika, "parse_document", lambda p: answer)
    monkeypatch.setattr(db, "get_collection_client", lambda c: nullcontext(object()))
    monkeypatch.setattr(db, "insert_arrow_durable", lambda c, name, table: stored.append((name, table.to_pylist())))
    with pytest.raises(ApplicationError) as caught:
        tika.run_tika_and_store(tika.RunTikaParams("c", "ds", "h", "input", 1900))
    assert caught.value.type == "TikaParseFailed"
    assert [name for name, _ in stored] == ["text", "tika_metadata", "file_types"]
    assert "java parse error" in stored[1][1][0]["tika_metadata_json"]
    assert stored[2][1][0]["mime_type"] == ["text/x-vcard"]
