"""Verify automatic page routing independently of manual settings and service transport."""

import pytest
from tasks.automatic_ocr import choose_pass, make_plan
from tasks.P3_parse_files.automatic_ocr import expected_outputs
from tasks.P3_parse_files import ocr_detection


def test_installed_tesseract_precedes_easyocr():
    assert choose_pass(dict(has_text=True, script="Latin", language="ro"),
                       dict(tesseract=["ron", "Latin"], easyocr=["ro"]))["passes"] == [dict(engine="tesseract", languages="ron")]


def test_unknown_language_uses_installed_script_model():
    result = choose_pass(dict(has_text=True, script="Latin", language="und"), dict(tesseract=["Latin"], easyocr=["en"]))
    assert result["reason"] == "unknown_language_script_coverage"
    assert result["passes"] == [dict(engine="tesseract", languages="Latin")]


def test_easyocr_uses_supported_models_when_tesseract_script_is_absent():
    result = choose_pass(dict(has_text=True, script="Arabic", language="fa"), dict(tesseract=["eng"], easyocr=["ar", "fa"]))
    assert result["passes"] == [dict(engine="easyocr", languages="fa")]


def test_unknown_easyocr_language_uses_a_compatible_script_group():
    result = choose_pass(dict(has_text=True, script="Arabic", language="und"), dict(tesseract=[], easyocr=["ar", "fa", "en"]))
    assert result["passes"] == [dict(engine="easyocr", languages="ar+fa")]


@pytest.mark.parametrize("found,status", [({"has_text": False}, "no_text"),
    ({"has_text": True, "script": ""}, "unsupported"), ({"has_text": True, "script": "Syriac"}, "unsupported")])
def test_negative_unknown_and_unsupported_states_are_distinct(found, status):
    assert choose_pass(found, dict(tesseract=[], easyocr=[]))["status"] == status


def test_plan_identity_is_stable_and_changes_with_capabilities():
    rows = [dict(page_id=101, has_text=True, script="Latin", language="en", detector_version=3)]
    first = make_plan("c_ds", "h", "revision", "original", rows, dict(tesseract=["eng"]), 1)
    assert first == make_plan("c_ds", "h", "revision", "original", rows, dict(tesseract=["eng"]), 1)
    assert first["plan_digest"] != make_plan("c_ds", "h", "revision", "original", rows, dict(tesseract=["eng", "Latin"]), 1)["plan_digest"]
    jobs = expected_outputs(first, [dict(part_index=1, first_page=1, last_page=100), dict(part_index=2, first_page=101, last_page=150)])
    assert [job[4] for job in jobs] == [[], [101]]


def test_detection_inspects_pages_after_one_hundred(monkeypatch):
    called = []
    monkeypatch.setattr(ocr_detection, "render_page", lambda path, page: called.append(page) or b"image")
    monkeypatch.setattr(ocr_detection, "detect_text", lambda image: {"has_text": False})
    rows = ocr_detection.pdf_rows("c_ds", "h", "original", "source", list(range(1, 152)))
    assert called == list(range(1, 152))
    assert len(rows) == 151


def test_an_unreadable_detector_answer_is_retryable(monkeypatch):
    from types import SimpleNamespace
    from tasks import ocr_client

    monkeypatch.setattr(ocr_client, "_endpoints_for", lambda _engine: [("tesseract", "http://ocr/ocr")])
    monkeypatch.setattr(ocr_client, "post_json", lambda *_a, **_k: SimpleNamespace(data=["not", "a", "dict"]))
    with pytest.raises(RuntimeError, match="unreadable answer"):
        ocr_client.detect_text(b"image")


def test_recognized_short_tsv_keeps_its_delimiter_after_download(tmp_path):
    from tasks.P3_parse_files.table_readers import read_cells
    path = tmp_path / "contenthash"
    path.write_text("Tsvupgradeunique\tOrchid\nGamma\tMaple\nDelta\tCedar\n")
    cells = list(read_cells(str(path), "csv", delimiter="\t"))
    assert len(cells) == 6
    assert {cell.column_id for _, _, cell in cells} == {1, 2}


def test_unavailable_easyocr_does_not_block_installed_tesseract():
    selected = choose_pass(dict(has_text=True, script="Latin", language="en"),
                           dict(tesseract=["eng"], easyocr=[], easyocr_unavailable=True))
    assert selected["passes"] == [dict(engine="tesseract", languages="eng")]


def test_required_unavailable_fallback_stays_retryable():
    selected = choose_pass(dict(has_text=True, script="Arabic", language="ar"),
                           dict(tesseract=["eng"], easyocr=[], easyocr_unavailable=True))
    assert (selected["status"], selected["reason"]) == ("failed", "easyocr_capabilities_unavailable")


def test_traditional_han_keeps_the_detected_model():
    selected = choose_pass(dict(has_text=True, script="Han", model="HanT", language="zh"),
                           dict(tesseract=["chi_sim", "chi_tra", "HanT"]))
    assert selected["passes"] == [dict(engine="tesseract", languages="chi_tra")]


def test_successful_negative_presence_requires_a_stored_plan():
    from tasks.P6_index_data.activities import document_ocr_presence
    class Client:
        def query(self, sql, parameters):
            assert "state IN ('published', 'applied')" in sql
            from types import SimpleNamespace
            return SimpleNamespace(result_rows=[("absent", 0), ("present", 1)])
    assert document_ocr_presence(Client(), "dataset", ["absent", "present", "unknown"]) == {"absent": 1, "present": 2}


def test_unknown_traditional_han_does_not_use_simplified_coverage():
    selected = choose_pass(dict(has_text=True, script="Han", model="HanT", language="und"),
                           dict(tesseract=["HanS"], easyocr=["ch_tra"]))
    assert selected["passes"] == [dict(engine="easyocr", languages="ch_tra")]


def test_detected_language_cannot_select_an_incompatible_script_model():
    selected = choose_pass(dict(has_text=True, script="Latin", language="ar"),
                           dict(tesseract=["ara", "Latin"]))
    assert selected["passes"] == [dict(engine="tesseract", languages="Latin")]


def test_automatic_errors_have_retry_stages_and_recovery_evidence():
    from tasks.stage_versions import canonical_stage
    from tasks.P_admin.rerun_selection import recovery_activity
    from tasks.task_timing import _outcome_name
    assert canonical_stage("automatic_ocr") == "ocr_plan"
    assert canonical_stage("detect_ocr_text") == "ocr_detection"
    assert recovery_activity("automatic_ocr") == "automatic_ocr"
    assert _outcome_name("automatic_ocr", "") == "automatic_ocr"


def test_script_fallback_covers_supported_cyrillic_languages_outside_the_legacy_list():
    selected = choose_pass(dict(has_text=True, script="Cyrillic", language="und"),
                           dict(tesseract=[], easyocr=["abq", "tjk"]))
    assert selected["passes"] == [dict(engine="easyocr", languages="abq+tjk")]


def test_searchable_pdf_availability_changes_the_publication_target(monkeypatch):
    from tasks import ocr_pdf_client
    from tasks.automatic_ocr import capability_digest
    monkeypatch.setattr(ocr_pdf_client, "service_configured", lambda: False)
    before = capability_digest({"tesseract": ["eng"]})
    monkeypatch.setattr(ocr_pdf_client, "service_configured", lambda: True)
    assert before != capability_digest({"tesseract": ["eng"]})


def test_rejected_image_input_is_skipped_with_an_empty_page(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    import requests
    from database import clickhouse
    from tasks import ocr_client, ocr_targets
    from tasks.P3_parse_files import automatic_ocr
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda name: nullcontext(None))
    monkeypatch.setattr(ocr_detection, "read_image", lambda *args: b"unreadable")
    error = requests.HTTPError(response=SimpleNamespace(status_code=422))
    monkeypatch.setattr(ocr_client, "run_ocr", lambda *args: (_ for _ in ()).throw(error))
    skips = []
    monkeypatch.setattr(ocr_targets, "record_ocr_skips", lambda *args: skips.append(args[1:]))
    output = automatic_ocr.image_output(
        SimpleNamespace(collectionname="collection", collection_dataset="dataset", op_id="op"),
        SimpleNamespace(item_hash="image", file_path="unused"), "tesseract", "eng", {})
    assert skips == [("dataset", "image", "image", "tesseract", ["eng"], "ocr_skipped_undecodable", "op")]
    assert output["pages"] == [(1, "")]
    assert "blob_key" not in output


def test_an_unresolved_page_takes_the_script_of_its_document():
    from tasks.automatic_ocr import make_plan
    rows = [dict(page_id=1, has_text=1, script="Hebrew", model="Hebrew", language="he", detector_version=4),
            dict(page_id=2, has_text=1, script="", model="", language="und", detector_version=4),
            dict(page_id=3, has_text=0, script="", model="", language="und", detector_version=4)]
    plan = make_plan("d", "h", "r", "original", rows, dict(tesseract=["Hebrew", "heb", "Latin"], easyocr=[]), 1)
    assert [(page["status"], page["reason"]) for page in plan["pages"]] == [
        ("ready", "detected_language"), ("ready", "unresolved_detected_language"), ("no_text", "detected_no_text")]
    assert plan["pages"][1]["passes"][0]["languages"] == "heb"


def test_an_unresolved_document_uses_the_latin_script_model():
    from tasks.automatic_ocr import make_plan
    rows = [dict(page_id=1, has_text=1, script="", model="", language="und", detector_version=4)]
    plan = make_plan("d", "h", "r", "image", rows, dict(tesseract=["Latin"], easyocr=[]), 1)
    assert plan["pages"][0]["status"] == "ready"
    assert plan["pages"][0]["reason"] == "unresolved_unknown_language_script_coverage"
    assert plan["pages"][0]["passes"][0]["languages"] == "Latin"


def test_publication_check_compares_one_row_for_each_pdf_part(monkeypatch):
    from types import SimpleNamespace
    from tasks.P3_parse_files import automatic_ocr, pdf_parts
    from tasks.P3_parse_files.parse_common import stored_page_bodies
    monkeypatch.setattr(pdf_parts, "source_parts", lambda *_: [dict(first_page=1, last_page=2), dict(first_page=3, last_page=3)])
    pages = [(1, "alpha"), (2, "beta"), (3, "gamma")]
    rows = automatic_ocr.publication_rows(None, "d", "h", "original", {"pdfocr_x": pages})
    assert rows == {"pdfocr_x": [(1, "alpha\fbeta"), (3, "gamma")]}
    assert automatic_ocr.publication_rows(None, "d", "h", "image", {"ocr_x": pages}) == {"ocr_x": pages}

    class Client:
        def query(self, sql, parameters):
            return SimpleNamespace(result_rows=stored_page_bodies(rows["pdfocr_x"]))

    params = SimpleNamespace(collection_dataset="d")
    automatic_ocr.verify_text_publication(Client(), params, "h", rows)
    with pytest.raises(RuntimeError, match="incomplete durable replacement"):
        automatic_ocr.verify_text_publication(Client(), params, "h", {"pdfocr_x": pages})
