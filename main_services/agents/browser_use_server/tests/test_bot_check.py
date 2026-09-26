"""The bot check wait in `read_page`, driven against a fake sidecar.

A real check page needs a live site. What can be wrong without one is the control flow:
how many probes a page with no check costs, whether a check that clears lets the
extraction run, and whether a check that stays is reported as blocked with no page text.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import time
from types import SimpleNamespace

import pytest

from browser_use_server import capture as capture_mod
from browser_use_server import read_page
from browser_use_server.read_page import PageRead, ReadResult

CHECK_URL = "https://checked.example/article"


def _answer(payload: dict) -> SimpleNamespace:
    """A sidecar `browser_evaluate` answer: prose around a JSON string."""
    body = f"### Result\n{json.dumps(json.dumps(payload))}\n"
    return SimpleNamespace(content=[SimpleNamespace(text=body)], is_error=False)


class FakeClient:
    """Answers the check probe from a script, and the extraction with a fixed page."""

    def __init__(self, checks: list[bool | None], stay: bool = False):
        self.checks = list(checks)
        self.stay = stay
        self.probes = 0
        self.extractions = 0

    async def call_tool(self, tool, arguments, raise_on_error=False):
        if tool == "browser_navigate":
            return SimpleNamespace(content=[], is_error=False)
        script = arguments["function"]
        if script == read_page._CHECK_JS:
            self.probes += 1
            if self.checks:
                check = self.checks.pop(0)
            else:
                check = True if self.stay else False
            if check is None:
                # The redirect destroyed the context while the probe ran.
                return SimpleNamespace(
                    content=[SimpleNamespace(text="Execution context was destroyed")],
                    is_error=True,
                )
            return _answer({
                "text": "just a moment" if check else "",
                "check": check,
                "url": CHECK_URL,
                "title": "Just a moment..." if check else "Article",
            })
        self.extractions += 1
        return _answer({"title": "Article", "url": CHECK_URL, "text": "the article text"})


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(read_page, "BOT_CHECK_POLL_S", 0.01)

    async def no_capture(chat, tool_name, username, failed=False):
        return capture_mod.CaptureResult()

    monkeypatch.setattr(capture_mod, "capture", no_capture)
    # The test host does not resolve, and the URL check is not what these tests cover.
    monkeypatch.setattr(read_page, "check_url", lambda url: None)


def _read(client: FakeClient) -> tuple[PageRead, float]:
    chat = SimpleNamespace(client=client)
    started = time.monotonic()
    page = asyncio.run(read_page._read_one(chat, CHECK_URL, "", 5000, "user"))
    return page, time.monotonic() - started


def test_no_check_costs_one_probe_and_no_wait():
    client = FakeClient([False])
    page, elapsed = _read(client)
    assert client.probes == 1
    assert client.extractions == 1
    assert elapsed < 0.05
    assert page.text == "the article text" and not page.blocked and not page.error


def test_a_check_that_clears_lets_the_extraction_run():
    client = FakeClient([True, True, None, True, False])
    page, _ = _read(client)
    assert client.probes == 5
    assert client.extractions == 1
    assert page.text == "the article text" and not page.blocked


def test_a_check_that_stays_is_blocked_with_no_extraction(monkeypatch):
    monkeypatch.setattr(read_page, "BOT_CHECK_WAIT_S", 0.2)
    client = FakeClient([], stay=True)
    page, elapsed = _read(client)
    assert page.blocked
    assert page.error == "blocked by a bot check"
    assert page.final_url == CHECK_URL
    assert page.text == ""
    assert client.extractions == 0
    assert 0.2 <= elapsed < 1.0


def test_the_label_names_the_url_and_the_wait(monkeypatch):
    monkeypatch.setattr(read_page, "BOT_CHECK_WAIT_S", 7.0)
    out = read_page.render(ReadResult(pages=[PageRead(
        url="https://a.example", final_url=CHECK_URL, title="Just a moment...",
        error="blocked by a bot check", blocked=True,
    )]))
    assert f"BLOCKED BY A BOT CHECK: {CHECK_URL}." in out
    assert "for 7 s" in out
    assert "wayback" in out
    assert "COULD NOT READ" not in out


def _text_pdf(line: str) -> bytes:
    """A one-page PDF with a text layer that holds `line`."""
    stream = f"BT /F1 12 Tf 72 720 Td ({line}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref,
    )
    return bytes(out)


class PdfClient:
    """A page that shows a PDF, served to the slice script in slices."""

    def __init__(self, data: bytes):
        self.data = data
        self.slices = 0

    async def call_tool(self, tool, arguments, raise_on_error=False):
        if tool == "browser_navigate":
            return SimpleNamespace(content=[], is_error=False)
        script = arguments["function"]
        if script == read_page._CHECK_JS:
            return _answer({"text": "", "check": False, "url": CHECK_URL, "title": "",
                            "type": "application/pdf"})
        self.slices += 1
        start, size = map(int, re.search(
            r"subarray\((\d+), Math.min\(all.length, \d+ \+ (\d+)\)\)", script
        ).groups())
        end = min(len(self.data), start + size)
        return _answer({"text": base64.b64encode(self.data[start:end]).decode(),
                        "total": len(self.data), "url": CHECK_URL})


def test_a_pdf_is_read_through_its_text_layer(monkeypatch):
    monkeypatch.setattr(read_page, "PDF_SLICE_BYTES", 200)
    client = PdfClient(_text_pdf("Neural Network Topologies"))
    page, _ = _read(client)
    assert "Neural Network Topologies" in page.text
    assert client.slices > 1
    assert not page.error and not page.note


def test_a_pdf_over_the_limit_is_not_read(monkeypatch):
    data = _text_pdf("Neural Network Topologies")
    monkeypatch.setattr(read_page, "PDF_SLICE_BYTES", 200)
    monkeypatch.setattr(read_page, "PDF_MAX_BYTES", 400)
    assert len(data) > 400
    parsed = []
    monkeypatch.setattr(read_page, "pdf_text", lambda b: parsed.append(b) or ("", "", ""))
    client = PdfClient(data)
    page, _ = _read(client)
    assert page.error == (
        f"the PDF has {len(data)} bytes, above the read limit of 400 bytes "
        "(READ_PAGE_PDF_MAX_BYTES), so it was not read"
    )
    assert parsed == []
    assert client.slices == 1
    assert page.text == "" and page.note == ""


def test_a_cut_pdf_gives_an_error_and_no_text():
    data = _text_pdf("Neural Network Topologies")
    title, text, error = read_page.pdf_text(data[: len(data) // 2])
    assert error and text == ""


def test_a_pdf_with_no_text_is_an_error():
    from pypdf import PdfWriter

    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(buffer)
    assert read_page.pdf_text(buffer.getvalue())[2] == "the PDF has no text layer"
