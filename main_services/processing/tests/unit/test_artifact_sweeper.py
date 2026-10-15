"""The chat-artifact clean-up: no age limit, deleted chats, shared objects and orphan grace.

The ClickHouse client and the object store are replaced by fakes that hold the rows and
objects built here, so the test reads the decisions of `_sweep_rows` and `sweep` directly.
"""

import datetime
from types import SimpleNamespace

from tasks.P_admin import artifact_sweeper as sw

NOW = datetime.datetime.now(datetime.timezone.utc)
OLD = NOW - datetime.timedelta(days=400)


class FakeClient:
    """`chat_artifacts` rows as `(artifact_id, session, user, thumb, body, is_deleted)`."""

    def __init__(self, rows):
        self.rows = rows
        self.queries = []
        self.deleted = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def query(self, sql, parameters=None):
        self.queries.append(sql)
        if "max(is_deleted) = 1" in sql:
            selected = [r[:5] for r in self.rows if r[5] == 1]
        else:
            selected = [(r[0], r[3], r[4]) for r in self.rows]
        return SimpleNamespace(result_rows=selected)

    def command(self, sql, parameters=None):
        self.deleted.extend(parameters["ids"])
        self.rows = [r for r in self.rows if r[0] not in parameters["ids"]]


class FakeS3:
    def __init__(self, objects):
        self.objects = dict(objects)
        self.removed = []

    def remove_object(self, bucket, key):
        self.removed.append(key)
        self.objects.pop(key, None)

    def list_objects(self, bucket, prefix, recursive):
        return [SimpleNamespace(object_name=k, last_modified=t) for k, t in self.objects.items()
                if k.startswith(prefix)]


def key(name: str) -> str:
    return f"{sw.DERIVED_PREFIX}s/{name}"


def run(monkeypatch, rows, objects):
    client, s3 = FakeClient(rows), FakeS3(objects)
    monkeypatch.setattr("database.clickhouse.get_global_client", lambda: client)
    monkeypatch.setattr("database.s3.get_s3_client", lambda: s3)
    return sw.sweep(), client, s3


def test_an_old_live_artifact_stays_and_the_select_has_no_age_rule(monkeypatch):
    rows = [("live-old", "s", "u", "", key("old-body"), 0)]
    result, client, s3 = run(monkeypatch, rows, {key("old-body"): OLD})
    assert result.expired_rows == 0 and not client.deleted and not s3.removed
    select = next(q for q in client.queries if "max(is_deleted) = 1" in q)
    assert "created_at" not in select and "INTERVAL" not in select
    # FINAL hides a tombstoned row of a ReplacingMergeTree with `is_deleted`.
    assert "FINAL" not in select


def test_a_deleted_artifact_goes_but_an_object_that_a_live_artifact_shares_stays(monkeypatch):
    rows = [("gone", "s", "u", key("gone-thumb"), key("shared"), 1),
            ("live", "s", "u", "", key("shared"), 0)]
    objects = {key("gone-thumb"): OLD, key("shared"): OLD}
    result, client, s3 = run(monkeypatch, rows, objects)
    assert client.deleted == ["gone"]
    assert s3.removed == [key("gone-thumb")]
    assert key("shared") in s3.objects
    assert result.deleted_rows == 1


def test_an_old_orphan_goes_and_a_recent_orphan_waits_for_its_grace(monkeypatch):
    objects = {key("old-orphan"): OLD, key("new-orphan"): NOW}
    result, _client, s3 = run(monkeypatch, [], objects)
    assert s3.removed == [key("old-orphan")]
    assert key("new-orphan") in s3.objects
    assert result.orphan_objects == 1


def test_the_sweep_summary_has_no_retention_setting(monkeypatch):
    client, s3 = FakeClient([]), FakeS3({})
    monkeypatch.setattr("database.clickhouse.get_global_client", lambda: client)
    monkeypatch.setattr("database.s3.get_s3_client", lambda: s3)
    assert "ttl_days" not in sw.sweep_json()
    assert not hasattr(sw, "ttl_days")
