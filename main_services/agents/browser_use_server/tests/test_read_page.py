"""What `read_page` decides before it touches a browser, and what it renders after.

The fetching itself needs a Chromium and is exercised by driving a real chat. Everything
here is the part that can be wrong without any browser being involved: the shapes a model
sends for a list, the budget arithmetic, and whether a page that failed is reported as
failed rather than as empty.
"""

from __future__ import annotations

import json
import asyncio
from types import SimpleNamespace

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

    def test_a_blocked_page_carries_the_label_not_could_not_read(self):
        out = read_page.render(
            ReadResult(pages=[PageRead(
                url="https://a.example", error=read_page.BOT_CHECK_ERROR, blocked=True
            )])
        )
        assert f"{read_page.BOT_CHECK_LABEL}: https://a.example." in out
        assert "COULD NOT READ" not in out

    def test_truncation_is_stated(self):
        out = read_page.render(
            ReadResult(pages=[PageRead(url="https://a.example", text="x", full_chars=100, truncated=True)])
        )
        assert "[cut: this call read 1 of the page's 100 characters. Call read_page with offset 1 for the next part. To find a text anywhere in the page, call read_page with find]" in out


def _loader(monkeypatch, texts):
    """Replace the navigation with a loader of `texts`, keyed by URL. Returns the list of
    the URLs it loaded."""
    calls = []

    async def load(_chat, url, _goal, _limit, _username):
        calls.append(url)
        return PageRead(url=url, title="T", final_url=url, full_text=texts[url])

    monkeypatch.setattr(read_page, "_read_one", load)
    return calls


def _read(chat, urls, ceiling, **kwargs):
    result = asyncio.run(read_page.read(chat, urls, "", "user", ceiling=ceiling, **kwargs))
    read_page.fit(result, ceiling)
    return result


def test_read_page_offsets_and_cached_text(monkeypatch):
    url = "https://a.example"
    chat = SimpleNamespace(page_reads={})
    calls = _loader(monkeypatch, {url: "a" * 30_000 + "b" * 10_000})
    first = _read(chat, [url], 24_000)
    text = first.pages[0].text
    assert 20_000 < len(text) < 24_000 and set(text) == {"a"}
    version = first.pages[0].version
    assert version == read_page.text_version("a" * 30_000 + "b" * 10_000)
    rendered = read_page.render(first)
    assert (f"Call read_page with offset {len(text)} for the next part, with version "
            f"{version}. To find a text anywhere in the page, call read_page with find]") in rendered
    middle = _read(chat, [url], 24_000, offset=30_000, version=version)
    assert middle.pages[0].text == "b" * 10_000
    assert not middle.pages[0].truncated
    beyond = _read(chat, [url], 24_000, offset=50_000)
    assert beyond.pages[0].text == ""
    assert beyond.pages[0].full_chars == 40_000
    assert "offset 50000 is at or past the page's 40,000 characters" in read_page.render(beyond)
    assert calls == [url]


def _people(count):
    """A large structured file: one JSON entry for each person, with multibyte names."""
    rows = []
    for i in range(count):
        name = f"Zoë Łukasz 名前 {i}"
        role = "Staff Engineer" if i % 97 == 0 else "Developer"
        rows.append(json.dumps({"id": i, "name": name, "role": role, "bio": "é" * 40},
                               ensure_ascii=False))
    return "[\n" + ",\n".join(rows) + "\n]"


def test_find_gives_exact_offsets_and_continues_on_the_same_text(monkeypatch):
    url = "https://gitlab.example/people.json"
    text = _people(3000)
    chat = SimpleNamespace(page_reads={})
    calls = _loader(monkeypatch, {url: text})
    expected = [i for i in range(len(text)) if text[i:i + 14].lower() == "staff engineer"]
    assert len(expected) == 31

    seen, offset, version, rounds = [], 0, "", 0
    while True:
        result = _read(chat, [url], 4_000, find="STAFF engineer", offset=offset,
                       version=version)
        page = result.pages[0]
        rendered = read_page.render(result)
        assert len(rendered.encode("utf-8")) <= 4_000
        assert page.total_matches == 31
        for match_start, start, end in page.matches:
            assert text[match_start:match_start + 14] == "Staff Engineer"
            assert f"[match at {match_start}, text from {start} to {end}]\n{text[start:end]}" in rendered
        seen += [m for m in expected if any(s <= m and m + 14 <= e for _, s, e in page.matches)]
        rounds += 1
        if page.next_offset is None:
            break
        assert (f"Call read_page with this URL, find \"STAFF engineer\", offset {page.next_offset} and version "
                f"{page.version} for the next matches]") in rendered
        offset, version = page.next_offset, page.version
    assert seen == expected and rounds > 1
    assert calls == [url]


def test_find_with_no_match_says_so_with_the_count_and_the_version(monkeypatch):
    url = "https://a.example"
    chat = SimpleNamespace(page_reads={})
    _loader(monkeypatch, {url: "alpha beta alpha"})
    result = _read(chat, [url], 2_000, find="alpha", offset=5)
    assert result.pages[0].shown_matches == 1
    result = _read(chat, [url], 2_000, find="gamma")
    rendered = read_page.render(result)
    version = read_page.text_version("alpha beta alpha")
    assert ('[find "gamma": no match from offset 0. The page has 0 matches in 16 characters. '
            f"Version {version}.]") in rendered
    # A short page shows its whole text, so the model sees which page it read.
    assert rendered.endswith("The whole text of the page follows.\n\nalpha beta alpha")


def test_a_long_page_with_no_match_shows_no_text(monkeypatch):
    url = "https://a.example"
    text = "word " * 400
    chat = SimpleNamespace(page_reads={})
    _loader(monkeypatch, {url: text})
    rendered = read_page.render(_read(chat, [url], 2_000, find="gamma"))
    assert "no match from offset 0" in rendered and "word" not in rendered


def test_a_match_that_does_not_fit_is_not_cut_and_starts_the_next_call(monkeypatch):
    url = "https://a.example"
    word = "needle" * 120
    chat = SimpleNamespace(page_reads={})
    _loader(monkeypatch, {url: "x" * 500 + word + "y" * 500})
    result = _read(chat, [url], 600, find=word)
    page = result.pages[0]
    assert page.matches == [] and page.next_offset == 500
    assert word not in read_page.render(result)


def test_a_changed_or_expired_text_is_reported_and_not_loaded_again(monkeypatch):
    url = "https://a.example"
    chat = SimpleNamespace(page_reads={})
    calls = _loader(monkeypatch, {url: "old text " * 3000})
    first = _read(chat, [url], 2_000)
    old_version = first.pages[0].version
    # The kept text expires.
    chat.page_reads.clear()
    expired = _read(chat, [url], 2_000, offset=1_500, version=old_version)
    assert expired.pages[0].error.startswith(f"the text of version {old_version} is no longer kept")
    assert "COULD NOT READ" in read_page.render(expired)
    assert calls == [url]
    # A new read keeps a changed text, and the old version no longer matches it.
    _loader(monkeypatch, {url: "new text " * 3000})
    fresh = _read(chat, [url], 2_000)
    new_version = fresh.pages[0].version
    assert new_version != old_version
    changed = _read(chat, [url], 2_000, offset=1_500, version=old_version)
    assert changed.pages[0].error.startswith(
        f"the page changed: the kept text is version {new_version}, not version {old_version}")


def test_a_text_that_is_not_kept_has_no_version_to_continue_with(monkeypatch):
    """A text above READ_PAGE_PDF_MAX_BYTES is not kept. Its cut line and its find result
    name no version, so a continuation reads the page again and reports no expiry."""
    url = "https://a.example"
    chat = SimpleNamespace(page_reads={})
    _loader(monkeypatch, {url: "word " * 6000})
    monkeypatch.setattr(read_page, "PDF_MAX_BYTES", 1_000)
    first = _read(chat, [url], 2_000)
    assert first.pages[0].version == "" and chat.page_reads == {}
    rendered = read_page.render(first)
    assert "for the next part. To find" in rendered and "version" not in rendered
    found = _read(chat, [url], 2_000, find="word")
    rendered = read_page.render(found)
    assert "Version" not in rendered and "version" not in rendered
    assert 'Call read_page with this URL, find "word" and offset' in rendered


def test_the_whole_result_fits_its_byte_ceiling_with_multibyte_text(monkeypatch):
    urls = [f"https://{i}.example" for i in range(3)]
    texts = {u: ("名前é " * 20_000) for u in urls}
    chat = SimpleNamespace(page_reads={})
    _loader(monkeypatch, texts)
    for ceiling in (1_500, 5_000, 24_000):
        result = _read(chat, urls, ceiling)
        rendered = read_page.render(result)
        assert len(rendered.encode("utf-8")) <= ceiling, ceiling
        for page in result.pages:
            assert page.text == texts[page.url][:len(page.text)]
            assert page.truncated
        result = _read(chat, urls, ceiling, find="名前é")
        assert len(read_page.render(result).encode("utf-8")) <= ceiling, ceiling


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


def test_the_rendered_page_shape_matches_the_worker_parser():
    """`tasks/P_agent/reports.py` reads this shape to record one evidence entry for each
    page: the separator, the URL on the second line of a section, the failure lines and the
    cut line. The worker cannot import this module, so the worker test holds the same
    literals."""
    text = read_page.render(ReadResult(pages=[
        PageRead(url="https://example.org/a", title="A", final_url="https://example.org/a",
                 text="x" * 10, full_chars=50, truncated=True),
        PageRead(url="https://example.org/b", error="timeout"),
    ]))
    first, second = text.split("\n\n---\n\n")
    assert first.split("\n")[1] == "https://example.org/a"
    assert "[cut: this call read 10 of the page's 50 characters." in first
    assert second.endswith("\n\nCOULD NOT READ: timeout")
    found = PageRead(url="https://example.org/p", full_text="abc Staff Engineer def",
                     find="Staff Engineer", version="0123456789abcdef", full_chars=22)
    read_page._fill_find(found, 1000)
    body = read_page.render(ReadResult(pages=[found])).split("\n", 2)[2].strip()
    assert body.startswith('[find "Staff Engineer": 1 of 1 matches from offset 0 are shown. '
                           "The page has 1 matches in 22 characters. Version 0123456789abcdef.]")
    assert "\n\n[match at 4, text from 0 to 22]\nabc Staff Engineer def" in body
    assert read_page.BOT_CHECK_LABEL == "BLOCKED BY A BOT CHECK"
    from browser_use_server.server import ARTIFACT_MARKER

    assert ARTIFACT_MARKER == "[hoover4:artifacts]"
