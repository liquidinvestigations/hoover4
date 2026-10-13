"""Verify bounded PDF transport, durable retry, cancellation, and continuation state."""

import asyncio
import dataclasses
from types import SimpleNamespace

import pytest
from temporalio.exceptions import ApplicationError, CancelledError

from test_pdf_parts import Store
from tasks import ocr_targets
from tasks.ocr_targets import SettingVersion
from tasks.P3_parse_files import pdf_cursor as cursor, pdf_parts as parts, pdf_chain, batch_runner as batch
from tasks.P_admin import workflows as admin, ocr_rerun
from temporalio.converter import PayloadConverter
from tasks.payload_guard import MAX_PAYLOAD_BYTES, MAX_ACTIVATION_BYTES, payload_size


def size(value):
    return payload_size(PayloadConverter.default.to_payloads([value])[0])


@pytest.fixture
def source_store(monkeypatch):
    import database.clickhouse as clickhouse
    db = Store()
    db.add_pdf("doc")
    for number in range(1, 1002):
        db.source_part(number, number, number)
    db.needs.append(dict(hash="doc", page_count=1001, ocr_pages=list(range(1, 1002))))
    setting = SimpleNamespace(value="eng", version=SettingVersion(17, True))
    monkeypatch.setattr(ocr_targets, "language_settings", lambda _dataset: {"tesseract": setting})
    monkeypatch.setattr(clickhouse, "get_collection_client", db.client)
    return db, setting


def source(db):
    manifest = parts.source_parts(db, "c_ds", "doc", "original")
    return cursor.PdfSource("doc", "/tmp/fixture.pdf", 100, "original", parts.PDF_SEGMENTATION_VERSION,
                            parts.source_digest(manifest, 1001, list(range(1, 1002))), 1001, 1001,
                            ["eng"], 17, True)


def parameters(db):
    return cursor.PdfPartCursorParams("c", "c_ds", "plan", "op", "tesseract", source(db))


def test_large_source_loads_parts_inside_each_bounded_activity(source_store, monkeypatch):
    db, _setting = source_store
    calls = []
    monkeypatch.setattr(parts, "build_part", lambda params, file: calls.append(
        (file.part_index, file.first_page, file.ocr_pages, params.languages)) or "complete")
    params = parameters(db)
    windows = []
    while True:
        result = parts.run_ocr_pdf_part_cursor(params)
        windows.append(result.completed)
        assert size(result) < MAX_PAYLOAD_BYTES
        assert "parts" not in dataclasses.asdict(result)
        if result.done:
            break
        params = dataclasses.replace(params, after=result.after)
    assert windows == [100] * 10 + [1]
    assert [row[0] for row in calls] == list(range(1, 1002))
    assert all(selected == [1] and languages == ["eng"] for _, _, selected, languages in calls)


def test_retry_after_repeated_cancellation_reuses_durable_parts(source_store, monkeypatch):
    db, _setting = source_store
    saved = set()
    requests = []
    interruptions = {4, 10}

    def build(params, file):
        if file.part_index in saved:
            return "saved"
        if file.part_index in interruptions:
            interruptions.remove(file.part_index)
            raise CancelledError("cancelled")
        saved.add(file.part_index)
        requests.append(file.part_index)
        return "saved"

    monkeypatch.setattr(parts, "build_part", build)
    with pytest.raises(CancelledError):
        parts.run_ocr_pdf_part_cursor(parameters(db))
    assert saved == {1, 2, 3}
    with pytest.raises(CancelledError):
        parts.run_ocr_pdf_part_cursor(parameters(db))
    assert saved == set(range(1, 10))
    result = parts.run_ocr_pdf_part_cursor(parameters(db))
    assert result.after == 100
    assert requests == list(range(1, 101))
    repeated = parts.run_ocr_pdf_part_cursor(parameters(db))
    assert repeated.after == result.after
    assert requests == list(range(1, 101))


@pytest.mark.parametrize("change", ["source", "pages", "languages", "version"])
def test_source_and_settings_changes_stop_before_part_work(source_store, monkeypatch, change):
    db, setting = source_store
    params = parameters(db)
    if change == "source":
        db.source[0]["s3_path"] = "s3://fixture/changed"
    elif change == "pages":
        db.needs[0]["ocr_pages"] = [1]
    elif change == "languages":
        setting.value = "fra"
    else:
        setting.version = SettingVersion(18, True)
    monkeypatch.setattr(parts, "build_part", lambda *_args: pytest.fail("part work started after an identity change"))
    with pytest.raises(ApplicationError) as failure:
        parts.run_ocr_pdf_part_cursor(params)
    assert failure.value.non_retryable
    assert failure.value.type in ("PdfSourceChanged", "PdfSettingsChanged")


def test_part_failure_returns_one_bounded_document_error(source_store, monkeypatch):
    db, _setting = source_store

    def build(_params, _file):
        raise ApplicationError("界" * 10000, type="Broken", non_retryable=True)

    monkeypatch.setattr(parts, "build_part", build)
    result = parts.run_ocr_pdf_part_cursor(parameters(db))
    assert result.result.item_hash == "doc"
    assert result.result.status == "failed"
    assert size(result) < 3000


class Continued(Exception):
    def __init__(self, params):
        self.params = params


@pytest.mark.parametrize("reason", ["events", "bytes", "suggested"])
def test_multiple_continuations_preserve_cursor_and_settings(monkeypatch, reason):
    sources = [cursor.PdfSource("doc", "/tmp/fixture", 0, "original", 1, "digest", 601, 601, ["eng"]),
               cursor.PdfSource("doc2", "/tmp/fixture2", 0, "preview", 1, "digest2", 1, 1, ["eng"])]
    params = cursor.PdfPartGroupParams("c", "ds", "plan", "op", "tesseract", sources)
    visited = []
    active = 0

    async def execute(name, arg, **_kwargs):
        nonlocal active
        active += 1
        await asyncio.sleep(0)
        active -= 1
        if name == "pdf_ocr_finalize_cursor":
            return batch.FileResult(arg.source.item_hash, "pdf", "ok")
        end = min(arg.after + 100, arg.source.part_count)
        visited.extend((arg.source.item_hash, number) for number in range(arg.after + 1, end + 1))
        assert arg.source.languages == ["eng"]
        return cursor.PdfPartProgress(end, end - arg.after, end == arg.source.part_count)

    def continuation(value):
        assert active == 0
        raise Continued(value)

    monkeypatch.setattr(cursor.workflow, "execute_activity", execute)
    monkeypatch.setattr(cursor.workflow, "continue_as_new", continuation)
    monkeypatch.setattr(cursor.workflow, "info", lambda: SimpleNamespace(
        get_current_history_length=lambda: cursor.PDF_HISTORY_EVENTS if reason == "events" else 0,
        get_current_history_size=lambda: cursor.PDF_HISTORY_BYTES if reason == "bytes" else 0,
        is_continue_as_new_suggested=lambda: reason == "suggested"))
    cycles = 0
    while True:
        try:
            results = asyncio.run(cursor.PdfPartGroup().run(params))
            break
        except Continued as continued:
            params = continued.params
            cycles += 1
    assert cycles == 7
    assert len(visited) == len(set(visited)) == 602
    assert [result.item_hash for result in results] == ["doc", "doc2"]
    assert params.completed == 601


def test_cancellation_stops_the_child_without_continuation_or_finalization(monkeypatch):
    calls = []

    async def execute(name, *_args, **_kwargs):
        calls.append(name)
        raise CancelledError("cancelled")

    monkeypatch.setattr(cursor.workflow, "execute_activity", execute)
    with pytest.raises(CancelledError):
        asyncio.run(cursor.PdfPartGroup().run(cursor.PdfPartGroupParams(
            "c", "ds", "plan", "op", "tesseract", [cursor.PdfSource(
                "doc", "/tmp/fixture", 0, "original", 1, "digest", 1, 1)])))
    assert calls == ["run_ocr_pdf_part_cursor"]


def test_worst_error_heartbeat_and_two_engine_commands_fit_with_image_siblings():
    errors = [batch.FileResult(f"{number:064x}", "run_ocr_pdf_and_store", "failed",
                              error_type="E" * batch.FILE_ERROR_TYPE_BYTES,
                              error_message="M" * batch.FILE_ERROR_MESSAGE_BYTES,
                              error_trace="T" * batch.FILE_ERROR_TRACE_BYTES,
                              non_retryable=True) for number in range(100)]
    state = batch._State("run_ocr_pdf_parts_batch", [row.item_hash for row in errors],
                         [row.task_name for row in errors], 1)
    for index, row in enumerate(errors):
        state._finish(index, row)
    state._publish()
    assert all("cut" not in row for row in state.detail["done"])
    assert size(state.detail) < MAX_PAYLOAD_BYTES
    sources = [cursor.PdfSource(row.item_hash, "/tmp/" + row.item_hash, 10**12,
                               "original", 1, "a" * 64, 65000, 6500000, ["eng"])
               for row in errors]
    groups = [cursor.PdfPartGroupParams("c", "ds", "p", "op", engine, sources, results=errors)
              for engine in ("tesseract", "easyocr")]
    assert all(size(group) < MAX_PAYLOAD_BYTES for group in groups)
    assert size(errors) < MAX_PAYLOAD_BYTES
    siblings = [batch.StageBatchParams("c", "ds", "p", [batch.BatchFile(
        row.item_hash, "/tmp/" + row.item_hash, 10**12) for row in errors], "op", engine)
                for engine in ("tesseract", "easyocr")]
    assert sum(size(value) for value in [*groups, *siblings]) < MAX_ACTIVATION_BYTES


def test_unexpected_oversized_result_has_a_compact_nonretryable_error():
    with pytest.raises(ApplicationError) as failed:
        parts.bounded_result({"unexpected": "x" * MAX_PAYLOAD_BYTES})
    assert failed.value.type == "PayloadTooLarge"
    assert failed.value.non_retryable
    assert len(str(failed.value)) < 100


def test_both_engines_use_bounded_source_lanes_and_compact_preparation(monkeypatch):
    files = [batch.BatchFile(f"{number:064x}", f"/tmp/{number}") for number in range(100)]
    stages = []
    children = []

    async def stage(name, items, engine=""):
        stages.append(name)
        if not items:
            return []
        if name == "pdf_metadata_batch":
            return [batch.FileResult(file.item_hash, name, "ok", dict(page_count=100000, size_bytes=100))
                    for file in items]
        assert name == "pdf_prepare_compact_batch"
        return [batch.FileResult(file.item_hash, "pdf_prepare", "ok", dict(
            segmentation=1, source_digest="a" * 64, part_count=1000, page_count=100000,
            has_ocr_pages=True, saved_engines=[], part_lists=4,
            languages={"tesseract": ["eng"], "easyocr": ["en"]},
            settings_versions={engine: dict(version_us=17, is_precise=True)
                               for engine in ("tesseract", "easyocr")})) for file in items]

    async def child(_run, arg, **kwargs):
        children.append((arg, kwargs))
        return [batch.FileResult(item.item_hash, "pdf", "failed" if item.item_hash == files[0].item_hash else "ok")
                for item in arg.sources]

    monkeypatch.setattr(cursor.workflow, "execute_child_workflow", child)
    monkeypatch.setattr(cursor.workflow, "info", lambda: SimpleNamespace(workflow_id="fixture"))
    preparation, variants = asyncio.run(pdf_chain.run_pdf_chain(
        files, stage, cursor_context=SimpleNamespace(collectionname="c", collection_dataset="ds",
                                                    op_id="op", plan_hash="plan")))
    assert stages == ["pdf_metadata_batch", "make_pdf_preview_batch", "pdf_prepare_compact_batch"]
    assert len(children) == 8
    assert len({kwargs["id"] for _, kwargs in children}) == 8
    assert all(len(arg.sources) == 25 for arg, _kwargs in children)
    assert sum(size(arg) for arg, _ in children) < MAX_ACTIVATION_BYTES // 2
    assert len(preparation) == 100 and len(variants) == 200
    assert variants[files[0].item_hash, "tesseract"].status == "failed"
    assert variants[files[0].item_hash, "easyocr"].status == "failed"


def test_compact_preparation_contains_no_part_or_page_arrays(source_store, monkeypatch):
    db, setting = source_store
    monkeypatch.setattr(ocr_targets, "language_settings", lambda _dataset:
                        {"tesseract": setting, "easyocr": SimpleNamespace(value="en", version=SettingVersion())})
    file = batch.BatchFile("doc", "/tmp/fixture")
    value = parts.preparation_value(db, batch.StageBatchParams("c", "c_ds", "p"), file,
                                    parts.source_parts(db, "c_ds", "doc", "original"),
                                    1001, list(range(1, 1002)), compact=True)
    assert value["part_count"] == 1001 and value["page_count"] == 1001
    assert not any(key in value for key in ("parts", "ocr_pages", "page_numbers"))
    assert size(value) < 1000


def test_descriptor_pages_recover_once_use_unique_directories_and_report_remaining_targets(monkeypatch):
    from test_ocr_run_workflow import Temporal, plan_params, image
    pages = [ocr_rerun.OcrRunPlanPage([image(f"i{number}")], [f"i{number}"], f"i{number}")
             for number in range(6)] + [ocr_rerun.OcrRunPlanPage()]
    loaded = []

    def load(arg):
        loaded.append(arg.after)
        return pages[len(loaded) - 1]

    env = Temporal(monkeypatch, parts=True, answers={
        "prepare_ocr_run_plan": 6,
        "load_ocr_run_plan_page": load,
        "download_plan_files": lambda arg: {"out_dir": f"/tmp/{arg.plan_hash}"},
        "ocr_text_pending_index": lambda arg: arg.hashes,
        "settle_ocr_run_targets_diagnostic": ocr_rerun.OcrRunSettlement(
            5, 1, ["file i5 stage pdf engine tesseract languages eng"]),
    })
    groups = []

    async def group(_self, _params, out_dir, index, files, _parts):
        groups.append((out_dir, index, files[0].item_hash))
        await asyncio.sleep(0)

    monkeypatch.setattr(admin.OcrRunPlan, "_group", group)
    with pytest.raises(ApplicationError, match="file i5 stage pdf engine tesseract languages eng"):
        asyncio.run(admin.OcrRunPlan().run(plan_params()))
    assert env.names().count("prepare_ocr_run_plan") == 1
    assert "load_ocr_run_plan" not in env.names()
    assert loaded == ["", "i0", "i1", "i2", "i3", "i4", "i5"]
    assert len({folder for folder, _, _ in groups}) == 6
    assert len({call[3]["id"] for call in env.calls if call[0] == "child"}) == 24
    cleanups = [call[2].plan_hash for call in env.calls if call[1] == "cleanup_plan_dir"]
    assert len(set(cleanups)) == 6


def test_descriptor_page_cancellation_removes_its_temporary_directory(monkeypatch):
    from test_ocr_run_workflow import Temporal, plan_params, image
    env = Temporal(monkeypatch, answers={
        "download_plan_files": {"out_dir": "/tmp/page"}})

    async def group(*_args, **_kwargs):
        raise CancelledError("cancelled")

    monkeypatch.setattr(admin.OcrRunPlan, "_group", group)
    with pytest.raises(CancelledError):
        asyncio.run(admin.OcrRunPlan()._run_page(
            plan_params(), ocr_rerun.OcrRunPlanPage([image("i")], [], "i"), 3))
    assert env.names() == ["download_plan_files", "cleanup_plan_dir"]
    assert env.calls[-1][2].plan_hash == "plan-1-page-3"


def test_descriptor_activity_pages_targets_without_repeating_recovery(monkeypatch):
    from test_ocr_run_workflow import COLLECTION, CD, OP
    from tasks import dataset_config, ocr_client, ocr_pdf_client
    import database.clickhouse as clickhouse
    import tasks.P2_execute_plan.activities as plan_activities
    db = Store()
    for number in range(250):
        db.add_image(f"i{number:03d}")
    monkeypatch.setattr(clickhouse, "get_collection_client", db.client)
    monkeypatch.setattr(ocr_client, "engine_configured", lambda engine: engine == "tesseract")
    monkeypatch.setattr(ocr_pdf_client, "service_configured", lambda: True)
    monkeypatch.setattr(ocr_pdf_client, "engines_for_provider", lambda: ["tesseract"])
    monkeypatch.setattr(dataset_config, "latest_setting_rows", lambda *_args:
                        {"ocr.tesseract.languages": dataset_config.SettingRow("eng", False, 17, True)})
    ocr_rerun.record_ocr_run_targets(ocr_rerun.RerunOcrParams(COLLECTION, CD, OP))
    metadata = [dict(item_hash=f"i{number:03d}", file_size_bytes=1, s3_url="", file_names=[])
                for number in range(250)]
    monkeypatch.setattr(plan_activities, "get_plan_items_metadata", lambda _params: metadata)
    monkeypatch.setattr(ocr_rerun, "_plan_items", lambda *_args: pytest.fail("recovery repeated in a descriptor page"))
    after = ""
    files = []
    counts = []
    while True:
        page = ocr_rerun.load_ocr_run_plan_page(ocr_rerun.OcrRunPlanPageParams(
            COLLECTION, CD, OP, "p1", False, after))
        if not page.after:
            break
        counts.append(len(page.files))
        files.extend(file.item_hash for file in page.files)
        after = page.after
    assert counts == [100, 100, 50]
    assert files == [row["item_hash"] for row in metadata]


@pytest.mark.parametrize("identity", ["PdfSourceChanged", "PdfSettingsChanged"])
def test_identity_change_propagates_without_document_errors_and_fresh_targets_remain_open(monkeypatch, identity):
    from temporalio.exceptions import ActivityError, ChildWorkflowError, RetryState
    from test_ocr_run_workflow import Temporal, plan_params, pdf
    from tasks import dataset_config, ocr_client, ocr_pdf_client
    import database.clickhouse as clickhouse
    db = Store()
    db.add_pdf("doc")
    monkeypatch.setattr(clickhouse, "get_collection_client", db.client)
    monkeypatch.setattr(dataset_config, "latest_setting_rows", lambda *_args:
                        {"ocr.tesseract.languages": dataset_config.SettingRow("eng", False, 17, True)})
    monkeypatch.setattr(ocr_client, "engine_configured", lambda engine: engine == "tesseract")
    monkeypatch.setattr(ocr_pdf_client, "service_configured", lambda: True)
    monkeypatch.setattr(ocr_pdf_client, "engines_for_provider", lambda: ["tesseract"])
    from ocr_store_fake import COLLECTION, CD
    initial = ocr_rerun.RerunOcrParams(COLLECTION, CD, "initial", parts_version=True)
    ocr_rerun.record_ocr_run_targets(initial)
    cause = ApplicationError("PDF identity changed", type=identity, non_retryable=True)
    failed = ActivityError("failed", scheduled_event_id=1, started_event_id=2, identity="fixture",
                           activity_type="run_ocr_pdf_part_cursor", activity_id="1",
                           retry_state=RetryState.NON_RETRYABLE_FAILURE)
    failed.__cause__ = cause

    async def activity_call(*_args, **_kwargs):
        raise failed

    env = Temporal(monkeypatch, parts=True)
    monkeypatch.setattr(cursor.workflow, "execute_activity", activity_call)
    with pytest.raises(ActivityError):
        asyncio.run(cursor.PdfPartGroup().run(cursor.PdfPartGroupParams(
            COLLECTION, CD, "p1", "initial", "tesseract", [cursor.PdfSource(
                "doc", "/tmp/fixture", 1, "original", 1, "digest", 1, 1)])))

    async def stages(name, files, _engine=""):
        value = dict(page_count=1, size_bytes=1) if name == "pdf_metadata_batch" else dict(
            segmentation=1, source_digest="digest", part_count=1, page_count=1,
            has_ocr_pages=True, saved_engines=[], languages={engine: ["eng"] for engine in ("tesseract", "easyocr")},
            settings_versions={engine: dict(version_us=17, is_precise=True) for engine in ("tesseract", "easyocr")})
        return [batch.FileResult(file.item_hash, name, "ok", value) for file in files]

    child_error = ChildWorkflowError("failed", namespace="default", workflow_id="fixture", run_id="fixture",
                                    workflow_type="PdfPartGroup", initiated_event_id=1,
                                    started_event_id=2, retry_state=RetryState.NON_RETRYABLE_FAILURE)
    child_error.__cause__ = failed

    async def child(*_args, **_kwargs):
        raise child_error

    monkeypatch.setattr(cursor.workflow, "execute_child_workflow", child)
    monkeypatch.setattr(cursor.workflow, "info", lambda: SimpleNamespace(workflow_id="fixture", run_id="fixture"))
    with pytest.raises(ChildWorkflowError):
        asyncio.run(pdf_chain.run_pdf_chain([batch.BatchFile("doc", "/tmp/fixture")], stages,
                                            cursor_context=plan_params()))
    env.answers.update({name: (lambda arg, stage=name: batch.BatchResult(stage, [
        batch.FileResult(file.item_hash, stage, "ok", dict(
            page_count=1, size_bytes=1, segmentation=1, source_digest="digest", part_count=1,
            has_ocr_pages=True, saved_engines=[],
            languages={engine: ["eng"] for engine in ("tesseract", "easyocr")},
            settings_versions={engine: dict(version_us=17, is_precise=True)
                               for engine in ("tesseract", "easyocr")})) for file in arg.files]))
        for name in ("pdf_metadata_batch", "pdf_prepare_compact_batch")})
    monkeypatch.setattr(cursor.workflow, "execute_activity", env.activity)
    with pytest.raises(ChildWorkflowError):
        asyncio.run(admin.OcrRunPlan()._group(plan_params(), "/tmp/fixture", 0, [pdf("doc")], True))
    assert "record_processing_errors" not in env.names()
    assert db.errors == []
    assert db.open_targets("initial")
    fresh = dataclasses.replace(initial, op_id="fresh")
    ocr_rerun.record_ocr_run_targets(fresh)
    assert db.open_targets("fresh")
    assert any(row["stage"] == "pdf" for row in db.open_targets("fresh").values())
