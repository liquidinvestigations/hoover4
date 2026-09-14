"""Disk folder listing pages preserve all entries under the Temporal result limit."""

import json
import os
from pathlib import Path

from tasks.P0_scan_disk import activities


def _params(dataset_path: Path, after_name: str = "") -> activities.ListDiskFolderParams:
    return activities.ListDiskFolderParams(
        collectionname="collection",
        collection_dataset="dataset",
        dataset_path=str(dataset_path),
        folder_path="/",
        after_name=after_name,
    )


def _walk_pages(dataset_path: Path):
    after_name = ""
    pages = []
    while True:
        page = activities.list_disk_folder(_params(dataset_path, after_name))
        pages.append(page)
        after_name = page["next_after_name"]
        if not after_name:
            return pages


def test_empty_directory_returns_one_final_page(tmp_path):
    assert activities.list_disk_folder(_params(tmp_path)) == {
        "dirs": [], "files": [], "next_after_name": "",
    }


def test_small_directory_returns_one_final_page(tmp_path):
    for index in range(10):
        (tmp_path / f"file-{index:02d}").write_text("x")

    page = activities.list_disk_folder(_params(tmp_path))

    assert page["next_after_name"] == ""
    assert [row["path"] for row in page["files"]] == [f"/file-{index:02d}" for index in range(10)]


def test_listing_pages_are_bounded_and_contain_each_entry_once(tmp_path):
    for index in range(6000):
        (tmp_path / f"file-{index:05d}").write_text("x")

    pages = _walk_pages(tmp_path)
    paths = [row["path"] for page in pages for row in page["files"]]

    assert len(pages) > 1
    assert paths == [f"/file-{index:05d}" for index in range(6000)]
    assert len(paths) == len(set(paths))
    assert all(
        len(json.dumps(page).encode("utf-8")) < activities.LISTING_PAGE_BUDGET_BYTES
        for page in pages
    )


def test_oversized_single_entry_is_not_dropped(tmp_path, monkeypatch):
    (tmp_path / "single-entry").write_text("x")
    monkeypatch.setattr(activities, "LISTING_PAGE_BUDGET_BYTES", 1)

    page = activities.list_disk_folder(_params(tmp_path))

    assert [row["path"] for row in page["files"]] == ["/single-entry"]
    assert page["next_after_name"] == ""


def test_surrogate_path_is_skipped_and_past_cursor_is_empty(tmp_path):
    encoded_path = os.fsencode(tmp_path) + b"/surrogate-\xff"
    fd = os.open(encoded_path, os.O_CREAT | os.O_WRONLY)
    os.close(fd)

    page = activities.list_disk_folder(_params(tmp_path))
    after_last = activities.list_disk_folder(_params(tmp_path, "zzzz"))

    assert page["files"] == []
    assert page["next_after_name"] == ""
    assert after_last == {"dirs": [], "files": [], "next_after_name": ""}
