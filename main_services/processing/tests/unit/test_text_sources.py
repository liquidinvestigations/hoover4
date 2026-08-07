"""The `extracted_by` convention is a storage key and a user-visible label at once.

Getting it wrong does not raise: it produces a second set of rows under a slightly
different name, which reads as "OCR ran twice" in the source selector and as a cache miss
to every left-anti join in the pipeline.
"""

import pytest

from tasks.text_sources import (
    ENGINE_EASYOCR,
    ENGINE_TESSERACT,
    easyocr_language_groups,
    join_languages,
    ocr_extracted_by,
    parse_ocr_extracted_by,
    split_languages,
)


def test_label_shape():
    assert ocr_extracted_by(ENGINE_TESSERACT, "eng+ron") == "ocr_tesseract_eng+ron"
    assert ocr_extracted_by(ENGINE_EASYOCR, "en") == "ocr_easyocr_en"


def test_round_trip():
    for engine, langs in ((ENGINE_TESSERACT, "eng+ron+deu"), (ENGINE_EASYOCR, "en")):
        assert parse_ocr_extracted_by(ocr_extracted_by(engine, langs)) == (engine, langs)


def test_native_extractors_are_not_ocr_variants():
    for native in ("pdftotext", "extractous", "office_xml", "email_parser", "raw_text", "qpdf"):
        assert parse_ocr_extracted_by(native) is None


def test_unknown_engine_is_refused_at_write_time():
    """The label is a key. A typo must fail here, not become a second silent variant."""
    with pytest.raises(ValueError):
        ocr_extracted_by("tesserakt", "eng")
    with pytest.raises(ValueError):
        ocr_extracted_by(ENGINE_TESSERACT, "")


def test_malformed_labels_parse_as_native_rather_than_guessing():
    assert parse_ocr_extracted_by("ocr_tesseract") is None
    assert parse_ocr_extracted_by("ocr_unknown_eng") is None
    assert parse_ocr_extracted_by("ocr_tesseract_") is None


def test_language_order_is_preserved_because_tesseract_cares():
    """`eng+ron` and `ron+eng` are different requests -- Tesseract treats the first as
    primary -- and therefore different variants. Sorting them would silently merge two
    distinct OCR runs into one row."""
    assert join_languages(["ron", "eng"]) == "ron+eng"
    assert join_languages(["eng", "ron"]) == "eng+ron"
    assert join_languages(["eng", "eng", "ron"]) == "eng+ron"
    assert split_languages(" eng + ron ") == ["eng", "ron"]


def test_tesseract_multi_language_is_one_variant_but_easyocr_is_several():
    """The asymmetry that drives the cost model: one Tesseract pass covers every
    language, while EasyOCR needs one Reader per script.

    `en+ru` is a single valid Reader (English rides along with any one other script), so
    two *scripts* are needed before the fan-out appears.
    """
    assert easyocr_language_groups("en") == ["en"]
    assert easyocr_language_groups("en+ru") == ["en+ru"]
    assert len(easyocr_language_groups("ru+ja")) == 2


def test_english_rides_along_rather_than_forming_its_own_pass():
    """EasyOCR accepts 'en' alongside any single other script, and recognition improves
    with it present. A separate latin-only pass would be a third full pass over the
    dataset for no gain."""
    groups = easyocr_language_groups("en+ru+ja")
    assert all(g.startswith("en+") for g in groups), groups
    assert len(groups) == 2, groups


def test_unknown_language_never_shares_a_pass_with_a_known_script():
    """EasyOCR will reject an unknown code whatever it is grouped with, but grouping it
    with a real script takes that script's pass down with it. Isolating it means one
    failed variant instead of two."""
    groups = easyocr_language_groups("en+zz+ru")
    assert len(groups) == 2, groups
    assert not any("zz" in g and "ru" in g for g in groups), groups


def test_no_languages_means_no_passes():
    assert easyocr_language_groups("") == []
    assert easyocr_language_groups("  ") == []
