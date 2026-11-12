"""The export reads each small frozen Manticore file whole, so a rewrite cannot cut its archive entry."""
import io
import json
import tarfile

import pytest

from tasks.P_ops import backup


def test_a_meta_file_rewritten_during_the_read_enters_the_archive_whole(tmp_path, monkeypatch):
    meta = tmp_path / "t.meta"
    full = json.dumps({"meta_version": 24, "schema": {"fields": ["title"] * 50}}).encode()
    reads = iter([full[:40], full, full])
    real_open = open

    class Reader:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return self.data

    def fake_open(path, mode="r", *args, **kwargs):
        if str(path) == str(meta) and mode == "rb":
            return Reader(next(reads))
        return real_open(path, mode, *args, **kwargs)

    meta.write_bytes(full[:40])
    monkeypatch.setattr("builtins.open", fake_open)
    monkeypatch.setattr(backup.time, "sleep", lambda s: None)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        size = backup._add_frozen_file(tar, str(meta))
    monkeypatch.undo()
    assert size == len(full)
    buffer.seek(0)
    with tarfile.open(fileobj=buffer) as tar:
        member = tar.getmember("t.meta")
        assert json.loads(tar.extractfile(member).read())["meta_version"] == 24


def test_a_file_that_keeps_changing_fails_the_export(tmp_path, monkeypatch):
    path = tmp_path / "t.meta"
    counter = {"n": 0}
    real_open = open

    class Reader:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            counter["n"] += 1
            return json.dumps({"n": counter["n"]}).encode()

    monkeypatch.setattr("builtins.open", lambda p, mode="r", *a, **k: Reader() if str(p) == str(path) else real_open(p, mode, *a, **k))
    monkeypatch.setattr(backup.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="kept changing during the freeze"):
        backup.stable_read(str(path), attempts=5)


def test_an_unchanged_file_is_read_once_more_to_confirm(tmp_path):
    path = tmp_path / "t.settings"
    path.write_bytes(b"settings")
    assert backup.stable_read(str(path), pause=0) == b"settings"
