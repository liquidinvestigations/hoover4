"""The "Run OCR" workflows, `RerunOcr` and `OcrRunPlan`, and the activities of their ledger.

The workflow tests patch `execute_activity`, `execute_child_workflow`, `now`, `info`,
`patched`, `wait` and `continue_as_new`, as `test_group_workflow.py` does, and record each
command in order. The activity tests run against the fake collection database of
`ocr_store_fake.py`.
"""

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from temporalio.exceptions import ApplicationError, CancelledError

import tasks.dataset_config as dataset_config
import tasks.ocr_client as ocr_client
import tasks.ocr_pdf_client as ocr_pdf_client
from ocr_store_fake import CD, COLLECTION, FakeOcrStore
from tasks.P_admin import ocr_rerun
from tasks.P_admin import workflows as admin_workflows
from tasks.P_admin.ocr_rerun import (
    OcrRunFile, OcrRunPlanParams, OcrRunPlanWork, RerunOcrParams, SettleOcrRunTargetsResult,
)
from tasks.P3_parse_files.batch_runner import STAGE_QUEUES, BatchResult, FileResult

NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)
OP = "rerun_ocr-c_ds-1"


class ContinuedAsNew(Exception):
    def __init__(self, params):
        super().__init__("continue as new")
        self.params = params


class Temporal:
    """A fake workflow environment that answers each command by its name."""

    def __init__(self, monkeypatch, patched=True, answers=None):
        self.calls = []
        self.answers = dict(answers or {})
        self.patched = patched
        w = admin_workflows.workflow
        monkeypatch.setattr(w, "execute_activity", self.activity)
        monkeypatch.setattr(w, "execute_child_workflow", self.child)
        monkeypatch.setattr(w, "now", lambda: NOW)
        monkeypatch.setattr(w, "info", lambda: SimpleNamespace(run_id="run-1"))
        monkeypatch.setattr(w, "patched", lambda _name: self.patched)
        monkeypatch.setattr(w, "continue_as_new", self.continue_as_new)

        async def wait(pending, **kwargs):
            return await asyncio.wait(pending, **kwargs)

        monkeypatch.setattr(w, "wait", wait)

    def continue_as_new(self, params):
        raise ContinuedAsNew(params)

    def _answer(self, name, arg):
        answer = self.answers.get(name)
        if callable(answer):
            return answer(arg)
        return answer

    def activity(self, fn, arg=None, **kwargs):
        name = fn if isinstance(fn, str) else fn.__name__
        self.calls.append(("activity", name, arg, kwargs))

        async def result():
            await asyncio.sleep(0)
            return self._answer(name, arg)
        return result()

    def child(self, run, arg=None, **kwargs):
        name = run if isinstance(run, str) else run.__qualname__.split(".")[0]
        self.calls.append(("child", name, arg, kwargs))

        async def result():
            await asyncio.sleep(0)
            return self._answer(name, arg)
        return result()

    def names(self):
        return [name for _, name, _, _ in self.calls]


def params(**fields):
    return RerunOcrParams(collectionname=COLLECTION, collection_dataset=CD, op_id=OP, **fields)


def raises(error):
    def answer(_arg):
        raise error
    return answer


# ---- RerunOcr ----------------------------------------------------------------------------

def test_an_execution_from_before_the_patch_replays_the_whole_plan_path(monkeypatch):
    env = Temporal(monkeypatch, patched=False, answers={
        "reopen_plans_for_ocr_rerun": 4, "ExecutePlans": {"plans_run": 4}})
    result = asyncio.run(admin_workflows.RerunOcr().run(params()))
    assert env.names() == ["reopen_plans_for_ocr_rerun", "ExecutePlans"]
    assert env.calls[1][3]["id"] == f"ocr-rerun-execute-{OP}"
    assert env.calls[1][2].op_id == OP
    assert result == {"plans": 4, "execution_counts": {"plans_run": 4}}


def test_a_finished_dataset_with_no_open_target_starts_no_ocr(monkeypatch):
    env = Temporal(monkeypatch, answers={
        "list_pending_plans": [], "count_new_blobs": 0, "record_ocr_run_targets": 0,
        "list_ocr_run_plans": [], "verify_ocr_run_completion": 0})
    result = asyncio.run(admin_workflows.RerunOcr().run(params()))
    assert env.names() == ["list_pending_plans", "count_new_blobs", "ensure_temp_dir_exists",
                           "record_ocr_run_targets", "list_ocr_run_plans",
                           "verify_ocr_run_completion"]
    assert env.calls[0][2].op_id == ""
    assert env.calls[2][2].base_temp_dir == "/tmp/hoover4/ocr-run"
    assert result["execution_counts"] == {"plans_run": 0, "failed_plans": 0,
                                          "failed_dataset_steps": 0}


def test_unfinished_plans_run_every_stage_before_the_targets_are_recorded(monkeypatch):
    env = Temporal(monkeypatch, answers={
        "list_pending_plans": ["p1", "p2"], "count_new_blobs": 0,
        "ExecutePlans": {"plans_run": 2, "failed_plans": 1, "failed_dataset_steps": 0},
        "list_ocr_run_plans": []})
    result = asyncio.run(admin_workflows.RerunOcr().run(params()))
    names = env.names()
    assert names.index("ExecutePlans") < names.index("record_ocr_run_targets")
    execute = env.calls[names.index("ExecutePlans")]
    assert execute[2].op_id == OP and execute[3]["id"] == f"run-ocr-plans-{OP}"
    assert result["plans"] == 2
    assert result["execution_counts"]["failed_plans"] == 1


def test_unplanned_blobs_also_run_execute_plans(monkeypatch):
    env = Temporal(monkeypatch, answers={
        "list_pending_plans": [], "count_new_blobs": 3, "ExecutePlans": {"plans_run": 1},
        "list_ocr_run_plans": []})
    asyncio.run(admin_workflows.RerunOcr().run(params()))
    assert "ExecutePlans" in env.names()


def test_each_plan_with_an_open_target_runs_then_the_dataset_steps(monkeypatch):
    env = Temporal(monkeypatch, answers={
        "list_pending_plans": [], "count_new_blobs": 0,
        "list_ocr_run_plans": ["a", "b", "c"], "OcrRunPlan": {"files": 1}})
    result = asyncio.run(admin_workflows.RerunOcr().run(params()))
    children = [c for c in env.calls if c[1] == "OcrRunPlan"]
    assert [c[2].plan_hash for c in children] == ["a", "b", "c"]
    assert children[0][3]["id"] == f"run-ocr-plan-{OP}-a"
    tail = env.names()[-3:]
    assert tail == ["index_entity_terms", "compact_collection_shards",
                    "verify_ocr_run_completion"]
    for call in env.calls[-3:-1]:
        assert call[3]["task_queue"] == "processing-indexing-queue"
    assert env.calls[-2][2].closed_only is False
    assert result["targets_plans"] == 3


def test_a_full_page_continues_as_new_after_its_last_plan(monkeypatch):
    page = [f"p{i:04d}" for i in range(ocr_rerun.OCR_RUN_PAGE)]
    env = Temporal(monkeypatch, answers={
        "list_pending_plans": [], "count_new_blobs": 0, "list_ocr_run_plans": page})
    with pytest.raises(ContinuedAsNew) as continued:
        asyncio.run(admin_workflows.RerunOcr().run(params()))
    following = continued.value.params
    assert following.after == page[-1] and following.listed and following.plans == len(page)
    assert "verify_ocr_run_completion" not in env.names()


def test_a_continuation_skips_phase_one_and_verifies_after_an_empty_page(monkeypatch):
    env = Temporal(monkeypatch, answers={"list_ocr_run_plans": []})
    result = asyncio.run(admin_workflows.RerunOcr().run(
        params(listed=True, after="p0999", plans=1000)))
    assert env.names() == ["list_ocr_run_plans", "index_entity_terms",
                           "compact_collection_shards", "verify_ocr_run_completion"]
    assert env.calls[0][2].after == "p0999"
    assert result["targets_plans"] == 1000


def test_a_failed_plan_counts_and_the_other_plans_still_run(monkeypatch):
    def plan(arg):
        if arg.plan_hash == "b":
            raise ApplicationError("plan failed", type="OcrRunIncomplete")
        return {}

    env = Temporal(monkeypatch, answers={
        "list_pending_plans": [], "count_new_blobs": 0,
        "list_ocr_run_plans": ["a", "b", "c"], "OcrRunPlan": plan})
    result = asyncio.run(admin_workflows.RerunOcr().run(params()))
    assert [c[2].plan_hash for c in env.calls if c[1] == "OcrRunPlan"] == ["a", "b", "c"]
    assert result["execution_counts"]["failed_plans"] == 1


def test_a_cancelled_plan_cancels_the_run(monkeypatch):
    env = Temporal(monkeypatch, answers={
        "list_pending_plans": [], "count_new_blobs": 0, "list_ocr_run_plans": ["a"],
        "OcrRunPlan": raises(CancelledError("cancelled"))})
    with pytest.raises(CancelledError):
        asyncio.run(admin_workflows.RerunOcr().run(params()))
    assert "verify_ocr_run_completion" not in env.names()


def test_an_open_target_after_normal_plans_fails_the_run(monkeypatch):
    env = Temporal(monkeypatch, answers={
        "list_pending_plans": [], "count_new_blobs": 0, "list_ocr_run_plans": ["a"],
        "verify_ocr_run_completion": raises(
            ApplicationError("1 of 3 OCR targets are not done", type="OcrRunIncomplete",
                             non_retryable=True))})
    with pytest.raises(ApplicationError, match="not done"):
        asyncio.run(admin_workflows.RerunOcr().run(params()))


# ---- OcrRunPlan --------------------------------------------------------------------------

def plan_params():
    return OcrRunPlanParams(COLLECTION, CD, OP, "plan-1")


def image(h, engines=("tesseract",)):
    return OcrRunFile(item_hash=h, file_size_bytes=10, s3_url=f"s3://b/{h}",
                      mime_types=["image/png"], image_engines=list(engines))


def pdf(h, engines=("tesseract",)):
    return OcrRunFile(item_hash=h, file_size_bytes=20, s3_url=f"s3://b/{h}",
                      mime_types=["application/pdf"], pdf_engines=list(engines))


def batch(status="ok"):
    def answer(arg):
        return BatchResult(stage="x", results=[
            FileResult(item_hash=f.item_hash, task_name="t", status=status,
                       error_type="Broken" if status == "failed" else "",
                       error_message="broken" if status == "failed" else "",
                       non_retryable=status == "failed")
            for f in arg.files])
    return answer


def run_plan(monkeypatch, work, pending=(), remaining=0, ocr_status="ok"):
    env = Temporal(monkeypatch, answers={
        "load_ocr_run_plan": work,
        "download_plan_files": {"out_dir": "/tmp/hoover4/ocr-run/c_ds/plan-1"},
        "make_image_preview_batch": batch("skipped"),
        "run_ocr_batch": batch(ocr_status),
        "run_ocr_pdf_batch": batch(),
        "ocr_text_pending_index": lambda arg: [h for h in arg.hashes if h in pending],
        "settle_ocr_run_targets": lambda arg: SettleOcrRunTargetsResult(
            settled=1, remaining=remaining if not arg.hashes else 0),
    })
    asyncio.run(admin_workflows.OcrRunPlan().run(plan_params()))
    return env


def test_a_plan_with_nothing_open_only_loads_and_settles(monkeypatch):
    env = run_plan(monkeypatch, OcrRunPlanWork())
    assert env.names() == ["load_ocr_run_plan", "settle_ocr_run_targets"]
    assert env.calls[1][2].hashes == []


def test_images_and_a_pdf_run_their_stages_on_the_stage_queues(monkeypatch):
    work = OcrRunPlanWork(files=[image("i1"), image("i2"), pdf("d1")])
    env = run_plan(monkeypatch, work)
    names = env.names()
    download = env.calls[names.index("download_plan_files")][2]
    assert [item["item_hash"] for item in download.items] == ["i1", "i2", "d1"]
    assert download.base_temp_dir == "/tmp/hoover4/ocr-run"
    assert names.index("make_image_preview_batch") < names.index("run_ocr_batch")
    for call in env.calls:
        if call[1] in STAGE_QUEUES:
            assert call[3]["task_queue"] == STAGE_QUEUES[call[1]]
    ocr = env.calls[names.index("run_ocr_batch")][2]
    assert [f.item_hash for f in ocr.files] == ["i1", "i2"] and ocr.engine == "tesseract"
    assert ocr.files[0].file_path == "/tmp/hoover4/ocr-run/c_ds/plan-1/i1"
    pdf_call = env.calls[names.index("run_ocr_pdf_batch")]
    assert [f.item_hash for f in pdf_call[2].files] == ["d1"]
    assert pdf_call[3]["task_queue"] == "processing-ocr-pdf-queue"
    preview = env.calls[names.index("make_image_preview_batch")][2]
    assert preview.files[0].routes == ["image"] and preview.files[0].mime_types == ["image/png"]
    # The index targets of new text are recorded before the group settles its targets.
    assert names.index("ocr_text_pending_index") < names.index("settle_ocr_run_targets")
    group_settle = env.calls[names.index("settle_ocr_run_targets")][2]
    assert group_settle.hashes == ["i1", "i2", "d1"]
    assert names[-2:] == ["settle_ocr_run_targets", "cleanup_plan_dir"]


def test_new_ocr_text_runs_p4_and_p5_then_p6_for_that_image_only(monkeypatch):
    work = OcrRunPlanWork(files=[image("i1"), image("i2")])
    env = run_plan(monkeypatch, work, pending={"i2"})
    names = env.names()
    children = [c for c in env.calls if c[0] == "child"]
    assert [c[1] for c in children] == ["ExtractEntitiesForPlan", "ScanRegexEntitiesForPlan",
                                        "ChunkEmbedForPlan", "IndexDatasetPlan"]
    for child in children:
        assert child[2].item_hashes == ["i2"] and child[2].op_id == OP
    assert children[3][3]["id"] == f"run-ocr-index-{OP}-plan-1"
    assert names.index("IndexDatasetPlan") < len(names) - 2
    assert names[-2:] == ["settle_ocr_run_targets", "cleanup_plan_dir"]
    assert "resolve_document_dates" not in names
    assert "resolve_canonical_file_type" not in names


def test_index_targets_alone_need_no_download(monkeypatch):
    env = run_plan(monkeypatch, OcrRunPlanWork(index_hashes=["i9"]), pending={"i9"})
    assert "download_plan_files" not in env.names()
    assert [c[1] for c in env.calls if c[0] == "child"][-1] == "IndexDatasetPlan"


def test_no_pending_text_runs_no_text_step(monkeypatch):
    env = run_plan(monkeypatch, OcrRunPlanWork(files=[image("i1")]))
    assert not [c for c in env.calls if c[0] == "child"]


def test_a_failed_image_records_one_error_row_with_the_operation(monkeypatch):
    env = run_plan(monkeypatch, OcrRunPlanWork(files=[image("i1")]), ocr_status="failed")
    records = [c[2] for c in env.calls if c[1] == "record_processing_errors"]
    rows = [row for record in records for row in record.errors]
    assert [(r["hash"], r["task_name"], r["op_id"]) for r in rows] == [
        ("i1", "run_ocr_and_store[tesseract]", OP)]


def test_a_skipped_image_records_no_error(monkeypatch):
    env = run_plan(monkeypatch, OcrRunPlanWork(files=[image("i1")]), ocr_status="skipped")
    assert "record_processing_errors" not in env.names()


def test_groups_of_100_and_their_error_sources_are_unique(monkeypatch):
    files = [image(f"i{n:03d}") for n in range(250)]
    env = run_plan(monkeypatch, OcrRunPlanWork(files=files), ocr_status="failed")
    ocr_calls = [c[2] for c in env.calls if c[1] == "run_ocr_batch"]
    assert sorted(len(c.files) for c in ocr_calls) == [50, 100, 100]
    rows = [row for c in env.calls if c[1] == "record_processing_errors" for row in c[2].errors]
    identities = [row["error_identity"] for row in rows]
    assert len(rows) == 250 and len(set(identities)) == 250


def test_an_open_target_after_the_plan_work_fails_the_plan(monkeypatch):
    with pytest.raises(ApplicationError) as failed:
        run_plan(monkeypatch, OcrRunPlanWork(files=[image("i1")]), remaining=1)
    assert failed.value.type == "OcrRunIncomplete"


# ---- the ledger activities ---------------------------------------------------------------

@pytest.fixture
def store(monkeypatch):
    store = FakeOcrStore()
    import database.clickhouse as clickhouse

    monkeypatch.setattr(clickhouse, "get_collection_client", store.client)
    monkeypatch.setattr(ocr_client, "engine_configured", lambda e: e == "tesseract")
    monkeypatch.setattr(ocr_pdf_client, "service_configured", lambda: True)
    monkeypatch.setattr(ocr_pdf_client, "engines_for_provider", lambda: ["tesseract"])
    rows = {"ocr.tesseract.languages": dataset_config.SettingRow("eng", False, 100_100_000, True)}
    monkeypatch.setattr(dataset_config, "latest_setting_rows",
                        lambda _cd, keys: {k: v for k, v in rows.items() if k in keys})
    return store


def test_recording_writes_only_the_open_targets_with_their_setting_version(store):
    store.add_image("i1")
    store.add_image("i2")
    store.add_pdf("d1", plan="p2")
    store.raw.append((CD, "i2", "tesseract", "eng", json.dumps({"text": ""})))
    assert ocr_rerun.record_ocr_run_targets(params()) == 2
    rows = store.open_targets(OP)
    assert {(k[2], k[3], r["plan_hash"]) for k, r in rows.items()} == {
        ("i1", "image", "p1"), ("d1", "pdf", "p2")}
    assert {r["since_us"] for r in rows.values()} == {100_100_000}
    assert {r["since_is_precise"] for r in rows.values()} == {1}
    # A retry computes the same rows and opens nothing new.
    assert ocr_rerun.record_ocr_run_targets(params()) == 2
    assert len(store.open_targets(OP)) == 2


def test_the_plan_list_pages_after_the_cursor(store):
    for plan in ("p1", "p2", "p3"):
        store.add_image(f"i-{plan}", plan=plan)
    ocr_rerun.record_ocr_run_targets(params())
    listed = ocr_rerun.list_ocr_run_plans(ocr_rerun.ListOcrRunPlansParams(COLLECTION, CD, OP, "p1"))
    assert listed == ["p2", "p3"]


def test_loading_settles_done_targets_and_returns_the_open_work(store):
    store.add_image("i1")
    store.add_image("i2")
    store.add_pdf("d1")
    store.plan_hits.append((CD, "x", "p1"))
    ocr_rerun.record_ocr_run_targets(params())
    # i2 got its result after the recording, from a cancelled earlier run.
    store.raw.append((CD, "i2", "tesseract", "eng", json.dumps({"text": "late text"})))
    import tasks.P2_execute_plan.activities as plan_activities

    store_items = [{"item_hash": h, "file_size_bytes": 5, "s3_url": f"s3://b/{h}",
                    "file_names": []} for h in ("d1", "i1", "i2")]
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(plan_activities, "get_plan_items_metadata", lambda _p: store_items)
        work = ocr_rerun.load_ocr_run_plan(OcrRunPlanParams(COLLECTION, CD, OP, "p1"))
    assert [(f.item_hash, f.image_engines, f.pdf_engines) for f in work.files] == [
        ("d1", [], ["tesseract"]), ("i1", ["tesseract"], [])]
    assert work.files[1].mime_types == ["image/png"]
    # The stored result of i2 gave its text, so it needs indexing without OCR.
    assert work.index_hashes == ["i2"]
    assert ("i2", "image") not in {(k[2], k[3]) for k in store.open_targets(OP)}


def test_settlement_counts_what_stays_open(store):
    store.add_image("i1")
    store.add_image("i2")
    ocr_rerun.record_ocr_run_targets(params())
    store.skips.append((CD, "i1", "image", "tesseract", "eng"))
    result = ocr_rerun.settle_ocr_run_targets(
        ocr_rerun.SettleOcrRunTargetsParams(COLLECTION, CD, OP, "p1"))
    assert (result.settled, result.remaining) == (1, 1)
    group = ocr_rerun.settle_ocr_run_targets(
        ocr_rerun.SettleOcrRunTargetsParams(COLLECTION, CD, OP, "p1", ["i1"]))
    assert (group.settled, group.remaining) == (0, 0)


def test_new_text_adds_an_index_target_once_and_indexing_settles_it(store):
    store.add_image("i1")
    ocr_rerun.record_ocr_run_targets(params())
    assert len(store.open_targets(OP)) == 1
    store.raw.append((CD, "i1", "tesseract", "eng", json.dumps({"text": "page"})))
    store.text.append((CD, "i1", "ocr_tesseract_eng", 1, "page", 5_300_000_000))
    pending_params = ocr_rerun.OcrTextPendingParams(COLLECTION, CD, OP, "p1", ["i1"])
    assert ocr_rerun.ocr_text_pending_index(pending_params) == ["i1"]
    assert ocr_rerun.ocr_text_pending_index(pending_params) == ["i1"]
    stages = sorted(k[3] for k in store.open_targets(OP))
    assert stages == ["image", "index"]
    # The total grew from 1 to 2 before the image target settles.
    totals = store.query("SELECT count() AS targets_total FROM ocr_run_targets FINAL",
                         {"op": OP, "cd": CD}).result_rows[0]
    assert totals == (2, 0)
    ocr_rerun.settle_ocr_run_targets(
        ocr_rerun.SettleOcrRunTargetsParams(COLLECTION, CD, OP, "p1", ["i1"]))
    assert [k[3] for k in store.open_targets(OP)] == ["index"]
    store.index_state.append((CD, "i1"))
    store.receipts.append((CD, "i1", "ocr_tesseract_eng", 1, 5_300_000_000, 1))
    # After indexing, the same call reopens nothing.
    assert ocr_rerun.ocr_text_pending_index(pending_params) == []
    result = ocr_rerun.settle_ocr_run_targets(
        ocr_rerun.SettleOcrRunTargetsParams(COLLECTION, CD, OP, "p1"))
    assert result.remaining == 0
    assert ocr_rerun.ocr_text_pending_index(pending_params) == []
    assert store.open_targets(OP) == {}


def test_verification_fails_with_bounded_samples_while_a_target_is_open(store):
    for n in range(8):
        store.add_image(f"i{n}")
    ocr_rerun.record_ocr_run_targets(params())
    with pytest.raises(ApplicationError) as failed:
        ocr_rerun.verify_ocr_run_completion(ocr_rerun.VerifyOcrRunParams(COLLECTION, CD, OP))
    assert failed.value.type == "OcrRunIncomplete" and failed.value.non_retryable
    assert failed.value.message.startswith("8 of 8 OCR targets are not done")
    assert str(failed.value).count("plan p1 file") == ocr_rerun.OCR_RUN_SAMPLES
    for n in range(8):
        store.skips.append((CD, f"i{n}", "image", "tesseract", "eng"))
    ocr_rerun.settle_ocr_run_targets(ocr_rerun.SettleOcrRunTargetsParams(COLLECTION, CD, OP, "p1"))
    assert ocr_rerun.verify_ocr_run_completion(
        ocr_rerun.VerifyOcrRunParams(COLLECTION, CD, OP)) == 8
