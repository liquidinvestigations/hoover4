"""Verify the reconciliation plan contract, adoption requests and the OCR selection scope."""

import pytest

from tasks import automatic_ocr
from tasks import ocr_recovery as recovery
from tasks.P3_parse_files import ocr_reconciliation as reconciliation
from tasks.P3_parse_files.automatic_ocr import artifact_rows, expected_identities, expected_outputs, plan_sources

INSTALLED = {"tesseract": ["deu", "eng", "fra", "Latin"], "easyocr": ["en", "de"]}


def _old_capability_digest(installed):
    """The `capability_digest` formula of `ocr_plan` version 1, with that version."""
    from tasks.P3_parse_files.ocr_detection import OCR_DETECTION_VERSION
    from tasks.ocr_pdf_client import service_configured
    from tasks.stage_versions import STAGE_VERSIONS
    from tasks.text_sources import PDF_SEGMENTATION_VERSION, PDF_TEXT_LAYER_VERSION
    versions = {stage: STAGE_VERSIONS[stage] for stage in
                ("ocr_image", "ocr_pdf", "image_pdf", "image_preview", "pdf_preview", "pdf", "index_text")}
    versions["ocr_plan"] = 1
    return automatic_ocr.digest(dict(searchable_pdf=service_configured(), artifact_segmentation=1, artifact_page_batch=32,
        stages=versions, engines={engine: installed.get(engine, []) for engine in ("tesseract", "easyocr")},
        detector=OCR_DETECTION_VERSION, segmentation=PDF_SEGMENTATION_VERSION, pdf_text_layer=PDF_TEXT_LAYER_VERSION))


def test_version_one_plans_stay_selected_as_current():
    from tasks.stage_versions import STAGE_VERSIONS
    assert STAGE_VERSIONS["ocr_plan"] == 2
    current, *accepted = automatic_ocr.accepted_capability_digests(INSTALLED)
    assert current == automatic_ocr.capability_digest(INSTALLED) != _old_capability_digest(INSTALLED)
    assert accepted == [_old_capability_digest(INSTALLED)]


def test_selector_accepts_compatible_digests(monkeypatch):
    from tasks.P_admin import automatic_ocr as admin
    monkeypatch.setattr(admin, "capabilities", lambda: INSTALLED)
    target = admin.target()
    assert target["caps"] == [target["cap"], _old_capability_digest(INSTALLED)]
    assert "IN {caps:Array(String)}" in admin.hash_sql()


def test_plan_output_contract_rejects_an_earlier_stage_contract(monkeypatch):
    old = dict(capabilities=INSTALLED, capability_digest=_old_capability_digest(INSTALLED))
    assert automatic_ocr.plan_output_contract(old) == automatic_ocr.output_contract()
    assert automatic_ocr.plan_output_contract(dict(old, capabilities={"tesseract": ["eng"]})) == ""
    from tasks import stage_versions
    monkeypatch.setitem(stage_versions.STAGE_VERSIONS, "ocr_image", 99)
    assert automatic_ocr.plan_output_contract(old) == ""
    assert old["capability_digest"] not in automatic_ocr.accepted_capability_digests(INSTALLED)


def _image(languages="eng+deu", detected="de", text="Guten Tag Welt heute morgen", words=True, artifacts=()):
    candidate = recovery.make_candidate(form=recovery.FORM_RAW_IMAGE, record=f"raw_ocr_results|tesseract|{languages}",
        engine="tesseract", languages=languages, source_kind="image", pages=[recovery.PageText.of(1, text)],
        word_boxes=words, artifacts=artifacts)
    detection = recovery.Detection(1, recovery.DETECTION_CURRENT, True, "Latin", "Latin", detected, 4)
    evidence = recovery.FileEvidence("c_ds", "h", "image", "h", (1,), (detection,), (candidate,), None, (), ((1, 1),))
    plan = automatic_ocr.make_plan("c_ds", "h", "h", "image", [detection.row()], INSTALLED, 1)
    return plan, evidence, candidate


def test_matching_image_is_adopted_under_the_detected_language():
    plan, evidence, candidate = _image()
    before = plan["plan_digest"]
    decision = recovery.classify_file(evidence, recovery.Contract(INSTALLED, searchable_pdf=True))
    sealed = reconciliation.apply_decision(plan, decision, evidence)
    page = sealed["pages"][0]
    assert page["passes"] == []
    assert page["adopted"] == [dict(candidate_id=candidate.candidate_id, form="raw_image", engine="tesseract",
        original_languages="eng+deu", languages="deu", extracted_by="ocr_tesseract_deu",
        reason="detected_language_superset", work=sorted(["text_publication", "dependent_indexing", "pdf_from_word_boxes"]))]
    assert sealed["reconciliation_diagnostics"]["decision_digest"] == decision.decision_digest
    diagnostic = dict(sealed, reconciliation_diagnostics=dict(decision_digest="other"))
    assert automatic_ocr.seal_plan(diagnostic)["plan_digest"] == sealed["plan_digest"]
    assert sealed["reconciliation"]["candidates"][candidate.candidate_id]["content_digest"] == candidate.content_digest
    assert sealed["output_contract"] == automatic_ocr.output_contract()
    assert sealed["plan_digest"] != before
    assert plan_sources(sealed) == {"ocr_tesseract_deu"}
    again, evidence, _ = _image()
    assert reconciliation.apply_decision(again, recovery.classify_file(
        evidence, recovery.Contract(INSTALLED, searchable_pdf=True)), evidence)["plan_digest"] == sealed["plan_digest"]
    parts = [dict(part_index=1, first_page=1, last_page=1, s3_path="", size_bytes=1)]
    assert expected_outputs(sealed, parts) == []
    jobs = reconciliation.adoption_jobs(sealed, parts, [])
    assert [(job["engine"], job["languages"], job["pages"], job["merge"]) for job in jobs] == [("tesseract", "deu", [1], "")]
    assert expected_identities(sealed, parts) == {jobs[0]["identity"]}


def test_wrong_language_image_keeps_its_new_ocr_pass():
    plan, evidence, candidate = _image(detected="fr", text="Bonjour tout le monde ici")
    sealed = reconciliation.apply_decision(plan, recovery.classify_file(
        evidence, recovery.Contract(INSTALLED, searchable_pdf=True)), evidence)
    page = sealed["pages"][0]
    assert page["passes"][0]["languages"] == "fra" and "adopted" not in page
    assert page["recovery"] == dict(action="new_ocr", reason="no_compatible_history")
    assert sealed["reconciliation_diagnostics"]["pages"] == {"1": dict(replaced=[candidate.candidate_id])}


def test_unresolved_history_fails_without_replacement():
    from temporalio.exceptions import ApplicationError
    plan, evidence, _ = _image(words=False)
    with pytest.raises(ApplicationError, match="word_boxes_missing") as raised:
        reconciliation.apply_decision(plan, recovery.classify_file(
            evidence, recovery.Contract(INSTALLED, searchable_pdf=True)), evidence)
    assert raised.value.non_retryable and raised.value.type == "OcrRecoveryUnresolved"


def test_missing_detection_requires_detection_before_any_change():
    plan, evidence, _ = _image()
    missing = recovery.FileEvidence("c_ds", "h", "image", "h", (1,), (), evidence.candidates, None, (), ((1, 1),))
    with pytest.raises(RuntimeError, match="detection is not current"):
        reconciliation.apply_decision(plan, recovery.classify_file(missing, recovery.Contract(INSTALLED)), missing)


def _pdf_plan(adopted_pages, new_pages, last=40):
    rows = [dict(page_id=page, has_text=1, script="Latin", model="Latin", language="de" if page in adopted_pages else "fr",
                 detector_version=4) for page in sorted(adopted_pages | new_pages)]
    plan = automatic_ocr.make_plan("c_ds", "h", "r", "original", rows, INSTALLED, 1)
    for page in plan["pages"]:
        if page["page_id"] in adopted_pages:
            page.update(passes=[], adopted=[dict(candidate_id="c1", form="pdf_parts", engine="tesseract",
                original_languages="eng+deu", languages="deu", extracted_by="pdfocr_tesseract_deu",
                reason="detected_language_superset", work=["pdf_from_saved_pages"])])
    parts = [dict(part_index=1, first_page=1, last_page=32, s3_path="s3://b/one", size_bytes=1),
             dict(part_index=2, first_page=33, last_page=last, s3_path="s3://b/two", size_bytes=1)]
    return automatic_ocr.seal_plan(plan), parts


def test_adoption_only_pair_covers_every_part():
    plan, parts = _pdf_plan({1, 2}, {3})
    recognition = expected_outputs(plan, parts)
    jobs = reconciliation.adoption_jobs(plan, parts, recognition)
    assert [(job["languages"], job["part"]["part_index"], job["pages"], job["merge"]) for job in jobs] == [
        ("deu", 1, [1, 2], ""), ("deu", 2, [], "")]
    assert [(job[2], job[4]) for job in recognition] == [("fra", [3]), ("fra", [])]


def test_adoption_and_recognition_of_one_pair_merge_into_one_part():
    plan, parts = _pdf_plan({1}, set())
    plan["pages"].append(dict(page_id=35, status="ready", passes=[dict(engine="tesseract", languages="deu", pass_id="x")]))
    plan = automatic_ocr.seal_plan(plan)
    recognition = expected_outputs(plan, parts)
    jobs = reconciliation.adoption_jobs(plan, parts, recognition)
    assert [(job["part"]["part_index"], job["pages"], job["merge"]) for job in jobs] == [(1, [1], recognition[0][0])]
    first = dict(engine="tesseract", languages="deu", part=parts[0], pages=[], blob_key="recognized", size_bytes=3)
    adopted = dict(engine="tesseract", languages="deu", part=parts[0], pages=[(1, "Hallo")], blob_key="assembled",
                   size_bytes=5, assembled=True)
    second = dict(engine="tesseract", languages="deu", part=parts[1], pages=[(35, "Neu")], blob_key="other", size_bytes=4)
    rows = artifact_rows("original", [first, adopted, second])
    assert [(value["blob_key"], part["part_index"], pages) for value, part, pages in rows] == [
        ("assembled", 1, [(1, "Hallo")]), ("other", 2, [(35, "Neu")])]


def test_plans_without_adoption_keep_their_request_identities():
    rows = [dict(page_id=101, has_text=True, script="Latin", language="en", detector_version=3)]
    plan = automatic_ocr.make_plan("c_ds", "h", "revision", "original", rows, dict(tesseract=["eng"]), 1)
    parts = [dict(part_index=1, first_page=1, last_page=100), dict(part_index=2, first_page=101, last_page=150)]
    assert expected_identities(plan, parts) == {job[0] for job in expected_outputs(plan, parts)}


def test_bounded_ranges_match_the_stored_artifact_parts():
    stored = [dict(first_page=1, last_page=20), dict(first_page=21, last_page=30)]
    assert reconciliation.bounded_ranges(stored) == [(1, 20), (21, 30)]
    assert reconciliation.bounded_ranges([dict(first_page=1, last_page=70)]) == [(1, 32), (33, 64), (65, 70)]


def test_stale_candidates_are_retired(monkeypatch):
    automatic = recovery.make_candidate(form=recovery.FORM_AUTOMATIC, record="automatic_ocr_output|p|applied",
        engine="tesseract", languages="eng", source_kind="original", plan_digest="p", pages=[recovery.PageText.of(1, "a")])
    current = dict(plan=dict(output_contract=automatic_ocr.output_contract()), source_revision="r")
    contract = automatic_ocr.output_contract()
    assert reconciliation._stale_reason(automatic, {"p": current}, "r", contract, False, 0) == ""
    assert reconciliation._stale_reason(automatic, {"p": current}, "other", contract, False, 0) == "source_changed"
    assert reconciliation._stale_reason(automatic, {"p": dict(current, plan=dict(output_contract="old"))}, "r",
                                        contract, False, 0) == "stage_contract_changed"
    legacy = recovery.make_candidate(form=recovery.FORM_PDF_PARTS, record="pdf_ocr_parts|1|live", engine="tesseract",
        languages="eng", source_kind="preview", pages=[recovery.PageText.of(3, "a")])
    assert reconciliation._stale_reason(legacy, {}, "r", contract, False, 3) == ""
    assert reconciliation._stale_reason(legacy, {}, "r", contract, False, 2) == "source_changed"
    assert reconciliation._stale_reason(legacy, {}, "r", contract, True, 3) == "stage_contract_changed"
    from tasks import stage_versions
    assert not reconciliation._legacy_stale()
    monkeypatch.setitem(stage_versions.STAGE_VERSIONS, "ocr_pdf", 3)
    assert reconciliation._legacy_stale()


def test_successful_no_text_detection_replaces_history():
    plan, evidence, candidate = _image()
    found = recovery.Detection(1, recovery.DETECTION_CURRENT, False, "", "", "und", 4)
    evidence = recovery.FileEvidence("c_ds", "h", "image", "h", (1,), (found,), evidence.candidates, None, (), ((1, 1),))
    plan = automatic_ocr.make_plan("c_ds", "h", "h", "image", [found.row()], INSTALLED, 1)
    sealed = reconciliation.apply_decision(plan, recovery.classify_file(evidence, recovery.Contract(INSTALLED)), evidence)
    assert sealed["pages"][0]["status"] == "no_text" and sealed["pages"][0]["passes"] == []
    assert sealed["pages"][0]["recovery"]["action"] == "no_text_replace"
    assert plan_sources(sealed) == set()
