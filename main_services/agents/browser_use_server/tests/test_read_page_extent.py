"""Source extent of a PDF read, PDF page windows, and the screenshot of a kept read.

A synthetic PDF of 60 pages holds the word "Kaminski" on page 57 only. The first read
extracts pages 1 to 50, and its find gives no match while naming that limit. A read with
`page_start` 51 finds the word. The kept texts of the two windows have their own versions.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from browser_use_server import read_page
from browser_use_server.read_page import PageRead

URL = "https://reports.example/powers.pdf"


def _pdf(pages: int, marked: int, word: str) -> bytes:
    """A PDF of `pages` pages. Each page holds its number, and page `marked` holds `word`."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    kids = []
    font = 3
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for n in range(1, pages + 1):
        line = f"Page {n} of the report." + (f" {word} appears here." if n == marked else "")
        stream = f"BT /F1 12 Tf 72 720 Td ({line}) Tj ET".encode()
        content = len(objects) + 1
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page = len(objects) + 1
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                       b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>" % (font, content))
        kids.append(page)
    objects[1] = (b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids)
                  + b"] /Count %d >>" % pages)
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


DATA = _pdf(60, 57, "Kaminski")


def test_pdf_text_names_its_extent_and_reads_a_later_window():
    _, text, error, extent = read_page.pdf_text(DATA)
    assert not error and extent == {"pages": 60, "first": 1, "last": 50}
    assert "Page 50 of" in text and "Kaminski" not in text
    _, later, error, extent = read_page.pdf_text(DATA, 51)
    assert not error and extent == {"pages": 60, "first": 51, "last": 60}
    assert "Kaminski appears here" in later and "Page 50 of" not in later
    _, none, error, extent = read_page.pdf_text(DATA, 61)
    assert none == "" and "past its end" in error and extent["pages"] == 60


def _loader(monkeypatch, calls):
    async def load(_chat, url, _goal, _limit, _username, _deadline, links=True, page_start=1):
        calls.append((url, page_start))
        title, text, error, extent = read_page.pdf_text(DATA, page_start)
        page = PageRead(url=url, title="Powers report", final_url=url, full_text=text,
                        error=error, extent=extent, page_start=page_start)
        page.image = {"kind": "capture", "artifact_id": f"capture-{page_start}",
                      "label": "Powers report", "width": 10, "height": 10}
        page.artifact = {"artifact_id": f"capture-{page_start}"}
        return page
    monkeypatch.setattr(read_page, "_read_fresh", load)


def _read(chat, **kwargs):
    result = asyncio.run(read_page.read(chat, [URL], "", "user", ceiling=8000, **kwargs))
    read_page.fit(result, 8000)
    return result


def test_a_find_miss_in_the_first_window_names_the_window(monkeypatch):
    calls = []
    _loader(monkeypatch, calls)
    chat = SimpleNamespace(page_reads={})
    first = _read(chat)
    version = first.pages[0].version
    rendered = read_page.render(first)
    assert "The text covers PDF pages 1 to 50 of 60 only." in rendered
    assert "Call read_page with page_start 51 for the next pages." in rendered
    miss = read_page.render(_read(chat, find="Kaminski", version=version))
    assert "no match from offset 0" in miss and "PDF pages 1 to 50 of 60 only" in miss
    later = _read(chat, find="Kaminski", page_start=51)
    page = later.pages[0]
    assert page.total_matches == 1 and page.version != version
    assert "covers PDF pages 51 to 60 of 60 only" in read_page.render(later)
    # A version of the first window cannot address the second window.
    wrong = _read(chat, page_start=51, version=version)
    assert wrong.pages[0].error.startswith("the page changed")
    assert calls == [(URL, 1), (URL, 51)]


def test_a_whole_pdf_says_that_it_is_whole(monkeypatch):
    page = PageRead(url=URL, extent={"pages": 12, "first": 1, "last": 12})
    assert read_page.extent_text(page) == "The text covers all 12 pages of the PDF."
    assert read_page.extent_text(PageRead(url=URL)) == ""


def test_a_kept_read_returns_its_screenshot_only_when_asked(monkeypatch):
    calls = []
    _loader(monkeypatch, calls)
    chat = SimpleNamespace(page_reads={})
    first = _read(chat)
    assert first.pages[0].image["artifact_id"] == "capture-1"
    version = first.pages[0].version
    plain = _read(chat, version=version)
    assert plain.pages[0].image is None
    asked = _read(chat, version=version, screenshot=True)
    assert asked.pages[0].image["artifact_id"] == "capture-1"
    assert calls == [(URL, 1)]


def test_page_start_on_a_web_page_selects_nothing(monkeypatch):
    async def load(_chat, url, *_args, **_kwargs):
        return PageRead(url=url, title="T", final_url=url, full_text="Plain web page text.")
    monkeypatch.setattr(read_page, "_read_fresh", load)
    result = _read(SimpleNamespace(page_reads={}), page_start=3)
    assert "is not a PDF, so page_start 3 selects nothing" in result.note
