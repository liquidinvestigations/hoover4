"""Tests for the target of the ClickHouse part of a collection export and import.

Compose writes and reads a file of the backup root. The site layout of k3s writes and reads
an object of the export bucket of the zone with the zone key.
"""

from contextlib import contextmanager
import json

import pytest

from database import clickhouse, s3, storage_identity
from tasks.P_ops import backup, restore
from tasks.P_ops.params import ExportParams, ImportParams

SITE_URL = "http://garage.stores:3900/zone-a-exports"


class _Rows:
    def __init__(self, rows):
        self.result_rows = rows


class _Client:
    def __init__(self, status_row):
        self.queries = []
        self.status_row = status_row

    def query(self, query, **_kwargs):
        self.queries.append(query)
        if "system.backups" in query:
            return _Rows([self.status_row])
        return _Rows([(7,)])


class _Phase:
    def __init__(self, *_args):
        return None

    def report(self, *_args, **_kwargs):
        return None

    def finish(self, result):
        return result


class _Stat:
    size = 123


class _S3:
    def __init__(self):
        self.calls = []

    def stat_object(self, bucket, key):
        self.calls.append(("stat", bucket, key))
        return _Stat()

    def fput_object(self, bucket, key, path):
        self.calls.append(("put", bucket, key))

    def remove_object(self, bucket, key):
        self.calls.append(("remove", bucket, key))

    def fget_object(self, bucket, key, path):
        self.calls.append(("get", bucket, key))
        with open(path, "wb") as out:
            out.write(b"x" * 123)


@pytest.fixture
def stores(monkeypatch):
    client = _Client(("BACKUP_CREATED", "", 3, 123, 123, 123, 0, 123))
    store = _S3()

    @contextmanager
    def connect(*_args):
        yield client

    monkeypatch.setattr(clickhouse, "get_collection_client", connect)
    monkeypatch.setattr(clickhouse, "get_global_client", connect)
    monkeypatch.setattr(clickhouse, "collection_db_name", lambda name: f"zone_a_Collection_{name}")
    monkeypatch.setattr(clickhouse, "migrate_collection", lambda _name: None)
    monkeypatch.setattr(clickhouse, "drop_collection_db", lambda _name: None)
    monkeypatch.setattr(s3, "get_s3_client", lambda: store)
    monkeypatch.setattr(s3, "S3_ACCESS_KEY", "GKzone")
    monkeypatch.setattr(s3, "S3_SECRET_KEY", "se'cret")
    monkeypatch.setattr(storage_identity, "setting",
                        lambda name, environ=None: "zone_a" if name == "clickhouse_database_prefix" else "")
    for module in (backup, restore):
        monkeypatch.setattr(module, "_Phase", _Phase)
        monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    return client, store


def _site(monkeypatch):
    monkeypatch.setattr(backup, "CLICKHOUSE_BACKUP_S3_URL", SITE_URL)
    monkeypatch.setattr(restore, "CLICKHOUSE_BACKUP_S3_URL", SITE_URL)


def test_site_export_writes_the_archive_into_the_zone_bucket(monkeypatch, stores, tmp_path):
    client, store = stores
    _site(monkeypatch)

    result = backup.export_clickhouse(ExportParams("op1", "demo", "dest", str(tmp_path)))

    assert client.queries[0] == (
        "BACKUP DATABASE `zone_a_Collection_demo` TO "
        f"S3('{SITE_URL}/dest/clickhouse-op1.tar', 'GKzone', 'se\\'cret') "
        "SETTINGS id='zone_a-op1', async=1")
    assert store.calls == [("stat", "zone-a-exports", "dest/clickhouse-op1.tar")]
    assert result.detail["object"] == {"bucket": "zone-a-exports", "key": "dest/clickhouse-op1.tar"}
    assert result.detail["artifact"] == "clickhouse/clickhouse-op1.tar"
    assert result.bytes_written == 123


def test_compose_export_keeps_the_file_of_the_backup_root(monkeypatch, stores, tmp_path):
    client, _store = stores
    (tmp_path / "clickhouse").mkdir()
    (tmp_path / "clickhouse" / "clickhouse-op1.tar").write_bytes(b"x" * 5)

    result = backup.export_clickhouse(ExportParams("op1", "demo", "dest", str(tmp_path)))

    assert client.queries[0].startswith(
        "BACKUP DATABASE `zone_a_Collection_demo` TO "
        "File('dest.partial-op1/clickhouse/clickhouse-op1.tar') SETTINGS id='zone_a-op1'")
    assert "object" not in result.detail
    assert result.bytes_written == 5


def _manifest(directory, block):
    (directory / "manifest.json").write_text(json.dumps({
        "format": backup.FORMAT, "format_version": backup.FORMAT_VERSION,
        "stores": {"clickhouse": {"artifact": "clickhouse/clickhouse-op1.tar", "bytes": 123, **block}},
    }))


def _restore_client(stores):
    client, store = stores
    client.status_row = ("RESTORED", "", 123, 123)
    return client, store


def test_site_import_reads_the_object_of_the_zone_bucket(monkeypatch, stores, tmp_path):
    client, store = _restore_client(stores)
    _site(monkeypatch)
    _manifest(tmp_path, {"object": {"bucket": "zone-a-exports", "key": "dest/clickhouse-op1.tar"}})

    restore.import_clickhouse(ImportParams("op2", "demo", "dest", str(tmp_path)))

    assert client.queries[0] == (
        "RESTORE DATABASE `zone_a_Collection_demo` FROM "
        f"S3('{SITE_URL}/dest/clickhouse-op1.tar', 'GKzone', 'se\\'cret') "
        "SETTINGS id='zone_a-op2', async=1")
    assert store.calls == []


def test_site_import_uploads_a_local_archive_and_removes_it(monkeypatch, stores, tmp_path):
    client, store = _restore_client(stores)
    client.status_row = ("RESTORE_FAILED", "broken", 0, 0)
    _site(monkeypatch)
    _manifest(tmp_path, {})
    (tmp_path / "clickhouse").mkdir()
    (tmp_path / "clickhouse" / "clickhouse-op1.tar").write_bytes(b"x")

    with pytest.raises(RuntimeError, match="RESTORE_FAILED"):
        restore.import_clickhouse(ImportParams("op2", "demo", "dest", str(tmp_path)))

    assert f"S3('{SITE_URL}/imports/op2/clickhouse.tar'" in client.queries[0]
    assert store.calls == [("put", "zone-a-exports", "imports/op2/clickhouse.tar"),
                           ("remove", "zone-a-exports", "imports/op2/clickhouse.tar")]


def test_site_import_refuses_an_object_of_another_bucket(monkeypatch, stores, tmp_path):
    client, _store = _restore_client(stores)
    _site(monkeypatch)
    _manifest(tmp_path, {"object": {"bucket": "zone-b-exports", "key": "dest/clickhouse-op1.tar"}})

    with pytest.raises(ValueError, match="zone-a-exports"):
        restore.import_clickhouse(ImportParams("op2", "demo", "dest", str(tmp_path)))
    assert client.queries == []


def test_compose_import_refuses_a_site_export_without_its_archive(stores, tmp_path):
    client, _store = _restore_client(stores)
    _manifest(tmp_path, {"object": {"bucket": "zone-a-exports", "key": "dest/clickhouse-op1.tar"}})

    with pytest.raises(ValueError, match="backup job"):
        restore.import_clickhouse(ImportParams("op2", "demo", "dest", str(tmp_path)))
    assert client.queries == []


def test_fetch_and_remove_the_object_of_an_export_folder(stores, tmp_path):
    _client, store = stores
    _manifest(tmp_path, {"object": {"bucket": "zone-a-exports", "key": "dest/clickhouse-op1.tar"}})

    path = backup.fetch_clickhouse_object(str(tmp_path))
    assert (tmp_path / "clickhouse" / "clickhouse-op1.tar").read_bytes() == b"x" * 123
    assert path == str(tmp_path / "clickhouse" / "clickhouse-op1.tar")
    assert backup.remove_clickhouse_object(str(tmp_path)) is True
    assert store.calls == [("get", "zone-a-exports", "dest/clickhouse-op1.tar"),
                           ("remove", "zone-a-exports", "dest/clickhouse-op1.tar")]
