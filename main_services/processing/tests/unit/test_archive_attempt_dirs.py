"""Extraction attempts retain separate directories until their scans finish."""

from tasks.P3_parse_files.temp_dirs import make_attempt_dir


def test_attempt_cleanup_preserves_another_attempt(tmp_path, monkeypatch):
    import shutil
    import tempfile
    from pathlib import Path

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    first = Path(make_attempt_dir("dataset", "extract", "entry"))
    member = first / "member.txt"
    member.write_text("first attempt")
    second = Path(make_attempt_dir("dataset", "extract", "entry"))
    assert first != second
    shutil.rmtree(second)
    assert member.read_text() == "first attempt"


def test_later_volume_resolves_conflicting_entry_occurrences(monkeypatch):
    from contextlib import contextmanager
    from tasks.P3_parse_files import parse_archives, split_volumes
    from tasks.P3_parse_files.batch_runner import BatchFile
    from database import clickhouse
    from temporalio.exceptions import ApplicationError
    import pytest

    rows = [("", "/a/x.001", "entry", 1, ""),
            ("", "/a/x.002", "later-a", 1, ""),
            ("", "/b/x.001", "entry", 1, ""),
            ("", "/b/x.002", "later-b", 1, "")]
    sets = split_volumes.group_volume_sets(rows, "dataset")
    resolved = []

    @contextmanager
    def client(_name):
        yield object()

    def resolve(_client, _dataset, file_hash):
        resolved.append(file_hash)
        return [s for s in sets if file_hash in s.hashes]

    monkeypatch.setattr(clickhouse, "get_collection_client", client)
    monkeypatch.setattr(split_volumes, "resolve_volume_sets", resolve)
    monkeypatch.setattr(parse_archives, "extract_split_set", lambda *_args: pytest.fail("ambiguous extraction"))
    with pytest.raises(ApplicationError) as error:
        parse_archives.split_step("collection", "dataset", BatchFile("later-a", "/tmp/input", 1), set(), set())
    assert error.value.type == split_volumes.SPLIT_ARCHIVE_AMBIGUOUS
    assert resolved == ["later-a", "entry"]
