"""The upload readers and writers, the claim and the admission conflict on ClickHouse.

Each test runs in a new collection database with every collection migration, and with a
registry row for its upload dataset. Rows that the tests write into the global
`operations` and `dataset` tables name that collection and are deleted afterwards.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import clickhouse_connect
import pytest

from database import clickhouse as db
from database import operations, uploads

pytestmark = pytest.mark.integration


@pytest.fixture
def upload_db():
    collection = "p69up" + uuid4().hex[:8]
    dataset = collection + "_inbox"
    database = db.COLLECTION_DB_PREFIX + collection
    admin = clickhouse_connect.get_client(host=db.CLICKHOUSE_HOST, username=db.CLICKHOUSE_USER,
                                          password=db.CLICKHOUSE_PASS, settings=db.CLIENT_SETTINGS)
    db._cluster().migrate(database, db.COLLECTION_MIGRATIONS_PATH, cluster_name=None,
                          create_db_if_no_exists=True, multi_statement=True)
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    admin.insert(f"{db.GLOBAL_DB}.dataset",
                 [[dataset, collection, "inbox", "inbox", "disk", "/testdata/none", None,
                   "test", now, now, 0]],
                 column_names=["collection_dataset", "collectionname", "dataset_name",
                               "dataset_display_name", "dataset_type", "dataset_path",
                               "dataset_access_json", "user_id", "date_created",
                               "date_modified", "is_deleted"])
    client = clickhouse_connect.get_client(host=db.CLICKHOUSE_HOST, username=db.CLICKHOUSE_USER,
                                           password=db.CLICKHOUSE_PASS, database=database,
                                           settings=db.CLIENT_SETTINGS)
    try:
        yield collection, dataset, client, admin
    finally:
        db.reset_client_pool_for_tests()
        for table in ("dataset", "operations"):
            admin.command(f"DELETE FROM {db.GLOBAL_DB}.{table} WHERE collectionname = {{c:String}}",
                          parameters={"c": collection})
        admin.command(f"DROP DATABASE IF EXISTS `{database}`")
        client.close()
        admin.close()


def _batch(client, dataset, batch_id, state="queued", op_id="", minute=0, version=3,
           username="alice"):
    at = datetime(2026, 10, 29, 12, minute)
    client.insert("upload_batches", [[batch_id, dataset, "/in", username, "d", "r" + batch_id,
                                      state, 2, 10, op_id, "", at, at, at, datetime(1970, 1, 1),
                                      version]],
                  column_names=list(uploads.BATCH_COLUMNS))


def _files(client, batch_id, rows):
    client.insert("upload_files", [[batch_id, n, path, 5, "", "", datetime(2026, 1, 1), state,
                                    file_hash, error, 4]
                                   for n, path, state, file_hash, error in rows],
                  column_names=list(uploads.FILE_COLUMNS))


def test_the_worker_writes_above_the_stored_version_and_never_over_a_transfer_state(upload_db):
    collection, dataset, client, _ = upload_db
    _batch(client, dataset, "b1", version=7)
    _batch(client, dataset, "b2", state="uploading")
    row = uploads.write_batch(collection, dataset, "b1", state="ingesting")
    assert row["row_version"] == 8
    assert uploads.read_batch(collection, dataset, "b1")["state"] == "ingesting"
    with pytest.raises(uploads.BatchStateConflict):
        uploads.write_batch(collection, dataset, "b2", state="ingesting")
    uploads.write_batch(collection, dataset, "b1", state="completed")
    assert uploads.write_batch(collection, dataset, "b1", state="failed")["state"] == "completed"

    _files(client, "b1", [(0, "/in/a", "placed", "", ""),
                          (1, "/in/b", "rejected", "", "The path exists in the dataset folder."),
                          (2, "/in/c", "not_sent", "", "")])
    written = uploads.write_files(collection, "b1", {
        0: {"state": "ingested", "file_hash": "h"}, 1: {"state": "ingested"},
        2: {"state": "ingested"}})
    assert written == 1
    states = {f["file_no"]: (f["state"], f["row_version"]) for f in uploads.read_files(collection, "b1")}
    assert states == {0: ("ingested", 5), 1: ("rejected", 4), 2: ("not_sent", 4)}


def test_a_partial_claim_is_completed_before_new_batches_are_taken(upload_db):
    from tasks.P_upload.activities import open_upload_operation
    from tasks.P_upload.params import UploadOperationParams

    collection, dataset, client, _ = upload_db
    for i in range(3):
        _batch(client, dataset, f"b{i}", minute=i)
    # A crash after the row and the first claim: two batches of the detail wait unclaimed.
    operations.create_operation("ingest_upload", collection, dataset,
                                detail={"batch_ids": ["b0", "b1", "b2"]}, op_id="op-first",
                                check_lock=False)
    uploads.claim_batches(collection, dataset, "op-first", ["b0"])
    _batch(client, dataset, "b9", minute=9)

    claim = open_upload_operation(UploadOperationParams(collection, dataset, "op-second"))
    assert claim.op_id == "op-first"
    assert claim.batch_ids == ["b0", "b1", "b2"]
    assert operations.get_operation("op-second") is None
    again = open_upload_operation(UploadOperationParams(collection, dataset, "op-second"))
    assert (again.op_id, again.batch_ids) == (claim.op_id, claim.batch_ids)
    assert uploads.read_batch(collection, dataset, "b9")["op_id"] == ""

    # The ended operation settles its open batches, and the next call takes the rest.
    operations.finish_operation("op-first", "errored", "test")
    nxt = open_upload_operation(UploadOperationParams(collection, dataset, "op-third"))
    assert (nxt.op_id, nxt.batch_ids, nxt.op_state) == ("op-third", ["b9"], "pending")
    settled = {b: uploads.read_batch(collection, dataset, b)["state"] for b in ("b0", "b1", "b2")}
    assert settled == {"b0": "failed", "b1": "failed", "b2": "failed"}
    assert "failed before it finished" in uploads.read_batch(collection, dataset, "b0")["error"]


def test_an_empty_claim_writes_no_operation(upload_db):
    from tasks.P_upload.activities import open_upload_operation
    from tasks.P_upload.params import UploadOperationParams

    collection, dataset, client, _ = upload_db
    _batch(client, dataset, "busy", state="uploading")
    claim = open_upload_operation(UploadOperationParams(collection, dataset, "op-none"))
    assert claim.op_id == "" and claim.dataset_live
    assert operations.get_operation("op-none") is None


def test_a_deleted_dataset_fails_its_waiting_batches(upload_db):
    from tasks.P_upload.activities import DATASET_DELETED_ERROR, open_upload_operation
    from tasks.P_upload.params import UploadOperationParams

    collection, dataset, client, admin = upload_db
    _batch(client, dataset, "w1")
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) + timedelta(seconds=1)
    admin.insert(f"{db.GLOBAL_DB}.dataset",
                 [[dataset, collection, "inbox", "inbox", "disk", "/testdata/none", None,
                   "test", now, now, 1]],
                 column_names=["collection_dataset", "collectionname", "dataset_name",
                               "dataset_display_name", "dataset_type", "dataset_path",
                               "dataset_access_json", "user_id", "date_created",
                               "date_modified", "is_deleted"])
    claim = open_upload_operation(UploadOperationParams(collection, dataset, "op-gone"))
    assert claim.op_id == "" and not claim.dataset_live
    row = uploads.read_batch(collection, dataset, "w1")
    assert (row["state"], row["error"]) == ("failed", DATASET_DELETED_ERROR)


@pytest.mark.parametrize("blocker_kind, same_target, conflicts", [
    ("rescan_dataset", True, True),
    ("rerun_ocr", True, True),
    ("delete_dataset", True, True),
    ("reindex_collection", True, True),
    ("ingest_upload", True, True),
    ("rescan_dataset", False, False),
])
def test_admission_sees_a_running_writer_of_the_same_target_of_any_kind(
        upload_db, blocker_kind, same_target, conflicts):
    collection, dataset, _, _ = upload_db
    target_dataset = dataset if same_target else collection + "_other"
    blocker = operations.create_operation(
        blocker_kind, collection, target_dataset if operations.KINDS[blocker_kind]["target_kind"] == "dataset" else "",
        op_id="blocker-" + uuid4().hex[:8], check_lock=False)
    operations.update_operation(blocker["op_id"], state="running")
    upload = operations.create_operation("ingest_upload", collection, dataset,
                                         op_id="upload-" + uuid4().hex[:8], check_lock=False)
    found = [row["op_id"] for row in operations.running_conflicts(upload)]
    assert found == ([blocker["op_id"]] if conflicts else [])
    # The other direction: the running upload holds the target against the other kind.
    operations.finish_operation(blocker["op_id"], "finished")
    operations.update_operation(upload["op_id"], state="running")
    other = operations.create_operation(
        blocker_kind, collection, target_dataset if operations.KINDS[blocker_kind]["target_kind"] == "dataset" else "",
        op_id="other-" + uuid4().hex[:8], check_lock=False)
    found = [row["op_id"] for row in operations.running_conflicts(other)]
    assert found == ([upload["op_id"]] if conflicts else [])


def _evidence_rows(client, dataset):
    """Two operations, an archive with two members, and a copy under a second name."""
    client.insert("vfs_files", [
        [dataset, "", "/in/a.txt", "ha", "s", 1, datetime(2026, 1, 1), "filesystem", datetime(2026, 1, 1), 0],
        [dataset, "", "/in/z.zip", "hz", "s", 1, datetime(2026, 1, 1), "filesystem", datetime(2026, 1, 1), 0],
        [dataset, "", "/in/copy.txt", "ha", "s", 1, datetime(2026, 1, 1), "filesystem", datetime(2026, 1, 1), 0],
        [dataset, "hz", "/m1.txt", "hm1", "s", 1, datetime(2026, 1, 1), "archive", datetime(2026, 1, 1), 0],
        [dataset, "hz", "/m2.txt", "hm2", "s", 1, datetime(2026, 1, 1), "archive", datetime(2026, 1, 1), 0],
    ], column_names=["collection_dataset", "container_hash", "path", "hash", "user_id",
                     "file_size_bytes", "mtime", "mtime_source", "updated_at", "is_deleted"])
    client.insert("vfs_nodes", [
        [dataset, "", p, dataset + p, dataset + "/in", 1, h, 1, 2, datetime(2026, 1, 1), 0, 1, 1]
        for p, h in (("/in/a.txt", "ha"), ("/in/z.zip", "hz"), ("/in/copy.txt", "ha"))
    ], column_names=["collection_dataset", "container_hash", "path", "node_key", "parent_key",
                     "kind", "file_hash", "file_size_bytes", "depth", "updated_at",
                     "subfolder_count", "subtree_file_count", "subtree_size_bytes"])
    client.insert("processing_plan_hits", [[dataset, h, "p" + h] for h in ("ha", "hz", "hm1", "hm2")],
                  column_names=["collection_dataset", "item_hash", "plan_hash"])
    client.insert("processing_plan_finished", [[dataset, "p" + h, datetime(2026, 1, 1)]
                                               for h in ("ha", "hz", "hm1", "hm2")],
                  column_names=["collection_dataset", "plan_hash", "finished_at"])
    # Recent times: `operation_plans` drops rows 180 days after `listed_at`.
    t1 = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    t0 = t1 - timedelta(hours=1)
    client.insert("operation_plans", [
        ["op-old", dataset, "pha", "listed", t0], ["op-new", dataset, "pha", "listed", t1],
        ["op-new", dataset, "phz", "listed", t1], ["op-new", dataset, "phm1", "listed", t1],
        ["op-new", dataset, "phm2", "listed", t1],
    ], column_names=["op_id", "collection_dataset", "plan_hash", "source", "listed_at"])
    # `ha` failed in the older operation and was recovered by the newer one. `hm2`, a member
    # of the archive, failed in the newer one.
    client.insert("processing_errors", [
        [dataset, "ha", "parse_error_tika", 1, "old", t0, 1, "w", "op-old", "e1", 1],
        [dataset, "hm2", "parse_error_tika", 1, "new", t1, 1, "w", "op-new", "e2", 1],
    ], column_names=["collection_dataset", "hash", "task_name", "run_time_ms", "error_logs",
                     "timestamp", "attempt", "workflow_run_id", "op_id", "error_identity",
                     "write_version"])


def test_the_outcome_reads_current_errors_members_and_published_paths(upload_db):
    collection, dataset, client, _ = upload_db
    _evidence_rows(client, dataset)
    with uploads._client(collection) as ch:
        assert uploads.current_error_hashes(ch, dataset, ["ha", "hz", "hm1", "hm2"]) == {"hm2"}
    _batch(client, dataset, "b1", state="processing", op_id="op-new")
    _files(client, "b1", [(0, "/in/a.txt", "ingested", "ha", ""),
                          (1, "/in/z.zip", "ingested", "hz", ""),
                          (2, "/in/copy.txt", "ingested", "ha", ""),
                          (3, "/in/never.txt", "not_sent", "", "")])
    counts = uploads.batch_outcome(collection, dataset, "b1")
    assert counts["state"] == "completed_with_errors"
    assert (counts["files"], counts["succeeded"], counts["current_errors"], counts["not_sent"],
            counts["published"]) == (4, 2, 1, 1, 3)


def test_finish_writes_the_outcome_once(upload_db):
    from tasks.P_upload.activities import finish_upload_batches
    from tasks.P_upload.params import FinishUploadBatchesParams

    collection, dataset, client, _ = upload_db
    _evidence_rows(client, dataset)
    _batch(client, dataset, "b1", state="processing", op_id="op-new")
    _files(client, "b1", [(0, "/in/a.txt", "ingested", "ha", "")])
    params = FinishUploadBatchesParams(collection, dataset, "op-new", ["b1"])
    assert finish_upload_batches(params) == {"completed": 1}
    assert finish_upload_batches(params) == {}
    row = uploads.read_batch(collection, dataset, "b1")
    assert row["state"] == "completed" and row["error"] == "" and row["finished_at"].year > 1970
