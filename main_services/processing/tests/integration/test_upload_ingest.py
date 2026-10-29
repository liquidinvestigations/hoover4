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
