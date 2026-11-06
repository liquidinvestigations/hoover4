"""Verify first-observed stage baselines and historical preview recovery selection."""

from pathlib import Path

import pytest

from database import clickhouse, processing_updates
from tasks import stage_versions
from tasks.P_admin import rerun_selection
from tasks.P_admin.rerun_params import SelectErrorsParams
from tasks.P_admin.updates import selectors
from .test_table_publication_receipts import collection

pytestmark = pytest.mark.integration


def test_direct_upgrade_keeps_archive_baseline_and_explicit_retry_selection(collection, monkeypatch):
    with clickhouse.get_collection_client(collection) as client:
        migration = Path("database/db_global_migrations/00051_processing_updates.sql").read_text()
        for statement in migration.split(";"):
            if "CREATE TABLE" in statement:
                client.command(statement)
        operation_schema = Path("database/db_global_migrations/00030_operations_row_version.sql").read_text().split(";")[0]
        client.command(operation_schema.replace("operations_row_version", "operations"))
        client.command("ALTER TABLE operations ADD COLUMN run_started_at DateTime DEFAULT toDateTime(0)")
        client.insert("processing_errors", [["dataset", "entry", "archive_scan", "old archive failure", "legacy_error", 1]],
                      column_names=["collection_dataset", "hash", "task_name", "error_logs", "error_identity", "write_version"])
        client.insert("processing_plan_hits", [["dataset", "entry", "legacy_plan"],
                                               ["dataset", "later_success", "legacy_plan"]],
                      column_names=["collection_dataset", "item_hash", "plan_hash"])
        client.insert("vfs_files", [["dataset", "", "/archive.001", "entry"],
                                     ["dataset", "", "/archive.002", "later_success"]],
                      column_names=["collection_dataset", "container_hash", "path", "hash"])
    monkeypatch.setattr(clickhouse, "get_global_client", lambda: clickhouse.get_collection_client(collection))
    assert stage_versions.register_stage_versions() > 0
    assert stage_versions.register_stage_versions() == 0
    entitled = processing_updates.entitled_stage_versions()
    assert "archive" not in entitled
    with clickhouse.get_collection_client(collection) as client:
        selection = selectors.select_failed(client, selectors.ScopeContext("dataset", "dataset", collection))
    assert selection.count == 1
    assert selection.automatic == 0
    assert selection.detail["manual_tasks"] == ["archive_scan"]
    pairs = rerun_selection._candidate_pairs(SelectErrorsParams("explicit_retry", collection, "dataset"))
    assert pairs == [("entry", "archive_scan")]
    classes = rerun_selection.classify_pairs(pairs, {"entry": ["legacy_plan"]}, lambda _task: False)
    assert classes["selected"] == [("entry", "archive_scan")]
    assert rerun_selection.recovery_activity("archive_scan") is not None


def test_historical_preview_skip_is_selected_without_changing_settled_ocr(collection):
    from tasks.ocr_targets import record_ocr_skips
    from tasks.P_admin.updates.selectors import image_preview_hash_sql
    with clickhouse.get_collection_client(collection) as client:
        client.insert("vfs_files", [["dataset", "", "/old.svg", "image"]],
                      column_names=["collection_dataset", "container_hash", "path", "hash"])
        client.insert("file_types", [["dataset", "image", "file", ["image/svg+xml"]]],
                      column_names=["collection_dataset", "hash", "extracted_by", "mime_type"])
        client.insert("raw_ocr_results", [["dataset", "image", "tesseract", "eng", '{"text":"existing text"}']],
                      column_names=["collection_dataset", "image_hash", "engine", "languages", "raw_json"])
        record_ocr_skips(client, "dataset", "image", "preview", "", [""], "preview_failed_svg")
        sql, values = image_preview_hash_sql()
        assert client.query(sql, parameters={"cd": "dataset", **values}).result_rows == [("image",)]
        assert client.query("SELECT count() FROM raw_ocr_results").result_rows[0][0] == 1


def test_processing_update_restores_a_skipped_svg_preview_and_preserves_ocr(collection):
    import io
    from PIL import Image
    from database.s3 import collection_bucket, get_s3_client
    from tasks.ocr_targets import Target, SettingVersion, STAGE_IMAGE, STAGE_INDEX, record_ocr_skips, settled
    from tasks.P3_parse_files.image_preview import read_preview_bytes
    from tasks.P_admin.updates.activities import restore_missing_image_previews
    from tasks.P_admin.updates.params import TablePlansParams
    source = b'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80"><rect width="120" height="80" fill="blue"/></svg>'
    storage = get_s3_client()
    bucket = collection_bucket(collection)
    storage.make_bucket(bucket)
    try:
        storage.put_object(bucket, "source.svg", io.BytesIO(source), len(source))
        with clickhouse.get_collection_client(collection) as client:
            client.insert("vfs_files", [["dataset", "", "/old.svg", "image"]],
                          column_names=["collection_dataset", "container_hash", "path", "hash"])
            client.insert("file_types", [["dataset", "image", "file", ["image/svg+xml"]]],
                          column_names=["collection_dataset", "hash", "extracted_by", "mime_type"])
            client.insert("blobs", [["dataset", "image", len(source), f"s3://{bucket}/source.svg"]],
                          column_names=["collection_dataset", "blob_hash", "blob_size_bytes", "s3_path"])
            client.insert("raw_ocr_results", [["dataset", "image", "tesseract", "eng", '{"text":"existing text"}']],
                          column_names=["collection_dataset", "image_hash", "engine", "languages", "raw_json"])
            client.insert("text_content", [["dataset", "image", "ocr_tesseract_eng", 1, "existing text", 13, 100]],
                          column_names=["collection_dataset", "file_hash", "extracted_by", "page_id", "text", "text_bytes", "version"])
            client.insert("index_state", [["dataset", "image", collection + "_1"]],
                          column_names=["collection_dataset", "file_hash", "shard_name"])
            client.insert("ocr_indexed_text", [["dataset", "image", "ocr_tesseract_eng", 1, 100]],
                          column_names=["collection_dataset", "file_hash", "extracted_by", "page_id", "text_version"])
            record_ocr_skips(client, "dataset", "image", "preview", "", [""], "preview_failed_svg")
            targets = {Target("image", STAGE_IMAGE, "tesseract", "eng"): SettingVersion(),
                       Target("image", STAGE_INDEX): SettingVersion()}
            assert settled(client, "dataset", targets, parts_version=True) == set(targets)
            scope = selectors.ScopeContext("dataset", "dataset", collection)
            target = {"image_engines": ["tesseract"], "pdf_engines": [],
                      "languages": {"tesseract": "eng", "easyocr": ""}, "sources": {}}
            assert selectors.select_ocr(client, scope, target).count == 0
            assert selectors.select_image_previews(client, scope).count == 1
        assert restore_missing_image_previews(TablePlansParams("preview_update", collection, "dataset")) == 1
        with clickhouse.get_collection_client(collection) as client:
            artifact = read_preview_bytes(client, "dataset", "image")
            assert artifact
            with Image.open(io.BytesIO(artifact)) as preview:
                assert preview.format == "JPEG"
                assert preview.width > 0 and preview.height > 0
            assert selectors.select_image_previews(client, scope).count == 0
            assert client.query("SELECT raw_json FROM raw_ocr_results").result_rows == [('{"text":"existing text"}',)]
            assert settled(client, "dataset", targets, parts_version=True) == set(targets)
    finally:
        for item in storage.list_objects(bucket, recursive=True):
            storage.remove_object(bucket, item.object_name)
        storage.remove_bucket(bucket)


def _verify_successful_legacy_split_archive(collection, tmp_path, upgrade=None):
    import hashlib
    import io
    import subprocess
    from database import manticore
    from database.s3 import collection_bucket, get_s3_client
    from tasks.P_admin.updates.archive_members import pending_archives, restore_archive_members, finish_archive_members
    from tasks.P_admin.updates.params import TablePlansParams
    empty = tmp_path / "empty"
    empty.mkdir()
    subprocess.run(["7z", "a", "-v64b", str(tmp_path / "archive.7z"), str(empty)],
                   capture_output=True, check=True)
    volumes = sorted(tmp_path.glob("archive.7z.*"))
    assert len(volumes) > 1
    storage, bucket = get_s3_client(), collection_bucket(collection)
    storage.make_bucket(bucket)
    manticore.create_shard_tables(collection, 1)
    manticore.create_vfs_table(collection)
    try:
        hashes = []
        with clickhouse.get_collection_client(collection) as client:
            for volume in volumes:
                data = volume.read_bytes()
                file_hash = hashlib.sha3_256(data).hexdigest()
                hashes.append(file_hash)
                storage.put_object(bucket, file_hash, io.BytesIO(data), len(data))
                client.insert("blobs", [["dataset", file_hash, len(data), f"s3://{bucket}/{file_hash}"]],
                              column_names=["collection_dataset", "blob_hash", "blob_size_bytes", "s3_path"])
                client.insert("vfs_files", [["dataset", "", "/" + volume.name, file_hash, len(data)]],
                              column_names=["collection_dataset", "container_hash", "path", "hash", "file_size_bytes"])
                client.insert("processing_plan_hits", [["dataset", file_hash, "legacy_plan"]],
                              column_names=["collection_dataset", "item_hash", "plan_hash"])
            entry = hashes[0]
            client.insert("archives", [["dataset", entry, "application/x-7z-compressed"]],
                          column_names=["collection_dataset", "archive_hash", "archive_type"])
            client.insert("processing_plan_finished", [["dataset", "legacy_plan"]],
                          column_names=["collection_dataset", "plan_hash"])
            client.insert("vfs_files", [["dataset", entry, "/removed.zip", "removed"],
                                         ["dataset", "removed", "/stale.txt", "stale"]],
                          column_names=["collection_dataset", "container_hash", "path", "hash"])
            if upgrade is not None:
                upgrade()
            assert set(pending_archives(client, "dataset")) == {entry}
        params = TablePlansParams("archive_upgrade", collection, "dataset")
        assert restore_archive_members(params) == 1
        from tasks.P3_parse_files.archive_reconciliation import reconcile_archive_descendants
        from tasks.P6_index_data.params import BuildVfsNodesParams
        reconcile_archive_descendants(BuildVfsNodesParams(collection, "dataset"))
        with clickhouse.get_collection_client(collection) as client:
            assert pending_archives(client, "dataset", stage="reconcile") == {}
            assert set(pending_archives(client, "dataset")) == {entry}
            assert client.query("SELECT count() FROM vfs_files FINAL WHERE hash = 'stale' AND is_deleted = 0").result_rows[0][0] == 0
        assert finish_archive_members(params) == 1
        with clickhouse.get_collection_client(collection) as client:
            assert pending_archives(client, "dataset") == {}
    finally:
        manticore.drop_collection_tables(collection)
        for item in storage.list_objects(bucket, recursive=True):
            storage.remove_object(bucket, item.object_name)
        storage.remove_bucket(bucket)


def test_successful_legacy_split_archive_gets_versioned_reconciliation(collection, tmp_path):
    _verify_successful_legacy_split_archive(collection, tmp_path)


def test_failed_table_parse_remains_selectable_on_explicit_retry(collection, monkeypatch):
    import hashlib
    import io
    from database.s3 import collection_bucket, get_s3_client
    from tasks.P3_parse_files import parse_table, table_generations
    from tasks.P_admin.updates.activities import reparse_update_tables
    from tasks.P_admin.updates.params import TablePlanParams
    source = b'{"name":"alpha","count":1}\n{"name":"beta","count":2}\n{bad\n'
    file_hash = hashlib.sha3_256(source).hexdigest()
    storage, bucket = get_s3_client(), collection_bucket(collection)
    storage.make_bucket(bucket)
    monkeypatch.setattr(table_generations, "send_command", table_generations.apply_table_generation_command)
    monkeypatch.setattr(parse_table, "_record_skip", lambda *_args: None)
    try:
        storage.put_object(bucket, "bad.jsonl", io.BytesIO(source), len(source))
        with clickhouse.get_collection_client(collection) as client:
            client.insert("vfs_files", [["dataset", "", "/bad.jsonl", file_hash, len(source)]],
                          column_names=["collection_dataset", "container_hash", "path", "hash", "file_size_bytes"])
            client.insert("file_types", [["dataset", file_hash, "file", ["application/x-ndjson"], [".jsonl"]]],
                          column_names=["collection_dataset", "hash", "extracted_by", "mime_type", "extensions"])
            client.insert("blobs", [["dataset", file_hash, len(source), f"s3://{bucket}/bad.jsonl"]],
                          column_names=["collection_dataset", "blob_hash", "blob_size_bytes", "s3_path"])
            client.insert("processing_plan_hits", [["dataset", file_hash, "plan"]],
                          column_names=["collection_dataset", "item_hash", "plan_hash"])
        params = TablePlanParams("table_retry", collection, "dataset", "plan")
        for _ in range(2):
            assert reparse_update_tables(params) == []
            with clickhouse.get_collection_client(collection) as client:
                assert selectors.select_tables(client, selectors.ScopeContext("dataset", "dataset", collection)).count == 1
                assert client.query("SELECT status FROM table_documents FINAL").result_rows == [("failed",)]
                assert client.query("SELECT count() FROM processing_output_receipts WHERE output_kind = 'table'").result_rows[0][0] == 0
    finally:
        for item in storage.list_objects(bucket, recursive=True):
            storage.remove_object(bucket, item.object_name)
        storage.remove_bucket(bucket)
