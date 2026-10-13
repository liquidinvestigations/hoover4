"""History failures retain bounded diagnostics without response bodies."""

import json
from types import SimpleNamespace

import requests

from tasks import operation_failure_capture as capture


def test_http_failure_retains_status_without_sensitive_response(monkeypatch):
    response = SimpleNamespace(status_code=503, text="private response content")

    def fail(*args, **kwargs):
        raise requests.HTTPError("private URL and response", response=response)

    monkeypatch.setattr(requests, "get", fail)
    errors = []
    assert capture._fetch_history_http("workflow", "run", errors) is None
    assert errors == [{"workflow_id": "workflow", "run_id": "run",
                       "error_type": "HTTPError", "http_status": 503}]
    assert "private" not in json.dumps(errors)


def test_capture_persists_history_error_alongside_chain(monkeypatch):
    def fetch(workflow_id, run_id, errors=None):
        errors.append({"error_type": "ReadTimeout", "http_status": None})
        return None

    monkeypatch.setattr(capture, "_fetch_history_http", fetch)
    monkeypatch.setattr(capture, "_resolve_op_id", lambda *args: "operation")
    rows = []
    monkeypatch.setattr(capture, "_insert_rows", lambda values: rows.extend(values) or len(values))
    params = capture.CaptureOperationFailureParams(
        "operation", "operation", "run", chain="ApplicationError\nmessage=failure")
    assert capture._capture_operation_failure_body(params) == "wrote 1"
    details = json.loads(rows[0][capture.FAILURE_COLUMNS.index("details_json")])
    assert details["truncated_reason"] == "history_read_failed"
    assert details["history_read_errors"] == [{"error_type": "ReadTimeout", "http_status": None}]
