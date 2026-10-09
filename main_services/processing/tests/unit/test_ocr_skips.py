"""Stored OCR skips, the storage order of OCR results, and the removed replace mode.

An image under the size floor or an empty input is a decision of the OCR stage. The stage
stores it in `ocr_skips`, so "Run OCR" does not select the file again. A result's text
reaches storage before its `raw_ocr_results` watermark, so a cancel or a failed text
write never leaves a watermark without text.
"""

import io
import json
from types import SimpleNamespace

import pyarrow as pa
import pytest
from temporalio.exceptions import ApplicationError, CancelledError

import database.clickhouse as clickhouse
import tasks.ocr_client as ocr_client
import tasks.ocr_pdf_client as ocr_pdf_client
from database.operation_inputs import project_inputs
from ocr_store_fake import CD, COLLECTION, FakeOcrStore
from tasks.P3_parse_files import parse_common, parse_ocr, parse_ocr_pdf
from tasks.P3_parse_files.batch_runner import run_batch
from tasks.P3_parse_files.insert_batch import parser_insert_batch
from tasks.task_timing import SkippedOutcome


@pytest.fixture
def store(monkeypatch):
    store = FakeOcrStore()
    monkeypatch.setattr(clickhouse, "get_collection_client", store.client)
    monkeypatch.setattr(parse_common.activity, "info", lambda: SimpleNamespace(
        workflow_run_id="run", activity_id="activity", attempt=1))
    monkeypatch.setattr(ocr_client, "engine_configured", lambda _engine: True)
    return store


def _png(width, height):
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (255, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def skipped(result):
    """The reason of a skipped outcome."""
    assert isinstance(result, SkippedOutcome)
    return result.value


def _no_ocr(*_args, **_kwargs):
    pytest.fail("an OCR request was sent")


def run_image(monkeypatch, tmp_path, data, passes=("eng",), ocr=_no_ocr, engine="tesseract"):
    path = tmp_path / "img"
    path.write_bytes(data)
    monkeypatch.setattr(parse_ocr, "_passes_for", lambda _engine, _cd: list(passes))
    monkeypatch.setattr(ocr_client, "run_ocr", ocr)
    return parse_ocr.run_ocr_and_store(parse_ocr.RunOcrParams(
        collectionname=COLLECTION, collection_dataset=CD, file_hash="img",
        file_path=str(path), engine=engine, timeout_seconds=30, op_id="op-1"))


def test_an_image_under_the_size_floor_stores_a_skip_for_each_open_pass(
        store, monkeypatch, tmp_path):
    store.raw.append((CD, "img", "easyocr", "de", json.dumps({"text": ""})))
    result = run_image(monkeypatch, tmp_path, _png(300, 40), passes=("en", "de", "ru"),
                       engine="easyocr")
    assert skipped(result) == "ocr_skipped_too_small"
    assert store.skips == [(CD, "img", "image", "easyocr", "en"),
                           (CD, "img", "image", "easyocr", "ru")]
    rows = store.inserts[-1][1]
    assert {(row["reason"], row["op_id"]) for row in rows} == {("ocr_skipped_too_small", "op-1")}


def test_an_empty_image_stores_its_skip(store, monkeypatch, tmp_path):
    assert skipped(run_image(monkeypatch, tmp_path, b"")) == "ocr_skipped_empty"
    assert store.skips == [(CD, "img", "image", "tesseract", "eng")]
    assert store.inserts[-1][1][0]["reason"] == "ocr_skipped_empty"


def test_an_empty_pdf_stores_its_skip(store, monkeypatch, tmp_path):
    path = tmp_path / "doc"
    path.write_bytes(b"")
    monkeypatch.setattr(ocr_pdf_client, "service_configured", lambda: True)
    monkeypatch.setattr(ocr_pdf_client, "engines_for_provider", lambda: ["tesseract"])
    monkeypatch.setattr(parse_ocr_pdf, "_passes_for", lambda _engine, _cd: ["eng"])
    result = parse_ocr_pdf.run_ocr_pdf_and_store(parse_ocr_pdf.RunOcrPdfParams(
        collectionname=COLLECTION, collection_dataset=CD, pdf_hash="doc",
        file_path=str(path), engine="tesseract", timeout_seconds=30, op_id="op-1"))
    assert skipped(result) == "ocr_pdf_skipped_empty"
    assert store.skips == [(CD, "doc", "pdf", "tesseract", "eng")]
    assert store.inserts[-1][1][0]["reason"] == "ocr_pdf_skipped_empty"


def test_outcomes_that_are_not_targets_store_no_skip(store, monkeypatch, tmp_path):
    assert skipped(run_image(monkeypatch, tmp_path, _png(400, 400), passes=())) == (
        "ocr_skipped_no_languages")
    monkeypatch.setattr(ocr_client, "engine_configured", lambda _engine: False)
    assert skipped(run_image(monkeypatch, tmp_path, _png(400, 400))) == (
        "ocr_skipped_tesseract_not_configured")
    monkeypatch.setattr(ocr_pdf_client, "service_configured", lambda: True)
    monkeypatch.setattr(ocr_pdf_client, "engines_for_provider", lambda: [])
    assert skipped(parse_ocr_pdf.run_ocr_pdf_and_store(parse_ocr_pdf.RunOcrPdfParams(
        collectionname=COLLECTION, collection_dataset=CD, pdf_hash="doc", file_path="x",
        engine="tesseract", timeout_seconds=30))) == "ocr_pdf_skipped_tesseract_not_requested"
    assert store.skips == [] and store.inserts == []


def test_no_operation_bypasses_an_existing_result(store, monkeypatch):
    """The replace mode is gone: an operation row that asks for it is never read."""
    import database.operations as operations

    monkeypatch.setattr(operations, "get_operation",
                        lambda _op: pytest.fail("the stage read the operation row"))
    store.raw.append((CD, "img", "tesseract", "eng", json.dumps({"text": ""})))
    store.pdf_results.append((CD, "doc", "tesseract", "eng", 1, 0))
    image = parse_ocr.RunOcrParams(collectionname=COLLECTION, collection_dataset=CD,
                                   file_hash="img", file_path="x", engine="tesseract",
                                   timeout_seconds=30, op_id="rerun_ocr-replace")
    document = parse_ocr_pdf.RunOcrPdfParams(collectionname=COLLECTION, collection_dataset=CD,
                                             pdf_hash="doc", file_path="x", engine="tesseract",
                                             timeout_seconds=30, op_id="rerun_ocr-replace")
    assert parse_ocr._already_done(store, image, "eng")
    assert parse_ocr_pdf._already_done(store, document, "eng")


def test_a_rerun_of_an_old_row_passes_no_replace_input():
    assert project_inputs("rerun_ocr", "c", CD, '{"replace_existing": true}') == {}


def test_a_stored_result_without_text_is_restored_without_ocr(store, monkeypatch, tmp_path):
    store.raw.append((CD, "img", "tesseract", "eng", json.dumps({"text": "harbour pilot"})))
    assert run_image(monkeypatch, tmp_path, _png(400, 400)) == "ocr_ok_1_passes"
    assert store.current_text("img")[("ocr_tesseract_eng", 1)][0] == "harbour pilot"


def _outcome(text):
    return ocr_client.OcrOutcome(text=text, confidence=90.0, engine="tesseract",
                                 languages="eng", run_time_ms=5,
                                 raw_json=json.dumps({"text": text}), provider="test")


def test_new_text_reaches_storage_before_its_watermark(store, monkeypatch, tmp_path):
    path = tmp_path / "img"
    path.write_bytes(_png(400, 400))
    monkeypatch.setattr(parse_ocr, "_passes_for", lambda _engine, _cd: ["eng"])
    monkeypatch.setattr(ocr_client, "run_ocr", lambda *_a, **_k: _outcome("cargo manifest"))

    def step(_item):
        return parse_ocr.run_ocr_and_store(parse_ocr.RunOcrParams(
            collectionname=COLLECTION, collection_dataset=CD, file_hash="img",
            file_path=str(path), engine="tesseract", timeout_seconds=30))

    result = run_batch("run_ocr_batch", ["img"], key=str, size=lambda _: 1, step=step,
                       task_name="run_ocr_and_store", budget=lambda _: 900)
    assert result.results[0].status == "ok"
    assert [table for table, _, _ in store.inserts] == ["text_content", "raw_ocr_results"]


class _Client:
    """Fails the text rows that `bad` names, with `error`."""

    def __init__(self, bad=(), error=None):
        self.rows = []
        self.bad = set(bad)
        self.error = error

    def insert_arrow(self, table, rows, *, settings):
        values = rows.column("value").to_pylist()
        if table == "text_content" and self.bad & set(values):
            raise self.error
        self.rows.extend((table, value) for value in values)


def _queue_like_the_earlier_order(client):
    """Queue the watermark first and the text second, as the stage did before."""
    def step(value):
        from database.clickhouse import insert_parser_arrow

        insert_parser_arrow(client, "raw_ocr_results", pa.table({"value": [value]}))
        insert_parser_arrow(client, "text_content", pa.table({"value": [value]}))
        return value
    return step


def test_the_buffer_writes_watermarks_after_text_whatever_the_queue_order():
    client = _Client()
    run_batch("run_ocr_batch", [1, 2], key=str, size=lambda _: 1,
              step=_queue_like_the_earlier_order(client), task_name="ocr",
              budget=lambda _: 900)
    assert client.rows == [("text_content", 1), ("text_content", 2),
                           ("raw_ocr_results", 1), ("raw_ocr_results", 2)]


def test_a_failed_text_write_keeps_that_file_without_a_watermark():
    client = _Client(bad={2}, error=ApplicationError("refused", type="BadRow",
                                                     non_retryable=True))
    result = run_batch("run_ocr_batch", [1, 2, 3], key=str, size=lambda _: 1,
                       step=_queue_like_the_earlier_order(client), task_name="ocr",
                       budget=lambda _: 900)
    assert [row.status for row in result.results] == ["ok", "failed", "ok"]
    assert ("raw_ocr_results", 2) not in client.rows
    assert ("raw_ocr_results", 1) in client.rows and ("raw_ocr_results", 3) in client.rows


def test_a_cancel_during_the_text_write_stores_no_watermark():
    client = _Client(bad={1}, error=CancelledError("cancelled"))
    with pytest.raises(CancelledError):
        with parser_insert_batch() as batch:
            batch.index = 0
            _queue_like_the_earlier_order(client)(1)
            batch.flush()
    assert client.rows == []
