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
import subprocess
import time
from types import SimpleNamespace

import pytest

from browser_use_server import capture as capture_mod
from browser_use_server import read_page
from browser_use_server.read_page import PageRead, ReadResult

CHECK_URL = "https://checked.example/article"


@pytest.mark.parametrize("title, body, blocked", [
    ("Security Check", "Myra. Our systems have detected unusual traffic. You must confirm that you are human.", True),
    ("Sicherheitsüberprüfung", "Myra. Bitte bestätigen Sie, dass Sie ein Mensch sind.", True),
    ("Security Verification", "Verification could not be completed. Please refresh the page to try again. Loading...", True),
    ("Security Verification", "Documentation for our account verification process.", False),
    ("Security verification guide", "The page can report: Verification could not be completed.", False),
    ("", "Please verify that you are human.", True),
    ("Myra security check guide", "This article describes a security check.", False),
])
def test_the_probe_detects_human_verification_pages(title, body, blocked):
    page = json.dumps({"title": title, "body": {"innerText": body}})
    script = (f"global.document = {page}; document.querySelector = () => null; "
              f"global.window = {{}}; global.location = {{href: {json.dumps(CHECK_URL)}}}; "
              f"console.log(({read_page._CHECK_JS})());")
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout)["check"] is blocked


@pytest.mark.parametrize("status", [0, 200, 404, 503])
@pytest.mark.parametrize("function", [read_page._CHECK_JS, read_page._EXTRACT_JS],
                         ids=["probe", "extraction"])
def test_page_scripts_report_the_document_http_status(status, function):
    script = (
        "global.document = {title: 'Example', contentType: 'application/json', readyState: 'complete', body: {innerText: 'Article about HTTP 404 errors.' + 'x'.repeat(2000)},"
        " querySelector: () => null, getElementsByTagName: () => [],"
        " querySelectorAll: () => [document.body], cloneNode: () => document};"
        "global.window = {}; global.location = {href: 'https://checked.example/article'};"
        "Object.defineProperty(globalThis, 'performance', {value: {getEntriesByType:"
        f" kind => kind === 'navigation' ? [{{responseStatus: {status}}}] : []}}}});"
        f"Promise.resolve(({function})()).then(value => console.log(value));"
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout)["status"] == status


@pytest.mark.parametrize("status", [None, 0, 200, 404, 503])
def test_extraction_preserves_articles_and_rejects_known_http_errors(status):
    page = PageRead(url=CHECK_URL)
    payload = {"title": "HTTP 404 guide", "url": CHECK_URL,
               "text": "An article about Page not found errors.", "status": status}
    read_page._extract(page, CHECK_URL, "", 5000, "", ("", json.dumps(payload)))
    if status in (404, 503):
        assert page.error == f"the page returned HTTP {status}"
        assert not page.text and not page.full_text
    else:
        assert not page.error
        assert page.text == payload["text"]


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

    async def fresh(chat, url, goal, limit, username, deadline, links=True, page_start=1):
        return await read_page._read_one(chat, url, goal, limit, username, links=links,
                                         page_start=page_start)
    monkeypatch.setattr(read_page, "_read_fresh", fresh)


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
    assert client.probes == 6
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


def test_an_http_error_has_no_kept_text_and_marks_its_capture_failed(monkeypatch):
    class HttpClient(FakeClient):
        async def call_tool(self, tool, arguments, raise_on_error=False):
            if tool == "browser_evaluate" and arguments["function"] == read_page._EXTRACT_JS:
                return _answer({"title": "Page not found", "url": CHECK_URL,
                                "text": "The requested page does not exist.", "status": 404})
            return await super().call_tool(tool, arguments, raise_on_error)

    captures = []

    async def capture(chat, tool_name, username, failed=False):
        captures.append(failed)
        return capture_mod.CaptureResult()

    monkeypatch.setattr(capture_mod, "capture", capture)
    chat = SimpleNamespace(client=HttpClient([False]), page_reads={})
    result = asyncio.run(read_page.read(chat, [CHECK_URL], "", "user"))
    assert result.pages[0].error == "the page returned HTTP 404"
    assert not result.pages[0].text and not chat.page_reads
    assert captures == [True]
    assert "COULD NOT READ" in read_page.render(result)


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


def test_a_pdf_http_error_is_rejected_before_fetching_bytes():
    client = PdfClient(_text_pdf("This error response must not become evidence."))
    page = PageRead(url=CHECK_URL)
    asyncio.run(read_page._read_pdf(SimpleNamespace(client=client), page, CHECK_URL,
                                   "", 5000, {"url": CHECK_URL, "status": 404}))
    assert page.error == "the page returned HTTP 404"
    assert not page.text and client.slices == 0


def test_a_pdf_over_the_limit_is_not_read(monkeypatch):
    data = _text_pdf("Neural Network Topologies")
    monkeypatch.setattr(read_page, "PDF_SLICE_BYTES", 200)
    monkeypatch.setattr(read_page, "PDF_MAX_BYTES", 400)
    assert len(data) > 400
    parsed = []
    monkeypatch.setattr(read_page, "pdf_text", lambda b, start=1: parsed.append(b) or ("", "", "", {}))
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
    title, text, error, _extent = read_page.pdf_text(data[: len(data) // 2])
    assert error and text == ""


def test_a_pdf_with_no_text_is_an_error():
    from pypdf import PdfWriter

    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(buffer)
    assert read_page.pdf_text(buffer.getvalue())[2] == "the PDF has no text layer"


@pytest.mark.parametrize("status,outcome", [(403, "forbidden"), (429, "rate_limited"),
                                             (451, "legal_restriction"), (503, "unavailable")])
def test_ordinary_http_failure_has_typed_outcome(status, outcome):
    class StatusClient(FakeClient):
        async def call_tool(self, tool, arguments, **kwargs):
            if tool == "browser_evaluate" and arguments["function"] == read_page._CHECK_JS:
                return _answer({"text": "", "check": False, "url": CHECK_URL, "status": status})
            return await super().call_tool(tool, arguments, **kwargs)
    client = StatusClient([])
    page, _ = _read(client)
    assert page.outcome == outcome and page.status == status
    assert not page.full_text and client.extractions == 0


def test_http_403_challenge_waits_then_reads_cleared_response():
    class ChallengeClient(FakeClient):
        async def call_tool(self, tool, arguments, **kwargs):
            result = await super().call_tool(tool, arguments, **kwargs)
            if tool == "browser_evaluate" and arguments["function"] == read_page._CHECK_JS:
                payload = read_page._decode(read_page._text(result))
                payload["status"] = 403 if payload["check"] else 200
                return _answer(payload)
            return result
    client = ChallengeClient([True, False])
    page, _ = _read(client)
    assert page.outcome == "content" and page.status == 200
    assert page.challenge_signal and page.full_text == "the article text"


def test_persistent_challenge_obeys_shared_deadline(monkeypatch):
    monkeypatch.setattr(read_page, "BOT_CHECK_WAIT_S", 10)
    client = FakeClient([], stay=True)
    chat = SimpleNamespace(client=client, deadline=time.monotonic() + 0.03)
    started = time.monotonic()
    page = asyncio.run(read_page._read_one(chat, CHECK_URL, "", 5000, "user"))
    assert page.outcome == "challenge" and not page.full_text
    assert time.monotonic() - started < 0.5


@pytest.mark.parametrize("destination", ["chrome-extension://blocked/index.html?url=secret", "moz-extension://block/page"])
def test_extension_redirect_never_becomes_source_content(destination):
    class ExtensionClient(FakeClient):
        async def call_tool(self, tool, arguments, **kwargs):
            if tool == "browser_evaluate":
                return _answer({"text": "extension block content", "url": destination, "check": False})
            return await super().call_tool(tool, arguments, **kwargs)
    page, _ = _read(ExtensionClient([]))
    assert page.outcome == "extension_block" and page.url == CHECK_URL
    assert not page.final_url and not page.full_text and not page.text


@pytest.mark.parametrize("value,expected", [("2", 2), ("", 0), ("invalid", 0), ("-3", 0)])
def test_retry_after_delay_is_bounded_by_the_caller(value, expected):
    assert read_page.retry_after_seconds(value) == expected


def test_rejected_later_redirect_clears_previously_valid_final_url():
    page = PageRead(url=CHECK_URL, final_url=CHECK_URL, full_text="")
    assert not asyncio.run(read_page._validate_final(page, "chrome-extension://blocked/page"))
    assert page.final_url == "" and page.outcome == "extension_block"


def test_persistent_403_challenge_preserves_status(monkeypatch):
    monkeypatch.setattr(read_page, "BOT_CHECK_WAIT_S", 0)
    class ChallengeClient(FakeClient):
        async def call_tool(self, tool, arguments, **kwargs):
            if tool == "browser_evaluate":
                return _answer({"text": "check", "check": True, "status": 403, "url": CHECK_URL})
            return await super().call_tool(tool, arguments, **kwargs)
    page, _ = _read(ChallengeClient([]))
    assert page.outcome == "challenge" and page.status == 403 and not page.full_text


def test_retry_after_http_date_and_oversized_delay():
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime
    value = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=30))
    assert 28 <= read_page.retry_after_seconds(value) <= 30
    assert read_page.retry_after_seconds("9" * 128) > read_page.CALL_TIMEOUT_S


def test_refused_initial_url_has_failure_outcome(monkeypatch):
    from browser_use_server.urlcheck import UrlNotAllowed
    def refuse(_):
        raise UrlNotAllowed("refused fixture")
    monkeypatch.setattr(read_page, "check_url", refuse)
    page, _ = _read(FakeClient([]))
    assert page.outcome == "transport_error" and not page.full_text


def test_foreign_document_has_failure_outcome():
    client = FakeClient([])
    client.document = lambda: "none"
    page, _ = _read(client)
    assert page.outcome == "transport_error" and not page.full_text
