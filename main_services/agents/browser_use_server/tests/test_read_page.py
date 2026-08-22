"""What `read_page` decides before it touches a browser, and what it renders after.

The fetching itself needs a Chromium and is exercised by driving a real chat. Everything
here is the part that can be wrong without any browser being involved: the shapes a model
sends for a list, the budget arithmetic, and whether a page that failed is reported as
failed rather than as empty.
"""

from __future__ import annotations

import json

from browser_use_server import read_page
from browser_use_server.read_page import PageRead, ReadResult


class TestPlan:
    def test_accepts_a_real_list(self):
        urls, _, _, note = read_page.plan(["https://a.example", "https://b.example"])
        assert urls == ["https://a.example", "https://b.example"]
        assert note == ""

    def test_accepts_a_json_encoded_list(self):
        # The shape an XML tool-call parser produces for every list parameter.
        urls, _, _, _ = read_page.plan('["https://a.example", "https://b.example"]')
        assert urls == ["https://a.example", "https://b.example"]

    def test_accepts_a_bare_string(self):
        urls, _, _, _ = read_page.plan("https://a.example")
        assert urls == ["https://a.example"]

    def test_repeats_are_run_once_and_said_out_loud(self):
        urls, repeats, _, note = read_page.plan(
            ["https://a.example", "https://a.example", "https://b.example"]
        )
        assert urls == ["https://a.example", "https://b.example"]
        assert repeats == ["https://a.example"]
        # Silent de-duplication teaches the model nothing; the note is the point.
        assert "repeated" in note and "https://a.example" in note

    def test_over_the_cap_is_named_not_dropped(self):
        many = [f"https://{i}.example" for i in range(read_page.MAX_URLS + 2)]
        urls, _, over, note = read_page.plan(many)
        assert len(urls) == read_page.MAX_URLS
        assert len(over) == 2
        assert over[0] in note

    def test_nothing_is_an_empty_plan_not_a_crash(self):
        urls, _, _, _ = read_page.plan(None)
        assert urls == []


class TestFocus:
    def test_short_text_is_untouched(self):
        text, truncated = read_page.focus("hello", "", 1000)
        assert (text, truncated) == ("hello", False)

    def test_no_goal_truncates_from_the_head(self):
        text, truncated = read_page.focus("a" * 5000, "", 1000)
        assert truncated and len(text) <= 1000 and text.startswith("a")

    def test_a_goal_keeps_the_paragraph_that_answers_it(self):
        filler = "\n\n".join("padding sentence about nothing at all." for _ in range(200))
        wanted = "The registered proprietor is Example Holdings Limited."
        text, truncated = read_page.focus(f"{filler}\n\n{wanted}", "registered proprietor", 900)
        assert truncated
        assert "Example Holdings Limited" in text


class TestRender:
    def test_a_failed_page_says_so_rather_than_reading_empty(self):
        out = read_page.render(
            ReadResult(pages=[PageRead(url="https://a.example", error="refused: private")])
        )
        assert "COULD NOT READ" in out and "refused" in out

    def test_pages_are_separated_and_titled(self):
        out = read_page.render(
            ReadResult(
                pages=[
                    PageRead(url="https://a.example", title="A", text="alpha"),
                    PageRead(url="https://b.example", title="B", text="beta"),
                ],
                note="one repeated URL was run once",
            )
        )
        assert "## A" in out and "## B" in out and "alpha" in out and "beta" in out
        assert "NOTE: one repeated URL" in out

    def test_truncation_is_stated(self):
        out = read_page.render(
            ReadResult(pages=[PageRead(url="https://a.example", text="x", truncated=True)])
        )
        assert "truncated" in out


class TestDecode:
    def test_finds_the_payload_inside_the_sidecars_prose(self):
        payload = json.dumps({"title": "T", "url": "https://a.example", "text": "body"})
        body = f"### Result\n{json.dumps(payload)}\n"
        assert read_page._decode(body)["text"] == "body"

    def test_finds_a_bare_object_too(self):
        body = '### Result\n{"title": "T", "url": "u", "text": "body"}\n'
        assert read_page._decode(body)["title"] == "T"

    def test_prose_with_no_payload_is_none(self):
        assert read_page._decode("### Result\nundefined\n") is None
