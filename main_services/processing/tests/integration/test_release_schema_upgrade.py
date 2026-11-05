"""Upgrade populated v0.1.0 schemas before verifying recovery selection."""

import io
import os
from pathlib import Path
import uuid

import pytest

from database import clickhouse, processing_updates
from database.s3 import collection_bucket, get_s3_client
from tasks import stage_versions
from tasks.ocr_targets import record_ocr_skips
from tasks.P_admin.rerun_params import SelectErrorsParams
from tasks.P_admin import rerun_selection
from tasks.P_admin.updates import selectors
from tasks.P_admin.updates.activities import restore_missing_image_previews
from tasks.P_admin.updates.params import TablePlansParams
from tasks.P3_parse_files.image_preview import read_preview_bytes

pytestmark = pytest.mark.integration


@pytest.fixture
def release_databases(monkeypatch):
    baseline = Path(os.getenv("HOOVER4_RELEASE_BASELINE", "/baseline")) / "main_services/processing/database"
    if not baseline.is_dir():
        pytest.skip("Mount the v0.1.0 migration snapshot at /baseline")
    collection = "release_" + uuid.uuid4().hex[:12]
    global_name = "release_global_" + uuid.uuid4().hex[:12]
    cluster = clickhouse._cluster()
    for name, folder in ((collection, "db_collection_migrations"), (global_name, "db_global_migrations")):
        cluster.migrate(clickhouse.collection_db_name(name), str(baseline / folder),
                        cluster_name=None, create_db_if_no_exists=True, multi_statement=True)
    monkeypatch.setattr(clickhouse, "get_global_client", lambda: clickhouse.get_collection_client(global_name))

    def upgrade():
        clickhouse.migrate_collection(collection)
        cluster.migrate(clickhouse.collection_db_name(global_name), clickhouse.GLOBAL_MIGRATIONS_PATH,
                        cluster_name=None, create_db_if_no_exists=True, multi_statement=True)

    try:
        yield collection, upgrade
    finally:
        client = clickhouse._client("default")
        for name in (collection, global_name):
            client.command(f"DROP DATABASE {clickhouse.collection_db_name(name)}")
        client.close()


def test_populated_release_upgrade_preserves_baseline_and_restores_a_failed_preview(release_databases):
    collection, upgrade = release_databases
    payload = b'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80"><rect width="120" height="80" fill="blue"/></svg>'
    storage, bucket = get_s3_client(), collection_bucket(collection)
    storage.make_bucket(bucket)
    try:
        storage.put_object(bucket, "source.svg", io.BytesIO(payload), len(payload))
        with clickhouse.get_collection_client(collection) as client:
            assert "stage_versions" not in {row[0] for row in client.query("SHOW TABLES").result_rows}
            client.insert("vfs_files", [["dataset", "", "/archive.001", "entry"],
                                         ["dataset", "", "/archive.002", "later_success"],
                                         ["dataset", "", "/old.svg", "image"]],
                          column_names=["collection_dataset", "container_hash", "path", "hash"])
            client.insert("processing_plan_hits", [["dataset", value, "legacy_plan"]
                                                   for value in ("entry", "later_success", "image")],
                          column_names=["collection_dataset", "item_hash", "plan_hash"])
            client.insert("processing_errors", [["dataset", "entry", "archive_scan", "legacy failure", "old_error", 1]],
                          column_names=["collection_dataset", "hash", "task_name", "error_logs", "error_identity", "write_version"])
            client.insert("file_types", [["dataset", "image", "file", ["image/svg+xml"]]],
                          column_names=["collection_dataset", "hash", "extracted_by", "mime_type"])
            client.insert("blobs", [["dataset", "image", len(payload), f"s3://{bucket}/source.svg"]],
                          column_names=["collection_dataset", "blob_hash", "blob_size_bytes", "s3_path"])
            client.insert("raw_ocr_results", [["dataset", "image", "tesseract", "eng", '{"text":"existing text"}']],
                          column_names=["collection_dataset", "image_hash", "engine", "languages", "raw_json"])
            record_ocr_skips(client, "dataset", "image", "preview", "", [""], "preview_failed_svg")
        upgrade()
        assert stage_versions.register_stage_versions() > 0
        assert stage_versions.register_stage_versions() == 0
        assert "archive" not in processing_updates.entitled_stage_versions()
        with clickhouse.get_collection_client(collection) as client:
            scope = selectors.ScopeContext("dataset", "dataset", collection)
            failures = selectors.select_failed(client, scope)
            assert failures.count == 1 and failures.automatic == 0
            assert selectors.select_image_previews(client, scope).count == 1
        assert rerun_selection._candidate_pairs(SelectErrorsParams("explicit", collection, "dataset")) == [("entry", "archive_scan")]
        assert restore_missing_image_previews(TablePlansParams("preview_update", collection, "dataset")) == 1
        with clickhouse.get_collection_client(collection) as client:
            assert read_preview_bytes(client, "dataset", "image")
            assert selectors.select_image_previews(client, scope).count == 0
            assert client.query("SELECT raw_json FROM raw_ocr_results").result_rows == [('{"text":"existing text"}',)]
    finally:
        for item in storage.list_objects(bucket, recursive=True):
            storage.remove_object(bucket, item.object_name)
        storage.remove_bucket(bucket)


def test_populated_release_successful_archive_gets_rewritten(release_databases, tmp_path):
    from .test_release_recovery import _verify_successful_legacy_split_archive
    collection, upgrade = release_databases
    _verify_successful_legacy_split_archive(collection, tmp_path, upgrade)
