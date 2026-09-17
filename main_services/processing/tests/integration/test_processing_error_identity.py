"""Verify Error identities and the replacement migration with ClickHouse."""

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from database import clickhouse, operation_ledger
from database.clickhouse import COLLECTION_MIGRATIONS_PATH, _client, _cluster, get_global_client
from tasks.P2_execute_plan.activities import RecordProcessingErrorsParams, record_processing_errors
from tasks.P3_parse_files import parse_common, parse_ocr, parse_ocr_pdf, parse_office_xml, parse_table

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def error_database():
    database = f"w17_errors_{uuid4().hex[:12]}"
    try:
        _cluster().migrate(
            database, COLLECTION_MIGRATIONS_PATH, cluster_name=None,
            create_db_if_no_exists=True, multi_statement=True,
        )
        client = _client(database)
        try:
            yield database, client
        finally:
            client.close()
    finally:
        with get_global_client() as admin:
            admin.command(f"DROP DATABASE IF EXISTS {database} SYNC")


@pytest.fixture
def isolated_errors(error_database, monkeypatch):
    database, client = error_database
    client.command("TRUNCATE TABLE processing_errors")
    client.command("TRUNCATE TABLE operation_error_events")

    @contextmanager
    def isolated_client(_collectionname):
        yield client

    monkeypatch.setattr(clickhouse, "get_collection_client", isolated_client)
    return database, client


def _counts(client, task_name):
    errors = client.query(
        "SELECT count(), uniqExact(error_identity) FROM processing_errors FINAL "
        "WHERE collection_dataset = 'dataset' AND task_name = {task:String}",
        parameters={"task": task_name},
    ).result_rows[0]
    events = client.query(
        "SELECT count() FROM operation_error_events FINAL "
        "WHERE op_id = 'operation' AND collection_dataset = 'dataset' "
        "AND task_name = {task:String} AND event = 'error'",
        parameters={"task": task_name},
    ).result_rows[0][0]
    return int(errors[0]), int(errors[1]), int(events)


def _fail_one_event(monkeypatch):
    original = operation_ledger.insert_error_events
    calls = 0

    def fail_once(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("event insert failed")
        return original(*args)

    monkeypatch.setattr(operation_ledger, "insert_error_events", fail_once)


@pytest.mark.parametrize("module,params,task_name,item_hash", [
    (parse_ocr, parse_ocr.RunOcrParams("collection", "dataset", "image-hash", "image", "easyocr", 30, "operation"),
     "run_ocr_and_store[easyocr]", "image-hash"),
    (parse_ocr_pdf, parse_ocr_pdf.RunOcrPdfParams("collection", "dataset", "pdf-hash", "pdf", "tesseract", 30, "operation"),
     "run_ocr_pdf_and_store[tesseract]", "pdf-hash"),
    (parse_table, parse_table.ParseTableParams("collection", "dataset", "table-hash", "table", 30, op_id="operation"),
     "parse_table_and_store", "table-hash"),
    (parse_office_xml, parse_office_xml.ParseOfficeXmlParams("collection", "dataset", "office-hash", "office", 30, "operation"),
     "parse_office_xml_and_store", "office-hash"),
])
def test_direct_writer_retry_and_new_attempt(
    isolated_errors, monkeypatch, module, params, task_name, item_hash
):
    _, client = isolated_errors
    source = SimpleNamespace(workflow_run_id="run", activity_id="activity", attempt=1)
    monkeypatch.setattr(parse_common.activity, "info", lambda: source)
    module._record_skip(params, 1, "source error")
    module._record_skip(params, 1, "source error")
    assert _counts(client, task_name) == (1, 1, 1)
    assert client.query(
        "SELECT DISTINCT hash FROM processing_errors FINAL WHERE task_name = {task:String}",
        parameters={"task": task_name},
    ).result_rows == [(item_hash,)]

    source.attempt = 2
    _fail_one_event(monkeypatch)
    with pytest.raises(RuntimeError, match="event insert failed"):
        module._record_skip(params, 1, "source error")
    module._record_skip(params, 1, "source error")
    assert _counts(client, task_name) == (2, 2, 1)


def test_helper_retry_and_new_source(isolated_errors, monkeypatch):
    _, client = isolated_errors
    row = {
        "collection_dataset": "dataset", "hash": "hash", "task_name": "P4_ExtractEntities",
        "error_logs": "source error", "op_id": "operation", "error_identity": "source-one",
    }
    params = RecordProcessingErrorsParams("collection", [row])
    record_processing_errors(params)
    record_processing_errors(params)
    assert _counts(client, row["task_name"]) == (1, 1, 1)
    _fail_one_event(monkeypatch)
    row = {**row, "error_identity": "source-two"}
    with pytest.raises(RuntimeError, match="event insert failed"):
        record_processing_errors(RecordProcessingErrorsParams("collection", [row]))
    record_processing_errors(RecordProcessingErrorsParams("collection", [row]))
    assert _counts(client, row["task_name"]) == (2, 2, 1)


def test_migration_keeps_equal_key_historical_rows():
    database = f"w17_legacy_{uuid4().hex[:12]}"
    root = Path(COLLECTION_MIGRATIONS_PATH)
    try:
        with get_global_client() as admin:
            admin.command(f"CREATE DATABASE {database}")
        client = _client(database)
        try:
            client.command((root / "00015_processing_errors.sql").read_text().rstrip().rstrip(";"))
            client.command(
                "INSERT INTO processing_errors (collection_dataset, hash, task_name, "
                "run_time_ms, error_logs, timestamp) VALUES "
                "('dataset', 'hash', 'task', 1, 'same', '2026-01-01 00:00:00'), "
                "('dataset', 'hash', 'task', 1, 'same', '2026-01-01 00:00:00')"
            )
            migration = (root / "00051_processing_errors_identity.sql").read_text()
            for statement in migration.split(";"):
                if statement.strip():
                    client.command(statement)
            assert client.query(
                "SELECT count(), uniqExact(error_identity) FROM processing_errors FINAL"
            ).result_rows == [(2, 2)]
        finally:
            client.close()
    finally:
        with get_global_client() as admin:
            admin.command(f"DROP DATABASE IF EXISTS {database} SYNC")
