"""Verify the stored result and model display contracts."""

import json

import pytest

from agent_common import workspace_results


@pytest.mark.parametrize("length", [14999, 15000, 15001])
def test_display_counts_unicode_characters(length):
    text = "α" * 2000 + "中" * (length - 4000) + "終" * 2000
    reference = {"path": "sources/web/example", "version": "fixed"}
    shown = workspace_results.display(text, reference, 15000)
    if length <= 15000:
        assert shown is None
    else:
        assert shown.startswith("α" * 2000)
        assert shown.endswith("終" * 2000)
        assert f"{length - 4000} characters omitted" in shown
        assert shown.count("sources/web/example") == 1


def test_storage_failure_has_no_recovery_path():
    shown = workspace_results.display("a" * 16000, None, 15000)
    assert "could not be saved" in shown
    assert "result_ref" not in shown


def test_document_identity_separates_identical_source_text(monkeypatch):
    rows = {}
    monkeypatch.setattr(workspace_results.artifacts, "_artifact_row", rows.get)

    def store(request, artifact_id, operation, body, content_type):
        rows[artifact_id] = json.loads(request.detail)
        return artifact_id

    monkeypatch.setattr(workspace_results.artifacts, "write_required", store)
    first = workspace_results.save("reader", "chat", "call", "read_documents",
                                   "same text", ["one"], {"file_hash": "a"})
    second = workspace_results.save("reader", "chat", "call", "read_documents",
                                    "same text", ["one"], {"file_hash": "b"})
    retry = workspace_results.save("reader", "chat", "call", "read_documents",
                                   "same text", ["one"], {"file_hash": "a"})
    assert first == retry
    assert second["path"] != first["path"]
    assert second["version"] == first["version"]
    assert len(rows) == 2
