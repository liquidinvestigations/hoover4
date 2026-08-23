"""Tests for the `change_ocr_languages` diff and the OCR'd-PDF key convention.

Two pure things carry the whole job. The diff decides what gets purged. Get a removal
wrong and either rows leak forever or a variant still in use is deleted. The key decides
where the derived object lives. Get it wrong and the ingest walker starts a re-derive
loop that bills an OCR pass per lap.
"""

import pytest

from tasks.P_admin.ocr_languages import compute_diff
from tasks.ocr_pdf_client import DERIVED_PREFIX, derived_key, engines_for_provider
from tasks.text_sources import ENGINE_EASYOCR, ENGINE_TESSERACT


def diff(before_tess, after_tess, before_easy="en", after_easy="en"):
    return compute_diff(
        {ENGINE_TESSERACT: before_tess, ENGINE_EASYOCR: before_easy},
        {ENGINE_TESSERACT: after_tess, ENGINE_EASYOCR: after_easy},
    )


class TestComputeDiff:
    def test_no_change_means_no_work(self):
        result = diff("eng", "eng")
        assert result.changed_engines == []
        assert result.added_variants == []
        assert result.removed_variants == []

    def test_adding_a_tesseract_language_replaces_the_variant(self):
        """One pass, one variant: `eng+ron` does not *extend* `eng`, it replaces it."""
        result = diff("eng", "eng+ron")
        assert result.changed_engines == [ENGINE_TESSERACT]
        assert result.added_variants == ["ocr_tesseract_eng+ron"]
        assert result.removed_variants == ["ocr_tesseract_eng"]
        assert result.removed_pairs == [[ENGINE_TESSERACT, "eng"]]

    def test_language_order_is_a_real_difference(self):
        """Tesseract's first language is the primary one, so this is not a no-op."""
        result = diff("eng+ron", "ron+eng")
        assert result.added_variants == ["ocr_tesseract_ron+eng"]
        assert result.removed_variants == ["ocr_tesseract_eng+ron"]

    def test_removing_every_language_removes_the_variant_and_adds_nothing(self):
        result = diff("eng", "")
        assert result.added_variants == []
        assert result.removed_variants == ["ocr_tesseract_eng"]

    def test_easyocr_scripts_become_one_variant_per_group(self):
        """Adding a language in a new script is a full extra pass, and shows up as one."""
        result = diff("eng", "eng", before_easy="en", after_easy="en+ru")
        assert result.changed_engines == [ENGINE_EASYOCR]
        # English rides along with the cyrillic group rather than forming a pass of its own.
        assert result.added_variants == ["ocr_easyocr_en+ru"]
        assert result.removed_variants == ["ocr_easyocr_en"]

    def test_both_engines_changing_reports_both(self):
        result = diff("eng", "eng+ron", before_easy="en", after_easy="ru")
        assert result.changed_engines == [ENGINE_TESSERACT, ENGINE_EASYOCR]
        assert len(result.added_variants) == 2
        assert len(result.removed_variants) == 2

    def test_removed_pairs_are_the_storage_key_not_the_label(self):
        """`pdf_ocr_results` and the derived object are keyed by (engine, languages)."""
        result = diff("eng+ron", "eng")
        assert result.removed_pairs == [[ENGINE_TESSERACT, "eng+ron"]]


class TestDerivedKey:
    def test_the_key_is_always_under_the_derived_prefix(self):
        key = derived_key("testdata_testfiles", "abc123", "tesseract", "eng+ron")
        assert key.startswith(DERIVED_PREFIX)
        assert key == "derived/ocr-pdf/testdata_testfiles/abc123/tesseract+eng+ron.pdf"

    def test_variants_of_one_pdf_do_not_collide(self):
        a = derived_key("ds", "hash", "tesseract", "eng")
        b = derived_key("ds", "hash", "tesseract", "eng+ron")
        c = derived_key("ds", "hash", "easyocr", "en")
        assert len({a, b, c}) == 3


class TestEnginesForProvider:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("tesseract", [ENGINE_TESSERACT]),
            ("easyocr", [ENGINE_EASYOCR]),
            ("both", [ENGINE_TESSERACT, ENGINE_EASYOCR]),
            ("none", []),
            ("", [ENGINE_TESSERACT]),
            ("  BOTH  ", [ENGINE_TESSERACT, ENGINE_EASYOCR]),
        ],
    )
    def test_reads_pdf_ocr_provider(self, monkeypatch, value, expected):
        monkeypatch.setenv("PDF_OCR_PROVIDER", value)
        assert engines_for_provider() == expected

    def test_an_unknown_value_produces_nothing_rather_than_guessing(self, monkeypatch):
        """Variants nobody asked for cost OCR time and leave rows a purge has to find."""
        monkeypatch.setenv("PDF_OCR_PROVIDER", "tesseractt")
        assert engines_for_provider() == []
