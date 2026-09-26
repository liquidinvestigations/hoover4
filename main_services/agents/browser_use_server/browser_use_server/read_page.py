"""`read_page`, open several URLs, read them, hand back the text.

This is the ninety-percent case of browsing, as one call. Reading a page used to be
`browser_navigate`, then `browser_snapshot`, then reading an accessibility tree, once per
URL, serially, three round trips and a tree full of markup for something the model wanted
as prose. Here it is navigate, settle, extract, capture, return, batched over URLs.

**`goal` is not an inner agent loop.** It is passed to the extraction, which uses it to
choose *which* part of a long page survives the character budget, and it is recorded on the
artifact so the capture says what the page was read for. An LLM loop inside a tool hides
cost and latency behind something that looks like a function call, and it cannot be
debugged from the outside; that shape was rejected deliberately and must not come back.

**The artifact contract is unchanged.** Each page produces the same screenshot-always,
MHTML-under-the-cap capture that an explicit snapshot produces, so the archived-page card
in the transcript renders exactly as it did, one card per page, several per call.

The shared character budget is divided across the URLs asked for, and what did not fit is
named in the note rather than silently dropped. See `agent_common.batching`.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import time
from dataclasses import dataclass, field

from agent_common import artifacts, batching

from browser_use_server import capture as capture_mod
from browser_use_server.urlcheck import UrlNotAllowed, check_url

log = logging.getLogger(__name__)

#: The whole call's text budget, shared across the URLs. Sized so a four-page read stays
#: comfortably inside a turn: four pages at ~7500 characters each is roughly 8k tokens.
TOTAL_CHARS = int(os.getenv("READ_PAGE_TOTAL_CHARS", "30000"))

#: More than this in one call is a model opening everything rather than choosing. The
#: surplus is refused by name in the note, which is information; silently reading the
#: first few would not be.
MAX_URLS = int(os.getenv("READ_PAGE_MAX_URLS", "6"))

#: How long one page gets to load before it is abandoned and reported as a failure. A page
#: that has not settled in this long is not going to, and the remaining URLs get the
#: rest of the call's time.
NAVIGATE_TIMEOUT_MS = int(os.getenv("READ_PAGE_NAVIGATE_TIMEOUT_MS", "25000"))

#: The extraction. Runs in the page, returns title plus the readable text with the
#: furniture removed. It is deliberately not Readability-the-library: an innerText read of
#: the densest text block is within a few percent of it on the pages this actually meets,
#: and it needs nothing injected into a page the router does not control.
_EXTRACT_JS = """
() => {
  const strip = ['script','style','noscript','svg','nav','header','footer','aside','form'];
  const doc = document.cloneNode(true);
  for (const tag of strip) {
    for (const el of Array.from(doc.getElementsByTagName(tag))) el.remove();
  }
  const candidates = Array.from(doc.querySelectorAll('article,main,[role=main],body'));
  let best = doc.body, bestLen = 0;
  for (const el of candidates) {
    const len = (el.innerText || el.textContent || '').length;
    if (len > bestLen) { best = el; bestLen = len; }
  }
  const text = (best.innerText || best.textContent || '')
    .replace(/[ \\t]+/g, ' ')
    .replace(/\\n{3,}/g, '\\n\\n')
    .trim();
  return JSON.stringify({ title: document.title || '', url: location.href, text });
}
"""

#: How long a page that shows a bot check gets to pass it before it is reported as
#: blocked. A Cloudflare check that a real browser passes clears in a few seconds.
BOT_CHECK_WAIT_S = float(os.getenv("READ_PAGE_BOT_CHECK_WAIT_S", "10"))

#: How often the page is probed again during that wait.
BOT_CHECK_POLL_S = 0.5

#: The label a blocked page carries in the text the model reads.
BOT_CHECK_LABEL = "BLOCKED BY A BOT CHECK"

#: The error recorded on a blocked page, also counted in the call's telemetry detail.
BOT_CHECK_ERROR = "blocked by a bot check"

#: Detects a bot check page. Runs in the page and returns a JSON string
#: `{text, check, url, title, type}`, where `text` names the signal that matched and
#: `type` is the document's content type.
_CHECK_JS = """
() => {
  const t = (document.title || '').toLowerCase();
  const b = ((document.body && document.body.innerText) || '').slice(0, 4000).toLowerCase();
  // Not the challenge-platform script: Cloudflare adds it to ordinary pages too, so it
  // marks a page as a check after the check has passed.
  const dom = !!(window._cf_chl_opt
    || document.querySelector('#challenge-form, #challenge-running, #challenge-stage'));
  const titles = ['just a moment', 'attention required', 'checking your browser', 'please wait', 'ddos-guard', 'access denied'];
  const phrases = ['performing security verification', 'verify you are human', 'checking your browser',
                   'enable javascript and cookies to continue', 'verifies you are not a bot'];
  const hit = dom ? 'dom' : (titles.find(x => t.includes(x)) || phrases.find(x => b.includes(x)) || '');
  return JSON.stringify({ text: hit, check: !!hit, url: location.href, title: document.title || '',
                          type: document.contentType || '' });
}
"""

#: A PDF larger than this is not read, and the page error names its size and this limit.
PDF_MAX_BYTES = int(os.getenv("READ_PAGE_PDF_MAX_BYTES", str(32 * 1024 * 1024)))

#: Only the text of this many pages of a PDF is read.
PDF_MAX_PAGES = 50

#: The bytes of a PDF come back through `browser_evaluate` as base64 in slices of this size.
PDF_SLICE_BYTES = 1024 * 1024

#: Reads one slice of the PDF the page shows. The request runs inside the page, so the
#: browser's proxy filter applies to it. The bytes stay on `window` between the slices.
_PDF_SLICE_JS = """
async () => {
  if (!window.__h4pdf) {
    const response = await fetch(location.href);
    window.__h4pdf = new Uint8Array(await response.arrayBuffer());
  }
  const all = window.__h4pdf;
  const part = all.subarray(START, Math.min(all.length, START + SIZE));
  let binary = '';
  for (let i = 0; i < part.length; i += 32768) {
    binary += String.fromCharCode.apply(null, part.subarray(i, i + 32768));
  }
  return JSON.stringify({ text: btoa(binary), total: all.length, url: location.href });
}
"""


@dataclass
class PageRead:
    """One URL's outcome. `text` is empty when `error` is set, and never both."""

    url: str
    title: str = ""
    final_url: str = ""
    text: str = ""
    error: str = ""
    truncated: bool = False
    artifact: dict | None = None
    #: The page stayed on a bot check for the whole wait. `error` is then set too.
    blocked: bool = False
    #: What the call note says about this page. It is empty when there is nothing to add.
    note: str = ""


@dataclass
class ReadResult:
    pages: list[PageRead] = field(default_factory=list)
    note: str = ""
    artifacts: list[dict] = field(default_factory=list)


def plan(raw_urls: object) -> tuple[list[str], list[str], list[str], str]:
    """`(to_read, repeats, over_cap, note)`, everything decided before a browser is touched.

    Separated from the fetching so the whole argument-shaping contract is testable without
    a Chromium: this is where a model's malformed list, its duplicate URLs and its
    twenty-at-once call are turned into a plan and a sentence explaining it.
    """
    urls = batching.as_list(raw_urls)
    kept, repeats = batching.dedupe(urls)
    over_cap = kept[MAX_URLS:]
    to_read = kept[:MAX_URLS]

    note = batching.corrective_note(
        batching.repeats_note(repeats, "URL"),
        (
            f"{len(over_cap)} URLs beyond the {MAX_URLS}-per-call limit were not read: "
            f"{', '.join(over_cap)}. Read the most promising ones first, then call again."
            if over_cap
            else ""
        ),
    )
    return to_read, repeats, over_cap, note


def focus(text: str, goal: str, limit: int) -> tuple[str, bool]:
    """Reduce `text` to `limit` characters, keeping the part that answers `goal`.

    With no goal this is a plain head truncation, which is the right default: a page's
    opening is its summary far more often than not. With a goal, paragraphs carrying the
    goal's words are kept first and the rest fills what is left, so a term appearing
    forty thousand characters down a reference page survives a budget that would otherwise
    have cut at the table of contents.

    No model is consulted. See the module docstring.
    """
    if len(text) <= limit:
        return (text, False)

    terms = {w for w in goal.casefold().split() if len(w) > 3}
    if not terms:
        return batching.truncate(text, limit)

    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    scored = [
        (sum(1 for t in terms if t in p.casefold()), i, p) for i, p in enumerate(paragraphs)
    ]
    chosen: list[tuple[int, str]] = []
    used = 0
    for score, index, para in sorted(scored, key=lambda s: (-s[0], s[1])):
        if score == 0 and used > 0:
            break
        if used + len(para) + 2 > limit:
            continue
        chosen.append((index, para))
        used += len(para) + 2
    if not chosen:
        return batching.truncate(text, limit)

    kept = "\n\n".join(p for _, p in sorted(chosen))
    remaining = limit - len(kept)
    if remaining > batching.MIN_ITEM_CHARS:
        picked = {i for i, _ in chosen}
        filler = "\n\n".join(p for i, p in enumerate(paragraphs) if i not in picked)
        extra, _ = batching.truncate(filler, remaining - 2)
        if extra:
            kept = f"{kept}\n\n{extra}"
    return (kept, True)


def render(result: ReadResult) -> str:
    """The text block the model reads. One clearly delimited section per page."""
    blocks: list[str] = []
    for page in result.pages:
        head = f"## {page.title or page.url}\n{page.final_url or page.url}"
        if page.blocked:
            where = page.final_url or page.url
            blocks.append(
                f"{head}\n\n{BOT_CHECK_LABEL}: {where}. The page stayed on its bot check for "
                f"{BOT_CHECK_WAIT_S:g} s, so this call has no text from it. Do not use this "
                "page as a source. Try its archived copy with web_search and sources "
                '["wayback"], or another page.'
            )
            continue
        if page.error:
            blocks.append(f"{head}\n\nCOULD NOT READ: {page.error}")
            continue
        tail = "\n\n[truncated, because this page's share of the shared budget ran out]" if page.truncated else ""
        blocks.append(f"{head}\n\n{page.text}{tail}")
    if result.note:
        blocks.append(f"NOTE: {result.note}")
    return "\n\n---\n\n".join(blocks) if blocks else "No pages were read."


async def read(chat, raw_urls: object, goal: str, username: str) -> ReadResult:
    """Navigate, extract and capture each URL in turn, inside one chat's browser.

    Serial rather than concurrent on purpose: there is one browser per chat and its calls
    are already serialised by the router's per-chat lock, so firing the navigations in
    parallel would queue them anyway while making the failure attribution worse.
    """
    to_read, _repeats, _over, note = plan(raw_urls)
    result = ReadResult(note=note)
    if not to_read:
        result.note = batching.corrective_note(
            note, "No URL was given. Pass `urls` as a list of http or https addresses."
        )
        return result

    per_page, fits = batching.divide_budget(TOTAL_CHARS, len(to_read))
    dropped = to_read[fits:]
    to_read = to_read[:fits]
    if dropped:
        result.note = batching.corrective_note(result.note, batching.dropped_note(dropped, "URL"))

    for url in to_read:
        page = await _read_one(chat, url, goal, per_page, username)
        result.pages.append(page)
        result.note = batching.corrective_note(result.note, page.note)
        if page.artifact:
            result.artifacts.append(page.artifact)
    return result


async def _read_one(chat, url: str, goal: str, limit: int, username: str) -> PageRead:
    page = PageRead(url=url)
    try:
        check_url(url)
    except UrlNotAllowed as exc:
        page.error = f"refused: {exc}"
        return page

    try:
        navigated, _ = await asyncio.wait_for(
            _call(chat, "browser_navigate", {"url": url}),
            timeout=NAVIGATE_TIMEOUT_MS / 1000.0,
        )
    except asyncio.TimeoutError:
        # The sidecar's own navigation timeout is longer than a batched read can afford:
        # one dead host must not spend the whole call's wall clock. Whatever loaded is
        # still extracted and captured below.
        navigated = f"navigation did not settle within {NAVIGATE_TIMEOUT_MS / 1000:g}s"
    if navigated:
        # A navigation that errored still leaves something on screen (a cookie wall, a
        # 403 page, a CAPTCHA), and that is exactly what the capture below is for. The
        # extraction is still attempted; only if it also comes back empty is this
        # reported as the failure.
        log.info("read_page: navigation to %s reported %s", url, navigated)

    first = await _probe(chat)
    if first and first.get("type") == "application/pdf":
        await _read_pdf(chat, page, url, goal, limit, first)
    elif (blocked_at := await _wait_out_check(chat, first)) is not None:
        # The check text is never returned as page text.
        page.blocked = True
        page.final_url = blocked_at or url
        page.error = BOT_CHECK_ERROR
    else:
        _extract(page, url, goal, limit, navigated, await _call(
            chat, "browser_evaluate", {"function": _EXTRACT_JS}
        ))

    captured = await capture_mod.capture(
        chat, "read_page", username, failed=bool(page.error)
    )
    if captured.artifact_id:
        entry = {
            "artifact_id": captured.artifact_id,
            "kind": artifacts.KIND_PAGE_CAPTURE,
            "status": captured.status,
            "url": captured.url or page.final_url or url,
            "title": captured.title or page.title,
        }
        detail = batching.corrective_note(captured.detail, f"read for: {goal}" if goal else "")
        if detail:
            entry["detail"] = detail
        page.artifact = entry
    return page


def _extract(
    page: PageRead, url: str, goal: str, limit: int, navigated: str, called: tuple[str, str]
) -> None:
    """Fill `page` from the extraction's `(error, text)` result."""
    failure, body = called
    payload = _decode(body) if not failure else None
    if payload is None:
        page.error = navigated or "the page returned no readable text"
        return
    page.title = str(payload.get("title") or "")
    page.final_url = str(payload.get("url") or url)
    text = str(payload.get("text") or "")
    if not text.strip():
        page.error = navigated or "the page returned no readable text"
    else:
        page.text, page.truncated = focus(text, goal or "", limit)


async def _probe(chat) -> dict | None:
    """Run the bot check probe. `None` when the call or its decode fails."""
    failure, body = await _call(chat, "browser_evaluate", {"function": _CHECK_JS})
    return None if failure else _decode(body)


async def _wait_out_check(chat, probe: dict | None) -> str | None:
    """Wait while the page shows a bot check. `None` when no check remains.

    `probe` is the first probe, taken after the navigation. A page with no check costs no
    wait. A page that is still a check after `BOT_CHECK_WAIT_S` returns the URL the last
    probe saw, which can be an empty string.
    """
    if not (probe and probe.get("check")):
        return None
    last_url = str(probe.get("url") or "")
    deadline = time.monotonic() + BOT_CHECK_WAIT_S
    while time.monotonic() < deadline:
        await asyncio.sleep(BOT_CHECK_POLL_S)
        probe = await _probe(chat)
        if probe is None:
            # The redirect after a passed check destroys the page context. Poll again.
            continue
        last_url = str(probe.get("url") or last_url)
        if not probe.get("check"):
            # The next navigation can still be in flight. Let it settle before the read.
            await asyncio.sleep(BOT_CHECK_POLL_S)
            return None
    return last_url


async def _read_pdf(chat, page: PageRead, url: str, goal: str, limit: int, probe: dict) -> None:
    """Read the text of the PDF the page shows, into `page`."""
    page.final_url = str(probe.get("url") or url)
    data = bytearray()
    total = 0
    while len(data) < PDF_MAX_BYTES:
        size = min(PDF_SLICE_BYTES, PDF_MAX_BYTES - len(data))
        script = _PDF_SLICE_JS.replace("START", str(len(data))).replace("SIZE", str(size))
        failure, body = await _call(chat, "browser_evaluate", {"function": script})
        payload = None if failure else _decode(body)
        if payload is None:
            page.error = failure or "the PDF could not be fetched in the page"
            return
        chunk = base64.b64decode(str(payload.get("text") or ""))
        total = int(payload.get("total") or 0)
        if total > PDF_MAX_BYTES:
            # A PDF keeps its cross-reference table at the end, so a cut file gives no text.
            page.error = (
                f"the PDF has {total} bytes, above the read limit of {PDF_MAX_BYTES} "
                "bytes (READ_PAGE_PDF_MAX_BYTES), so it was not read"
            )
            return
        data.extend(chunk)
        if not chunk or len(data) >= total:
            break
    title, text, error = await asyncio.to_thread(pdf_text, bytes(data))
    page.title = title
    if error:
        page.error = error
    else:
        page.text, page.truncated = focus(text, goal or "", limit)


def pdf_text(data: bytes) -> tuple[str, str, str]:
    """`(title, text, error)` of the first `PDF_MAX_PAGES` pages of a PDF."""
    from pypdf import PdfReader

    # pypdf logs a warning for each font it cannot parse in full, many for each page.
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        pages = [
            (reader.pages[i].extract_text() or "").strip()
            for i in range(min(PDF_MAX_PAGES, len(reader.pages)))
        ]
        title = str((reader.metadata or {}).get("/Title") or "")
    except Exception as exc:  # noqa: BLE001 - a damaged or cut PDF raises many types
        return ("", "", f"the PDF could not be read: {exc}")
    text = "\n\n".join(p for p in pages if p)
    if not text:
        return (title, "", "the PDF has no text layer")
    return (title, text, "")


async def _call(chat, tool: str, arguments: dict) -> tuple[str, str]:
    """Forward one sidecar call. `(error, text)`, exactly one of the two is non-empty.

    The unbound sidecar tools are still *callable* (they stopped being advertised, not
    routable) which is what lets this compose `browser_evaluate` without exposing it.
    """
    try:
        call = await chat.client.call_tool(tool, arguments, raise_on_error=False)
    except Exception as exc:  # noqa: BLE001 - a dead sidecar looks like this
        return (f"{tool} failed: {exc}", "")
    text = _text(call)
    if getattr(call, "is_error", False):
        return (text[:300] or f"{tool} failed", "")
    return ("", text)


def _text(call) -> str:
    parts = []
    for block in getattr(call, "content", None) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts).strip()


def _decode(body: str) -> dict | None:
    """The extraction's return value, which the sidecar wraps in prose around JSON.

    `browser_evaluate` answers with a `### Result` heading and the value beneath it, so
    the JSON object has to be found rather than parsed off the front. The extraction
    returns a *string* of JSON, which the sidecar then JSON-encodes again, hence the
    second decode.
    """
    decoder = json.JSONDecoder()
    for index, char in enumerate(body or ""):
        if char not in '{"':
            continue
        try:
            value, _ = decoder.raw_decode(body, index)
        except ValueError:
            continue
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                continue
        if isinstance(value, dict) and "text" in value:
            return value
    return None


__all__ = [
    "BOT_CHECK_ERROR",
    "BOT_CHECK_LABEL",
    "BOT_CHECK_WAIT_S",
    "MAX_URLS",
    "NAVIGATE_TIMEOUT_MS",
    "PageRead",
    "ReadResult",
    "TOTAL_CHARS",
    "focus",
    "plan",
    "read",
    "render",
]
