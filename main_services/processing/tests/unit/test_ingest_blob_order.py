"""Verify blob value durability and continued ingestion after an unreadable file."""

from contextlib import contextmanager
from types import SimpleNamespace

import pyarrow as pa
import pytest

from tasks.P0_scan_disk import activities as scan


class Client:
    def __init__(self, fail_table=""):
        self.rows = {"blob_values": {}, "blobs": {}, "vfs_files": {}}
        self.inserts = []
        self.fail_table = fail_table

    def query_arrow(self, query):
        if "FROM blob_values" in query:
            return pa.table({"blob_hash": list(self.rows["blob_values"])})
        if "FROM blobs" in query:
            return pa.table({name: [row[name] for row in self.rows["blobs"].values()]
                for name in ("blob_hash", "stored_in_clickhouse", "s3_path")})
        return pa.table({"path": []})

    def insert_arrow(self, table, data):
        self.inserts.append(table)
        key = "path" if table == "vfs_files" else "blob_hash"
        for row in data.to_pylist():
            self.rows[table][row[key]] = row
        if self.fail_table == table:
            self.fail_table = ""
            raise RuntimeError("Insert completed before the connection failed.")


@pytest.fixture
def files_and_client(tmp_path, monkeypatch):
    import database.clickhouse as clickhouse
    for name in ("first", "second"):
        (tmp_path / name).write_text(name)
    client = Client()

    @contextmanager
    def get_client(_collection):
        yield client

    monkeypatch.setattr(scan, "get_collection_client", get_client)
    monkeypatch.setattr(clickhouse, "get_collection_client", get_client)
    return tmp_path, client


@pytest.mark.parametrize("fail_table", ["blob_values", "blobs"])
def test_retry_never_keeps_a_blob_without_its_value(files_and_client, fail_table):
    directory, client = files_and_client
    client.fail_table = fail_table
    params = scan.IngestFilesBatchParams("collection", "dataset", str(directory), ["/first", "/second"])
    with pytest.raises(RuntimeError):
        scan.ingest_files_batch(params)
    assert set(client.rows["blobs"]) <= set(client.rows["blob_values"])
    scan.ingest_files_batch(params)
    assert len(client.rows["blobs"]) == len(client.rows["blob_values"]) == 2
    assert len(client.rows["vfs_files"]) == 2
    assert client.inserts.index("blob_values") < client.inserts.index("blobs")


def test_ingest_client_defaults_wait_for_async_inserts():
    from database.clickhouse import CLIENT_SETTINGS
    assert CLIENT_SETTINGS["async_insert"] == 1
    assert CLIENT_SETTINGS["wait_for_async_insert"] == 1


def test_unreadable_file_does_not_stop_readable_files(files_and_client, monkeypatch):
    from tasks.P2_execute_plan import activities as execution
    directory, client = files_and_client
    recorded = []
    compute = scan._compute_hashes_streaming

    def hash_file(path):
        if path.endswith("first"):
            raise PermissionError("File access denied.")
        return compute(path)

    monkeypatch.setattr(scan, "_compute_hashes_streaming", hash_file)
    monkeypatch.setattr(execution, "record_processing_errors", lambda params: recorded.extend(params.errors))
    scan.ingest_files_batch(scan.IngestFilesBatchParams(
        "collection", "dataset", str(directory), ["/first", "/second"], op_id="operation"))
    assert list(client.rows["vfs_files"]) == ["/second"]
    assert len(recorded) == 1
    assert recorded[0]["hash"] == ""
    assert recorded[0]["op_id"] == "operation"
    assert "/first" in recorded[0]["error_logs"]
    assert "PermissionError" in recorded[0]["error_logs"]


def test_unreadable_value_after_hash_does_not_stop_other_files(files_and_client, monkeypatch):
    import builtins
    from tasks.P2_execute_plan import activities as execution
    directory, client = files_and_client
    calls = 0
    recorded = []

    def open_file(path, *args, **kwargs):
        nonlocal calls
        if str(path).endswith("first"):
            calls += 1
            if calls == 2:
                raise PermissionError("File became unreadable after hashing.")
        return builtins.open(path, *args, **kwargs)

    monkeypatch.setattr(scan, "open", open_file, raising=False)
    monkeypatch.setattr(execution, "record_processing_errors", lambda params: recorded.extend(params.errors))
    scan.ingest_files_batch(scan.IngestFilesBatchParams(
        "collection", "dataset", str(directory), ["/first", "/second"], op_id="operation"))
    assert list(client.rows["vfs_files"]) == ["/second"]
    assert len(client.rows["blobs"]) == len(client.rows["blob_values"]) == 1
    assert recorded[-1]["op_id"] == "operation"
