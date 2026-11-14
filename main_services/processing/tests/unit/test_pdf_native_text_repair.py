"""Native PDF text of a PDF whose cross-reference table qpdf rebuilds.

qpdf counts the pages of a PDF without its cross-reference table, and pdftotext cannot open
it. The preparation then read an empty page list. It failed the file five times with
"PDF native text extraction did not return every page". These tests run the
qpdf and pdftotext binaries of the worker image.
"""

import os
import shutil

import pytest
from temporalio.exceptions import ApplicationError

from tasks.P3_parse_files import parse_pdf
from tasks.P3_parse_files.pdf_parts import PDF_PAGE_MISMATCH, native_text_pages

pytestmark = pytest.mark.skipif(not (shutil.which("qpdf") and shutil.which("pdftotext")),
                                reason="qpdf and pdftotext are in the worker image")


def make_pdf(pages: int) -> bytes:
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               ("<< /Type /Pages /Kids [%s] /Count %d >>" % (
                   " ".join(f"{3 + 2 * i} 0 R" for i in range(pages)), pages)).encode()]
    font = 3 + 2 * pages
    for i in range(pages):
        objects.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
                        f"/Resources << /Font << /F1 {font} 0 R >> >> >>").encode())
        stream = f"BT /F1 24 Tf 72 700 Td (Page number {i + 1}) Tj ET".encode()
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def write(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def test_a_readable_pdf_keeps_its_own_path(tmp_path):
    path = write(tmp_path, "good.pdf", make_pdf(3))
    pages, readable = native_text_pages(path, 3, str(tmp_path))
    assert readable == path
    assert [page.strip() for page in pages] == ["Page number 1", "Page number 2", "Page number 3"]


def test_a_pdf_without_its_cross_reference_table_reads_from_a_qpdf_copy(tmp_path):
    good = make_pdf(3)
    damaged = good[:good.index(b"xref")] + b"%%EOF\n"
    path = write(tmp_path, "damaged.pdf", damaged)
    assert parse_pdf._qpdf_show_npages(path) == 3
    assert parse_pdf._pdftotext_pages(path) == []

    folder = tmp_path / "work"
    folder.mkdir()
    pages, readable = native_text_pages(path, 3, str(folder))
    assert readable == os.path.join(str(folder), "repaired.pdf")
    assert [page.strip() for page in pages] == ["Page number 1", "Page number 2", "Page number 3"]
    # The page checks of `page_needs` run pdfinfo on the copy.
    assert parse_pdf._pdftotext_pages(readable) == pages


def test_another_page_count_after_the_copy_is_a_non_retryable_file_error(tmp_path):
    # The page tree says 5 pages and holds 3. qpdf reports 5, pdftotext reads 3.
    path = write(tmp_path, "count.pdf", make_pdf(3).replace(b"/Count 3", b"/Count 5"))
    with pytest.raises(ApplicationError) as raised:
        native_text_pages(path, 5, str(tmp_path))
    assert raised.value.type == PDF_PAGE_MISMATCH
    assert raised.value.non_retryable
    assert "qpdf counts 5" in str(raised.value)
