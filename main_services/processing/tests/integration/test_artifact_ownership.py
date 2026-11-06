"""Verify proven capture repair and deletion against actual metadata and object stores."""
import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from database import agent_runs, artifact_ownership, clickhouse
from database.s3 import get_s3_client
from tasks.P_admin import artifact_sweeper
from .test_agent_recovery import global_store

pytestmark = pytest.mark.integration


def seed(owner="owner", chat="actual-chat", artifact="capture", deleted=False):
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    run = str(uuid.uuid4())
    agent_runs.create_run(agent_runs.RunRow(run, owner, chat, thread_id=str(uuid.uuid4())))
    with clickhouse.get_global_client() as client:
        client.insert("chat_sessions", [[chat, owner, now, int(deleted)]],
                      column_names=["session_id", "username", "updated_at", "is_deleted"])
        client.insert("chat_artifacts", [[artifact, run, owner, "page_capture", "body", 4, now, now]],
                      column_names=["artifact_id", "session_id", "username", "kind", "body_key", "body_bytes", "created_at", "updated_at"])
    return run, now


def test_repair_progress_preserves_shared_bytes_then_chat_deletion_collects_them(global_store, monkeypatch):
    bucket = "capture-recovery-" + uuid.uuid4().hex[:12]
    storage = get_s3_client()
    storage.make_bucket(bucket)
    monkeypatch.setattr(artifact_sweeper, "BUCKET", bucket)
    try:
        storage.put_object(bucket, "body", io.BytesIO(b"body"), 4)
        run, now = seed()
        with clickhouse.get_global_client() as client:
            client.insert("chat_artifacts", [["unknown", str(uuid.uuid4()), "aaa", "page_capture"]],
                          column_names=["artifact_id", "session_id", "username", "kind"])
        first = artifact_ownership.repair_browser_ownership(apply=True, limit=1)
        assert first["unproven"] == 1
        second = artifact_ownership.repair_browser_ownership(apply=True, limit=1, after=tuple(first["next"]))
        assert second["repaired"] == 1
        with clickhouse.get_global_client() as client:
            assert client.query("SELECT session_id,body_key FROM chat_artifacts FINAL WHERE artifact_id='capture'").result_rows == [("actual-chat", "body")]
            client.insert("chat_artifacts", [["capture", run, "owner", "page_capture", "body", now+timedelta(seconds=5), 1]],
                          column_names=["artifact_id", "session_id", "username", "kind", "body_key", "updated_at", "is_deleted"])
        assert artifact_sweeper.sweep().deleted_objects == 0
        assert storage.stat_object(bucket, "body").size == 4
        with clickhouse.get_global_client() as client:
            client.insert("chat_sessions", [["actual-chat", "owner", now+timedelta(seconds=10), 1]],
                          column_names=["session_id", "username", "updated_at", "is_deleted"])
        assert artifact_sweeper.sweep().deleted_objects == 1
        from minio.error import S3Error
        with pytest.raises(S3Error) as missing:
            storage.stat_object(bucket, "body")
        assert missing.value.code == "NoSuchKey"
    finally:
        for item in storage.list_objects(bucket, recursive=True):
            storage.remove_object(bucket, item.object_name)
        storage.remove_bucket(bucket)


def test_repair_observes_chat_deletion_during_replacement(global_store, monkeypatch):
    run, now = seed()
    original = artifact_ownership.insert_durable
    def delete_chat_after_insert(client, table, rows, **kwargs):
        original(client, table, rows, **kwargs)
        client.insert("chat_sessions", [["actual-chat", "owner", now+timedelta(seconds=10), 1]],
                      column_names=["session_id", "username", "updated_at", "is_deleted"])
    monkeypatch.setattr(artifact_ownership, "insert_durable", delete_chat_after_insert)
    assert artifact_ownership.repair_browser_ownership(apply=True)["repaired"] == 1
    with clickhouse.get_global_client() as client:
        assert client.query("SELECT count() FROM chat_artifacts FINAL WHERE artifact_id='capture'").result_rows == [(0,)]


def test_partial_repair_preserves_newer_target_tombstone(global_store):
    run, now = seed()
    with clickhouse.get_global_client() as client:
        client.insert("chat_artifacts", [["capture", "actual-chat", "owner", "page_capture", "newer metadata", "body", now+timedelta(seconds=60), 1]],
                      column_names=["artifact_id", "session_id", "username", "kind", "title", "body_key", "updated_at", "is_deleted"])
    assert artifact_ownership.repair_browser_ownership(apply=True)["repaired"] == 1
    with clickhouse.get_global_client() as client:
        assert client.query("SELECT title,is_deleted FROM chat_artifacts WHERE session_id='actual-chat' ORDER BY updated_at DESC LIMIT 1").result_rows == [("newer metadata", 1)]
        assert client.query("SELECT count() FROM chat_artifacts WHERE session_id={run:String}", parameters={"run": run}).result_rows == [(0,)]


def test_conflicting_target_retains_original_object_reference(global_store):
    run, now = seed()
    with clickhouse.get_global_client() as client:
        client.insert("chat_artifacts", [["capture", "actual-chat", "owner", "page_capture", "different"]],
                      column_names=["artifact_id", "session_id", "username", "kind", "body_key"])
    result = artifact_ownership.repair_browser_ownership(apply=True)
    assert result["conflicted"] == 1 and result["repaired"] == 0
    with clickhouse.get_global_client() as client:
        assert client.query("SELECT body_key FROM chat_artifacts FINAL WHERE session_id={s:String}",
                            parameters={"s": run}).result_rows == [("body",)]
