"""The OCR targets of "Run OCR" and the rule that says when one is done.

A fake collection database answers each query by its table (`ocr_store_fake.py`). The
targets come from `_plan_targets` of `tasks/P_admin/ocr_rerun.py`, with the OCR
configuration patched. The rule comes from `tasks/ocr_targets.py`.
"""

import json
from datetime import datetime, timezone

import pytest

import tasks.dataset_config as dataset_config
import tasks.ocr_client as ocr_client
import tasks.ocr_pdf_client as ocr_pdf_client
from ocr_store_fake import CD, COLLECTION, FakeOcrStore
from tasks import ocr_targets
from tasks.ocr_targets import (
    STAGE_IMAGE, STAGE_INDEX, STAGE_PDF, SettingVersion, Target, settled, text_pending_index,
)
from tasks.P_admin import ocr_rerun
from tasks.P3_parse_files.batch_runner import FileResult
from tasks.P3_parse_files.parse_mime import LOCAL_DETECTORS
from tasks.P3_parse_files.workflows import (
    combine_detector_results, detector_results_for_file, route_stages,
)

PRECISE = SettingVersion(100_100_000, True)
HISTORICAL = SettingVersion(100_000_000, False)
NO_ROW = SettingVersion()


@pytest.fixture
def store(monkeypatch):
    store = FakeOcrStore()
    import database.clickhouse as clickhouse

    monkeypatch.setattr(clickhouse, "get_collection_client", store.client)
    return store


@pytest.fixture
def config(monkeypatch):
    """Tesseract and the builder configured, EasyOCR not, and the dataset at `eng`."""
    state = {"engines": {"tesseract"}, "builder": True, "provider": ["tesseract"],
             "rows": {"ocr.tesseract.languages": ("eng", 100_100_000, True),
                      "ocr.easyocr.languages": ("en", 100_100_000, True)}}
    monkeypatch.setattr(ocr_client, "engine_configured", lambda e: e in state["engines"])
    monkeypatch.setattr(ocr_pdf_client, "service_configured", lambda: state["builder"])
    monkeypatch.setattr(ocr_pdf_client, "engines_for_provider", lambda: list(state["provider"]))

    def rows(_cd, keys):
        return {key: dataset_config.SettingRow(value, False, version, precise)
                for key, (value, version, precise) in state["rows"].items() if key in keys}

    monkeypatch.setattr(dataset_config, "latest_setting_rows", rows)
    return state


def targets_of(store, items):
    pairs = ocr_targets.current_pairs(ocr_targets.language_settings(CD))
    targets, _ = ocr_rerun._plan_targets(store, COLLECTION, CD, items, pairs)
    return targets


def open_targets(store, items):
    targets = targets_of(store, items)
    return set(targets) - settled(store, CD, targets)


IMAGE_ENG = Target("img", STAGE_IMAGE, "tesseract", "eng")
PDF_ENG = Target("doc", STAGE_PDF, "tesseract", "eng")
INDEX = Target("img", STAGE_INDEX)


# ---- image targets ---------------------------------------------------------------------

def test_an_image_without_a_result_has_one_open_image_target(store, config):
    store.add_image("img")
    assert open_targets(store, ["img"]) == {IMAGE_ENG}
    assert targets_of(store, ["img"])[IMAGE_ENG] == PRECISE


def test_a_result_settles_the_image_target(store, config):
    store.add_image("img")
    store.raw.append((CD, "img", "tesseract", "eng", json.dumps({"text": ""})))
    assert open_targets(store, ["img"]) == set()


def test_a_stored_skip_settles_the_image_target(store, config):
    store.add_image("img")
    store.skips.append((CD, "img", STAGE_IMAGE, "tesseract", "eng"))
    assert open_targets(store, ["img"]) == set()


@pytest.mark.parametrize(("since", "write_version", "seconds", "done"), [
    pytest.param(PRECISE, 100_800_000, 100, True, id="precise-later-same-second"),
    pytest.param(PRECISE, 100_050_000, 100, False, id="precise-earlier-same-second"),
    pytest.param(PRECISE, 99_000_000, 99, False, id="precise-older"),
    pytest.param(PRECISE, 0, 101, False, id="precise-and-an-error-without-version"),
    pytest.param(HISTORICAL, 100_800_000, 100, True, id="historical-same-second"),
    pytest.param(HISTORICAL, 0, 100, True, id="historical-same-second-without-version"),
    pytest.param(HISTORICAL, 99_900_000, 99, False, id="historical-previous-second"),
    pytest.param(HISTORICAL, 0, 99, False, id="historical-previous-second-without-version"),
    pytest.param(NO_ROW, 0, 50, True, id="no-setting-row-without-version"),
    pytest.param(NO_ROW, 7, 0, True, id="no-setting-row"),
])
def test_an_error_settles_its_target_when_it_is_current(store, since, write_version, seconds,
                                                        done):
    store.errors.append((CD, "img", "run_ocr_and_store[tesseract]", write_version, seconds))
    assert (IMAGE_ENG in settled(store, CD, {IMAGE_ENG: since})) is done


def test_an_error_of_another_stage_or_engine_does_not_settle(store):
    store.errors.append((CD, "img", "run_ocr_pdf_and_store[tesseract]", 200_000_000, 200))
    store.errors.append((CD, "img", "run_ocr_and_store[easyocr]", 200_000_000, 200))
    assert settled(store, CD, {IMAGE_ENG: PRECISE}) == set()


def test_easyocr_without_an_endpoint_has_no_image_target(store, config):
    config["engines"] = {"tesseract", "easyocr"}
    store.add_image("img")
    assert {t.engine for t in targets_of(store, ["img"])} == {"tesseract", "easyocr"}
    config["engines"] = {"tesseract"}
    assert {t.engine for t in targets_of(store, ["img"])} == {"tesseract"}


def test_empty_languages_have_no_image_and_no_pdf_target(store, config):
    config["rows"]["ocr.tesseract.languages"] = ("", 100_100_000, True)
    config["rows"]["ocr.easyocr.languages"] = ("", 100_100_000, True)
    config["engines"] = {"tesseract", "easyocr"}
    store.add_image("img")
    store.add_pdf("doc")
    assert targets_of(store, ["img", "doc"]) == {}


# ---- PDF targets -----------------------------------------------------------------------

def test_a_pdf_with_a_pdfs_row_has_one_open_pdf_target(store, config):
    store.add_pdf("doc")
    assert open_targets(store, ["doc"]) == {PDF_ENG}


def test_a_tombstoned_searchable_pdf_leaves_the_target_open(store, config):
    store.add_pdf("doc")
    store.pdf_results.append((CD, "doc", "tesseract", "eng", 1, 0))
    assert open_targets(store, ["doc"]) == set()
    store.pdf_results.append((CD, "doc", "tesseract", "eng", 2, 1))
    assert open_targets(store, ["doc"]) == {PDF_ENG}


def test_a_pdf_without_a_pdfs_row_has_no_target(store, config):
    store.add_pdf("doc", pdfs_row=False)
    assert targets_of(store, ["doc"]) == {}


@pytest.mark.parametrize("change", ["provider-none", "builder-off"])
def test_no_pdf_target_without_a_provider_or_a_builder(store, config, change):
    if change == "provider-none":
        config["provider"] = []
    else:
        config["builder"] = False
    store.add_pdf("doc")
    assert targets_of(store, ["doc"]) == {}


# ---- routes ------------------------------------------------------------------------------

def test_a_mail_container_that_also_reads_as_an_image_has_no_target(store, config):
    store.plan_hits.append((CD, "pst", "p1"))
    store.file_types += [
        (CD, "pst", "file", ["application/vnd.ms-outlook"], [], ["email"], []),
        (CD, "pst", "magika", ["image/png"], [], ["image"], []),
    ]
    assert targets_of(store, ["pst"]) == {}


def test_an_authoritative_table_sniff_has_no_target(store, config):
    store.plan_hits.append((CD, "db", "p1"))
    store.file_types += [
        (CD, "db", "content_sniff", ["application/vnd.sqlite3"], [], ["table"], []),
        (CD, "db", "magika", ["image/png"], [], ["image"], []),
    ]
    assert targets_of(store, ["db"]) == {}


def test_an_item_with_no_detector_row_has_no_target(store, config):
    store.plan_hits.append((CD, "bare", "p1"))
    assert targets_of(store, ["bare"]) == {}


DETECTOR_SETS = [
    {"file": {"mime_types": ["image/png"], "coarse_types": ["image"]},
     "magika": {"mime_types": ["image/png"], "coarse_types": ["image"]}},
    {"file": {"mime_types": ["application/pdf"], "coarse_types": ["pdf"],
              "mime_encodings": ["binary"]},
     "extension": {"mime_types": ["application/pdf"], "coarse_types": ["pdf"],
                   "extensions": [".pdf"]}},
    {"file": {"mime_types": ["application/vnd.ms-outlook"], "coarse_types": ["email"]},
     "magika": {"mime_types": ["image/png"], "coarse_types": ["image"]}},
    {"content_sniff": {"mime_types": ["text/csv"], "coarse_types": ["table"]},
     "file": {"mime_types": ["text/plain"], "coarse_types": ["text"]},
     "extension": {"mime_types": ["text/csv"], "coarse_types": ["table"],
                   "extensions": [".csv"]}},
    {"file": {"mime_types": ["image/tiff"], "coarse_types": ["image"]},
     "magika": {"mime_types": ["application/pdf"], "coarse_types": ["pdf"]},
     "content_sniff": {"mime_types": [], "coarse_types": []}},
]


@pytest.mark.parametrize("detectors", DETECTOR_SETS)
def test_stored_routes_equal_the_routes_of_the_group_workflow(store, detectors):
    """The routes rebuilt from stored rows stay in step with ingestion's routing."""
    for name, result in detectors.items():
        store.file_types.append((CD, "f", name, result.get("mime_types", []),
                                 result.get("mime_encodings", []),
                                 result.get("coarse_types", []),
                                 result.get("extensions", [])))
    detect = FileResult(item_hash="f", task_name="detect_mime_all", status="ok",
                        value={"detectors": detectors, "errors": {}})
    combined = combine_detector_results(detector_results_for_file(detect))
    stored = ocr_targets.stored_routes(store, CD, ["f"])["f"]
    assert stored.routes == tuple(route_stages(combined))
    assert stored.mime_types == tuple(combined["mime_types"])
    assert set(detectors) <= set(LOCAL_DETECTORS)


# ---- index targets -----------------------------------------------------------------------

def with_text(store, versions=(5_300_000_000,)):
    store.add_image("img")
    store.raw.append((CD, "img", "tesseract", "eng", json.dumps({"text": "a page"})))
    for page, version in enumerate(versions, start=1):
        store.text.append((CD, "img", "ocr_tesseract_eng", page, "a page", version))


def test_ocr_text_without_an_index_row_opens_an_index_target(store, config):
    with_text(store)
    assert open_targets(store, ["img"]) == {INDEX}
    assert text_pending_index(store, CD, ["img"]) == ["img"]


def test_exact_receipts_settle_an_index_written_in_the_same_second(store):
    with_text(store)
    store.index_state.append((CD, "img"))
    store.receipts.append((CD, "img", "ocr_tesseract_eng", 1, 5_300_000_000, 5_000_001))
    assert settled(store, CD, {INDEX: NO_ROW}) == {INDEX}


def test_an_index_row_without_a_receipt_leaves_the_target_open(store):
    with_text(store)
    store.index_state.append((CD, "img"))
    assert settled(store, CD, {INDEX: NO_ROW}) == set()


@pytest.mark.parametrize("receipt", [None, 5_200_000_000])
def test_one_missing_or_stale_receipt_of_two_segments_leaves_the_target_open(store, receipt):
    with_text(store, versions=(5_300_000_000, 5_400_000_000))
    store.index_state.append((CD, "img"))
    store.receipts.append((CD, "img", "ocr_tesseract_eng", 1, 5_300_000_000, 1))
    if receipt:
        store.receipts.append((CD, "img", "ocr_tesseract_eng", 2, receipt, 2))
    assert settled(store, CD, {INDEX: NO_ROW}) == set()


def test_receipts_without_an_index_row_leave_the_target_open(store):
    with_text(store)
    store.receipts.append((CD, "img", "ocr_tesseract_eng", 1, 5_300_000_000, 1))
    assert settled(store, CD, {INDEX: NO_ROW}) == set()


@pytest.mark.parametrize(("write_version", "seconds", "done"), [
    pytest.param(5_300_001, 5, True, id="precise-error-after-the-text"),
    pytest.param(5_299_999, 5, False, id="precise-error-before-the-text"),
    pytest.param(0, 6, True, id="error-without-version-a-later-second"),
    pytest.param(0, 5, False, id="error-without-version-the-same-second"),
])
def test_a_text_page_error_newer_than_the_text_settles_the_index_target(
        store, write_version, seconds, done):
    with_text(store)
    store.errors.append((CD, "img", "P6_IndexTextPages", write_version, seconds))
    assert (INDEX in settled(store, CD, {INDEX: NO_ROW})) is done


def test_a_file_without_ocr_text_has_no_index_work(store):
    store.add_image("img")
    store.text.append((CD, "img", "tika", 1, "native text", 7))
    assert settled(store, CD, {INDEX: NO_ROW}) == {INDEX}
    assert text_pending_index(store, CD, ["img"]) == []


def test_every_hash_query_reads_at_most_500_hashes(store, config):
    items = [f"h{i:04d}" for i in range(1200)]
    for item in items:
        store.add_image(item)
    targets = targets_of(store, items)
    assert len(targets) == 1200
    settled(store, CD, targets)
    sizes = [len(p["h"]) for _, p in store.queries if "h" in p]
    assert sizes and max(sizes) <= 500
    assert sum(1 for _, p in store.queries if "h" in p and len(p["h"]) == 200) > 0


# ---- recovery of stored text -------------------------------------------------------------

def test_a_result_without_text_writes_its_text_and_opens_the_index_target(store, config):
    store.add_image("img")
    store.raw.append((CD, "img", "tesseract", "eng", json.dumps({"text": "harbour vessel"})))
    pairs = ocr_targets.current_pairs(ocr_targets.language_settings(CD))
    targets, recovered = ocr_rerun._plan_targets(store, COLLECTION, CD, ["img"], pairs)
    assert recovered == ["img"]
    assert [text for text, _ in store.current_text("img").values()] == ["harbour vessel"]
    assert set(targets) - settled(store, CD, targets) == {INDEX}


def test_matching_text_keeps_its_version_and_writes_nothing(store):
    store.raw.append((CD, "img", "tesseract", "eng", json.dumps({"text": " a page \n"})))
    store.text.append((CD, "img", "ocr_tesseract_eng", 1, "a page", 77))
    assert ocr_targets.recover_ocr_text(
        store, COLLECTION, CD, ["img"], [("tesseract", "eng")]) == []
    assert store.inserts == []
    assert store.current_text("img") == {("ocr_tesseract_eng", 1): ("a page", 77)}


def test_an_incomplete_source_is_written_again_once(store):
    big = "word " * 60_000   # two segments of 256 KiB
    store.raw.append((CD, "img", "tesseract", "eng", json.dumps({"text": big})))
    store.text.append((CD, "img", "ocr_tesseract_eng", 1, "a stale first segment", 1))
    store.text.append((CD, "img", "ocr_tesseract_eng", 3, "an obsolete segment", 1))
    assert ocr_targets.recover_ocr_text(
        store, COLLECTION, CD, ["img"], [("tesseract", "eng")]) == ["img"]
    assert [table for table, _, _ in store.inserts] == ["text_content"]
    from tasks.P3_parse_files.parse_common import stored_page_bodies, text_chunk_pages

    pages = store.current_text("img")
    expected = dict(stored_page_bodies(text_chunk_pages(big)))
    assert {page: text for (_, page), (text, _) in pages.items()} == expected
    assert sorted(expected) == [1, 2]


def test_an_empty_result_needs_no_text(store):
    store.raw.append((CD, "img", "tesseract", "eng", json.dumps({"text": "  "})))
    assert ocr_targets.recover_ocr_text(
        store, COLLECTION, CD, ["img"], [("tesseract", "eng")]) == []
    assert store.inserts == []
    assert text_pending_index(store, CD, ["img"]) == []


@pytest.mark.parametrize("payload", ['{"confidence": 3}', "not json", '{"text": null}'])
def test_a_payload_without_its_text_fails_and_keeps_the_result(store, payload):
    from temporalio.exceptions import ApplicationError

    store.raw.append((CD, "img", "tesseract", "eng", payload))
    with pytest.raises(ApplicationError) as failed:
        ocr_targets.recover_ocr_text(store, COLLECTION, CD, ["img"], [("tesseract", "eng")])
    assert failed.value.type == ocr_targets.OCR_TEXT_RECOVERY_FAILED
    assert failed.value.non_retryable
    assert len(store.raw) == 1 and store.inserts == []


def test_a_language_change_and_back_restores_the_text_without_ocr(store, config, monkeypatch):
    """A change from eng to eng+deu purges the eng text and keeps its raw result. The
    change back to eng finds the raw result, so the stage sends no OCR request, and the
    retained payload restores the text."""
    monkeypatch.setattr(ocr_client, "run_ocr",
                        lambda *a, **k: pytest.fail("an OCR request was sent"))
    store.add_image("img")
    store.raw.append((CD, "img", "tesseract", "eng", json.dumps({"text": "cargo manifest"})))
    store.raw.append((CD, "img", "tesseract", "eng+deu", json.dumps({"text": "cargo"})))
    store.text.append((CD, "img", "ocr_tesseract_eng+deu", 1, "cargo", 9))
    targets = targets_of(store, ["img"])
    assert store.current_text("img")[("ocr_tesseract_eng", 1)][0] == "cargo manifest"
    assert set(targets) - settled(store, CD, targets) == {INDEX}
    # The eng+deu text is not a variant of the current settings, so it is left alone.
    assert store.current_text("img")[("ocr_tesseract_eng+deu", 1)] == ("cargo", 9)


# ---- settings ------------------------------------------------------------------------------

def test_the_targets_read_the_latest_row_and_not_the_cache(monkeypatch, config):
    dataset_config._cache[CD] = (float("inf"), {"ocr.tesseract.languages": "deu"})
    try:
        settings = ocr_targets.language_settings(CD)
    finally:
        dataset_config.invalidate(CD)
    assert settings["tesseract"].value == "eng"
    assert settings["tesseract"].version == PRECISE


def test_a_deleted_or_absent_setting_gives_the_default_and_its_version(monkeypatch):
    rows = {"ocr.tesseract.languages": dataset_config.SettingRow("ron", True, 5, False)}
    monkeypatch.setattr(dataset_config, "latest_setting_rows", lambda _cd, keys: rows)
    settings = ocr_targets.language_settings(CD)
    assert settings["tesseract"] == ocr_targets.LanguageSetting(
        dataset_config.DEFAULTS["ocr.tesseract.languages"], SettingVersion(5, False))
    assert settings["easyocr"].version == NO_ROW
