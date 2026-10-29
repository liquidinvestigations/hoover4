"""The folder scan leaves out the temporary file of an upload placement copy."""

from tasks.P0_scan_disk.activities import ListDiskFolderParams, _range_entries, list_disk_folder

PART = ".hoover4-upload-0123456789abcdef0123456789abcdef-3.hoover4-part"


def _folder(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / PART).write_text("partial")
    (tmp_path / "b.hoover4-part").write_text("b")
    (tmp_path / "sub").mkdir()
    return ListDiskFolderParams("c", "c_d", str(tmp_path), "/")


def test_both_listings_skip_a_placement_part_in_a_dataset_folder(tmp_path):
    params = _folder(tmp_path)
    assert [name for name, _ in _range_entries(params)] == ["a.txt", "b.hoover4-part", "sub"]
    listed = list_disk_folder(params)
    assert sorted(f["path"] for f in listed["files"]) == ["/a.txt", "/b.hoover4-part"]
    assert [d["path"] for d in listed["dirs"]] == ["/sub"]


def test_a_container_member_with_the_part_name_is_kept(tmp_path):
    params = _folder(tmp_path)
    params.container_hash = "archive"
    assert PART in [name for name, _ in _range_entries(params)]
