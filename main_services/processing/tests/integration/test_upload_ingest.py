"""`ingest_upload_paths` on ClickHouse: resume after a crash inside a chunk, and per-file
rejections.

The dataset folder is a temporary folder that the test names as a dataset mount. Files
stay below the small-blob limit, so their bytes go to ClickHouse and no object store is
used.
"""

import json
import os
from datetime import datetime, timezone
from uuid import uuid4

import clickhouse_connect
import pytest

from database import clickhouse as db
from database import uploads

pytestmark = pytest.mark.integration


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    collection = "p69in" + uuid4().hex[:8]
    upload_dataset = collection + "_inbox"
    folder = tmp_path / "inbox"
    folder.mkdir()
    monkeypatch.setenv("HOOVER4_DATASET_MOUNTS", json.dumps(
        [{"name": "t", "path": str(tmp_path), "writable": True}]))
    database = db.COLLECTION_DB_PREFIX + collection
    admin = clickhouse_connect.get_client(host=db.CLICKHOUSE_HOST, username=db.CLICKHOUSE_USER,
                                          password=db.CLICKHOUSE_PASS, settings=db.CLIENT_SETTINGS)
    db._cluster().migrate(database, db.COLLECTION_MIGRATIONS_PATH, cluster_name=None,
                          create_db_if_no_exists=True, multi_statement=True)
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    admin.insert(f"{db.GLOBAL_DB}.dataset",
                 [[upload_dataset, collection, "inbox", "inbox", "disk", str(folder), None,
                   "test", now, now, 0]],
                 column_names=["collection_dataset", "collectionname", "dataset_name",
                               "dataset_display_name", "dataset_type", "dataset_path",
                               "dataset_access_json", "user_id", "date_created",
                               "date_modified", "is_deleted"])
    client = clickhouse_connect.get_client(host=db.CLICKHOUSE_HOST, username=db.CLICKHOUSE_USER,
                                           password=db.CLICKHOUSE_PASS, database=database,
                                           settings=db.CLIENT_SETTINGS)
    try:
        yield collection, upload_dataset, folder, client
    finally:
        db.reset_client_pool_for_tests()
        admin.command(f"DELETE FROM {db.GLOBAL_DB}.dataset WHERE collectionname = {{c:String}}",
                      parameters={"c": collection})
        admin.command(f"DROP DATABASE IF EXISTS `{database}`")
        client.close()
        admin.close()


def _batch(client, upload_dataset, folder, names, op_id="op1"):
    at = datetime(2026, 10, 29, 12)
    client.insert("upload_batches", [["b1", upload_dataset, "/up", "alice", "d", "r", "queued",
                                      len(names), 30, op_id, "", at, at, at,
                                      datetime(1970, 1, 1), 3]],
                  column_names=list(uploads.BATCH_COLUMNS))
    rows = []
    for n, name in enumerate(names):
        path = f"/up/{name}"
        target = folder / path.lstrip("/")
        size = target.stat().st_size if os.path.lexists(target) and not target.is_symlink() else 5
        rows.append(["b1", n, path, size, "", "", datetime(2026, 1, 1), "placed", "", "", 4])
    client.insert("upload_files", rows, column_names=list(uploads.FILE_COLUMNS))


def _write(folder, name, data):
    path = folder / "up" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_a_crash_inside_a_chunk_repeats_it_with_one_live_row_per_path(dataset, monkeypatch):
    from tasks.P_upload import activities
    from tasks.P_upload.params import UploadBatchParams

    collection, upload_dataset, folder, client = dataset
    names = ["a.txt", "deep/b.txt", "deep/er/c.txt"]
    for i, name in enumerate(names):
        _write(folder, name, f"content {i}\n".encode())
    _batch(client, upload_dataset, folder, names)
    params = UploadBatchParams(collection, upload_dataset, "op1", "b1")

    real = uploads.write_files

    def crash(*_args, **_kwargs):
        raise RuntimeError("the worker died after the blobs and before the file rows")

    monkeypatch.setattr(uploads, "write_files", crash)
    with pytest.raises(RuntimeError):
        activities.ingest_upload_paths(params)
    assert {f["state"] for f in uploads.read_files(collection, "b1")} == {"placed"}
    assert uploads.read_batch(collection, upload_dataset, "b1")["state"] == "ingesting"

    monkeypatch.setattr(uploads, "write_files", real)
    counts = activities.ingest_upload_paths(params)
    assert counts["ingested"] == 3 and counts["rejected"] == 0
    files = uploads.read_files(collection, "b1")
    assert [f["state"] for f in files] == ["ingested"] * 3
    live = client.query(
        "SELECT path, count(), any(hash) FROM vfs_files FINAL WHERE is_deleted = 0 "
        "AND container_hash = '' GROUP BY path ORDER BY path").result_rows
    assert [(p, c) for p, c, _ in live] == [("/up/a.txt", 1), ("/up/deep/b.txt", 1),
                                            ("/up/deep/er/c.txt", 1)]
    assert {f["path"]: f["file_hash"] for f in files} == {p: h for p, _, h in live}
    assert client.query("SELECT uniqExact(blob_hash), count() FROM blobs").result_rows[0][0] == 3
    directories = [r[0] for r in client.query(
        "SELECT path FROM vfs_directories FINAL ORDER BY path").result_rows]
    assert directories == ["/up", "/up/deep", "/up/deep/er"]
    assert uploads.read_batch(collection, upload_dataset, "b1")["state"] == "processing"
    # A third attempt skips every settled entry and writes nothing.
    again = activities.ingest_upload_paths(params)
    assert (again["skipped"], again["ingested"], again["rejected"]) == (3, 0, 0)
    assert client.query("SELECT count() FROM upload_files").result_rows[0][0] == 6


def test_a_missing_or_linked_file_is_rejected_and_the_others_continue(dataset):
    from tasks.P_upload import activities
    from tasks.P_upload.params import UploadBatchParams

    collection, upload_dataset, folder, client = dataset
    _write(folder, "ok.txt", b"fine\n")
    _write(folder, "gone.txt", b"soon gone\n")
    outside = folder.parent / "outside.txt"
    outside.write_bytes(b"secret\n")
    (folder / "up" / "link.txt").symlink_to(outside)
    _batch(client, upload_dataset, folder, ["ok.txt", "gone.txt", "link.txt"])
    (folder / "up" / "gone.txt").unlink()

    counts = activities.ingest_upload_paths(UploadBatchParams(collection, upload_dataset, "op1", "b1"))
    assert (counts["ingested"], counts["rejected"]) == (1, 2)
    files = {f["path"]: f for f in uploads.read_files(collection, "b1")}
    assert files["/up/ok.txt"]["state"] == "ingested"
    for path in ("/up/gone.txt", "/up/link.txt"):
        assert files[path]["state"] == "rejected"
        assert files[path]["error"].startswith(uploads.INGEST_REJECTION_PREFIX)
    paths = [r[0] for r in client.query("SELECT path FROM vfs_files FINAL").result_rows]
    assert paths == ["/up/ok.txt"]


def test_a_batch_of_another_operation_is_left_alone(dataset):
    from tasks.P_upload import activities
    from tasks.P_upload.params import UploadBatchParams

    collection, upload_dataset, folder, client = dataset
    _write(folder, "x.txt", b"x\n")
    _batch(client, upload_dataset, folder, ["x.txt"], op_id="op-other")
    params = UploadBatchParams(collection, upload_dataset, "op1", "b1")
    assert activities.upload_batch_limits(params).skip
    assert activities.ingest_upload_paths(params)["files"] == 0
    assert client.query("SELECT count() FROM vfs_files").result_rows[0][0] == 0


@pytest.mark.parametrize("kind, expected", [
    ("ingest_upload", [("h-member", "parse_office_xml_and_store"), ("h-own", "archive_scan")]),
    ("rescan_dataset", [("h-member", "parse_office_xml_and_store"), ("h-other", "parse_error_tika"),
                        ("h-own", "archive_scan")]),
])
def test_an_upload_operation_selects_the_old_errors_of_its_own_files_only(dataset, monkeypatch, kind, expected):
    import database.operations as operations
    from tasks.P_admin import rerun_selection
    from tasks.P_admin.rerun_params import SelectErrorsParams

    collection, upload_dataset, folder, client = dataset
    _write(folder, "own.zip", b"zip\n")
    _batch(client, upload_dataset, folder, ["own.zip"], op_id="op1")
    client.command("ALTER TABLE upload_files UPDATE file_hash = 'h-own', state = 'ingested' "
                   "WHERE batch_id = 'b1' SETTINGS mutations_sync = 2")
    client.insert("vfs_files", [[upload_dataset, "h-own", "/m.docx", "h-member", "", 4,
                                 datetime(2026, 1, 1), ""]],
                  column_names=["collection_dataset", "container_hash", "path", "hash", "user_id",
                                "file_size_bytes", "mtime", "mtime_source"])
    at = datetime(2026, 10, 1)
    # The table keeps one row for each error identity, so each row has its own.
    client.insert("processing_errors", [
        [upload_dataset, h, task, 1, "e", at, 0, "", "op-old", f"{h}:{task}", 1]
        for h, task in (("h-own", "archive_scan"), ("h-member", "parse_office_xml_and_store"),
                        ("h-other", "parse_error_tika"))
    ], column_names=["collection_dataset", "hash", "task_name", "run_time_ms", "error_logs",
                     "timestamp", "attempt", "workflow_run_id", "op_id", "error_identity",
                     "write_version"])
    monkeypatch.setattr(operations, "get_operation", lambda op_id: {"op_id": op_id, "kind": kind})
    assert rerun_selection._candidate_pairs(SelectErrorsParams("op1", collection, upload_dataset)) == expected


def test_replacing_a_checked_path_with_a_symlink_does_not_change_the_ingested_bytes(dataset, monkeypatch):
    from tasks.P0_scan_disk import activities as scan
    from tasks.P_upload import activities
    from tasks.P_upload.params import UploadBatchParams
    import hashlib

    collection, upload_dataset, folder, client = dataset
    original = b"the uploaded bytes"
    _write(folder, "a.txt", original)
    secret = folder.parent / "outside.txt"
    secret.write_bytes(b"outside the dataset")
    _batch(client, upload_dataset, folder, ["a.txt"])
    real_ingest = scan.ingest_files

    def replace_then_ingest(params, **kwargs):
        path = folder / "up" / "a.txt"
        path.unlink()
        path.symlink_to(secret)
        return real_ingest(params, **kwargs)

    monkeypatch.setattr(scan, "ingest_files", replace_then_ingest)
    result = activities.ingest_upload_paths(UploadBatchParams(collection, upload_dataset, "op1", "b1"))
    assert result["ingested"] == 1
    [file] = uploads.read_files(collection, "b1")
    assert file["file_hash"] == hashlib.sha3_256(original).hexdigest()


def test_empty_dataset_creates_typed_search_tables_before_writing(dataset):
    from database.manticore import get_manticore_client, drop_collection_tables
    from tasks.P_admin.activities import purge_dataset_from_manticore, PurgeDatasetParams
    from tasks.P6_index_data.activities import (
        BuildVfsNodesParams, build_vfs_nodes, index_vfs_structure, index_entity_terms,
    )

    collection, upload_dataset, _folder, _client = dataset
    params = BuildVfsNodesParams(collection, upload_dataset)
    try:
        build_vfs_nodes(params)
        index_vfs_structure(params)
        index_entity_terms(params)
        with get_manticore_client() as connection:
            with connection.cursor() as cursor:
                for suffix in ("vfs", "entities"):
                    cursor.execute(f"DESCRIBE {collection}_{suffix}")
                    fields = {row[0]: row[1] for row in cursor.fetchall()}
                    assert fields["collection_dataset"] == "string"
        purge_dataset_from_manticore(PurgeDatasetParams(collection, upload_dataset))
    finally:
        drop_collection_tables(collection)
