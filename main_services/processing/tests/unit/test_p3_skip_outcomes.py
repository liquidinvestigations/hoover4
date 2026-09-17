"""P3 valid no-work cases return skipped outcomes without Error rows."""

from types import SimpleNamespace
import pytest

from database import clickhouse
from tasks.P3_parse_files import parse_ocr, parse_ocr_pdf, parse_table
from tasks.task_timing import SkippedOutcome


@pytest.fixture(autouse=True)
def activity_source(monkeypatch):
    from tasks.P3_parse_files import parse_common
    monkeypatch.setattr(parse_common.activity, "info", lambda: SimpleNamespace(
        workflow_run_id="run", activity_id="activity", attempt=1,
    ))


class _Client:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def query(self, *_args, **_kwargs):
        return SimpleNamespace(result_rows=[[0]])


class _NoRowsClient(_Client):
    def query(self, *_args, **_kwargs):
        return SimpleNamespace(result_rows=[])


def _ocr_params(file_path: str, op_id: str = "operation-1"):
    return parse_ocr.RunOcrParams(
        collectionname="collection",
        collection_dataset="dataset",
        file_hash="hash",
        file_path=file_path,
        engine="easyocr",
        timeout_seconds=30,
        op_id=op_id,
    )


def test_ocr_unconfigured_engine_is_skipped(monkeypatch):
    calls = []
    monkeypatch.setattr(parse_ocr, "_record_skip", lambda *args: calls.append(args))
    monkeypatch.setattr("tasks.ocr_client.engine_configured", lambda _engine: False)

    result = parse_ocr.run_ocr_and_store(_ocr_params("missing"))

    assert isinstance(result, SkippedOutcome)
    assert result.value == "ocr_skipped_easyocr_not_configured"
    assert calls == []


def test_ocr_without_languages_is_skipped(monkeypatch):
    calls = []
    monkeypatch.setattr(parse_ocr, "_record_skip", lambda *args: calls.append(args))
    monkeypatch.setattr("tasks.ocr_client.engine_configured", lambda _engine: True)
    monkeypatch.setattr(parse_ocr, "_passes_for", lambda _engine, _dataset: [])

    result = parse_ocr.run_ocr_and_store(_ocr_params("missing"))

    assert isinstance(result, SkippedOutcome)
    assert result.value == "ocr_skipped_no_languages"
    assert calls == []


def test_ocr_pdf_engine_excluded_by_provider_is_skipped(monkeypatch):
    monkeypatch.setattr("tasks.ocr_pdf_client.service_configured", lambda: True)
    monkeypatch.setattr("tasks.ocr_pdf_client.engines_for_provider", lambda: ["tesseract"])
    params = parse_ocr_pdf.RunOcrPdfParams(
        "collection", "dataset", "pdf-hash", "pdf", "easyocr", 30, "operation"
    )

    result = parse_ocr_pdf.run_ocr_pdf_and_store(params)

    assert isinstance(result, SkippedOutcome)
    assert result.value == "ocr_pdf_skipped_easyocr_not_requested"


def test_ocr_empty_input_is_skipped(monkeypatch, tmp_path):
    image_path = tmp_path / "empty-image"
    image_path.touch()
    calls = []
    monkeypatch.setattr(parse_ocr, "_record_skip", lambda *args: calls.append(args))
    monkeypatch.setattr("tasks.ocr_client.engine_configured", lambda _engine: True)
    monkeypatch.setattr(parse_ocr, "_passes_for", lambda _engine, _dataset: ["eng"])
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: _NoRowsClient())

    result = parse_ocr.run_ocr_and_store(_ocr_params(str(image_path)))

    assert isinstance(result, SkippedOutcome)
    assert result.value == "ocr_skipped_empty"
    assert calls == []


def test_ocr_unreadable_input_records_bracketed_error(monkeypatch):
    calls = []
    monkeypatch.setattr(parse_ocr, "_record_skip", lambda *args: calls.append(args))
    monkeypatch.setattr("tasks.ocr_client.engine_configured", lambda _engine: True)
    monkeypatch.setattr(parse_ocr, "_passes_for", lambda _engine, _dataset: ["eng"])
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: _Client())
    params = _ocr_params("missing", op_id="operation-2")

    assert parse_ocr.run_ocr_and_store(params) == "ocr_skipped_unreadable"
    assert calls[0][0] is params
    assert params.op_id == "operation-2"


def test_ocr_skip_writer_uses_bracketed_task_and_op_id(monkeypatch):
    from tasks.P2_execute_plan import activities

    writes = []
    monkeypatch.setattr(activities, "record_processing_errors", writes.append)
    params = _ocr_params("missing", op_id="operation-2")

    parse_ocr._record_skip(params, 12, "ocr_skipped_unreadable")

    row = writes[0].errors[0]
    assert row["task_name"] == "run_ocr_and_store[easyocr]"
    assert row["op_id"] == "operation-2"


def test_table_without_reader_is_skipped(monkeypatch):
    calls = []
    monkeypatch.setattr(parse_table, "_record_skip", lambda *args: calls.append(args))
    monkeypatch.setattr(parse_table, "table_reader_for", lambda *_args: None)
    params = parse_table.ParseTableParams(
        collectionname="collection",
        collection_dataset="dataset",
        file_hash="hash",
        file_path="file.unknown",
        timeout_seconds=30,
        op_id="operation-3",
    )

    result = parse_table.parse_table_and_store(params)

    assert isinstance(result, SkippedOutcome)
    assert result.value == {"status": "skipped", "reason": "no reader for this file"}
    assert calls == []


def test_table_reader_failure_records_op_id(monkeypatch):
    from tasks.P3_parse_files import table_readers

    calls = []
    monkeypatch.setattr(parse_table, "_record_skip", lambda *args: calls.append(args))
    monkeypatch.setattr(parse_table, "table_reader_for", lambda *_args: "reader")
    monkeypatch.setattr(parse_table, "table_format_for", lambda *_args: "format")
    monkeypatch.setattr(table_readers, "fallback_reader", lambda _reader: None)
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: _NoRowsClient())
    monkeypatch.setattr(clickhouse, "insert_arrow_idempotent", lambda *_args: None)

    def fail_reader(*_args, **_kwargs):
        raise RuntimeError("reader failed")

    monkeypatch.setattr(table_readers, "read_cells", fail_reader)
    params = parse_table.ParseTableParams(
        collectionname="collection",
        collection_dataset="dataset",
        file_hash="hash",
        file_path="file.csv",
        timeout_seconds=30,
        op_id="operation-4",
    )

    result = parse_table.parse_table_and_store(params)

    assert result["status"] == "failed"
    assert calls[0][0] is params
    assert params.op_id == "operation-4"


def test_table_skip_writer_uses_op_id(monkeypatch):
    from tasks.P2_execute_plan import activities

    writes = []
    monkeypatch.setattr(activities, "record_processing_errors", writes.append)
    params = parse_table.ParseTableParams(
        collectionname="collection",
        collection_dataset="dataset",
        file_hash="hash",
        file_path="file.csv",
        timeout_seconds=30,
        op_id="operation-4",
    )

    parse_table._record_skip(params, 12, "table_reader_failed")

    row = writes[0].errors[0]
    assert row["task_name"] == "parse_table_and_store"
    assert row["op_id"] == "operation-4"
