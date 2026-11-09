"""Classify historical OCR evidence with synthetic candidates, without storage."""

import random
from dataclasses import replace

import pytest

from tasks import ocr_recovery as r

CAPS = dict(tesseract=["Latin", "Cyrillic", "HanS", "HanT", "eng", "deu", "fra", "rus", "srp", "srp_latn",
                       "chi_sim", "chi_tra"],
            easyocr=["en", "de", "fr", "ru", "ch_sim", "ch_tra", "rs_latin", "rs_cyrillic"])
CONTRACT = r.Contract(CAPS)
WORDS = "Der schnelle braune Fuchs springt hoch"


def detect(page=1, language="de", script="Latin", has_text=True, model="Latin", state=r.DETECTION_CURRENT):
    return r.Detection(page, state, has_text, script, model, language, 4)


def image(engine="tesseract", languages="eng+deu", text=WORDS, words=True, retired="", artifacts=(), record=None,
          form=r.FORM_RAW_IMAGE, kind="image"):
    return r.make_candidate(form=form, record=record or f"raw_ocr_results|{engine}|{languages}", engine=engine,
                            languages=languages, source_kind=kind, pages=[r.PageText.of(1, text)],
                            word_boxes=words, retired=retired, artifacts=artifacts)


def pdf(pages, engine="tesseract", languages="eng+deu", kind="original", artifacts=(), retired="", record=None,
        form=r.FORM_PDF_PARTS, recovery=""):
    return r.make_candidate(form=form, record=record or f"pdf_ocr_parts|1|{engine}|{languages}", engine=engine,
                            languages=languages, source_kind=kind,
                            pages=[r.PageText.of(page, text) for page, text in pages.items()],
                            artifacts=artifacts, retired=retired, recovery=recovery)


def evidence(candidates, detections=(detect(),), kind="image", eligible=(1,), applied=None, published=(),
             ranges=((1, 1),)):
    return r.FileEvidence("c_ds", "h" * 64, kind, "rev", eligible, tuple(detections), tuple(candidates), applied,
                          tuple(published), ranges)


def page(decision, number=1):
    return next(item for item in decision.pages if item.page_id == number)


def test_matching_image_language_reuses_text_under_the_detected_identity():
    result = r.classify_file(evidence([image()]), CONTRACT)
    item = page(result)
    assert item.action == r.REUSE_TEXT and item.reason == "detected_language_superset"
    assert [(a.engine, a.original_languages, a.canonical_languages, a.extracted_by) for a in item.accepted] == [
        ("tesseract", "eng+deu", "deu", "ocr_tesseract_deu")]
    assert r.WORK_TEXT in item.work and r.WORK_INDEX in item.work
    assert r.WORK_PDF_WORDS in item.work and not item.planned


def test_image_without_pdf_or_word_boxes_reports_missing_evidence():
    item = page(r.classify_file(evidence([image(words=False)]), CONTRACT))
    assert item.action == r.UNRESOLVED and item.reason == "word_boxes_missing"
    assert item.accepted[0].canonical_languages == "deu"


def test_image_with_present_pdf_needs_only_text_publication():
    artifact = r.Artifact("b", "derived/x/c_ds/h/a.pdf", 1, 1, 10, r.ARTIFACT_PRESENT, 2)
    item = page(r.classify_file(evidence([image(artifacts=(artifact,))]), CONTRACT))
    assert item.work == [r.WORK_TEXT, r.WORK_INDEX]


def test_wrong_language_requests_automatic_ocr_and_lists_replaced_history():
    candidate = image()
    item = page(r.classify_file(evidence([candidate], [detect(language="fr")]), CONTRACT))
    assert item.action == r.NEW_OCR
    assert item.planned == [dict(engine="tesseract", languages="fra")]
    assert item.replaced == [candidate.candidate_id]


def test_mixed_language_pdf_requests_ocr_only_for_incompatible_pages():
    ranges = ((1, 3),)
    artifact = r.Artifact("b", "derived/ocr-pdf/c_ds/h/x.pdf", 1, 3, 10, r.ARTIFACT_PRESENT, 2)
    candidate = pdf({1: WORDS, 2: "Le renard brun saute", 3: WORDS}, artifacts=(artifact,))
    found = [detect(1), detect(2, language="fr"), detect(3)]
    result = r.classify_file(evidence([candidate], found, kind="original", eligible=(1, 2, 3), ranges=ranges), CONTRACT)
    assert [page(result, n).action for n in (1, 2, 3)] == [r.REUSE_TEXT, r.NEW_OCR, r.REUSE_TEXT]
    assert page(result, 1).accepted[0].extracted_by == "pdfocr_tesseract_deu"
    assert r.WORK_PDF_PAGES in page(result, 1).work
    assert result.action == r.NEW_OCR


def test_both_historical_engines_keep_their_own_provenance():
    result = r.classify_file(evidence([image(), image("easyocr", "en+de")]), CONTRACT)
    item = page(result)
    assert sorted((a.engine, a.canonical_languages) for a in item.accepted) == [("easyocr", "de"), ("tesseract", "deu")]
    assert not item.planned


def test_several_candidates_prefer_exact_language_and_are_order_independent():
    exact, superset = image(languages="deu"), image(languages="eng+deu")
    automatic = image(languages="eng+deu", form=r.FORM_AUTOMATIC, record="automatic_ocr_output|p|applied")
    candidates = [superset, automatic, exact]
    first = r.classify_file(evidence(candidates), CONTRACT)
    for seed in range(5):
        random.Random(seed).shuffle(candidates)
        again = r.classify_file(evidence(candidates), CONTRACT)
        assert again.decision_digest == first.decision_digest
    item = page(first)
    assert item.accepted[0].candidate_id == exact.candidate_id
    assert item.accepted[0].reason == "detected_language_exact"
    assert sorted(item.duplicates) == sorted([superset.candidate_id, automatic.candidate_id])


def test_superset_ties_use_form_rank_then_identity():
    raw, automatic = image(), image(form=r.FORM_AUTOMATIC, record="automatic_ocr_output|p|applied")
    assert page(r.classify_file(evidence([raw, automatic]), CONTRACT)).accepted[0].candidate_id == automatic.candidate_id


def test_unknown_language_keeps_the_original_identity():
    item = page(r.classify_file(evidence([image()], [detect(language="und")]), CONTRACT))
    assert item.action == r.REUSE_TEXT and item.reason == "unknown_language_retained"
    assert item.accepted[0].canonical_languages == "eng+deu"
    assert item.accepted[0].extracted_by == "ocr_tesseract_eng+deu"


def test_no_text_detection_replaces_historical_text():
    candidate = image()
    item = page(r.classify_file(evidence([candidate], [detect(has_text=False, language="und", script="", model="")]),
                                CONTRACT))
    assert item.action == r.NO_TEXT_REPLACE and item.replaced == [candidate.candidate_id]
    empty = page(r.classify_file(evidence([image(text="")], [detect(has_text=False, script="", model="")]), CONTRACT))
    assert empty.action == r.NO_TEXT and not empty.replaced


@pytest.mark.parametrize("state", [r.DETECTION_MISSING, r.DETECTION_OUTDATED, r.DETECTION_FAILED])
def test_incomplete_detection_cannot_settle(state):
    candidate = image()
    result = r.classify_file(evidence([candidate], [detect(state=state)]), CONTRACT)
    assert result.action == r.REQUIRE_DETECTION and page(result).reason == "detection_" + state
    assert page(result).retained == [candidate.candidate_id] and not page(result).replaced


def test_absent_detection_row_is_missing_detection():
    result = r.classify_file(evidence([image()], []), CONTRACT)
    assert page(result).reason == "detection_missing"


def test_unprepared_pdf_has_no_page_identity():
    result = r.classify_file(evidence([pdf({1: WORDS})], kind="original", eligible=None), CONTRACT)
    assert result.action == r.REQUIRE_DETECTION and result.reason == "source_not_prepared" and not result.pages


def test_undecodable_image_with_historical_text_is_unresolved():
    found = [detect(has_text=False, script="", model=r.UNDECODABLE, language="und")]
    assert page(r.classify_file(evidence([image()], found), CONTRACT)).action == r.UNRESOLVED
    assert page(r.classify_file(evidence([], found), CONTRACT)).action == r.NO_TEXT


@pytest.mark.parametrize("languages,model,expected", [
    ("chi_sim", "HanS", r.REUSE_TEXT), ("chi_sim", "HanT", r.NEW_OCR), ("chi_tra", "HanT", r.REUSE_TEXT)])
def test_han_variants_are_separate_identities(languages, model, expected):
    item = page(r.classify_file(evidence([image(languages=languages, text="中文文本 中文文本")],
                                         [detect(language="zh", script="Han", model=model)]), CONTRACT))
    assert item.action == expected
    if expected == r.NEW_OCR:
        assert item.planned == [dict(engine="tesseract", languages="chi_tra")]


@pytest.mark.parametrize("languages,script,expected", [
    ("srp", "Cyrillic", r.REUSE_TEXT), ("srp", "Latin", r.NEW_OCR), ("srp_latn", "Latin", r.REUSE_TEXT)])
def test_serbian_scripts_are_separate_identities(languages, script, expected):
    item = page(r.classify_file(evidence([image(languages=languages)], [detect(language="sr", script=script, model=script)]),
                                CONTRACT))
    assert item.action == expected


def test_easyocr_set_keeps_easyocr_provenance():
    item = page(r.classify_file(evidence([image("easyocr", "en+ru")], [detect(language="ru", script="Cyrillic",
                                                                             model="Cyrillic")]), CONTRACT))
    assert [(a.engine, a.canonical_languages, a.extracted_by) for a in item.accepted] == [("easyocr", "ru", "ocr_easyocr_ru")]


def test_script_model_and_script_group_are_no_language_proof():
    assert page(r.classify_file(evidence([image(languages="Latin")]), CONTRACT)).action == r.NEW_OCR
    assert page(r.classify_file(evidence([image("easyocr", "en")]), CONTRACT)).action == r.NEW_OCR
    assert page(r.classify_file(evidence([image(languages="eng+deuX")]), CONTRACT)).action == r.NEW_OCR


def test_a_script_model_matching_the_planned_pass_is_reused():
    contract = r.Contract(dict(tesseract=["Latin"], easyocr=[]))
    item = page(r.classify_file(evidence([image(languages="Latin")]), contract))
    assert item.action == r.REUSE_TEXT and item.reason == "planned_pass"


def test_language_and_script_mismatch_is_no_proof():
    item = page(r.classify_file(evidence([image(languages="deu")], [detect(language="de", script="Cyrillic",
                                                                         model="Cyrillic")]), CONTRACT))
    assert item.action == r.NEW_OCR and item.reason == "language_script_mismatch"


def test_applied_plan_is_kept_when_it_satisfies_the_contract():
    found = detect(language="de")
    applied = r.AppliedPlan("p", "applied", 2, "cap", "rev", {1: (found.digest, "ready", (("tesseract", "deu"),))})
    current = replace(CONTRACT, capability_digest="cap")
    assert page(r.classify_file(evidence([], [found], applied=applied), current)).reason == "applied_plan_current"
    assert page(r.classify_file(evidence([], [found], applied=applied), CONTRACT)).reason == "applied_pass_matches_plan"
    stale = replace(applied, pages={1: (found.digest, "ready", (("tesseract", "Latin"),))})
    assert page(r.classify_file(evidence([], [found], applied=stale), CONTRACT)).action == r.NEW_OCR
    moved = replace(applied, source_revision="other")
    assert page(r.classify_file(evidence([], [found], applied=moved), current)).action == r.NEW_OCR


def test_retired_history_is_reported_and_not_adopted():
    candidate = image(retired="superseded_by_automatic")
    item = page(r.classify_file(evidence([candidate]), CONTRACT))
    assert item.action == r.NEW_OCR and item.retired_compatible == [candidate.candidate_id] and not item.replaced


def test_preview_history_cannot_supply_the_original():
    preview = pdf({1: WORDS}, kind="preview")
    result = r.classify_file(evidence([preview], kind="original", ranges=((1, 1),)), CONTRACT)
    assert result.rejected == [[preview.candidate_id, "source_kind_mismatch"]]
    assert page(result).action == r.NEW_OCR


def test_changed_content_cannot_reuse_another_identity():
    first, second = image(text=WORDS), image(text=WORDS + " anders")
    assert first.record == second.record and first.candidate_id != second.candidate_id
    forged = replace(second, content_digest=first.content_digest)
    result = r.classify_file(evidence([forged]), CONTRACT)
    assert result.rejected == [[forged.candidate_id, "content_digest_mismatch"]]
    assert page(result).action == r.NEW_OCR


def test_text_with_black_squares_is_not_reused():
    item = page(r.classify_file(evidence([image(text="Stra■e ist lang und breit")]), CONTRACT))
    assert item.action == r.NEW_OCR


def test_successful_empty_result_is_reused_as_empty():
    item = page(r.classify_file(evidence([image(languages="deu", text="")]), CONTRACT))
    assert item.accepted[0].empty and r.WORK_PDF_WORDS not in item.work


@pytest.mark.parametrize("state,layer,text,expected", [
    (r.ARTIFACT_MISSING, 2, WORDS, "artifact_missing"),
    (r.ARTIFACT_TRUNCATED, 2, WORDS, "artifact_truncated"),
    (r.ARTIFACT_WRONG_OWNER, 2, WORDS, "artifact_wrong_owner"),
    (r.ARTIFACT_PRESENT, 1, "Привет мир это текст", "text_layer_defective")])
def test_pdf_artifact_limits_are_unresolved(state, layer, text, expected):
    artifact = r.Artifact("b", "derived/ocr-pdf/c_ds/h/x.pdf", 1, 1, 10, state, layer)
    languages, found = ("eng+deu", detect()) if layer == 2 else ("rus", detect(language="ru", script="Cyrillic", model="Cyrillic"))
    candidate = pdf({1: text}, languages=languages, artifacts=(artifact,))
    item = page(r.classify_file(evidence([candidate], [found], kind="original"), CONTRACT))
    assert item.action == r.UNRESOLVED and item.reason == expected and item.accepted


def test_pdf_without_artifact_is_unresolved():
    item = page(r.classify_file(evidence([pdf({1: WORDS})], kind="original"), CONTRACT))
    assert item.reason == "artifact_missing"


def test_published_pdf_page_with_matching_artifact_is_current():
    artifact = r.Artifact("b", "derived/ocr-pdf/c_ds/h/x.pdf", 1, 1, 10, r.ARTIFACT_PRESENT, 2)
    candidate = pdf({1: WORDS}, languages="deu", artifacts=(artifact,))
    item = page(r.classify_file(evidence([candidate], kind="original", published=("pdfocr_tesseract_deu",)), CONTRACT))
    assert item.action == r.KEEP_CURRENT and item.reason == "historical_result_published"
    other = r.Artifact("b", "derived/ocr-pdf/c_ds/h/x.pdf", 1, 2, 10, r.ARTIFACT_PRESENT, 2)
    candidate = pdf({1: WORDS}, languages="deu", artifacts=(other,))
    item = page(r.classify_file(evidence([candidate], kind="original", published=("pdfocr_tesseract_deu",)), CONTRACT))
    assert item.action == r.ARTIFACT_ONLY and item.work == [r.WORK_PDF_PAGES]


def test_raster_pdf_text_is_reused_and_unread_raster_is_unresolved():
    artifact = r.Artifact("b", "derived/ocr-pdf/c_ds/h/eng.pdf", 1, 2, 10, r.ARTIFACT_PRESENT)
    raster = pdf({1: "The quick brown fox", 2: "jumps over"}, languages="eng", form=r.FORM_RASTER_PDF,
                 record="pdf_ocr_results|raster", artifacts=(artifact,))
    found = [detect(1, language="en"), detect(2, language="en")]
    result = r.classify_file(evidence([raster], found, kind="original", eligible=(1, 2), ranges=((1, 2),)), CONTRACT)
    assert [page(result, n).action for n in (1, 2)] == [r.REUSE_TEXT, r.REUSE_TEXT]
    assert page(result, 1).accepted[0].form == r.FORM_RASTER_PDF and page(result, 2).page_id == 2
    unread = pdf({}, languages="eng", form=r.FORM_RASTER_PDF, record="pdf_ocr_results|raster", recovery="raster_not_read")
    result = r.classify_file(evidence([unread], found, kind="original", eligible=(1, 2), ranges=((1, 2),)), CONTRACT)
    assert page(result, 1).action == r.UNRESOLVED and page(result, 1).reason == "raster_not_read"


def test_overlay_without_page_text_is_not_split_from_published_text():
    overlay = pdf({}, form=r.FORM_OVERLAY_PDF, record="pdf_ocr_results|overlay", recovery="overlay_without_page_text")
    item = page(r.classify_file(evidence([overlay], kind="original"), CONTRACT))
    assert item.action == r.UNRESOLVED and item.reason == "overlay_without_page_text"


def test_history_outside_eligible_pages_is_counted():
    result = r.classify_file(evidence([pdf({1: WORDS, 5: WORDS})], kind="original", ranges=((1, 5),)), CONTRACT)
    assert list(result.outside_eligible.values()) == [1]
