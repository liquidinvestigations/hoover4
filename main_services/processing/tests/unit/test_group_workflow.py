"""The batched group workflow: which stage activities it schedules, and its Error rows.

`workflow.execute_activity`, `now` and `info` are patched. A stage activity is scheduled
by its registered name, and the fake answers it with one `FileResult` for each file. The
real error recorder runs, and the fake keeps the rows of each record activity.
"""

import ast
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, RetryState

from tasks.P2_execute_plan import workflows as plan_workflows
from tasks.P2_execute_plan.activities import record_processing_errors
from tasks.P3_parse_files import batch_runner as br
from tasks.P3_parse_files.parse_mime import LOCAL_DETECTORS
from tasks.text_sources import OCR_ENGINES

PROCESSING_ROOT = Path(__file__).parents[2]
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
REMOVED_WORKFLOWS = {"ParseSingleFile", "EmailExtractionAndScan", "ArchiveExtractionAndScan",
                     "PdfProcessingAndScan", "VideoProcessingAndScan"}


def _ok(file, value):
    return br.FileResult(item_hash=file.item_hash, task_name="step", status="ok", value=value)


def _failed(file, error_type="Broken", message="broken"):
    return br.FileResult(item_hash=file.item_hash, task_name="step", status="failed",
                         error_type=error_type, error_message=message, non_retryable=True)


def _activity_error(cause):
    error = ActivityError("activity failed", scheduled_event_id=1, started_event_id=2,
                          identity="worker", activity_type="stage", activity_id="1",
                          retry_state=RetryState.NON_RETRYABLE_FAILURE)
    error.__cause__ = cause
    return error


class _Group:
    """A fake stage fleet for one group, with the types that each file's detectors find."""

    def __init__(self, monkeypatch, types, run_id="group-run"):
        self.types = types
        self.calls = []
        self.records = []
        self.overrides = {}
        monkeypatch.setattr(plan_workflows.workflow, "execute_activity", self.execute_activity)
        monkeypatch.setattr(plan_workflows.workflow, "execute_child_workflow",
                            lambda *a, **k: pytest.fail("the group started a child workflow"))
        monkeypatch.setattr(plan_workflows.workflow, "now", lambda: NOW)
        monkeypatch.setattr(plan_workflows.workflow, "info",
                            lambda: SimpleNamespace(run_id=run_id))

    def _types(self, file):
        coarse, mimes = self.types[file.item_hash]
        return {"coarse_types": list(coarse), "mime_types": list(mimes)}

    def default(self, name, file):
        if name == "detect_mime_batch":
            return _ok(file, {"detectors": {d: self._types(file) for d in LOCAL_DETECTORS},
                              "errors": {}})
        if name == "run_tika_batch":
            return _ok(file, self._types(file))
        if name == "extract_email_attachments_batch":
            return _ok(file, {"out_dir": f"/tmp/email_{file.item_hash}", "attachment_count": 1})
        if name == "extract_archive_batch":
            return _ok(file, {"out_dir": f"/tmp/extract_{file.item_hash}", "entry_count": 2})
        if name == "pdf_metadata_batch":
            return _ok(file, {"page_count": 3, "size_bytes": 10})
        if name in ("pdf_extract_batch", "video_batch"):
            return _ok(file, {"out_dir": f"/tmp/{name}_{file.item_hash}"})
        if name == "scan_container_folders":
            return br.FileResult(item_hash=file.container_hash, task_name="scan_folder_tree",
                                 status="ok", value={"status": "scanned"})
        return _ok(file, {"ok": name})

    def execute_activity(self, name, arg, **options):
        async def result():
            if name is record_processing_errors:
                self.records.append(arg.errors)
                return len(arg.errors)
            self.calls.append((name, arg, options))
            items = arg.folders if name == "scan_container_folders" else arg.files
            override = self.overrides.get(name)
            if isinstance(override, BaseException):
                raise override
            return br.BatchResult(stage=name, results=[
                self.default(name, item) if override is None else override(item)
                for item in items])
        return result()

    def run(self, hashes, sizes=None):
        items = [{"item_hash": h, "file_size_bytes": (sizes or {}).get(h, 0)} for h in hashes]
        params = plan_workflows.ProcessItemsBatchedParams(
            "collection", "dataset", "plan", "/tmp/plan", items, "op")
        return asyncio.run(plan_workflows.ProcessItemsBatched().run(params))

    def scheduled(self, name, engine=None):
        return [arg for called, arg, _ in self.calls
                if called == name and (engine is None or arg.engine == engine)]

    def hashes(self, name, engine=None):
        [arg] = self.scheduled(name, engine)
        if name == "scan_container_folders":
            return [folder.container_hash for folder in arg.folders]
        return [file.item_hash for file in arg.files]

    def rows(self):
        return [(row["hash"], row["task_name"]) for rows in self.records for row in rows]


EMAIL = (["email", "text"], ["message/rfc822"])
PDF = (["pdf"], ["application/pdf"])
IMAGE = (["image"], ["image/png"])
TEXT = (["text"], ["text/plain"])
ARCHIVE = (["archive"], ["application/zip"])
VIDEO = (["video"], ["video/mp4"])


# Scheduling.

def test_three_files_schedule_each_stage_once_with_its_files_and_queue(monkeypatch):
    group = _Group(monkeypatch, {"e": EMAIL, "p": PDF, "i": IMAGE})
    assert group.run(["e", "p", "i"], sizes={"e": 1250, "p": 2500}) == "processed 3 items"

    expected = {
        "detect_mime_batch": ["e", "p", "i"],
        "run_tika_batch": ["e", "p", "i"],
        "extract_plaintext_batch": ["e"],
        "parse_image_metadata_batch": ["i"],
        "parse_email_headers_batch": ["e"],
        "extract_email_attachments_batch": ["e"],
        "pdf_metadata_batch": ["p"],
        "pdf_extract_batch": ["p"],
        "scan_container_folders": ["e", "p"],
    }
    for name, hashes in expected.items():
        assert group.hashes(name) == hashes, name
    for engine in OCR_ENGINES:
        assert group.hashes("run_ocr_batch", engine) == ["i"]
        assert group.hashes("run_ocr_pdf_batch", engine) == ["p"]
    assert len(group.calls) == len(expected) + 2 * len(OCR_ENGINES)

    for name, arg, options in group.calls:
        assert options["task_queue"] == br.STAGE_QUEUES[name]
        assert options["retry_policy"] == RetryPolicy(maximum_attempts=0)
        assert options["result_type"] is br.BatchResult
        if name == "scan_container_folders":
            seconds = br.folder_stage_timeout_seconds(arg.folders)
        else:
            seconds = br.stage_timeout_seconds(name, [f.file_size_bytes for f in arg.files])
        assert options["start_to_close_timeout"].total_seconds() == seconds
        assert arg.op_id == "op"
    [pdf_file] = group.scheduled("pdf_extract_batch")[0].files
    assert (pdf_file.page_count, pdf_file.pdf_size_bytes) == (3, 10)
    assert group.rows() == []


def test_zero_items_schedule_nothing(monkeypatch):
    group = _Group(monkeypatch, {})
    assert group.run([]) == "no items"
    assert group.calls == []


@pytest.mark.parametrize("attachments,activities", [(0, 5), (1, 6)])
def test_100_emails_take_five_activities_and_six_with_an_attachment(
        monkeypatch, attachments, activities):
    hashes = [f"m{index}" for index in range(100)]
    group = _Group(monkeypatch, {h: EMAIL for h in hashes})
    group.overrides["extract_email_attachments_batch"] = lambda f: _ok(
        f, {"out_dir": f"/tmp/email_{f.item_hash}",
            "attachment_count": attachments if f.item_hash == "m0" else 0})
    group.run(hashes)
    assert len(group.calls) == activities


def test_a_failed_tika_stage_leaves_the_routes_to_the_local_detectors(monkeypatch):
    group = _Group(monkeypatch, {"t": TEXT})
    group.overrides["run_tika_batch"] = _activity_error(ApplicationError(
        "stuck", type=br.STAGE_NO_PROGRESS, non_retryable=True))
    group.run(["t"])
    assert group.hashes("extract_plaintext_batch") == ["t"]
    assert group.rows() == [("t", "detector_error_tika")]


def test_a_file_whose_headers_fail_is_not_in_the_attachments_input(monkeypatch):
    group = _Group(monkeypatch, {"a": EMAIL, "b": EMAIL})
    group.overrides["parse_email_headers_batch"] = (
        lambda f: _failed(f) if f.item_hash == "a" else _ok(f, {}))
    group.run(["a", "b"])
    assert group.hashes("extract_email_attachments_batch") == ["b"]
    assert ("a", "email_scan") in group.rows()


def test_only_an_extraction_that_succeeded_with_members_reaches_the_scan(monkeypatch):
    group = _Group(monkeypatch, {"x": ARCHIVE, "y": ARCHIVE, "z": ARCHIVE})
    group.overrides["extract_archive_batch"] = lambda f: {
        "x": _ok(f, {"out_dir": "/tmp/extract_x", "entry_count": 2, "member_count": 700}),
        "y": _ok(f, {"out_dir": "/tmp/extract_y", "entry_count": 0}),
        "z": _failed(f),
    }[f.item_hash]
    group.run(["x", "y", "z"])
    [scan] = group.scheduled("scan_container_folders")
    assert [(d.container_hash, d.error_task_name, d.member_count) for d in scan.folders] == [
        ("x", "archive_scan", 700)]
    [archive] = group.scheduled("extract_archive_batch")
    assert archive.files[0].mime_types == ["application/zip"]


# The catch point.

@pytest.mark.parametrize("stage,types,error_name,later", [
    ("parse_email_headers_batch", EMAIL, "email_scan", ["extract_email_attachments_batch"]),
    ("extract_archive_batch", ARCHIVE, "archive_scan", []),
    ("pdf_metadata_batch", PDF, "pdf_process", ["pdf_extract_batch", "run_ocr_pdf_batch"]),
    ("video_batch", VIDEO, "video_process", []),
])
def test_a_failed_chain_stage_gives_each_file_the_chain_error(
        monkeypatch, stage, types, error_name, later):
    group = _Group(monkeypatch, {"a": types, "b": types})
    group.overrides[stage] = _activity_error(ApplicationError(
        "stuck", type=br.STAGE_NO_PROGRESS, non_retryable=True))
    group.run(["a", "b"])
    assert [row for row in group.rows() if row[1] == error_name] == [
        ("a", error_name), ("b", error_name)]
    for name in later + ["scan_container_folders"]:
        assert group.scheduled(name) == []


def test_a_failed_stage_keeps_the_files_that_its_last_detail_lists_as_finished(monkeypatch):
    group = _Group(monkeypatch, {h: TEXT for h in "abc"})
    stage = "extract_plaintext_batch"
    row = {"task_name": "extract_plaintext_chunks", "status": "ok", "value": {"ok": 1}}
    detail = {"v": br.BATCH_DETAIL_VERSION, "stage": stage,
              "keys": br.stage_keys_digest(["a", "b", "c"]), "att": 5, "prog": 1,
              "done": [{"i": 0, **row}, {"i": 1, **row}], "wait": [], "run": None, "lost": {}}
    group.overrides[stage] = _activity_error(ApplicationError(
        "stuck", detail, type=br.STAGE_NO_PROGRESS, non_retryable=True))
    group.run(["a", "b", "c"])
    assert group.rows() == [("c", "extract_plaintext_chunks")]


def test_an_error_in_chain_code_fails_the_group_without_error_rows(monkeypatch):
    group = _Group(monkeypatch, {"t": TEXT})

    def broken(_types):
        raise KeyError("coarse_types")

    monkeypatch.setattr(plan_workflows, "route_stages", broken)
    with pytest.raises(KeyError):
        group.run(["t"])
    assert group.records == []


# Error rows.

def test_a_tika_parse_failure_beside_a_text_parse_gives_one_parse_error_tika_row(monkeypatch):
    rows = []
    for _ in range(2):
        group = _Group(monkeypatch, {h: TEXT for h in "abc"}, run_id="run")
        group.overrides["run_tika_batch"] = lambda f: (
            _failed(f, "TikaParseFailed", "extractous refused it") if f.item_hash == "b"
            else _ok(f, group._types(f)))
        group.run(["a", "b", "c"])
        rows.append([row for batch in group.records for row in batch])
    assert [(row["hash"], row["task_name"], row["op_id"]) for row in rows[0]] == [
        ("b", "parse_error_tika", "op")]
    source = plan_workflows.source_execution_id("run", "P3.group.detector", 9)
    expected = hashlib.sha256(json.dumps(
        [source, "parse_error_tika", "dataset", "b"], ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    assert rows[0][0]["error_identity"] == expected
    assert rows[1][0]["error_identity"] == expected


def test_a_missing_copy_for_every_detector_gives_one_row(monkeypatch):
    group = _Group(monkeypatch, {"a": TEXT})
    missing = lambda f: _failed(f, "TempCopyMissing", "temporary copy is gone")
    group.overrides["detect_mime_batch"] = missing
    group.overrides["run_tika_batch"] = missing
    group.run(["a"])
    assert group.rows() == [("a", f"detector_error_{LOCAL_DETECTORS[0]}")]


def test_a_stage_attempt_lost_result_gives_one_row_under_the_stage_error_name(monkeypatch):
    group = _Group(monkeypatch, {"a": TEXT, "b": TEXT})
    group.overrides["extract_plaintext_batch"] = lambda f: (
        _failed(f, br.STAGE_ATTEMPT_LOST, "2 attempts ended") if f.item_hash == "a"
        else _ok(f, {}))
    group.run(["a", "b"])
    assert group.rows() == [("a", "extract_plaintext_chunks")]


def test_parser_ids_count_every_entry_of_the_group(monkeypatch):
    group = _Group(monkeypatch, {"p": PDF, "i": IMAGE}, run_id="run")
    failing = lambda f: _failed(f)
    group.overrides["run_ocr_batch"] = failing
    group.overrides["run_ocr_pdf_batch"] = failing
    group.run(["p", "i"])
    [rows] = group.records[-1:]
    names = [(row["hash"], row["task_name"]) for row in rows]
    assert names == (
        [("p", f"run_ocr_pdf_and_store[{e}]") for e in OCR_ENGINES]
        + [("i", f"run_ocr_and_store[{e}]") for e in OCR_ENGINES])


# Registrations.

def _workers():
    tree = ast.parse((PROCESSING_ROOT / "tasks/run_worker.py").read_text())
    workers = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Worker":
            options = {kw.arg: kw.value for kw in node.keywords}
            queue = options.get("task_queue")
            if not isinstance(queue, ast.Constant):
                continue
            names = lambda key: {n.id for n in ast.walk(options[key]) if isinstance(n, ast.Name)} \
                if key in options else set()
            workers[queue.value] = (names("workflows"), names("activities"))
    return workers


def test_every_stage_activity_is_registered_on_the_worker_of_its_queue():
    workers = _workers()
    for name, queue in br.STAGE_QUEUES.items():
        assert name in workers[queue][1], f"{name} is not registered on {queue}"


def test_no_removed_workflow_type_is_registered_and_handle_folders_stays():
    workers = _workers()
    registered = set().union(*(flows for flows, _ in workers.values()))
    assert not registered & REMOVED_WORKFLOWS
    assert "HandleFolders" in workers["processing-common-queue"][0]
    assert "ProcessItemsBatched" in workers["processing-common-queue"][0]
