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


# --------------------------------------------------------------------------------------
# read_range: the owner check and the clamp
# --------------------------------------------------------------------------------------


def _range_row(monkeypatch, body: bytes, username="alice", session_id="s1"):
    from agent_common import artifacts as artifacts_module, s3_store as store_module

    reads = []
    monkeypatch.setattr(artifacts_module, "_artifact_row", lambda artifact_id: {
        "username": username, "session_id": session_id, "body_key": "k", "body_bytes": len(body),
    } if artifact_id == "a1" else None)

    def get_range(key, start, length, client=None):
        reads.append((start, length))
        return body[start:start + length]

    monkeypatch.setattr(store_module, "get_range", get_range)
    return reads


def test_read_range_returns_the_owner_a_clamped_range(monkeypatch):
    from agent_common.artifacts import read_range

    reads = _range_row(monkeypatch, b"0123456789")
    assert read_range("alice", "s1", "a1", 4, 3) == (b"456", 10)
    assert read_range("alice", "s1", "a1", 8, 100) == (b"89", 10)
    assert reads == [(4, 3), (8, 2)]


def test_read_range_refuses_another_caller_and_another_chat(monkeypatch):
    import pytest
    from agent_common.artifacts import ArtifactForbidden, ArtifactNotFound, read_range

    reads = _range_row(monkeypatch, b"0123456789")
    for username, session_id in (("mallory", "s1"), ("alice", "s2"), ("", "s1")):
        with pytest.raises(ArtifactForbidden):
            read_range(username, session_id, "a1", 0, 1)
    with pytest.raises(ArtifactNotFound):
        read_range("alice", "s1", "unknown", 0, 1)
    assert reads == []


def test_read_range_refuses_a_start_past_the_end(monkeypatch):
    import pytest
    from agent_common.artifacts import ArtifactRangeRefused, read_range

    _range_row(monkeypatch, b"0123456789")
    for start in (10, 11):
        with pytest.raises(ArtifactRangeRefused):
            read_range("alice", "s1", "a1", start, 1)
    with pytest.raises(ArtifactRangeRefused):
        read_range("alice", "s1", "a1", -1, 1)
