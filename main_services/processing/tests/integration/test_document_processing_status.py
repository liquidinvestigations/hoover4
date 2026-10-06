"""Verify the viewer query against plan, operation, and file failure rows."""

import os
from pathlib import Path
from uuid import uuid4

import pytest

from database.clickhouse import get_global_client
from .test_text_storage_migration import storage

pytestmark = pytest.mark.integration


def backend_source(relative):
    root = os.getenv("HOOVER4_REPO_ROOT")
    if root:
        candidates = [Path(root) / "website/backend/src" / relative]
    else:
        candidates = [parent / "website/backend/src" / relative
                      for parent in Path(__file__).resolve().parents]
        candidates.append(Path("/mirror/website-backend-src") / relative)
    for path in candidates:
        if path.is_file():
            return path.read_text()
    pytest.fail("Current website source is unavailable. Set HOOVER4_REPO_ROOT.")


def test_viewer_processing_query_distinguishes_ended_pending_active_and_empty(storage):
    _, client, _, _ = storage
    source = backend_source("api/documents/get_document_sources.rs")
    sql = source.split('const DOCUMENT_PROCESSING_SQL: &str = r#"', 1)[1].split('"#;', 1)[0]
    for parameter in ("dataset", "hash", "dataset", "dataset", "dataset", "hash"):
        sql = sql.replace("?", "{" + parameter + ":String}", 1)
    prefix = "viewer" + uuid4().hex
    dataset = prefix
    try:
        for name, state in (("download", "errored"), ("cancel", "cancelled"),
                            ("active", "running"), ("queued", "pending"),
                            ("empty", "finished"), ("failed", "errored")):
            client.command("INSERT INTO processing_plan_hits VALUES ({ds:String}, {h:String}, {h:String})",
                           parameters={"ds": dataset, "h": name})
            client.command("INSERT INTO operation_plans (op_id, collection_dataset, plan_hash, source) "
                           "VALUES ({op:String}, {ds:String}, {h:String}, 'listed')",
                           parameters={"op": prefix + name, "ds": dataset, "h": name})
            with get_global_client() as global_client:
                global_client.command("INSERT INTO operations (op_id, state, started_at, row_version) "
                                      "VALUES ({op:String}, {state:String}, now(), 1)",
                                      parameters={"op": prefix + name, "state": state})
        client.command("INSERT INTO processing_plan_hits VALUES ({ds:String}, 'pending', 'pending')",
                       parameters={"ds": dataset})
        client.command("INSERT INTO processing_plan_finished VALUES ({ds:String}, 'empty', now())",
                       parameters={"ds": dataset})
        client.command("INSERT INTO processing_errors (collection_dataset, hash, task_name, op_id, error_identity) "
                       "VALUES ({ds:String}, 'failed', 'tika_text_batch', {op:String}, 'error')",
                       parameters={"ds": dataset, "op": prefix + "failed"})
        expected = {"download": (1, 0, [], "errored"), "cancel": (1, 0, [], "cancelled"),
                    "pending": (1, 0, [], ""), "active": (1, 0, [], "running"),
                    "queued": (1, 0, [], "pending"), "empty": (1, 1, [], "finished"),
                    "failed": (1, 0, ["tika_text_batch"], "errored"), "unplanned": (0, 0, [], "")}
        for name, row in expected.items():
            result = client.query(sql, parameters={"dataset": dataset, "hash": name})
            assert result.result_rows == [row], name
            assert [column.name for column in result.column_types] == [
                "UInt64", "UInt64", "Array(String)", "String",
            ], name
    finally:
        with get_global_client() as global_client:
            global_client.command("ALTER TABLE operations DELETE WHERE startsWith(op_id, {prefix:String}) "
                                  "SETTINGS mutations_sync = 2", parameters={"prefix": prefix})


def test_table_match_count_excludes_cells_outside_current_sheet(storage):
    import re
    _, client, _, _ = storage
    source = backend_source("api/documents/table_browse.rs")
    sql = source.split('"SELECT count() FROM table_cells AS c FINAL', 1)[1].split('",', 1)[0]
    sql = "SELECT count() FROM table_cells AS c FINAL" + re.sub(r"\\\n\s*", " ", sql)
    for parameter in ("dataset", "hash", "hash", "query"):
        sql = sql.replace("?", "{" + parameter + ":String}", 1)
    client.command("INSERT INTO table_sheets (collection_dataset, hash, sheet_id, row_count, column_count, header_row) "
                   "VALUES ('dataset', 'file', 0, 2, 1, 1)")
    client.command("INSERT INTO table_cells (file_hash, sheet_id, column_id, row_id, cell_text) VALUES "
                   "('file', 0, 1, 1, 'needle'), ('file', 0, 1, 2, 'needle'), "
                   "('file', 0, 2, 2, 'needle'), ('file', 0, 1, 3, 'needle'), ('file', 1, 1, 2, 'needle')")
    assert client.query(sql, parameters={"dataset": "dataset", "hash": "file", "query": "needle"}).result_rows == [(1,)]
