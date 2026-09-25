"""The member scan of one group: each container folder is scanned in process, then removed.

The first tests patch the two disk scan functions and check the loop and the folder rules.
The last tests run the real `scan_folder_range` over a temporary folder inside an activity
context, and check that its file cursor goes through the batch heartbeat.
"""

import dataclasses

import pytest
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from tasks.P0_scan_disk import activities as disk
from tasks.P0_scan_disk.activities import FolderRanges, RangeResult
from tasks.P3_parse_files import batch_runner, member_scan
from tasks.P3_parse_files.batch_runner import ContainerFolder, ScanContainerFoldersParams


def _params(*folders):
    return ScanContainerFoldersParams(collectionname="c", collection_dataset="c_d",
                                      plan_hash="plan", folders=list(folders), op_id="op-1")


def _folder(path, container_hash="h1", member_count=0):
    return ContainerFolder(container_hash=container_hash, out_dir=str(path),
                           error_task_name="archive_scan", source_size_bytes=100,
                           member_count=member_count)


@pytest.fixture
def scan_calls(monkeypatch):
    """Patch plan and scan. The folder "/" has one subfolder "/sub"."""
    calls = []

    def plan(params):
        calls.append(("plan", params.folder_path, params.after_name, params.container_hash))
        return FolderRanges([], "")

    def scan(params):
        folder = params.folder
        calls.append(("scan", folder.folder_path, folder.after_name, params.until_name,
                      folder.dataset_path, folder.container_hash))
        return RangeResult(["/sub"] if folder.folder_path == "/" else [], 1, 0)

    monkeypatch.setattr(member_scan, "plan_folder_ranges", plan)
    monkeypatch.setattr(member_scan, "scan_folder_range", scan)
    return calls


def test_nested_folder_is_scanned_then_removed(tmp_path, scan_calls):
    out_dir = tmp_path / "extract_h1"
    (out_dir / "sub").mkdir(parents=True)
    (out_dir / "sub" / "m.txt").write_text("m")

    batch = member_scan.scan_container_folders(_params(_folder(out_dir)))

    assert batch.stage == "scan_container_folders"
    result = batch.results[0]
    assert (result.status, result.value, result.task_name) == (
        "ok", {"status": "scanned"}, "scan_folder_tree")
    assert scan_calls == [
        ("plan", "/", "", "h1"),
        ("scan", "/", "", "", str(out_dir), "h1"),
        ("plan", "/sub", "", "h1"),
        ("scan", "/sub", "", "", str(out_dir), "h1"),
    ]
    assert not out_dir.exists()


def test_gone_folder_fails_with_container_folder_missing(tmp_path, scan_calls):
    batch = member_scan.scan_container_folders(_params(_folder(tmp_path / "email_h1")))

    result = batch.results[0]
    assert result.status == "failed"
    assert result.error_type == "ContainerFolderMissing"
    assert result.attempts == 1
    assert scan_calls == []


def test_failed_scan_leaves_the_folder(tmp_path, monkeypatch):
    out_dir = tmp_path / "pdf_h1"
    out_dir.mkdir()
    monkeypatch.setattr(member_scan, "plan_folder_ranges", lambda _p: FolderRanges([], ""))

    def scan(_params):
        raise ApplicationError("unreadable member", type="ScanFailed", non_retryable=True)

    monkeypatch.setattr(member_scan, "scan_folder_range", scan)
    batch = member_scan.scan_container_folders(_params(_folder(out_dir)))

    result = batch.results[0]
    assert result.status == "failed" and result.error_type == "ScanFailed"
    assert out_dir.is_dir()


def test_results_follow_folder_order_for_one_hash(tmp_path, scan_calls):
    """One file can extract two folders with one hash. Each keeps its own result."""
    present = tmp_path / "email_h1"
    present.mkdir()
    batch = member_scan.scan_container_folders(_params(
        _folder(tmp_path / "extract_h1"), _folder(present)))

    assert [r.status for r in batch.results] == ["failed", "ok"]
    assert [r.item_hash for r in batch.results] == ["h1", "h1"]


def test_plan_continues_from_its_last_boundary(tmp_path, monkeypatch):
    """A plan that stops at a boundary is planned again from it, as HandleFolders continues."""
    plans = iter([FolderRanges(["b", "d"], "d"), FolderRanges([], "")])
    ranges = []
    monkeypatch.setattr(member_scan, "plan_folder_ranges", lambda _p: next(plans))
    monkeypatch.setattr(
        member_scan, "scan_folder_range",
        lambda p: ranges.append((p.folder.after_name, p.until_name)) or RangeResult([], 0, 0))

    member_scan.scan_folder_tree("c", "c_d", str(tmp_path), "h1")

    assert ranges == [("", "b"), ("b", "d"), ("d", "")]


def test_folder_budget_follows_the_member_count():
    small = batch_runner.member_scan_seconds(_folder("/x", member_count=500))
    large = batch_runner.member_scan_seconds(_folder("/x", member_count=501))
    assert large - small == batch_runner.MEMBER_SCAN_RANGE_SECONDS


# The file cursor of the real scan_folder_range.

def _members(path, names):
    path.mkdir(parents=True, exist_ok=True)
    for name in names:
        (path / name).write_text(name)


@pytest.fixture
def ingested(monkeypatch):
    """Patch the two writers of scan_folder_range, and record the file paths it ingests."""
    paths = []
    monkeypatch.setattr(disk, "insert_vfs_directories", lambda _p: 0)
    monkeypatch.setattr(disk, "ingest_files_batch",
                        lambda p: paths.extend(p.file_paths) or "ok")
    return paths


def test_cursor_heartbeat_follows_the_batch_detail(tmp_path, ingested):
    out_dir = tmp_path / "extract_h1"
    _members(out_dir, ["a", "b"])
    beats = []
    env = ActivityEnvironment()
    env.on_heartbeat = lambda *details: beats.append(details)

    batch = env.run(member_scan.scan_container_folders, _params(_folder(out_dir)))

    assert batch.results[0].status == "ok"
    assert ingested == ["/a", "/b"]
    cursor = [beat for beat in beats if len(beat) == 2]
    assert cursor, beats
    detail, cursor_detail = cursor[-1]
    assert detail["stage"] == "scan_container_folders" and detail["run"][0] == 0
    assert cursor_detail == {"last_file_name": "b"}


def test_retry_of_another_folder_scans_its_whole_range(tmp_path, ingested):
    """The cursor of a range inside the member scan is never details[0], so it is not read."""
    _members(tmp_path, ["a", "n", "z"])
    stage_detail = {"v": batch_runner.BATCH_DETAIL_VERSION, "stage": "scan_container_folders",
                    "keys": "0000000000000000", "att": 1, "prog": 0, "done": [],
                    "wait": [], "run": [0, 1, 0], "lost": {}}
    env = ActivityEnvironment()
    env.info = dataclasses.replace(env.info, attempt=2,
                                   heartbeat_details=[stage_detail, {"last_file_name": "m"}])
    folder = disk.ListDiskFolderParams("c", "c_d", str(tmp_path), "/", "", "h1", "")

    result = env.run(disk.scan_folder_range, disk.ScanFolderRangeParams(folder, ""))

    assert result.files_ingested == 3
    assert ingested == ["/a", "/n", "/z"]
