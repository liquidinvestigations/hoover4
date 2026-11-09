"""Verify historical OCR reconciliation with real collection storage and counted OCR requests.

Each test seeds earlier OCR output into a new collection database, runs automatic OCR
execution, and counts the calls of the substituted OCR clients. These tests are the
upgrade acceptance cases of historical OCR reconciliation.
"""

import base64
import io
import json
import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from database import clickhouse
from tasks.P3_parse_files import automatic_ocr as automatic, ocr_detection
from tasks.P3_parse_files.batch_runner import BatchFile, StageBatchParams
from tasks.text_sources import ocr_extracted_by, pdf_ocr_extracted_by
from .test_table_publication_receipts import collection  # noqa: F401 -- pytest fixture

pytestmark = pytest.mark.integration

INSTALLED = {"tesseract": ["Latin", "deu", "eng", "fra"], "easyocr": ["de", "en", "fr"]}
GERMAN = "Guten Morgen liebe Leser dieser Seite"
FRENCH = "Bonjour chers lecteurs de cette page"
TINY = str(Path(__file__).resolve().parent.parent / "fixtures" / "tiny" / "tiny.pdf")
WORDS = [dict(text=word, left=10 * index, top=10, width=8, height=8, confidence=90)
         for index, word in enumerate(GERMAN.split())]


class Services:
    """Substituted detection and OCR clients that count every recognition request."""

    def __init__(self, monkeypatch, languages, searchable=False):
        from tasks import ocr_client, ocr_pdf_client
        self.languages = dict(languages)
        self.run_ocr, self.pdf_ocr, self.image_pdf = [], [], []
        self.fail_detection = False
        self.storage = None
        monkeypatch.setattr(automatic, "capabilities", lambda: INSTALLED)
        monkeypatch.setattr(ocr_detection, "engine_configured", lambda engine: True)
        monkeypatch.setattr(ocr_detection, "image_dimensions", lambda data: (500, 500))
        monkeypatch.setattr(ocr_detection, "read_image", lambda *args: b"image-1")
        monkeypatch.setattr(ocr_detection, "render_page", lambda path, page: f"image-{page}".encode())
        monkeypatch.setattr(ocr_detection, "detected_language", lambda model, text: text or "und")
        monkeypatch.setattr(ocr_detection, "detect_text", self.detect)
        monkeypatch.setattr(ocr_pdf_client, "service_configured", lambda: searchable)
        monkeypatch.setattr(ocr_client, "run_ocr", self.recognize)
        monkeypatch.setattr(ocr_pdf_client, "build_ocr_pdf", self.build)

    def detect(self, data):
        if self.fail_detection:
            raise RuntimeError("injected detection failure")
        page = int(data.decode().rsplit("-", 1)[-1])
        language = self.languages[page]
        if language is None:
            return dict(has_text=False)
        return dict(has_text=True, script="Latin", model="Latin", text="" if language == "und" else language)

    def recognize(self, engine, languages, data):
        self.run_ocr.append((engine, languages))
        text = f"Recognized {languages}"
        return SimpleNamespace(engine=engine, languages=languages, text=text,
                               raw_json=json.dumps(dict(text=text, words=[])))

    def build(self, **kwargs):
        from database.s3 import collection_bucket, get_s3_client
        storage = get_s3_client()
        if kwargs.get("mode") == "image":
            self.image_pdf.append((kwargs["engine"], kwargs["languages"], len(kwargs.get("words") or [])))
            data = Path(TINY).read_bytes()
            pages = []
        else:
            self.pdf_ocr.append((kwargs["engine"], kwargs["languages"], list(kwargs["ocr_pages"])))
            data = base64.b64decode(kwargs["source_b64"]) if kwargs.get("source_b64") else _read(storage,
                kwargs["source_bucket"], kwargs["source_key"])
            pages = [dict(page=page, text=f"Recognized {kwargs['languages']} page {page}") for page in kwargs["ocr_pages"]]
        bucket = collection_bucket(kwargs["collectionname"])
        storage.put_object(bucket, kwargs["dest_key"], io.BytesIO(data), len(data), content_type="application/pdf")
        return SimpleNamespace(engine=kwargs["engine"], languages=kwargs["languages"], dest_key=kwargs["dest_key"],
                               size_bytes=len(data), blob_hash="", pages=pages)

    @property
    def requests(self):
        return len(self.run_ocr) + len(self.pdf_ocr)


def _read(storage, bucket, key):
    payload = storage.get_object(bucket, key)
    try:
        return payload.read()
    finally:
        payload.close()
        payload.release_conn()


@pytest.fixture
def bucket(collection):
    from database.s3 import collection_bucket, get_s3_client
    storage, name = get_s3_client(), collection_bucket(collection)
    storage.make_bucket(name)
    try:
        yield name
    finally:
        for item in storage.list_objects(name, recursive=True):
            storage.remove_object(name, item.object_name)
        storage.remove_bucket(name)


def put_pdf(bucket, key, pages):
    """Store a PDF with `pages` copies of the fixture page. Return its size."""
    from database.s3 import get_s3_client
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "out.pdf")
        subprocess.run(["qpdf", "--empty", "--pages", *[value for _ in range(pages) for value in (TINY, "1")],
                        "--", path], check=True, capture_output=True)
        get_s3_client().fput_object(bucket, key, path, content_type="application/pdf")
        return os.path.getsize(path)


def text_rows(client, h="image"):
    return sorted(client.query("SELECT extracted_by, page_id, argMax(text, version) FROM text_content "
                               "WHERE file_hash = {h:String} GROUP BY extracted_by, page_id", parameters={"h": h}).result_rows)


def published_plan(client, h="image"):
    rows = client.query("SELECT plan_json, state FROM automatic_ocr_plans FINAL WHERE hash = {h:String} "
                        "AND state IN ('published', 'applied')", parameters={"h": h}).result_rows
    assert len(rows) == 1
    return json.loads(rows[0][0])


def seed_image(client, raws, texts=()):
    client.insert("vfs_files", [["dataset", "", "/source.png", "image"]],
                  column_names=["collection_dataset", "container_hash", "path", "hash"])
    client.insert("image", [["dataset", "image", 500, 500, ""]],
                  column_names=["collection_dataset", "image_hash", "width_pixels", "height_pixels", "image_metadata"])
    for engine, languages, text, words in raws:
        client.insert("raw_ocr_results", [["dataset", "image", engine, languages, 0.9, 1, "",
                      json.dumps(dict(text=text, words=words, engine=engine, languages=languages))]],
                      column_names=["collection_dataset", "image_hash", "engine", "languages", "confidence",
                                    "run_time_ms", "result_hash", "raw_json"])
    for extracted_by, text in texts:
        client.insert("text_content", [["dataset", "image", extracted_by, 1, text, len(text), 1]],
                      column_names=["collection_dataset", "file_hash", "extracted_by", "page_id", "text", "text_bytes", "version"])


def image_scope(collection, tmp_path, op="operation"):
    path = tmp_path / "source.png"
    path.write_bytes(b"image")
    file = BatchFile("image", str(path), routes=["image"])
    return StageBatchParams(collection, "dataset", "plan", [file], op), file


def test_matching_image_keeps_its_text_under_the_detected_language(collection, tmp_path, monkeypatch):
    services = Services(monkeypatch, {1: "de"})
    old = ocr_extracted_by("tesseract", "eng+deu")
    with clickhouse.get_collection_client(collection) as client:
        seed_image(client, [("tesseract", "eng+deu", GERMAN, [])], [(old, GERMAN)])
    scope, file = image_scope(collection, tmp_path)
    automatic.execute_file(scope, file)
    assert services.requests == 0
    with clickhouse.get_collection_client(collection) as client:
        assert text_rows(client) == [(ocr_extracted_by("tesseract", "deu"), 1, GERMAN)]
        page = published_plan(client)["pages"][0]
        assert page["passes"] == [] and page["adopted"][0]["original_languages"] == "eng+deu"
        assert page["adopted"][0]["reason"] == "detected_language_superset"
        assert client.query("SELECT count() FROM raw_ocr_results").result_rows[0][0] == 1


def test_wrong_language_image_is_replaced_by_new_ocr(collection, tmp_path, monkeypatch):
    services = Services(monkeypatch, {1: "fr"})
    with clickhouse.get_collection_client(collection) as client:
        seed_image(client, [("tesseract", "eng+deu", GERMAN, [])], [(ocr_extracted_by("tesseract", "eng+deu"), GERMAN)])
    scope, file = image_scope(collection, tmp_path)
    automatic.execute_file(scope, file)
    assert services.run_ocr == [("tesseract", "fra")]
    with clickhouse.get_collection_client(collection) as client:
        assert text_rows(client) == [(ocr_extracted_by("tesseract", "fra"), 1, "Recognized fra")]
        assert published_plan(client)["pages"][0]["recovery"]["action"] == "new_ocr"


def test_both_engines_keep_their_results(collection, tmp_path, monkeypatch):
    services = Services(monkeypatch, {1: "en"})
    with clickhouse.get_collection_client(collection) as client:
        seed_image(client, [("tesseract", "eng", "Tesseract English text", []), ("easyocr", "en", "EasyOCR English text", [])])
    scope, file = image_scope(collection, tmp_path)
    automatic.execute_file(scope, file)
    assert services.requests == 0
    with clickhouse.get_collection_client(collection) as client:
        assert text_rows(client) == [(ocr_extracted_by("easyocr", "en"), 1, "EasyOCR English text"),
                                     (ocr_extracted_by("tesseract", "eng"), 1, "Tesseract English text")]


def test_candidate_choice_is_deterministic_and_keeps_duplicates(collection, tmp_path, monkeypatch):
    from tasks.automatic_ocr import make_plan
    from tasks.P3_parse_files.ocr_reconciliation import reconcile_plan
    services = Services(monkeypatch, {1: "de"})
    with clickhouse.get_collection_client(collection) as client:
        seed_image(client, [("tesseract", "eng+deu", "Superset German text here", []), ("tesseract", "deu", GERMAN, [])])
    scope, file = image_scope(collection, tmp_path)
    ocr_detection._detect_file(scope, file)
    digests = []
    with clickhouse.get_collection_client(collection) as client:
        rows = automatic.detection_rows(client, "dataset", "image", "image")
        for _ in range(2):
            plan = reconcile_plan(client, scope, file, "image", make_plan("dataset", "image", "image", "image", rows, INSTALLED, 1), [(1, 1)])
            digests.append(plan["plan_digest"])
    assert digests[0] == digests[1]
    page = plan["pages"][0]
    assert [item["original_languages"] for item in page["adopted"]] == ["deu"]
    assert len(plan["reconciliation_diagnostics"]["pages"]["1"]["duplicates"]) == 1
    automatic.execute_file(scope, file)
    assert services.requests == 0
    with clickhouse.get_collection_client(collection) as client:
        assert text_rows(client) == [(ocr_extracted_by("tesseract", "deu"), 1, GERMAN)]


def test_unknown_language_keeps_the_original_identity(collection, tmp_path, monkeypatch):
    services = Services(monkeypatch, {1: "und"})
    with clickhouse.get_collection_client(collection) as client:
        seed_image(client, [("tesseract", "eng+deu", GERMAN, [])])
    scope, file = image_scope(collection, tmp_path)
    automatic.execute_file(scope, file)
    assert services.requests == 0
    with clickhouse.get_collection_client(collection) as client:
        assert text_rows(client) == [(ocr_extracted_by("tesseract", "eng+deu"), 1, GERMAN)]
        assert published_plan(client)["pages"][0]["adopted"][0]["reason"] == "unknown_language_retained"


def test_no_text_detection_replaces_historical_text(collection, tmp_path, monkeypatch):
    from tasks.P6_index_data.activities import document_ocr_presence
    services = Services(monkeypatch, {1: None})
    with clickhouse.get_collection_client(collection) as client:
        seed_image(client, [("tesseract", "eng", "Old English text", [])], [(ocr_extracted_by("tesseract", "eng"), "Old English text")])
    scope, file = image_scope(collection, tmp_path)
    automatic.execute_file(scope, file)
    assert services.requests == 0
    with clickhouse.get_collection_client(collection) as client:
        assert text_rows(client) == []
        assert document_ocr_presence(client, "dataset", ["image"]) == {"image": 1}
        assert published_plan(client)["pages"][0]["recovery"]["action"] == "no_text_replace"
        assert client.query("SELECT count() FROM raw_ocr_results").result_rows[0][0] == 1


def test_failed_detection_keeps_the_earlier_output(collection, tmp_path, monkeypatch):
    services = Services(monkeypatch, {1: "de"})
    services.fail_detection = True
    old = ocr_extracted_by("tesseract", "eng+deu")
    with clickhouse.get_collection_client(collection) as client:
        seed_image(client, [("tesseract", "eng+deu", GERMAN, [])], [(old, GERMAN)])
    scope, file = image_scope(collection, tmp_path)
    with pytest.raises(Exception):
        automatic.execute_file(scope, file)
    assert services.requests == 0
    with clickhouse.get_collection_client(collection) as client:
        assert text_rows(client) == [(old, 1, GERMAN)]
        assert client.query("SELECT count() FROM automatic_ocr_plans FINAL WHERE state IN ('published', 'applied')").result_rows[0][0] == 0


def test_image_pdf_is_rebuilt_from_word_boxes_without_ocr(collection, bucket, tmp_path, monkeypatch):
    services = Services(monkeypatch, {1: "de"}, searchable=True)
    with clickhouse.get_collection_client(collection) as client:
        seed_image(client, [("tesseract", "eng+deu", GERMAN, WORDS)])
    scope, file = image_scope(collection, tmp_path)
    automatic.execute_file(scope, file)
    assert services.requests == 0
    assert services.image_pdf == [("tesseract", "deu", len(WORDS))]
    with clickhouse.get_collection_client(collection) as client:
        rows = client.query("SELECT engine, languages, blob_key FROM pdf_ocr_results FINAL WHERE is_deleted = 0").result_rows
        assert [(engine, languages) for engine, languages, _ in rows] == [("tesseract", "deu")]
        assert rows[0][2].endswith("tesseract+deu.reconciled.pdf")


@pytest.mark.parametrize("problem", ["missing", "truncated", "wrong_owner"])
def test_unusable_artifact_fails_and_keeps_the_earlier_output(collection, bucket, tmp_path, monkeypatch, problem):
    from temporalio.exceptions import ApplicationError
    from tasks.P3_parse_files.pdf_parts import write_row
    services = Services(monkeypatch, {1: "en"}, searchable=True)
    key = "derived/ocr-pdf/dataset/image/tesseract+eng.pdf" if problem != "wrong_owner" else "derived/ocr-pdf/other/x.pdf"
    size = 0 if problem == "missing" else put_pdf(bucket, key, 1)
    old = ocr_extracted_by("tesseract", "eng")
    with clickhouse.get_collection_client(collection) as client:
        seed_image(client, [("tesseract", "eng", "English words for a searchable image", [])], [(old, "English words for a searchable image")])
        write_row(client, "pdf_ocr_results", dict(collection_dataset="dataset", pdf_hash="image", engine="tesseract",
            languages="eng", source_kind="image", form="raster", blob_key=key, blob_hash="", page_count=1,
            size_bytes=size + (5 if problem == "truncated" else 0) or 10, run_time_ms=0, part_count=1, text_complete=1))
    scope, file = image_scope(collection, tmp_path)
    with pytest.raises(ApplicationError) as raised:
        automatic.execute_file(scope, file)
    assert raised.value.type == "OcrRecoveryUnresolved"
    assert services.requests == 0 and services.image_pdf == []
    with clickhouse.get_collection_client(collection) as client:
        assert text_rows(client) == [(old, 1, "English words for a searchable image")]


def seed_pdf(client, bucket, texts, languages="eng+deu", raster=False):
    """A two-page original PDF with earlier OCR of every page in one stored part."""
    from tasks.P3_parse_files.pdf_parts import write_row
    from tasks.text_sources import OCR_PAGE_RULE_VERSION
    client.insert("vfs_files", [["dataset", "", "/source.pdf", "pdf"]],
                  column_names=["collection_dataset", "container_hash", "path", "hash"])
    write_row(client, "ocr_page_needs", dict(collection_dataset="dataset", hash="pdf", source_kind="original",
              page_count=2, ocr_pages=[1, 2], rule_version=OCR_PAGE_RULE_VERSION))
    write_row(client, "pdf_parts", dict(collection_dataset="dataset", hash="pdf", source_kind="original",
              segmentation=1, part_index=1, first_page=1, last_page=2, s3_path="", size_bytes=1))
    key = f"derived/ocr-pdf/dataset/pdf/tesseract+{languages}.pdf"
    size = put_pdf(bucket, key, 2)
    write_row(client, "pdf_ocr_results", dict(collection_dataset="dataset", pdf_hash="pdf", engine="tesseract",
        languages=languages, source_kind="original", form="raster" if raster else "overlay", blob_key=key, blob_hash="",
        page_count=2, size_bytes=size, run_time_ms=0, part_count=1, text_complete=1))
    if not raster:
        write_row(client, "pdf_ocr_parts", dict(collection_dataset="dataset", hash="pdf", source_kind="original",
            engine="tesseract", languages=languages, segmentation=1, part_index=1, first_page=1, last_page=2,
            blob_key=key, size_bytes=size, page_numbers=[1, 2], page_texts=list(texts), borrows_source=0, text_layer=2))
    old = pdf_ocr_extracted_by("tesseract", languages)
    client.insert("text_content", [["dataset", "pdf", old, 1, "\f".join(texts), 10, 1]],
                  column_names=["collection_dataset", "file_hash", "extracted_by", "page_id", "text", "text_bytes", "version"])
    return key


def pdf_scope(collection, tmp_path, op="operation"):
    source = tmp_path / "source.pdf"
    subprocess.run(["qpdf", "--empty", "--pages", TINY, "1", TINY, "1", "--", str(source)], check=True, capture_output=True)
    file = BatchFile("pdf", str(source), source_kind="original")
    return StageBatchParams(collection, "dataset", "plan", [file], op), file


def npages(bucket, key):
    from database.s3 import get_s3_client
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "p.pdf")
        get_s3_client().fget_object(bucket, key, path)
        return int(subprocess.run(["qpdf", "--show-npages", path], capture_output=True, check=True).stdout)


def assert_mixed_result(client, bucket):
    rows = text_rows(client, "pdf")
    assert [(source, page) for source, page, _ in rows] == [(pdf_ocr_extracted_by("tesseract", "deu"), 1),
                                                            (pdf_ocr_extracted_by("tesseract", "fra"), 1)]
    assert GERMAN in rows[0][2] and FRENCH not in rows[0][2]
    assert "Recognized fra page 2" in rows[1][2] and GERMAN not in rows[1][2]
    parts = client.query("SELECT languages, blob_key, page_numbers FROM pdf_ocr_parts FINAL WHERE is_deleted = 0 "
                         "ORDER BY languages").result_rows
    assert [(languages, list(pages)) for languages, _, pages in parts] == [("deu", [1]), ("fra", [2])]
    assert parts[0][1].endswith("/tesseract+deu/1.reconciled.pdf")
    for _, key, _ in parts:
        assert npages(bucket, key) == 2
    assert client.query("SELECT languages FROM pdf_ocr_results FINAL WHERE is_deleted = 0 ORDER BY languages").result_rows == [
        ("deu",), ("fra",)]


def test_mixed_language_pdf_requests_ocr_only_for_the_incompatible_page(collection, bucket, tmp_path, monkeypatch):
    services = Services(monkeypatch, {1: "de", 2: "fr"}, searchable=True)
    with clickhouse.get_collection_client(collection) as client:
        seed_pdf(client, bucket, [GERMAN, FRENCH])
    scope, file = pdf_scope(collection, tmp_path)
    automatic.execute_file(scope, file)
    assert services.pdf_ocr == [("tesseract", "fra", [2])] and services.run_ocr == []
    with clickhouse.get_collection_client(collection) as client:
        assert_mixed_result(client, bucket)


@pytest.mark.parametrize("fault", ["adoption", "publication"])
def test_restart_repeats_no_completed_ocr(collection, bucket, tmp_path, monkeypatch, fault):
    from tasks.P3_parse_files import ocr_reconciliation
    services = Services(monkeypatch, {1: "de", 2: "fr"}, searchable=True)
    with clickhouse.get_collection_client(collection) as client:
        seed_pdf(client, bucket, [GERMAN, FRENCH])
    scope, file = pdf_scope(collection, tmp_path)
    target = (ocr_reconciliation, "assemble_part") if fault == "adoption" else (automatic, "supersede_prior_plans")
    original, failures = getattr(*target), []

    def interrupted(*args, **kwargs):
        if not failures:
            failures.append(1)
            raise RuntimeError("injected interruption")
        return original(*args, **kwargs)
    monkeypatch.setattr(*target, interrupted)
    with pytest.raises(RuntimeError, match="injected interruption"):
        automatic.execute_file(scope, file)
    with clickhouse.get_collection_client(collection) as client:
        before = text_rows(client, "pdf")
    if fault == "adoption":
        assert before == [(pdf_ocr_extracted_by("tesseract", "eng+deu"), 1, f"{GERMAN}\f{FRENCH}")]
    first = automatic.execute_file(scope, file)
    assert automatic.execute_file(scope, file) == first
    assert services.pdf_ocr == [("tesseract", "fra", [2])]
    with clickhouse.get_collection_client(collection) as client:
        assert_mixed_result(client, bucket)


def test_raster_pdf_keeps_physical_pages_without_ocr(collection, bucket, tmp_path, monkeypatch):
    services = Services(monkeypatch, {1: "en", 2: "en"}, searchable=True)
    with clickhouse.get_collection_client(collection) as client:
        key = seed_pdf(client, bucket, [], languages="eng", raster=True)
    scope, file = pdf_scope(collection, tmp_path)
    automatic.execute_file(scope, file)
    assert services.requests == 0
    with clickhouse.get_collection_client(collection) as client:
        rows = text_rows(client, "pdf")
        assert [(source, page) for source, page, _ in rows] == [(pdf_ocr_extracted_by("tesseract", "eng"), 1)]
        assert rows[0][2].count("zanzibar") == 2
        assert client.query("SELECT blob_key, page_numbers FROM pdf_ocr_parts FINAL WHERE is_deleted = 0").result_rows == [
            (key, [1, 2])]


def test_older_claim_cannot_overwrite_a_later_publication(collection, tmp_path, monkeypatch):
    services = Services(monkeypatch, {1: "fr"})
    with clickhouse.get_collection_client(collection) as client:
        seed_image(client, [("tesseract", "eng", "Old English text", [])])
    older, file = image_scope(collection, tmp_path, "older")
    recognize = services.recognize
    from tasks import ocr_client
    monkeypatch.setattr(ocr_client, "run_ocr", lambda *args: (_ for _ in ()).throw(RuntimeError("injected OCR outage")))
    with pytest.raises(RuntimeError, match="injected OCR outage"):
        automatic.execute_file(older, file)
    monkeypatch.setattr(ocr_client, "run_ocr", recognize)
    monkeypatch.setattr(automatic, "capabilities", lambda: dict(INSTALLED, tesseract=INSTALLED["tesseract"] + ["ita"]))
    newer, _ = image_scope(collection, tmp_path, "newer")
    automatic.execute_file(newer, file)
    with pytest.raises(Exception, match="later automatic OCR plan is already published"):
        automatic.execute_file(older, file)
    assert services.run_ocr == [("tesseract", "fra")]
    with clickhouse.get_collection_client(collection) as client:
        assert text_rows(client) == [(ocr_extracted_by("tesseract", "fra"), 1, "Recognized fra")]


def test_second_update_selects_nothing_and_a_stage_change_rejects_stale_adoption(collection, tmp_path, monkeypatch):
    from tasks import stage_versions
    from tasks.P_admin import automatic_ocr as admin
    services = Services(monkeypatch, {1: "de"})
    monkeypatch.setattr(admin, "capabilities", lambda: INSTALLED)
    with clickhouse.get_collection_client(collection) as client:
        seed_image(client, [("tesseract", "eng+deu", GERMAN, [])])
    scope, file = image_scope(collection, tmp_path)
    automatic.execute_file(scope, file)
    with clickhouse.get_collection_client(collection) as client:
        plan = published_plan(client)
        automatic.write_plan(client, plan, "applied", presence=1)
        assert client.query(admin.hash_sql(), parameters={"cd": "dataset", **admin.target()}).result_rows == []
    again, _ = image_scope(collection, tmp_path, "second")
    automatic.execute_file(again, file)
    assert services.requests == 0
    with clickhouse.get_collection_client(collection) as client:
        automatic.write_plan(client, published_plan(client), "applied", presence=1)
    monkeypatch.setitem(stage_versions.STAGE_VERSIONS, "ocr_image", stage_versions.STAGE_VERSIONS["ocr_image"] + 1)
    with clickhouse.get_collection_client(collection) as client:
        assert client.query(admin.hash_sql(), parameters={"cd": "dataset", **admin.target()}).result_rows == [("image",)]
    later, _ = image_scope(collection, tmp_path, "stage-change")
    automatic.execute_file(later, file)
    assert services.run_ocr == [("tesseract", "deu")]
    with clickhouse.get_collection_client(collection) as client:
        assert text_rows(client) == [(ocr_extracted_by("tesseract", "deu"), 1, "Recognized deu")]
