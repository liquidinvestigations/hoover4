"""`write_required`: the strict artifact writer, raises instead of swallowing a failure.

No live ClickHouse or S3 call: `s3_store.put_bytes`, `artifacts.insert_row` and
`artifacts._read_back_body_sha256` are monkeypatched, one fake per test, so what is under
test is the ordering and error handling in `write_required` itself.
"""

from __future__ import annotations

import hashlib

import pytest

from agent_common import artifacts


def _request(session_id: str = "s1", username: str = "alice") -> artifacts.ArtifactRequest:
    return artifacts.ArtifactRequest(
        session_id=session_id,
        username=username,
        kind=artifacts.KIND_AGENT_RAW_RESULT,
        tool_name="search_collections",
    )


class TestWriteRequiredSuccess:
    def test_stores_object_then_row_then_confirms(self, monkeypatch):
        body = b'{"documents": []}'
        digest = hashlib.sha256(body).hexdigest()
        calls: list[str] = []

        monkeypatch.setattr(artifacts.s3_store, "get_s3_client", lambda: object())
        monkeypatch.setattr(
            artifacts.s3_store,
            "put_bytes",
            lambda key, data, content_type, client=None: (calls.append("put_bytes"), len(data))[1],
        )

        inserted_row: dict = {}

        def fake_insert_row(row: artifacts.ArtifactRow) -> None:
            calls.append("insert_row")
            inserted_row.update(row.as_json_row())

        monkeypatch.setattr(artifacts, "insert_row", fake_insert_row)
        monkeypatch.setattr(
            artifacts, "_read_back_body_sha256", lambda username, artifact_id: (calls.append("read_back"), digest)[1]
        )

        result = artifacts.write_required(_request(), "artifact-1", "idem-1", body, "application/json")

        assert result == "artifact-1"
        assert calls == ["put_bytes", "insert_row", "read_back"]
        assert inserted_row["body_sha256"] == digest
        assert inserted_row["idempotency_key"] == "idem-1"
        assert inserted_row["status"] == artifacts.STATUS_OK
        assert inserted_row["body_key"]  # non-empty: the route needs it to serve a body


class TestWriteRequiredFailures:
    def test_no_session_raises(self, monkeypatch):
        monkeypatch.setattr(artifacts.s3_store, "put_bytes", lambda *a, **k: 0)
        with pytest.raises(artifacts.ArtifactWriteFailed):
            artifacts.write_required(_request(session_id=""), "artifact-1", "idem-1", b"x", "application/json")

    def test_object_write_failure_raises(self, monkeypatch):
        monkeypatch.setattr(artifacts.s3_store, "get_s3_client", lambda: object())

        def boom(*a, **k):
            raise RuntimeError("s3 is down")

        monkeypatch.setattr(artifacts.s3_store, "put_bytes", boom)
        with pytest.raises(artifacts.ArtifactWriteFailed):
            artifacts.write_required(_request(), "artifact-1", "idem-1", b"x", "application/json")

    def test_row_insert_failure_raises(self, monkeypatch):
        monkeypatch.setattr(artifacts.s3_store, "get_s3_client", lambda: object())
        monkeypatch.setattr(artifacts.s3_store, "put_bytes", lambda *a, **k: 1)

        def boom(row):
            raise RuntimeError("clickhouse is down")

        monkeypatch.setattr(artifacts, "insert_row", boom)
        with pytest.raises(artifacts.ArtifactWriteFailed):
            artifacts.write_required(_request(), "artifact-1", "idem-1", b"x", "application/json")

    def test_digest_mismatch_on_readback_raises(self, monkeypatch):
        monkeypatch.setattr(artifacts.s3_store, "get_s3_client", lambda: object())
        monkeypatch.setattr(artifacts.s3_store, "put_bytes", lambda *a, **k: 1)
        monkeypatch.setattr(artifacts, "insert_row", lambda row: None)
        monkeypatch.setattr(artifacts, "_read_back_body_sha256", lambda username, artifact_id: "wrong-digest")

        with pytest.raises(artifacts.ArtifactWriteFailed):
            artifacts.write_required(_request(), "artifact-1", "idem-1", b"x", "application/json")

    def test_disabled_container_raises(self, monkeypatch):
        monkeypatch.setattr(artifacts, "enabled", lambda: False)
        with pytest.raises(artifacts.ArtifactWriteFailed):
            artifacts.write_required(_request(), "artifact-1", "idem-1", b"x", "application/json")
