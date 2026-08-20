"""Magika is constructed once per process, not once per file."""

from tasks.P3_parse_files import parse_mime


def test_magika_detector_is_built_once(monkeypatch):
    parse_mime.reset_magika_for_tests()
    constructed = {"n": 0}

    class FakeMagika:
        def __init__(self):
            constructed["n"] += 1

        def identify_path(self, path):
            return ("identified", path)

    monkeypatch.setattr("magika.Magika", FakeMagika)

    first = parse_mime.identify_path_with_magika("/tmp/a")
    second = parse_mime.identify_path_with_magika("/tmp/b")
    assert constructed["n"] == 1
    assert first == ("identified", "/tmp/a")
    assert second == ("identified", "/tmp/b")
    parse_mime.reset_magika_for_tests()
