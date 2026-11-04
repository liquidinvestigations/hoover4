"""Verify the OCR detection stage rules, without a service."""

import pytest

from tasks import document_language
from tasks.P3_parse_files import ocr_detection
from tasks.P6_index_data.activities import document_ocr_attributes, pages_replace_sql


def test_spaced_pages_keep_short_lists_and_bound_long_lists():
    assert ocr_detection.spaced_pages([3, 5, 9], limit=10) == [3, 5, 9]
    pages = list(range(1, 1001))
    chosen = ocr_detection.spaced_pages(pages)
    assert len(chosen) == ocr_detection.MAX_DETECTED_PAGES
    assert chosen[0] == 1 and chosen[1] == 11 and chosen[-1] == 991
    assert chosen == sorted(set(chosen))


def test_a_single_language_script_needs_no_sample():
    assert document_language.detected_language("Tamil", "") == "ta"
    assert document_language.detected_language("HanT", "") == "zh"


def test_a_short_sample_stays_undetermined():
    assert document_language.detected_language("Latin", "only few") == "und"


def test_a_sample_of_lines_gets_a_language_under_the_source_limit():
    sample = "The quarterly report of the company shows a rise in revenue"
    assert sum(c.isalpha() for c in sample) < 200
    assert document_language.detect_language(sample) == "und"
    assert document_language.detected_language("Latin", sample) == "en"


def test_a_row_without_a_result_is_a_decision_without_text():
    row = ocr_detection._row("c_ds", "h", "image", 1, None)
    assert (row["has_text"], row["box_count"], row["script"], row["language"]) == (0, 0, "", "und")
    assert row["detector_version"] == ocr_detection.OCR_DETECTION_VERSION


def test_a_row_takes_the_script_and_the_language_of_the_result():
    row = ocr_detection._row("c_ds", "h", "original", 7, {
        "has_text": True, "box_count": 12, "script": "Latin", "model": "Latin", "run_time_ms": 90,
        "text": "The quarterly report of the company shows a rise in revenue"})
    assert (row["page_id"], row["has_text"], row["script"], row["language"]) == (7, 1, "Latin", "en")


def test_an_image_under_the_size_gate_sends_no_request(monkeypatch):
    monkeypatch.setattr(ocr_detection, "image_dimensions", lambda data: (40, 40))
    monkeypatch.setattr(ocr_detection, "detect_text", lambda data: pytest.fail("no request"))
    assert ocr_detection.image_rows("c_ds", "h", b"x")[0]["has_text"] == 0


def test_a_page_that_cannot_render_stores_a_row_and_sends_no_request(monkeypatch):
    monkeypatch.setattr(ocr_detection, "render_page", lambda path, page: None)
    monkeypatch.setattr(ocr_detection, "detect_text", lambda data: pytest.fail("no request"))
    rows = ocr_detection.pdf_rows("c_ds", "h", "original", "/none", [2, 4])
    assert [(row["page_id"], row["has_text"]) for row in rows] == [(2, 0), (4, 0)]


def test_a_writer_names_the_ocr_columns_only_for_a_table_that_has_them():
    row = {"collection_dataset": "d", "file_hash": "h", "extracted_by": "e", "page_id": 1, "page_text": "t",
           "date_min": 0, "date_max": 0, "file_size_bytes": 0, "struct_flags": 0, "primary_filename": "",
           "mentioned_date_min": 0, "mentioned_date_max": 0}
    assert "ocr_script" not in pages_replace_sql("t_1_pages", row)
    sql = pages_replace_sql("t_1_pages", {**row, "ocr_script": "(5)", "ocr_language": "(6)"})
    assert "ocr_script, ocr_language)" in sql and sql.rstrip().endswith("(5), (6))")


def test_document_attributes_leave_out_empty_values():
    class Client:
        def query(self, sql, parameters):
            assert "has_text = 1" in sql
            class Result:
                result_rows = [("a", ["Latin"], ["en"]), ("b", ["Hebrew"], []), ("c", [], [])]
            return Result()

    scripts, languages = document_ocr_attributes(Client(), "c_ds")
    assert scripts == {"a": ["Latin"], "b": ["Hebrew"]}
    assert languages == {"a": ["en"]}
