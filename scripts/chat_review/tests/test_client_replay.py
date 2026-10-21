"""Preserve failed requests and isolate corrections from storage writers."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
import requests

from scripts.chat_review.client import (TransportFailure, begin_attempt, finish_attempt, make_request,
                                       read_json, request_review, response_content)
from scripts.chat_review.replay import propose_delivery, delivery_diff, verify_delivery
from scripts.chat_review.review import run_review
from scripts.chat_review.schema import Incomplete, Invalid, digest, review_scope, text_digest
from scripts.chat_review.grade import grade
from .conftest import empty_review, reference_for, labels_for, approve, seal


def response(value, finish="stop"):
    return {"choices": [{"finish_reason": finish, "message": {"content": json.dumps(value)}}]}


def receipt(packet):
    return {"state": "review_complete", "packet_digest": packet["identity"]["packet_digest"],
            "review_scope": review_scope(packet["delivery"]), "review": empty_review(packet)}


def proposal(packet):
    return {"files": [{"name": f["name"], "content": f["content"], "requirement_id": None}
                       for f in packet["delivery"]["files"]],
            "closing_answer": packet["delivery"]["closing_answer"]["content"], "audit": []}


@pytest.mark.parametrize("value", [None, {}, {"choices": []}, {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
                                  {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]}])
def test_empty_or_truncated_response_is_incomplete(value, packet, config, tmp_path):
    result, code = run_review(packet, packet["delivery"], config, tmp_path, lambda *_: value)
    assert code == 2
    assert result["state"] == "review_incomplete"


def test_transport_does_not_retry_or_record_secrets(monkeypatch, tmp_path):
    calls = []
    def fail(*args, **kwargs):
        calls.append(kwargs)
        raise requests.ReadTimeout("private-token private-endpoint")
    monkeypatch.setattr(requests, "post", fail)
    endpoint = SimpleNamespace(base_url="https://example.invalid", api_key="private-token")
    with pytest.raises(TransportFailure):
        request_review({"model": "fixture"}, endpoint, tmp_path / "call", (2, 8))
    assert len(calls) == 1
    assert calls[0]["timeout"] == (2, 8)
    assert calls[0]["allow_redirects"] is False
    assert "private-token" not in "".join(p.read_text() for p in (tmp_path / "call").iterdir())
    assert read_json(tmp_path / "call/status.json")["outcome"] == "unknown"


def test_provider_rejection_is_not_silently_retried(monkeypatch, tmp_path):
    monkeypatch.setattr(requests, "post", lambda *a, **k: SimpleNamespace(status_code=400))
    with pytest.raises(Invalid):
        request_review({"model": "fixture"}, SimpleNamespace(base_url="https://example.invalid", api_key=""), tmp_path / "call")
    assert read_json(tmp_path / "call/status.json")["body_omitted"]


def test_explicit_settings(config):
    body = make_request([], config)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["max_tokens"] == 1000
    assert "temperature" not in body


def test_resume_rejects_changed_packet_or_prompt(tmp_path):
    out = tmp_path / "attempt"
    inputs = {"packet": "original", "prompt": "original"}
    assert begin_attempt(out, inputs) is None
    finish_attempt(out, {"state": "review_complete"}, 0)
    assert begin_attempt(out, inputs, True)["exit_code"] == 0
    with pytest.raises(Invalid):
        begin_attempt(out, {**inputs, "prompt": "changed"}, True)
    with pytest.raises(Invalid):
        begin_attempt(out, {**inputs, "packet": "changed"}, True)
    (out / "manifest.json").write_text("{}")
    with pytest.raises(Invalid):
        begin_attempt(out, inputs, True)


def test_interrupted_attempt_requires_new_directory(tmp_path):
    out = tmp_path / "attempt"
    begin_attempt(out, {})
    with pytest.raises(Invalid):
        begin_attempt(out, {}, True)


def test_replay_keeps_workspace_version_separate_from_local_revision(packet, tmp_path):
    original = deepcopy(packet)
    value = proposal(packet)
    value["files"][0]["content"] = "The cities are Rome and Madrid."
    delivery = propose_delivery(packet, receipt(packet), lambda *_: response(value), tmp_path)
    assert packet == original
    assert delivery["files"][0]["base_version"] == 2
    assert "version" not in delivery["files"][0]
    assert delivery_diff(packet["delivery"], delivery)["changed"] == ["cities.md"]
    assert (tmp_path / "files/cities.md").read_text() == value["files"][0]["content"]


def test_replay_never_calls_production_writer(packet, tmp_path, monkeypatch):
    from database import chat_workspace
    def forbidden(*args, **kwargs):
        pytest.fail("Replay called a production writer.")
    monkeypatch.setattr(chat_workspace, "write_version", forbidden)
    monkeypatch.setattr(chat_workspace, "write_receipt", forbidden)
    propose_delivery(packet, receipt(packet), lambda *_: response(proposal(packet)), tmp_path)


@pytest.mark.parametrize("mode", ["traversal", "extra", "omission", "source"])
def test_replay_rejects_invalid_output_before_writing(packet, tmp_path, mode):
    value = proposal(packet)
    if mode == "traversal":
        value["files"][0]["name"] = "../cities.md"
    elif mode == "extra":
        value["files"].append({"name": "unrequested.md", "content": "new", "requirement_id": None})
    elif mode == "source":
        value["evidence"] = []
    else:
        value["files"] = []
    with pytest.raises(Incomplete):
        propose_delivery(packet, receipt(packet), lambda *_: response(value), tmp_path)
    assert not (tmp_path / "files").exists()


def test_replay_can_restore_an_explicit_missing_output(packet, tmp_path):
    packet["delivery"]["files"] = []
    packet["coverage"]["available"] = ["<closing>"]
    seal(packet)
    value = {"files": [{"name": "cities.md", "content": "Rome and Madrid.", "requirement_id": "req-cities"}],
             "closing_answer": "The report is ready.", "audit": []}
    result = propose_delivery(packet, receipt(packet), lambda *_: response(value), tmp_path)
    assert result["files"][0]["base_version"] is None
    assert result["files"][0]["base_digest"] is None


def test_verification_binds_corrected_delivery_digest(packet, config, tmp_path):
    value = proposal(packet)
    value["closing_answer"] = "Corrected city report."
    proposed = propose_delivery(packet, receipt(packet), lambda *_: response(value), tmp_path)
    verify_dir = tmp_path / "verify"
    verify_dir.mkdir()
    seen = []
    def stale(messages, _):
        seen.extend(messages)
        return response(empty_review(packet))
    _, code = verify_delivery(packet, proposed, stale, config, verify_dir)
    assert code == 2
    payload = json.loads(seen[1]["content"])
    assert payload["delivery_digest"] == digest(proposed)
    assert "findings" not in payload
    assert "audit" not in payload


def test_changed_closing_cannot_be_described_as_unchanged(packet, tmp_path):
    value = proposal(packet)
    value["closing_answer"] = "The closing answer stayed unchanged."
    proposed = propose_delivery(packet, receipt(packet), lambda *_: response(value), tmp_path)
    ref = reference_for(packet, proposed)
    ref["files"][1]["claims"][0]["action_check"] = {"target": "<closing>", "changed": False}
    approve(ref)
    assert grade(packet, proposed, ref, labels_for(ref))["verdict"] == "delivery_fail"


def test_duplicate_json_fields_are_rejected():
    reply = {"choices": [{"finish_reason": "stop", "message": {"content": '{"findings":[],"findings":"bad"}'}}]}
    with pytest.raises(Invalid):
        response_content(reply)
