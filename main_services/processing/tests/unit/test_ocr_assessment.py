"""Run the read-only OCR assessment over a fake collection and record every boundary call."""

import json
import re
from types import SimpleNamespace

import pytest

from tasks import ocr_recovery as r
from tasks.P_admin import ocr_assessment as a

CD = "c_ds"
IMAGE, PDF, PREVIEW = "a" * 64, "b" * 64, "c" * 64
CAPS = dict(tesseract=["eng", "deu", "fra", "Latin"], easyocr=["en", "de"])
WORDS = "Der schnelle braune Fuchs springt hoch"
ALL_COLUMNS = {
    "vfs_files": [], "blobs": [], "image": [], "pdf_metadata": ["defect"], "pdf_previews": [], "pdf_parts": [],
    "ocr_page_needs": [], "ocr_detection": ["model"], "processing_errors": [], "raw_ocr_results": [],
    "pdf_ocr_results": ["source_kind", "form", "part_count", "text_complete"], "pdf_ocr_parts": ["text_layer"],
    "automatic_ocr_plans": [], "automatic_ocr_output": [], "text_content": []}


class FakeClient:
    """Answer each tagged assessment query from fixture rows. Fail on any write."""

    def __init__(self, tables=None):
        self.tables = dict(ALL_COLUMNS if tables is None else tables)
        self.queries = []
        self.rows = {
            "datasets": [(CD,)],
            "images": [(IMAGE,)], "previews": [(PREVIEW,)],
            "sizes": [(IMAGE, 100), (PDF, 2000), (PREVIEW, 300)],
            "needs": [(PDF, "original", 2, [1, 2]), (PREVIEW, "preview", 1, [1])],
            "parts": [(PDF, "original", 1, 1, 2, f"s3://c/{PDF}", 2000), (PREVIEW, "preview", 1, 1, 1, "s3://c/p", 300)],
            "detection": [(IMAGE, "image", 1, 4, 1, "Latin", "de", "Latin"),
                          (PDF, "original", 1, 4, 1, "Latin", "de", "Latin"),
                          (PDF, "original", 2, 4, 1, "Latin", "fr", "Latin")],
            "errors": [(PREVIEW,)],
            "raw": [(IMAGE, "tesseract", "eng+deu", json.dumps(dict(engine="tesseract", languages="eng+deu", text=WORDS,
                                                                     words=[dict(text="Der")]))),
                    (IMAGE, "easyocr", "en", json.dumps(dict(engine="easyocr", languages="en", text=WORDS, words=[])))],
            "results": [(PDF, "tesseract", "eng+deu", (f"derived/ocr-pdf/{CD}/{PDF}/x.pdf", 50, 2, "original", "overlay",
                                                        1, 1, 0)),
                        (PREVIEW, "tesseract", "eng", (f"derived/ocr-pdf/{CD}/{PREVIEW}/eng.pdf", 40, 1, "preview",
                                                        "raster", 1, 0, 1))],
            "ocr_parts": [(PDF, "original", "tesseract", "eng+deu", 1, 1,
                           (1, 2, f"derived/ocr-pdf/{CD}/{PDF}/x.pdf", 50, [1, 2], [WORDS, "Le renard"], 0, 2, 0)),
                          (PDF, "preview", "tesseract", "deu", 1, 1,
                           (1, 1, f"derived/ocr-pdf/{CD}/{PDF}/p.pdf", 50, [1], [WORDS], 0, 2, 0))],
            "plans": [], "outputs": [], "published": [(PDF, ["pdfocr_tesseract_eng+deu"])],
        }

    def query(self, sql, parameters=None):
        self.queries.append(sql)
        tag = re.match(r"\s*/\* (\w+) \*/", sql).group(1)
        if tag == "schema":
            return SimpleNamespace(result_rows=[(table, column) for table, columns in self.tables.items()
                                                for column in (columns or ["x"])])
        if tag == "files":
            after = parameters["after"]
            return SimpleNamespace(result_rows=[(h,) for h in sorted([IMAGE, PDF, PREVIEW]) if h > after][:parameters["n"]])
        return SimpleNamespace(result_rows=self.rows.get(tag, []))

    def command(self, *args, **kwargs):
        raise AssertionError("the assessment wrote to ClickHouse")

    insert = insert_arrow = insert_df = command


class FakeObjects:
    def __init__(self, sizes):
        self.sizes, self.stats, self.downloads = sizes, [], []

    def stat_object(self, bucket, key):
        self.stats.append(key)
        if key not in self.sizes:
            raise type("S3Error", (Exception,), {"code": "NoSuchKey"})()
        return SimpleNamespace(size=self.sizes[key])

    def fget_object(self, bucket, key, path):
        self.downloads.append(path)
        open(path, "wb").close()

    def fput_object(self, *args, **kwargs):
        raise AssertionError("the assessment wrote an object")

    remove_object = put_object = fput_object


@pytest.fixture
def boundaries(monkeypatch):
    """Fail on every write and inference boundary that the pipeline can reach."""
    calls = []

    def refuse(name):
        def call(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"the assessment called {name}")
        return call

    from database import clickhouse
    from tasks import ocr_client, ocr_pdf_client
    from tasks.P3_parse_files import automatic_ocr, ocr_detection, pdf_parts, table_generations
    from tasks.P_ops import cli
    for module, name in [(clickhouse, "insert_durable"), (clickhouse, "insert_arrow_durable"),
                         (clickhouse, "insert_parser_arrow"), (table_generations, "send_command"),
                         (ocr_client, "run_ocr"), (ocr_client, "detect_text"), (ocr_detection, "detect_text"),
                         (ocr_detection, "store_rows"), (ocr_pdf_client, "build_ocr_pdf"), (automatic_ocr, "write_plan"),
                         (automatic_ocr, "save_output"), (pdf_parts, "write_row"), (pdf_parts, "write_rows"),
                         (cli, "submit_operation")]:
        monkeypatch.setattr(module, name, refuse(name))
    monkeypatch.setattr(ocr_pdf_client, "service_configured", lambda: True)
    monkeypatch.setattr("database.s3.collection_bucket", lambda name: "c")
    return calls


def run(client, objects=None, **options):
    return a.assess("c", [CD], capabilities=CAPS, client=client, objects=objects, **options)


def test_assessment_counts_actions_without_any_write(boundaries):
    client = FakeClient()
    objects = FakeObjects({f"derived/ocr-pdf/{CD}/{PDF}/x.pdf": 50})
    report = run(client, objects, check_objects=10)
    assert boundaries == []
    assert all(re.match(r"\s*/\* \w+ \*/ (SELECT|WITH)", sql) for sql in client.queries)
    assert report["files"]["total"] == 3 and report["complete"]
    assert report["files"]["by_action"] == {"new_ocr": 1, "require_detection": 1, "reuse_text": 1}
    assert report["pages"]["by_action"] == {"new_ocr": 1, "require_detection": 1, "reuse_text": 2}
    assert report["pages"]["by_reason"]["require_detection:detection_failed"] == 1
    assert report["overlapping"]["pages_pdf_from_word_boxes"] == 1
    assert "pages_with_several_engines_accepted" not in report["overlapping"]
    assert report["files"]["bytes_by_action"]["new_ocr"] == 2000
    assert objects.stats == [f"derived/ocr-pdf/{CD}/{PDF}/x.pdf"]
    sample = report["samples"]["reuse_text:detected_language_superset"][0]
    assert sample["accepted"][0]["canonical"] == "deu" and "text" not in json.dumps(sample["accepted"]).lower().replace(
        "text_publication", "")


def test_preview_parts_cannot_supply_the_original(boundaries):
    report = run(FakeClient())
    assert report["rejected"] == {"source_kind_mismatch": 1}


def test_missing_artifact_is_reported_without_repair(boundaries):
    objects = FakeObjects({})
    report = run(FakeClient(), objects, check_objects=10)
    assert report["missing_evidence"] == {"artifact_missing": 1}
    assert report["files"]["by_action"]["unresolved"] == 1


def test_truncated_and_wrongly_owned_artifacts_are_reported(boundaries):
    client = FakeClient()
    report = run(client, FakeObjects({f"derived/ocr-pdf/{CD}/{PDF}/x.pdf": 7}), check_objects=10)
    assert report["missing_evidence"] == {"artifact_truncated": 1}
    client.rows["ocr_parts"][0] = client.rows["ocr_parts"][0][:6] + (
        (1, 2, "derived/ocr-pdf/other/x.pdf", 50, [1, 2], [WORDS, "Le renard"], 0, 2, 0),)
    report = run(client, FakeObjects({}), check_objects=10)
    assert report["missing_evidence"] == {"artifact_wrong_owner": 1}


def test_raster_reads_stay_in_the_temporary_folder(boundaries, monkeypatch):
    from tasks.P3_parse_files import parse_pdf
    monkeypatch.setattr(parse_pdf, "_qpdf_show_npages", lambda path, name: 1)
    monkeypatch.setattr(parse_pdf, "_pdftotext_pages", lambda path: ["Saved raster text"])
    objects = FakeObjects({})
    report = run(FakeClient(), objects, read_raster=1)
    assert len(objects.downloads) == 1 and "hoover4-ocr-assessment-" in objects.downloads[0]
    assert report["raster_reads"] == 1
    guarded = a.ReadOnlyObjects(objects, "/tmp/somewhere")
    with pytest.raises(PermissionError):
        guarded.fget_object("c", "k", "/tmp/elsewhere/x.pdf")


def test_historical_schema_without_later_tables_and_columns(boundaries):
    tables = {name: [] for name in ("vfs_files", "blobs", "image", "pdf_metadata", "pdf_previews", "raw_ocr_results",
                                    "pdf_ocr_results", "text_content")}
    client = FakeClient(tables)
    report = run(client)
    assert report["schema"]["ocr_detection"] == "missing"
    assert report["schema"]["pdf_ocr_results"] == ["form", "part_count", "source_kind", "text_complete"]
    assert report["pages"]["by_reason"]["require_detection:detection_missing"] == 1
    assert report["files"]["by_reason"]["require_detection:source_not_prepared"] == 2
    assert report["unknown"]["files_without_page_identity"] == 2
    results = next(sql for sql in client.queries if "/* results */" in sql)
    assert "'raster' AS form" in results and "'original' AS source_kind" in results
    assert not any("/* detection */" in sql or "/* plans */" in sql for sql in client.queries)


def test_pagination_is_bounded_and_resumable(boundaries):
    first = run(FakeClient(), page_size=1, max_files=2)
    assert first["files_examined"] == 2 and not first["complete"]
    assert first["scopes"][0]["next_after"] == PDF
    rest = run(FakeClient(), after=first["scopes"][0]["next_after"])
    assert rest["files_examined"] == 1 and rest["complete"]


def test_shuffled_rows_give_the_same_report(boundaries):
    client = FakeClient()
    first = run(client)
    for key in ("raw", "ocr_parts", "detection", "results"):
        client.rows[key] = list(reversed(client.rows[key]))
    assert run(client) == first


def test_read_only_client_refuses_statements_other_than_select():
    guarded = a.ReadOnlyClient(FakeClient())
    for sql in ("INSERT INTO t VALUES (1)", "/* x */ ALTER TABLE t DELETE WHERE 1", "DELETE FROM t WHERE 1"):
        with pytest.raises(PermissionError):
            guarded.query(sql)


def test_applied_automatic_plan_is_current_in_both_contracts(boundaries):
    from tasks.automatic_ocr import make_plan
    client = FakeClient()
    found = dict(page_id=1, has_text=1, script="Latin", language="de", detector_version=4, model="Latin")
    plan = make_plan(CD, IMAGE, IMAGE, "image", [found], CAPS, 1)
    client.rows["plans"] = [(IMAGE, plan["plan_digest"], "applied", plan["policy_version"], plan["capability_digest"],
                             IMAGE, json.dumps(plan), 5)]
    client.rows["outputs"] = [(IMAGE, plan["plan_digest"], "o1", json.dumps(dict(
        engine="tesseract", languages="deu", pages=[[1, WORDS]], raw_json=json.dumps(dict(words=[])))))]
    for contract in ("upgrade", "current"):
        report = run(client, contract=contract)
        assert report["pages"]["by_reason"][f"keep_current:applied_{'pass_matches_plan' if contract == 'upgrade' else 'plan_current'}"] == 1
        assert report["overlapping"]["pages_with_retired_compatible_history"] == 1
