"""Generic OLE files require a workbook stream before they use the table route."""

import pytest
import olefile

from tasks.P3_parse_files import parse_mime


@pytest.mark.parametrize("streams,excel,outlook", [
    ({"WordDocument", "1Table"}, False, False),
    ({"PowerPoint Document"}, False, False),
    ({"Workbook"}, True, False),
    ({"Book"}, True, False),
    ({"__properties_version1.0", "Workbook"}, False, True),
    (set(), False, False),
])
def test_ole_directory_selects_the_document_type(tmp_path, monkeypatch, streams, excel, outlook):
    path = tmp_path / "hash"
    path.write_bytes(bytes.fromhex("d0cf11e0a1b11ae1") + bytes(512))

    class Directory:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def exists(self, name):
            return name in streams

    monkeypatch.setattr(olefile, "OleFileIO", lambda _path: Directory())
    monkeypatch.setattr(parse_mime, "_magic_output", lambda _path: "Composite Document File")
    result = parse_mime._detect_by_content(
        parse_mime.DetectMimeParams("c", "ds", "h", str(path), 30),
        (["application/x-ole-storage"], [], []),
    )
    assert ("application/vnd.ms-excel" in result["mime_types"]) == excel
    assert ("application/vnd.ms-outlook" in result["mime_types"]) == outlook


def test_invalid_ole_does_not_select_excel(tmp_path, monkeypatch):
    path = tmp_path / "hash"
    path.write_bytes(bytes.fromhex("d0cf11e0a1b11ae1") + bytes(512))
    monkeypatch.setattr(parse_mime, "_magic_output", lambda _path: "Composite Document File")
    result = parse_mime._detect_by_content(
        parse_mime.DetectMimeParams("c", "ds", "h", str(path), 30),
        (["application/x-ole-storage"], [], []),
    )
    assert "application/vnd.ms-excel" not in result["mime_types"]
