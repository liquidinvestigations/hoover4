"""Verify automatic plan publication with real collection storage and substituted OCR transport."""

import json
from types import SimpleNamespace

import pytest

from database import clickhouse
from tasks.P3_parse_files import automatic_ocr as automatic, ocr_detection
from tasks.P3_parse_files.batch_runner import BatchFile, StageBatchParams
from tasks.P3_parse_files.table_generations import send_command as transport_send_command
from tasks.P6_index_data.activities import document_ocr_presence
from .test_table_publication_receipts import collection
from .test_archive_and_index_publication import search_collection

pytestmark = pytest.mark.integration


def seed(client, h="image"):
    client.insert("vfs_files", [["dataset", "", "/source.png", h]],
                  column_names=["collection_dataset", "container_hash", "path", "hash"])
    client.insert("text_content", [["dataset", h, "ocr_easyocr_en", 1, "Prior OCR text", 14, 1]],
                  column_names=["collection_dataset", "file_hash", "extracted_by", "page_id", "text", "text_bytes", "version"])


def image_scope(collection, tmp_path):
    path = tmp_path / "source.png"
    path.write_bytes(b"image")
    file = BatchFile("image", str(path), routes=["image"])
    return StageBatchParams(collection, "dataset", "plan", [file], "operation"), file


def services(monkeypatch):
    from tasks import ocr_client, ocr_pdf_client
    monkeypatch.setattr(automatic, "capabilities", lambda: {"tesseract": ["eng", "Latin"], "easyocr": ["en"]})
    monkeypatch.setattr(ocr_detection, "engine_configured", lambda engine: True)
    monkeypatch.setattr(ocr_detection, "image_dimensions", lambda data: (500, 500))
    monkeypatch.setattr(ocr_detection, "read_image", lambda *args: b"image")
    monkeypatch.setattr(ocr_detection, "detect_text", lambda data: dict(has_text=True, script="Latin", model="Latin", text=""))
    monkeypatch.setattr(ocr_pdf_client, "service_configured", lambda: False)
    calls = []
    def run(engine, languages, data):
        calls.append((engine, languages))
        return SimpleNamespace(engine=engine, languages=languages, text="Current OCR replacement", raw_json='{"text":"Current OCR replacement","words":[]}')
    monkeypatch.setattr(ocr_client, "run_ocr", run)
    return calls


def test_publication_replaces_old_variants_and_retry_reuses_staged_output(collection, tmp_path, monkeypatch):
    calls = services(monkeypatch)
    scope, file = image_scope(collection, tmp_path)
    with clickhouse.get_collection_client(collection) as client:
        seed(client)
        assert document_ocr_presence(client, "dataset", ["image"]) == {}
    original = automatic.publish
    attempts = []
    def interrupted(*args):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("injected before publication")
        return original(*args)
    monkeypatch.setattr(automatic, "publish", interrupted)
    with pytest.raises(RuntimeError, match="injected"):
        automatic.execute_file(scope, file)
    with clickhouse.get_collection_client(collection) as client:
        assert client.query("SELECT extracted_by FROM text_content").result_rows == [("ocr_easyocr_en",)]
        assert client.query("SELECT state FROM automatic_ocr_plans FINAL").result_rows == [("failed",)]
    monkeypatch.setattr(automatic, "capabilities", lambda: {"tesseract": ["ron"], "easyocr": []})
    automatic.execute_file(scope, file)
    automatic.execute_file(scope, file)
    assert calls == [("tesseract", "Latin")]
    with clickhouse.get_collection_client(collection) as client:
        assert client.query("SELECT extracted_by, text FROM text_content").result_rows == [("ocr_tesseract_Latin", "Current OCR replacement")]
        assert document_ocr_presence(client, "dataset", ["image"]) == {"image": 2}
        assert client.query("SELECT count() FROM automatic_ocr_output FINAL WHERE output_id != 'publication-metadata'").result_rows[0][0] == 1


def test_unknown_script_keeps_prior_output_and_is_visibly_incomplete(collection, tmp_path, monkeypatch):
    calls = services(monkeypatch)
    monkeypatch.setattr(ocr_detection, "detect_text", lambda data: dict(has_text=True, script="", model="", text=""))
    scope, file = image_scope(collection, tmp_path)
    with clickhouse.get_collection_client(collection) as client:
        seed(client)
    with pytest.raises(Exception, match="incomplete script coverage"):
        automatic.execute_file(scope, file)
    assert not calls
    with clickhouse.get_collection_client(collection) as client:
        assert client.query("SELECT state, reason FROM automatic_ocr_plans FINAL").result_rows == [("incomplete", "unknown_script")]
        assert client.query("SELECT text FROM text_content").result_rows == [("Prior OCR text",)]
        assert document_ocr_presence(client, "dataset", ["image"]) == {}


def test_verified_negative_publication_is_absent_and_not_unknown(collection, tmp_path, monkeypatch):
    calls = services(monkeypatch)
    monkeypatch.setattr(ocr_detection, "detect_text", lambda data: {"has_text": False})
    scope, file = image_scope(collection, tmp_path)
    with clickhouse.get_collection_client(collection) as client:
        seed(client)
    automatic.execute_file(scope, file)
    assert not calls
    with clickhouse.get_collection_client(collection) as client:
        assert client.query("SELECT count() FROM text_content").result_rows[0][0] == 0
        assert document_ocr_presence(client, "dataset", ["image"]) == {"image": 1}


def test_lost_text_write_cannot_publish_success(collection, tmp_path, monkeypatch):
    services(monkeypatch)
    from tasks.P3_parse_files import parse_common
    monkeypatch.setattr(parse_common, "insert_text_sources", lambda *args, **kwargs: 0)
    scope, file = image_scope(collection, tmp_path)
    with clickhouse.get_collection_client(collection) as client:
        seed(client)
    with pytest.raises(RuntimeError, match="incomplete durable replacement text"):
        automatic.execute_file(scope, file)
    with clickhouse.get_collection_client(collection) as client:
        assert client.query("SELECT state FROM automatic_ocr_plans FINAL").result_rows == [("failed",)]
        assert client.query("SELECT text FROM text_content").result_rows == [("Prior OCR text",)]


def test_same_extractor_removes_obsolete_pages_before_publication(collection, tmp_path, monkeypatch):
    services(monkeypatch)
    from tasks.P3_parse_files.insert_batch import parser_insert_batch
    scope, file = image_scope(collection, tmp_path)
    with clickhouse.get_collection_client(collection) as client:
        seed(client)
        client.insert("text_content", [["dataset", "image", "ocr_tesseract_Latin", 1, "old first", 9, 1],
                                       ["dataset", "image", "ocr_tesseract_Latin", 2, "old second", 10, 1]],
                      column_names=["collection_dataset", "file_hash", "extracted_by", "page_id", "text", "text_bytes", "version"])
    with parser_insert_batch() as buffer:
        buffer.index = 0
        result = automatic.execute_file(scope, file)
    with clickhouse.get_collection_client(collection) as client:
        assert client.query("SELECT page_id, argMax(text, version) FROM text_content GROUP BY page_id").result_rows == [(1, "Current OCR replacement")]
        assert client.query("SELECT plan_digest FROM automatic_ocr_plans FINAL").result_rows == [(result,)]


def test_one_character_output_has_no_published_text_presence(collection, tmp_path, monkeypatch):
    services(monkeypatch)
    from tasks import ocr_client
    monkeypatch.setattr(ocr_client, "run_ocr", lambda engine, languages, data:
        SimpleNamespace(engine=engine, languages=languages, text="X", raw_json='{"text":"X","words":[]}'))
    scope, file = image_scope(collection, tmp_path)
    with clickhouse.get_collection_client(collection) as client:
        seed(client)
    automatic.execute_file(scope, file)
    with clickhouse.get_collection_client(collection) as client:
        assert client.query("SELECT count() FROM text_content").result_rows[0][0] == 0
        assert document_ocr_presence(client, "dataset", ["image"]) == {"image": 1}


def test_new_failed_plan_retains_previously_published_presence(collection, tmp_path, monkeypatch):
    services(monkeypatch)
    scope, file = image_scope(collection, tmp_path)
    with clickhouse.get_collection_client(collection) as client:
        seed(client)
    automatic.execute_file(scope, file)
    scope.op_id = "replacement-operation"
    # A stage version change rejects the published output, so the next plan needs new OCR.
    from tasks import stage_versions
    monkeypatch.setitem(stage_versions.STAGE_VERSIONS, "ocr_image", stage_versions.STAGE_VERSIONS["ocr_image"] + 1)
    monkeypatch.setattr(automatic, "image_output", lambda *args: (_ for _ in ()).throw(RuntimeError("service unavailable")))
    with pytest.raises(RuntimeError, match="service unavailable"):
        automatic.execute_file(scope, file)
    with clickhouse.get_collection_client(collection) as client:
        assert document_ocr_presence(client, "dataset", ["image"]) == {"image": 2}
        assert client.query("SELECT text FROM text_content").result_rows == [("Current OCR replacement",)]


def test_actual_producer_identity_reaches_verifier_and_retry(search_collection, monkeypatch):
    from database import manticore
    from tasks.P_admin.automatic_ocr import AutomaticOcrScope, run_automatic_ocr_files, verify_automatic_ocr_files
    from tasks.P_admin import automatic_ocr as admin_automatic
    services(monkeypatch)
    monkeypatch.setattr(ocr_detection, "detect_text", lambda data: {"has_text": False})
    monkeypatch.setattr(admin_automatic, "capabilities", automatic.capabilities)
    name = search_collection
    with clickhouse.get_collection_client(name) as client:
        seed(client)
        client.insert("image", [["dataset", "image"]], column_names=["collection_dataset", "image_hash"])
        client.insert("blobs", [["dataset", "image", 5, 1]],
                      column_names=["collection_dataset", "blob_hash", "blob_size_bytes", "stored_in_clickhouse"])
        client.insert("blob_values", [["dataset", "image", "image"]], column_names=["collection_dataset", "blob_hash", "blob_value"])
    scope = AutomaticOcrScope(name, "dataset", "operation", hashes=["image"])
    scope.plans = run_automatic_ocr_files(scope)
    assert len(scope.plans["image"]) == 64
    assert run_automatic_ocr_files(scope) == scope.plans
    with clickhouse.get_collection_client(name) as client:
        client.insert("index_state", [["dataset", "image", name + "_1"]],
                      column_names=["collection_dataset", "file_hash", "shard_name"])
    table = manticore.shard_table_name(name, 1)
    with manticore.get_manticore_client() as connection:
        cursor = connection.cursor()
        cursor.execute(f"REPLACE INTO {table} (id, collection_dataset, file_hash, extracted_by, page_id, has_ocr_output) "
                       "VALUES (1, 'dataset', 'image', 'filename_index', -1, 1)")
        connection.commit()
    from tasks.P_admin.automatic_ocr import verify_ingested_automatic_ocr, hash_sql, target
    with manticore.get_manticore_client() as connection:
        connection.cursor().execute(f"ALTER TABLE {table} DROP COLUMN has_ocr_output")
        connection.commit()
    manticore._COLUMN_CACHE.pop(table, None)
    with pytest.raises(RuntimeError, match="requires the current search schema"):
        verify_ingested_automatic_ocr(scope)
    with manticore.get_manticore_client() as connection:
        connection.cursor().execute(f"ALTER TABLE {table} ADD COLUMN has_ocr_output int")
        connection.cursor().execute(f"REPLACE INTO {table} (id, collection_dataset, file_hash, extracted_by, page_id, has_ocr_output) VALUES (1, 'dataset', 'image', 'filename_index', -1, 1)")
        connection.commit()
    manticore._COLUMN_CACHE.pop(table, None)
    verify_ingested_automatic_ocr(scope)
    verify_ingested_automatic_ocr(scope)
    with clickhouse.get_collection_client(name) as client:
        assert client.query(hash_sql(), parameters={"cd": "dataset", **target()}).result_rows == []
    verify_automatic_ocr_files(scope)
    with clickhouse.get_collection_client(name) as client:
        assert client.query("SELECT state FROM automatic_ocr_plans FINAL").result_rows == [("applied",)]
    bad = AutomaticOcrScope(name, "dataset", "operation", hashes=["image"], plans={"image": "stale"})
    with pytest.raises(RuntimeError, match="publication changed"):
        verify_automatic_ocr_files(bad)


def test_mixed_script_pdf_after_page_one_hundred_uses_bounded_requests(collection, tmp_path, monkeypatch):
    import io
    import subprocess
    from pathlib import Path
    from database.s3 import collection_bucket, get_s3_client
    from tasks import ocr_pdf_client
    from tasks.P3_parse_files.pdf_parts import write_row
    from tasks.text_sources import OCR_PAGE_RULE_VERSION
    source = tmp_path / "many.pdf"
    tiny = str(Path("tests/fixtures/tiny/tiny.pdf").resolve())
    subprocess.run(["qpdf", "--empty", "--pages", *[value for _ in range(131) for value in (tiny, "1")], "--", str(source)], check=True, capture_output=True)
    storage, bucket = get_s3_client(), collection_bucket(collection)
    storage.make_bucket(bucket)
    calls = []
    attempts = []
    try:
        with clickhouse.get_collection_client(collection) as client:
            seed(client, "pdf")
            write_row(client, "ocr_page_needs", dict(collection_dataset="dataset", hash="pdf", source_kind="original",
                      page_count=131, ocr_pages=list(range(1, 132)), rule_version=OCR_PAGE_RULE_VERSION))
            write_row(client, "pdf_parts", dict(collection_dataset="dataset", hash="pdf", source_kind="original",
                      segmentation=1, part_index=1, first_page=1, last_page=131, s3_path="", size_bytes=source.stat().st_size))
        monkeypatch.setattr(automatic, "capabilities", lambda: {"tesseract": ["Latin"], "easyocr": ["ar"]})
        monkeypatch.setattr(ocr_detection, "engine_configured", lambda engine: True)
        monkeypatch.setattr(ocr_detection, "render_page", lambda path, page: str(page).encode())
        def detect(data):
            page = int(data)
            return dict(has_text=page != 131, script="Latin" if page <= 32 or page > 100 else "Arabic", model="", text="")
        monkeypatch.setattr(ocr_detection, "detect_text", detect)
        monkeypatch.setattr(ocr_pdf_client, "service_configured", lambda: True)
        def build(**kwargs):
            attempts.append(kwargs["dest_key"])
            if len(attempts) == 2:
                raise RuntimeError("injected OCR service failure")
            selected = kwargs["ocr_pages"]
            assert 0 < len(selected) <= 32
            payload = storage.get_object(kwargs["source_bucket"], kwargs["source_key"])
            try:
                data = payload.read()
            finally:
                payload.close()
                payload.release_conn()
            storage.put_object(bucket, kwargs["dest_key"], io.BytesIO(data), len(data), content_type="application/pdf")
            calls.append((kwargs["engine"], selected))
            return SimpleNamespace(engine=kwargs["engine"], languages=kwargs["languages"], dest_key=kwargs["dest_key"],
                                   size_bytes=len(data), pages=[dict(page=page, text=f"Recognized page {page}") for page in selected])
        monkeypatch.setattr(ocr_pdf_client, "build_ocr_pdf", build)
        file = BatchFile("pdf", str(source), source_kind="original")
        scope = StageBatchParams(collection, "dataset", "plan", [file], "operation")
        with pytest.raises(RuntimeError, match="injected OCR service failure"):
            automatic.execute_file(scope, file)
        with clickhouse.get_collection_client(collection) as client:
            assert client.query("SELECT text FROM text_content").result_rows == [("Prior OCR text",)]
        identity = automatic.execute_file(scope, file)
        assert automatic.execute_file(scope, file) == identity
        assert len(calls) == 6
        assert sum(len(pages) for engine, pages in calls if engine == "tesseract") == 62
        assert sum(len(pages) for engine, pages in calls if engine == "easyocr") == 68
        with clickhouse.get_collection_client(collection) as client:
            assert client.query("SELECT count() FROM ocr_detection FINAL").result_rows[0][0] == 131
            assert client.query("SELECT count() FROM text_content").result_rows[0][0] == 130
            assert client.query("SELECT max(last_page - first_page + 1) FROM pdf_ocr_parts FINAL").result_rows[0][0] <= 32
            assert client.query("SELECT count() FROM pdf_ocr_results FINAL WHERE is_deleted = 0 AND text_complete = 1").result_rows[0][0] == 2
    finally:
        for item in storage.list_objects(bucket, recursive=True):
            storage.remove_object(bucket, item.object_name)
        storage.remove_bucket(bucket)


def test_failed_detection_batch_resumes_without_negative_rows(collection, tmp_path, monkeypatch):
    from tasks.P3_parse_files.pdf_parts import write_row
    from tasks.text_sources import OCR_PAGE_RULE_VERSION
    path = tmp_path / "unused.pdf"
    path.write_bytes(b"source")
    with clickhouse.get_collection_client(collection) as client:
        seed(client, "pdf")
        write_row(client, "ocr_page_needs", dict(collection_dataset="dataset", hash="pdf", source_kind="original",
                  page_count=70, ocr_pages=list(range(1, 71)), rule_version=OCR_PAGE_RULE_VERSION))
    monkeypatch.setattr(ocr_detection, "engine_configured", lambda engine: True)
    rendered = []
    failed = []
    def render(path, page):
        rendered.append(page)
        if page == 40 and not failed:
            failed.append(page)
            raise RuntimeError("injected renderer failure")
        return b"rendered"
    monkeypatch.setattr(ocr_detection, "render_page", render)
    monkeypatch.setattr(ocr_detection, "detect_text", lambda data: dict(has_text=True, script="Latin", model="", text=""))
    file = BatchFile("pdf", str(path), source_kind="original")
    scope = StageBatchParams(collection, "dataset", "plan", [file], "operation")
    from tasks.P3_parse_files.insert_batch import parser_insert_batch
    with parser_insert_batch() as buffer:
        buffer.index = 0
        with pytest.raises(RuntimeError, match="renderer failure"):
            ocr_detection._detect_file(scope, file)
    with clickhouse.get_collection_client(collection) as client:
        assert client.query("SELECT count(), sum(has_text) FROM ocr_detection FINAL").result_rows == [(32, 32)]
    with parser_insert_batch() as buffer:
        buffer.index = 0
        ocr_detection._detect_file(scope, file)
    assert rendered.count(1) == 1
    assert rendered.count(33) == 2
    with clickhouse.get_collection_client(collection) as client:
        assert client.query("SELECT count(), sum(has_text) FROM ocr_detection FINAL").result_rows == [(70, 70)]
        assert client.query("SELECT text FROM text_content").result_rows == [("Prior OCR text",)]


def test_dataset_purge_removes_unpublished_owned_objects_only(collection, tmp_path, monkeypatch):
    import io
    from database.s3 import collection_bucket, get_s3_client
    from tasks.P_admin.activities import PurgeDatasetParams, purge_dataset_from_clickhouse
    services(monkeypatch)
    scope, file = image_scope(collection, tmp_path)
    storage, bucket = get_s3_client(), collection_bucket(collection)
    storage.make_bucket(bucket)
    keys = ["derived/automatic-ocr/dataset/image/failed.pdf",
            "derived/automatic-ocr-source/dataset/image/1-32.pdf",
            "derived/automatic-ocr/dataset/image/aborted-without-receipt.pdf",
            "derived/automatic-ocr/other/image/keep.pdf", "borrowed-original.pdf"]
    try:
        with clickhouse.get_collection_client(collection) as client:
            seed(client)
        for key in keys:
            storage.put_object(bucket, key, io.BytesIO(b"pdf"), 3)
        monkeypatch.setattr(automatic, "publish", lambda *args: (_ for _ in ()).throw(RuntimeError("failed staged publication")))
        with pytest.raises(RuntimeError, match="failed staged publication"):
            automatic.execute_file(scope, file)
        purge_dataset_from_clickhouse(PurgeDatasetParams(collection, "dataset"))
        assert {item.object_name for item in storage.list_objects(bucket, recursive=True)} == set(keys[-2:])
        with clickhouse.get_collection_client(collection) as client:
            assert client.query("SELECT count() FROM automatic_ocr_output").result_rows[0][0] == 0
            assert client.query("SELECT count() FROM automatic_ocr_plans").result_rows[0][0] == 0
    finally:
        for item in storage.list_objects(bucket, recursive=True):
            storage.remove_object(bucket, item.object_name)
        storage.remove_bucket(bucket)


def test_distinct_operation_can_replace_a_pinned_plan_and_fences_old_retry(collection, tmp_path, monkeypatch):
    calls = services(monkeypatch)
    scope, file = image_scope(collection, tmp_path)
    with clickhouse.get_collection_client(collection) as client:
        seed(client)
    first = automatic.execute_file(scope, file)
    scope.op_id = "next-operation"
    monkeypatch.setattr(automatic, "capabilities", lambda: {"tesseract": [], "easyocr": ["en"]})
    # A stage version change rejects the published output, so the next plan needs new OCR.
    from tasks import stage_versions
    monkeypatch.setitem(stage_versions.STAGE_VERSIONS, "ocr_image", stage_versions.STAGE_VERSIONS["ocr_image"] + 1)
    second = automatic.execute_file(scope, file)
    assert first != second
    assert calls == [("tesseract", "Latin"), ("easyocr", "en")]
    scope.op_id = "operation"
    with pytest.raises(Exception, match="later automatic OCR plan"):
        automatic.execute_file(scope, file)
    with clickhouse.get_collection_client(collection) as client:
        assert client.query("SELECT extracted_by FROM text_content").result_rows == [("ocr_easyocr_en",)]
        assert client.query("SELECT state FROM automatic_ocr_plans FINAL WHERE plan_digest = {p:String}", parameters={"p": first}).result_rows == [("superseded",)]


def test_same_plan_retry_cannot_lower_the_published_epoch(collection, tmp_path, monkeypatch):
    services(monkeypatch)
    scope, file = image_scope(collection, tmp_path)
    with clickhouse.get_collection_client(collection) as client:
        seed(client)
    first = automatic.execute_file(scope, file)
    scope.op_id = "second-operation"
    monkeypatch.setattr(automatic, "capabilities", lambda: {"tesseract": [], "easyocr": ["en"]})
    from tasks import stage_versions
    version = stage_versions.STAGE_VERSIONS["ocr_image"]
    # A stage version change rejects the published output, so the second plan needs new OCR.
    monkeypatch.setitem(stage_versions.STAGE_VERSIONS, "ocr_image", version + 1)
    second = automatic.execute_file(scope, file)
    assert first != second
    scope.op_id = "third-operation"
    monkeypatch.setitem(stage_versions.STAGE_VERSIONS, "ocr_image", version)
    monkeypatch.setattr(automatic, "capabilities", lambda: {"tesseract": ["eng", "Latin"], "easyocr": ["en"]})
    assert automatic.execute_file(scope, file) == first
    scope.op_id = "operation"
    assert automatic.execute_file(scope, file) == first
    with clickhouse.get_collection_client(collection) as client:
        current = json.loads(client.query("SELECT plan_json FROM automatic_ocr_plans FINAL WHERE plan_digest = {p:String}",
                                         parameters={"p": first}).result_rows[0][0])
        assert current["claim_version"] == 3
        assert automatic.require_current_claim(client, current) == 3
    scope.op_id = "second-operation"
    with pytest.raises(Exception, match="later automatic OCR plan"):
        automatic.execute_file(scope, file)
    with clickhouse.get_collection_client(collection) as client:
        assert client.query("SELECT extracted_by FROM text_content").result_rows == [("ocr_tesseract_Latin",)]


def test_paused_old_publication_cannot_overwrite_a_newer_plan(collection, tmp_path, monkeypatch):
    import asyncio
    import os
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from temporalio.client import Client
    from temporalio.worker import Replayer
    from tasks import document_language
    from tasks.P3_parse_files import parse_common, table_generations
    from tasks.P3_parse_files.table_generations import TableGenerationCommand
    from tasks.run_worker import sandboxed_runner
    from tasks.temporal_readiness import TEMPORAL_ADDRESS
    from .test_table_generation_bridge import common, planner
    calls = services(monkeypatch)
    monkeypatch.setattr(table_generations, "send_command", transport_send_command)
    def language(pages):
        assert not threading.current_thread().name.startswith("publication-planner")
        return "und"
    monkeypatch.setattr(document_language, "source_language", language)
    scope, file = image_scope(collection, tmp_path)
    with clickhouse.get_collection_client(collection) as client:
        seed(client)
    entered, release = threading.Event(), threading.Event()
    original_insert = parse_common.insert_text_sources
    def paused_insert(*args, **kwargs):
        if "ocr_tesseract_Latin" in args[3] and not entered.is_set():
            entered.set()
            assert release.wait(15), "The publication pause was not released"
        return original_insert(*args, **kwargs)
    monkeypatch.setattr(parse_common, "insert_text_sources", paused_insert)
    original_publish = automatic._publish_serialized
    timings = []
    def timed_publish(*args):
        started = time.monotonic()
        try:
            return original_publish(*args)
        finally:
            timings.append(dict(op_id=args[3]["owner_op"], seconds=time.monotonic() - started))
    monkeypatch.setattr(automatic, "_publish_serialized", timed_publish)
    async def run():
        client = await Client.connect(TEMPORAL_ADDRESS)
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="publication-planner") as executor:
            async with common(client), planner(client, executor):
                old = asyncio.create_task(asyncio.to_thread(automatic.execute_file, scope, file))
                assert await asyncio.to_thread(entered.wait, 15), "The old writer did not reach its mutation boundary"
                monkeypatch.setattr(automatic, "capabilities", lambda: {"tesseract": [], "easyocr": ["en"]})
                # A stage version change rejects the staged output of the paused plan.
                from tasks import stage_versions
                monkeypatch.setitem(stage_versions.STAGE_VERSIONS, "ocr_image", stage_versions.STAGE_VERSIONS["ocr_image"] + 1)
                import dataclasses
                new_scope = dataclasses.replace(scope, op_id="new-operation")
                new = asyncio.create_task(asyncio.to_thread(automatic.execute_file, new_scope, file))
                await asyncio.sleep(0.3)
                assert not new.done()
                assert calls == [("tesseract", "Latin")]
                release.set()
                first, second = await asyncio.gather(old, new)
                assert first != second
                with clickhouse.get_collection_client(collection) as db:
                    assert db.query("SELECT extracted_by FROM text_content").result_rows == [("ocr_easyocr_en",)]
                    current = automatic.pinned_plan(db, "dataset", "image", "new-operation")
                    assert automatic.require_current_claim(db, current) == 2
                history = await client.get_workflow_handle(f"table-generation-{collection}-image").fetch_history()
                await Replayer(workflows=[TableGenerationCommand], workflow_runner=sandboxed_runner()).replay_workflow(history)
                if os.getenv("AUTOMATIC_PUBLICATION_HISTORY"):
                    Path(os.environ["AUTOMATIC_PUBLICATION_HISTORY"]).write_text(json.dumps({"automatic-publication": dict(
                        workflow_id=history.workflow_id, workflow_type="TableGenerationCommand", history=json.loads(history.to_json()))}, indent=2))
                with pytest.raises(Exception):
                    await asyncio.to_thread(automatic.execute_file, scope, file)
                with clickhouse.get_collection_client(collection) as db:
                    assert db.query("SELECT extracted_by FROM text_content").result_rows == [("ocr_easyocr_en",)]
        if os.getenv("AUTOMATIC_PUBLICATION_METRICS"):
            Path(os.environ["AUTOMATIC_PUBLICATION_METRICS"]).write_text(json.dumps(timings, indent=2))
    try:
        asyncio.run(run())
    finally:
        release.set()


def test_automatic_selection_preserves_known_pdf_defect_skips(collection):
    from tasks.P_admin.automatic_ocr import hash_sql
    with clickhouse.get_collection_client(collection) as client:
        client.insert("vfs_files", [["dataset", "", "/encrypted.pdf", "encrypted"], ["dataset", "", "/healthy.pdf", "healthy"]],
                      column_names=["collection_dataset", "container_hash", "path", "hash"])
        client.insert("pdf_metadata", [["dataset", "encrypted", "password"], ["dataset", "healthy", None]],
                      column_names=["collection_dataset", "hash", "defect"])
        assert client.query(hash_sql(), parameters={"cd": "dataset", "policy": 1, "cap": "current", "caps": ["current"]}).result_rows == [("healthy",)]


def test_direct_automatic_run_prepares_an_uncommon_image_before_detection(collection, monkeypatch):
    from database.s3 import collection_bucket, get_s3_client
    from tasks.P_admin import automatic_ocr as admin_automatic
    from tasks.P3_parse_files.image_preview import read_preview_bytes
    services(monkeypatch)
    monkeypatch.setattr(ocr_detection, "detect_text", lambda data: {"has_text": False})
    source = b'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80"><rect width="120" height="80" fill="blue"/></svg>'
    storage, bucket = get_s3_client(), collection_bucket(collection)
    storage.make_bucket(bucket)
    try:
        with clickhouse.get_collection_client(collection) as client:
            seed(client)
            client.insert("image", [["dataset", "image"]], column_names=["collection_dataset", "image_hash"])
            client.insert("blobs", [["dataset", "image", len(source), 1]],
                column_names=["collection_dataset", "blob_hash", "blob_size_bytes", "stored_in_clickhouse"])
            client.insert("blob_values", [["dataset", "image", source.decode()]], column_names=["collection_dataset", "blob_hash", "blob_value"])
        params = admin_automatic.AutomaticOcrScope(collection, "dataset", "operation", hashes=["image"])
        assert len(admin_automatic.run_automatic_ocr_files(params)["image"]) == 64
        with clickhouse.get_collection_client(collection) as client:
            preview = read_preview_bytes(client, "dataset", "image")
            assert preview and preview.startswith(b"\xff\xd8\xff")
            assert client.query("SELECT count() FROM image_previews FINAL").result_rows == [(1,)]
    finally:
        for item in storage.list_objects(bucket, recursive=True):
            storage.remove_object(bucket, item.object_name)
        storage.remove_bucket(bucket)
