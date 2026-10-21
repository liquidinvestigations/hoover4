"""Verify command outcomes, fixed comparisons, and independent grading."""

from copy import deepcopy
import json
import pytest
from scripts.chat_review.run import execute, main
from scripts.chat_review.client import Client, TransportFailure, read_json
from scripts.chat_review.schema import digest
from .conftest import reference_for, labels_for, empty_review, make_packet, approve


def test_cli_grade_and_resume(packet, tmp_path):
    reference = reference_for(packet)
    inputs = {"packet": packet, "delivery": packet["delivery"], "reference": reference, "labels": labels_for(reference)}
    result, code = execute("grade", inputs, tmp_path / "grade")
    assert code == 0 and result["verdict"] == "delivery_pass"
    assert execute("grade", inputs, tmp_path / "grade", resume=True)[1] == 0
    assert main(["grade", "--packet", "absent", "--delivery", "absent", "--reference", "absent", "--labels", "absent", "--out", str(tmp_path/'x')]) == 4


def test_cli_grade_failure_does_not_become_transport_error(packet, tmp_path):
    reference = reference_for(packet, labels={"cities.md": "unsupported"})
    result, code = execute("grade", {"packet": packet, "delivery": packet["delivery"],
                           "reference": reference, "labels": labels_for(reference)}, tmp_path / "grade")
    assert code == 1
    assert result["verdict"] == "delivery_fail"


def test_comparison_keeps_quality_separate_from_execution(packet, config, tmp_path, monkeypatch):
    def response(self, messages, directory):
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(empty_review(packet))}}]}
    monkeypatch.setattr(Client, "__call__", response)
    reference = reference_for(packet, labels={"cities.md": "unsupported"})
    schedule = {"schema_version": 1, "attempts": [{"id": "method-a", "pair": "case", "command": "review",
                "inputs": {"packet": packet, "config": config},
                "grade_inputs": {"reference": reference, "labels": labels_for(reference)}}]}
    result, code = execute("compare", {"schedule": schedule}, tmp_path / "compare")
    assert code == 0
    assert result["quality"][0]["verdict"] == "delivery_fail"
    assert result["attempts"][0]["execution_code"] == 0


def test_comparison_rejects_unmatched_packets(packet, config, tmp_path):
    other = make_packet(closing="Different answer.")
    schedule = {"schema_version": 1, "attempts": [{"id": name, "pair": "case", "command": "review",
                "inputs": {"packet": p, "config": config}} for name, p in (("a", packet), ("b", other))]}
    assert execute("compare", {"schedule": schedule}, tmp_path / "compare")[1] == 4


def test_transport_failure_remains_distinct(packet, config, tmp_path, monkeypatch):
    def fail(*args):
        raise TransportFailure("No response.")
    monkeypatch.setattr(Client, "__call__", fail)
    result, code = execute("review", {"packet": packet, "config": config}, tmp_path / "review")
    assert code == 3 and result["state"] == "transport_failed"


def test_interrupt_is_recorded(packet, config, tmp_path, monkeypatch):
    def stop(*args):
        raise KeyboardInterrupt
    monkeypatch.setattr(Client, "__call__", stop)
    result, code = execute("review", {"packet": packet, "config": config}, tmp_path / "review")
    assert code == 130 and result["outcome"] == "unknown"


def test_reference_and_labels_never_enter_review_prompt(packet, config, tmp_path, monkeypatch):
    seen = []
    def response(self, messages, directory):
        seen.append(messages)
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(empty_review(packet))}}]}
    monkeypatch.setattr(Client, "__call__", response)
    reference = reference_for(packet)
    reference["author"] = "INDEPENDENT-REFERENCE-SECRET"
    approve(reference)
    schedule = {"schema_version": 1, "attempts": [{"id": "a", "pair": "case", "command": "review",
        "inputs": {"packet": packet, "config": config},
        "grade_inputs": {"reference": reference, "labels": labels_for(reference)}}]}
    assert execute("compare", {"schedule": schedule}, tmp_path / "compare")[1] == 0
    assert "INDEPENDENT-REFERENCE-SECRET" not in json.dumps(seen)


def test_comparison_invalid_grade_is_incomplete(packet, config, tmp_path, monkeypatch):
    monkeypatch.setattr(Client, '__call__', lambda *args: {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(empty_review(packet))}}]})
    reference = reference_for(packet)
    labels = labels_for(reference)
    labels['reference_digest'] = 'a' * 64
    schedule = {'schema_version': 1, 'attempts': [{'id': 'a', 'pair': 'case', 'command': 'review',
                'inputs': {'packet': packet, 'config': config}, 'grade_inputs': {'reference': reference, 'labels': labels}}]}
    result, code = execute('compare', {'schedule': schedule}, tmp_path / 'compare')
    assert code == 2
    assert result['attempts'][0]['grade']['state'] == 'invalid'


def test_comparison_interrupt_returns_interrupt_status(packet, config, tmp_path, monkeypatch):
    def interrupt(*args):
        raise KeyboardInterrupt
    monkeypatch.setattr(Client, '__call__', interrupt)
    schedule = {'schema_version': 1, 'attempts': [{'id': 'a', 'pair': 'case', 'command': 'review',
                'inputs': {'packet': packet, 'config': config}}]}
    assert execute('compare', {'schedule': schedule}, tmp_path / 'compare')[1] == 130
