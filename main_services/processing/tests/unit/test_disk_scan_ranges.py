"""Disk scan ranges keep workflow inputs bounded by entry names."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tasks.P0_scan_disk import activities, workflows


def _params(tmp_path, after_name=""):
    return activities.ListDiskFolderParams(
        "collection", "dataset", str(tmp_path), "/", after_name,
    )


def _scan(tmp_path, after_name="", until_name=""):
    return activities.ScanFolderRangeParams(_params(tmp_path, after_name), until_name)


def test_folder_range_boundaries_and_limit(tmp_path, monkeypatch):
    for index in range(1250):
        (tmp_path / f"file-{index:04d}").write_text("x")

    plan = activities.plan_folder_ranges(_params(tmp_path))
    assert plan.boundaries == ["file-0499", "file-0999"]
    assert plan.more_after == ""

    monkeypatch.setattr(activities, "MAX_BOUNDARIES", 2)
    limited = activities.plan_folder_ranges(_params(tmp_path))
    assert limited.boundaries == ["file-0499", "file-0999"]
    assert limited.more_after == "file-0999"


def test_range_edges_open_end_and_added_file(tmp_path, monkeypatch):
    for name in ("a", "b", "c"):
        (tmp_path / name).write_text(name)
    batches = []
    monkeypatch.setattr(activities, "insert_vfs_directories", lambda _params: 0)
    monkeypatch.setattr(activities, "ingest_files_batch", lambda params: batches.append(params) or "ok")

    closed = activities.scan_folder_range(_scan(tmp_path, "a", "b"))
    assert [path for batch in batches for path in batch.file_paths] == ["/b"]
    assert closed.files_ingested == 1

    batches.clear()
    (tmp_path / "bb").write_text("bb")
    open_range = activities.scan_folder_range(_scan(tmp_path, "a"))
    assert [path for batch in batches for path in batch.file_paths] == ["/b", "/bb", "/c"]
    assert open_range.files_ingested == 3


@pytest.mark.parametrize(
    ("heartbeat_detail", "expected_files"),
    [
        ({"last_file_name": "b-finished"}, ["/c-pending"]),
        ("scan_folder_range", ["/b-finished", "/c-pending"]),
    ],
)
def test_range_retry_keeps_folders_and_recovers_file_cursor(
    tmp_path, monkeypatch, heartbeat_detail, expected_files,
):
    (tmp_path / "a-folder").mkdir()
    (tmp_path / "b-finished").write_text("b")
    (tmp_path / "c-pending").write_text("c")
    batches = []
    monkeypatch.setattr(activities, "insert_vfs_directories", lambda _params: 0)
    monkeypatch.setattr(
        activities, "ingest_files_batch", lambda params: batches.append(params) or "ok",
    )
    monkeypatch.setattr(
        activities.activity,
        "info",
        lambda: SimpleNamespace(heartbeat_details=[heartbeat_detail]),
    )

    result = activities.scan_folder_range(_scan(tmp_path))

    assert result.subfolders == ["/a-folder"]
    assert [path for batch in batches for path in batch.file_paths] == expected_files


def test_history_budget_starts_one_range(monkeypatch):
    started = []

    class Info:
        def get_current_history_length(self):
            return workflows.HISTORY_EVENTS_PER_RUN + 1

        def is_continue_as_new_suggested(self):
            return False

    async def wait(pending, **kwargs):
        return await asyncio.wait(pending, **kwargs)

    async def run_range(after_name, until_name):
        started.append((after_name, until_name))

    monkeypatch.setattr(workflows.workflow, "info", Info)
    monkeypatch.setattr(workflows.workflow, "wait", wait)
    count = asyncio.run(workflows.run_ranges_until_budget(
        [("", "a"), ("a", "b")], run_range, 8,
    ))
    assert count == 1
    assert started == [("", "a")]


def test_child_failure_stops_before_reconcile(monkeypatch):
    async def child(*_args, **_kwargs):
        raise RuntimeError("child failed")

    async def activity_call(*_args, **_kwargs):
        pytest.fail("reconcile must not run after a failed child")

    monkeypatch.setattr(workflows.workflow, "execute_child_workflow", child)
    monkeypatch.setattr(workflows.workflow, "execute_activity", activity_call)
    monkeypatch.setattr(workflows.workflow, "now", lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    params = workflows.IngestDiskDatasetParams("collection", "dataset", "/tmp/data")
    with pytest.raises(RuntimeError, match="child failed"):
        asyncio.run(workflows.IngestDiskDataset().run(params))


def test_handle_folders_raises_the_first_child_failure(monkeypatch):
    class Info:
        def get_current_history_length(self):
            return 0

        def is_continue_as_new_suggested(self):
            return False

    async def execute_activity(fn, _params, **_kwargs):
        if fn is workflows.plan_folder_ranges:
            return activities.FolderRanges(["z"], "")
        return activities.RangeResult(["/child"], 0, 1)

    async def wait(pending, **kwargs):
        return await asyncio.wait(pending, **kwargs)

    async def run_window(_factories, _limit):
        return [RuntimeError("child failed")]

    monkeypatch.setattr(workflows.workflow, "info", Info)
    monkeypatch.setattr(workflows.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(workflows.workflow, "wait", wait)
    monkeypatch.setattr(workflows, "run_with_window", run_window)
    params = workflows.HandleFoldersParams("collection", "dataset", "/tmp/data", "/")
    with pytest.raises(RuntimeError, match="child failed"):
        asyncio.run(workflows.HandleFolders().run(params))
