"""`page_id` is a page number now, not a segment ordinal (plans/1-part-2.md D3).

These tests pin the two halves of that change that are cheap to get wrong again: the
1-based numbering, and the per-page split of PDF text. Both are silent when broken --
a 0-based page column produces a viewer that jumps one page short, and a missing page
split produces one enormous row that still looks like a successful extraction.
"""

import pytest

from tasks.P3_parse_files.parse_common import (
    DEFAULT_TEXT_SEGMENT_BYTES,
    insert_text_pages,
    split_text_segments,
)
from tasks.P3_parse_files import parse_pdf


def test_segment_size_is_256kb_not_32mb():
    """The old 32MB value made page_id an ordinal over a blob nothing could address."""
    assert DEFAULT_TEXT_SEGMENT_BYTES == 256 * 1024


def test_split_text_segments_cuts_at_the_segment_size():
    text = "a" * (DEFAULT_TEXT_SEGMENT_BYTES + 10)
    segments = split_text_segments(text)
    assert len(segments) == 2
    assert len(segments[0]) == DEFAULT_TEXT_SEGMENT_BYTES
    assert len(segments[1]) == 10


def test_split_text_segments_ignores_content_too_short_to_be_text():
    assert split_text_segments("") == []
    assert split_text_segments("  \n ") == []
    assert split_text_segments(None) == []


def test_page_zero_is_refused():
    """`page_id` must never be 0. The check runs before any database client is opened,
    which is what makes this testable without a live ClickHouse."""
    with pytest.raises(ValueError, match="1-based"):
        insert_text_pages("c", "c_1", "hash", "pdftotext", [(0, "text")])


def test_pdftotext_pages_splits_on_the_form_feed(monkeypatch):
    """pdftotext writes a form feed after every page, including the last.

    The trailing one produces an empty element past the last real page, and counting it
    as a page would report every PDF as one page longer than it is.
    """
    monkeypatch.setattr(parse_pdf, "_maybe_pdftotext",
                        lambda path: "page one\x0cpage two\x0cpage three\x0c")
    assert parse_pdf._pdftotext_pages("/tmp/x.pdf") == ["page one", "page two", "page three"]


def test_pdftotext_pages_keeps_empty_pages_in_place(monkeypatch):
    """An empty page is not the same as a missing one: a blank page 2 in a scanned PDF
    is the signal that page 2 needs OCR, and dropping it here would renumber page 3 to
    page 2 and misalign the OCR variant against the native one."""
    monkeypatch.setattr(parse_pdf, "_maybe_pdftotext",
                        lambda path: "text\x0c\x0cmore text\x0c")
    assert parse_pdf._pdftotext_pages("/tmp/x.pdf") == ["text", "", "more text"]


def test_pdftotext_failure_is_not_a_page(monkeypatch):
    """No output at all is an empty list, distinct from a document of blank pages."""
    monkeypatch.setattr(parse_pdf, "_maybe_pdftotext", lambda path: None)
    assert parse_pdf._pdftotext_pages("/tmp/x.pdf") == []
