"""A .docx is one document, not a folder of XML parts.

`file -k` keeps going past the first match, so a .docx comes back as OOXML *and*
`application/zip` *and* `application/octet-stream`. Unioning the coarse types over every
detector then puts `archive` next to `doc`, the archive branch 7z-explodes the file, and
every internal part (`word/document.xml`, `_rels/.rels`, `docProps/app.xml`, ...) becomes
its own indexed document carrying the ZIP epoch 1980-01-01 as a trusted historical date.

The strings below are the literal stdout of `file -k` against real corpus fixtures --
`\\012` is GNU file's own escape for the newline between keep-going matches, not a typo.
"""

import pytest

from tasks.P0_scan_disk.mime_type_mapper import (
    _ZIP_BASED_DOCUMENT_MIMES,
    coarse_file_type,
    should_expand_as_archive,
)
from tasks.P3_parse_files import parse_mime


# name -> (--mime-type, --mime-encoding, --extension) as `file -k -b` prints them.
FILE_K = {
    "easychair.docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        "\\012- application/zip\\012- application/zip\\012- application/octet-stream",
        "binary",
        "docx\\012- zip/cbz\\012- ???",
    ),
    "easychair.odt": (
        "application/vnd.oasis.opendocument.text\\012- application/octet-stream",
        "binary",
        "odt\\012- ???",
    ),
    "sample-xlsx-file-for-testing.xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        "\\012- application/zip\\012- application/zip\\012- application/octet-stream",
        "binary",
        "xlsx\\012- zip/cbz\\012- ???",
    ),
    "slides.pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        "\\012- application/zip\\012- application/zip\\012- application/zip"
        "\\012- application/octet-stream",
        "binary",
        "pptx\\012- zip/cbz\\012- ???",
    ),
    "book.epub": (
        "application/epub+zip\\012- application/octet-stream",
        "binary",
        "epub\\012- ???",
    ),
    "box.zip": (
        "application/zip\\012- application/zip\\012- application/zip"
        "\\012- application/octet-stream",
        "binary",
        "\\012- zip/cbz\\012- ???",
    ),
    "libical.jar": (
        "application/java-archive\\012- application/java-archive"
        "\\012- application/octet-stream",
        "binary",
        "jar\\012- jar\\012- ???",
    ),
    "attachments-have-octet-stream-content-type.eml": (
        "message/rfc822\\012- text/plain",
        "us-ascii",
        "???",
    ),
}


class _FakeCompletedProcess:
    def __init__(self, stdout: str):
        self.returncode = 0
        self.stdout = stdout
        self.stderr = ""


@pytest.fixture
def detect(monkeypatch):
    """Run the real `file` output parser over a recorded fixture; return (mimes, coarse)."""
    def _detect(name: str):
        outputs = dict(zip(("--mime-type", "--mime-encoding", "--extension"), FILE_K[name]))

        def fake_run(cmd, **kwargs):
            # `file` prefixes every line with "<path>: " unless -b; the parser strips it.
            return _FakeCompletedProcess(f"{cmd[-1]}: {outputs[cmd[2]]}\n")

        monkeypatch.setattr(parse_mime.subprocess, "run", fake_run)
        mime_types, _encodings, _extensions = parse_mime._run_file_multi(f"/data/{name}")
        return mime_types, sorted({coarse_file_type(m) for m in mime_types})

    return _detect


@pytest.mark.parametrize("name,document_type", [
    ("easychair.docx", "doc"),
    ("easychair.odt", "doc"),
    ("sample-xlsx-file-for-testing.xlsx", "xls"),
    ("slides.pptx", "ppt"),
])
def test_office_containers_are_documents_and_are_never_expanded(detect, name, document_type):
    mimes, coarse = detect(name)
    assert document_type in coarse
    assert not should_expand_as_archive(coarse, mimes)


def test_docx_still_reports_archive_but_is_not_expanded(detect):
    """The union is left accurate -- only the *decision* changed."""
    mimes, coarse = detect("easychair.docx")
    assert mimes == [
        "application/octet-stream",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
    ]
    assert coarse == ["archive", "doc", "other"]
    assert not should_expand_as_archive(coarse, mimes)


def test_epub_is_not_expanded_even_though_its_coarse_type_is_other(detect):
    """`application/epub+zip` maps to `other`, so only the MIME set can save it."""
    mimes, coarse = detect("book.epub")
    assert "archive" not in coarse
    assert not should_expand_as_archive(coarse, mimes)
    assert not should_expand_as_archive(coarse + ["archive"], mimes)


def test_plain_zip_still_expands(detect):
    mimes, coarse = detect("box.zip")
    assert "archive" in coarse
    assert should_expand_as_archive(coarse, mimes)


def test_a_jar_is_untouched_by_the_document_set(detect):
    """`file` reports a .jar as application/java-archive alone, which this mapper has
    never called an archive -- it falls through to `other` and is not expanded. The
    document set must not change that in either direction: a .jar is not a document, and
    making it one would be a behaviour change nobody asked for."""
    mimes, coarse = detect("libical.jar")
    assert not (_ZIP_BASED_DOCUMENT_MIMES & set(mimes))
    assert not should_expand_as_archive(coarse, mimes)


def test_eml_is_an_email_not_an_archive(detect):
    mimes, coarse = detect("attachments-have-octet-stream-content-type.eml")
    assert coarse == ["email", "text"]
    assert not should_expand_as_archive(coarse, mimes)


def test_one_detector_calling_a_docx_an_archive_does_not_outvote_the_others(detect):
    """The decision is over the whole detected set, not membership in the union."""
    file_mimes, file_coarse = detect("easychair.docx")
    # Magika groups a container it does not recognise as `archive` with no OOXML MIME.
    union_coarse = sorted(set(file_coarse) | {"archive"})
    union_mimes = sorted(set(file_mimes) | {"application/zip"})
    assert not should_expand_as_archive(union_coarse, union_mimes)


def test_zip_based_document_mimes_never_map_to_archive():
    for mime in _ZIP_BASED_DOCUMENT_MIMES:
        assert coarse_file_type(mime) != "archive"
