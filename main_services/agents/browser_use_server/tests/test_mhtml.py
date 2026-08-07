"""The MHTML -> self-contained HTML converter, against fixtures rather than the live web.

Testing this against a real page would make the suite fail whenever that page changes,
which tells us nothing. The fixtures below are the five shapes the plan names, each one a
case where getting it wrong produces a capture that *renders* — just wrongly, with no
error anywhere.
"""

import base64
import re

import pytest

from browser_use_server import mhtml


def build(parts, root_location="https://example.com/page"):
    """Assemble a minimal multipart/related MHTML document.

    Written by hand rather than captured from Chromium so each test controls exactly one
    variable — a real capture is 3 MB of noise around the one line under test.
    """
    boundary = "----MultipartBoundary--test--"
    out = [
        "From: <Saved by Blink>",
        f"Snapshot-Content-Location: {root_location}",
        f"Content-Location: {root_location}",
        "MIME-Version: 1.0",
        f'Content-Type: multipart/related; boundary="{boundary}"; type="text/html"',
        "",
    ]
    for location, content_type, encoding, payload in parts:
        out.append(f"--{boundary}")
        out.append(f"Content-Type: {content_type}")
        out.append(f"Content-Transfer-Encoding: {encoding}")
        out.append(f"Content-Location: {location}")
        out.append("")
        out.append(payload)
        out.append("")
    out.append(f"--{boundary}--")
    return "\r\n".join(out).encode("utf-8")


PIXEL_PNG = base64.b64encode(
    base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
).decode()


class TestRootSelection:
    def test_the_root_is_the_part_matching_the_message_content_location(self):
        raw = build(
            [
                ("https://example.com/frame", "text/html", "quoted-printable", "<html><body>frame</body></html>"),
                ("https://example.com/page", "text/html", "quoted-printable", "<html><body>ROOT</body></html>"),
            ]
        )
        assert "ROOT" in mhtml.convert(raw).html

    def test_it_falls_back_to_the_first_html_part(self):
        raw = build(
            [("https://other.example/x", "text/html", "quoted-printable", "<html><body>only</body></html>")],
            root_location="https://example.com/missing",
        )
        assert "only" in mhtml.convert(raw).html

    def test_an_archive_with_no_html_is_an_error_not_an_empty_page(self):
        raw = build([("https://example.com/a.css", "text/css", "quoted-printable", "body{}")])
        with pytest.raises(ValueError):
            mhtml.convert(raw)


class TestInlining:
    def test_quoted_printable_css_is_decoded_and_inlined(self):
        """Chromium encodes CSS as quoted-printable, so `=3D` is `=` and a soft line
        break is `=\\r\\n`. A converter that skipped the decode would inline the *encoded*
        bytes, and the page would render unstyled with no error."""
        raw = build(
            [
                (
                    "https://example.com/page",
                    "text/html",
                    "quoted-printable",
                    '<html><head><link rel=3D"stylesheet" href=3D"https://example.com/a.css">'
                    "</head><body>hi</body></html>",
                ),
                (
                    "https://example.com/a.css",
                    "text/css",
                    "quoted-printable",
                    "body{color:=23ff0000}",
                ),
            ]
        )
        html = mhtml.convert(raw).html
        assert "<style>" in html
        assert "color:#ff0000" in html
        assert "<link" not in html

    def test_srcset_entries_keep_their_descriptors(self):
        raw = build(
            [
                (
                    "https://example.com/page",
                    "text/html",
                    "quoted-printable",
                    '<html><body><img srcset="https://example.com/a.png 1x, '
                    'https://example.com/b.png 2x"></body></html>',
                ),
                ("https://example.com/a.png", "image/png", "base64", PIXEL_PNG),
                ("https://example.com/b.png", "image/png", "base64", PIXEL_PNG),
            ]
        )
        html = mhtml.convert(raw).html
        assert "1x" in html and "2x" in html
        assert html.count("data:image/png;base64,") >= 2
        assert "https://example.com/a.png" not in html

    def test_url_inside_an_inline_style_attribute_is_inlined(self):
        raw = build(
            [
                (
                    "https://example.com/page",
                    "text/html",
                    "quoted-printable",
                    '<html><body><div style="background:url(https://example.com/a.png)">'
                    "x</div></body></html>",
                ),
                ("https://example.com/a.png", "image/png", "base64", PIXEL_PNG),
            ]
        )
        html = mhtml.convert(raw).html
        assert "data:image/png;base64," in html
        assert "url(https://example.com/a.png)" not in html

    def test_a_relative_reference_resolves_against_the_parts_own_location(self):
        """The trap the plan names: `url(../img/x.png)` inside a stylesheet served from
        a CDN means a CDN path, not a path under the page's own URL. Resolving against
        the document produces a capture with silently missing images."""
        raw = build(
            [
                (
                    "https://example.com/page",
                    "text/html",
                    "quoted-printable",
                    '<html><head><link rel="stylesheet" href="https://cdn.example/css/app.css">'
                    "</head><body>x</body></html>",
                ),
                (
                    "https://cdn.example/css/app.css",
                    "text/css",
                    "quoted-printable",
                    "body{background:url(../img/x.png)}",
                ),
                ("https://cdn.example/img/x.png", "image/png", "base64", PIXEL_PNG),
            ]
        )
        result = mhtml.convert(raw)
        assert "data:image/png;base64," in result.html
        assert result.unresolved == []

    def test_a_missing_resource_is_recorded_rather_than_silently_dropped(self):
        raw = build(
            [
                (
                    "https://example.com/page",
                    "text/html",
                    "quoted-printable",
                    '<html><head><link rel="stylesheet" href="https://example.com/gone.css">'
                    "</head><body>x</body></html>",
                ),
            ]
        )
        result = mhtml.convert(raw)
        assert "https://example.com/gone.css" in result.unresolved
        assert "<link" not in result.html


class TestStripping:
    def test_scripts_and_event_handlers_are_removed(self):
        raw = build(
            [
                (
                    "https://example.com/page",
                    "text/html",
                    "quoted-printable",
                    "<html><body><script>alert(1)</script>"
                    '<div onclick="steal()">x</div>'
                    '<base href="https://evil.example/">'
                    "</body></html>",
                )
            ]
        )
        result = mhtml.convert(raw)
        assert "<script" not in result.html.lower()
        assert "alert(1)" not in result.html
        assert "onclick" not in result.html.lower()
        assert "<base" not in result.html.lower()
        assert result.dropped_scripts >= 1

    def test_a_javascript_href_loses_its_href(self):
        raw = build(
            [
                (
                    "https://example.com/page",
                    "text/html",
                    "quoted-printable",
                    '<html><body><a href="javascript:steal()">x</a></body></html>',
                )
            ]
        )
        html = mhtml.convert(raw).html
        assert "javascript:" not in html

    def test_remaining_links_are_marked_as_leaving_the_archive(self):
        raw = build(
            [
                (
                    "https://example.com/page",
                    "text/html",
                    "quoted-printable",
                    '<html><body><a href="https://real.example/x">x</a></body></html>',
                )
            ]
        )
        html = mhtml.convert(raw).html
        assert 'rel="noopener noreferrer nofollow"' in html
        assert 'target="_blank"' in html

    def test_an_existing_rel_is_replaced_not_duplicated(self):
        raw = build(
            [
                (
                    "https://example.com/page",
                    "text/html",
                    "quoted-printable",
                    '<html><body><a rel="author" target="_self" href="https://x.example/">x</a></body></html>',
                )
            ]
        )
        html = mhtml.convert(raw).html
        assert html.count("rel=") == 1
        assert 'target="_self"' not in html


class TestBanner:
    def test_the_banner_names_the_captured_url_and_time(self):
        raw = build(
            [("https://example.com/page", "text/html", "quoted-printable", "<html><body>x</body></html>")]
        )
        html = mhtml.convert(raw, captured_at="2026-08-07 10:00 UTC").html
        assert "Archived copy" in html
        assert "https://example.com/page" in html
        assert "2026-08-07 10:00 UTC" in html

    def test_the_banner_sits_immediately_after_body(self):
        raw = build(
            [("https://example.com/page", "text/html", "quoted-printable", "<html><body>content</body></html>")]
        )
        html = mhtml.convert(raw).html
        body = re.search(r"<body[^>]*>", html, re.IGNORECASE)
        assert html[body.end():].lstrip().startswith("<div")

    def test_a_url_with_markup_in_it_cannot_break_out_of_the_banner(self):
        raw = build(
            [("https://x.example/<script>", "text/html", "quoted-printable", "<html><body>x</body></html>")],
            root_location="https://x.example/<script>",
        )
        html = mhtml.convert(raw).html
        assert "&lt;script&gt;" in html


class TestByteCap:
    def test_an_oversized_archive_is_refused_before_parsing(self):
        raw = build(
            [("https://example.com/page", "text/html", "quoted-printable", "<html><body>x</body></html>")]
        )
        with pytest.raises(mhtml.SnapshotTooLarge):
            mhtml.convert(raw, max_bytes=10)


class TestHelpers:
    def test_page_title_is_extracted_and_collapsed(self):
        assert mhtml.page_title("<html><title>  A\n  B </title>") == "A B"

    def test_page_title_of_a_titleless_document_is_empty(self):
        assert mhtml.page_title("<html><body>x</body></html>") == ""
