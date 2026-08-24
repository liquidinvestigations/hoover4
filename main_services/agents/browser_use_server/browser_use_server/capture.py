"""Capture what the agent saw, on the two tools whose whole purpose is to look.

**Captures are explicit.** `browser_take_screenshot` and `browser_snapshot` produce one;
nothing else does. Capturing after every action that could change the screen means a
screenshot plus an MHTML serialisation after almost every click, which is tens of rows and
over ten megabytes in a single day of demo use, most of them of pages nobody will ever open.

The argument for implicit capture is real. "The transcript must not depend on the
model's judgement", and a model that forgets to screenshot the CAPTCHA it hit leaves a
transcript where the failure is invisible. Explicit still wins, because the browser cards
render an explicit snapshot well enough that asking the model to take one is a reasonable
instruction rather than a hope. **Do not reintroduce implicit capture.**

Capture does happen **on the failure path** of those two tools. A screenshot of a cookie wall is the most valuable artifact this module produces,
and the tool "failing" is not a reason to discard the evidence of why.

Two artefacts per capture:

1. a **screenshot**, downscaled to 1280x720 and encoded WebP q72. Taken **even when the
   tool returned an error**: a CAPTCHA, a cookie wall or a blocked page is precisely what
   the user wants to see, and an error path with no evidence is the one that costs an hour
   of debugging.
2. an **MHTML snapshot**, inlined into self-contained HTML by :mod:`.mhtml`. Over
   `CAPTURE_MAX_SNAPSHOT_BYTES` it is dropped and the row is written `status='too_large'`
   with a `detail` the card shows. The thumbnail is kept regardless.

Both go through the router's *own* CDP connection to the same Chromium the sidecar is
driving. CDP allows a second client, and neither `Page.captureScreenshot` nor
`Page.captureSnapshot` needs anything Playwright holds exclusively.

## Cost control

An MHTML serialisation of a real page is megabytes and takes hundreds of milliseconds,
which is what makes capturing after every click expensive. Capturing only when the model
asks to look is the cost control.

**Do not add body-key reuse on top of it.** Deduplicating a capture whose
`(url, document.lastModified)` matches the previous one in the same chat looks free, but
two explicit snapshots of the same page are a deliberate act, and pointing the second at
the first one's bytes makes two `chat_artifacts` rows share an object. The retention
sweeper then has to be careful never to delete one out from under the other. (It is
careful, because transcripts contain rows written that way.)
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import time
from dataclasses import dataclass

from agent_common import artifacts

from browser_use_server.chat_browser import ChatBrowser
from browser_use_server import mhtml as mhtml_mod

log = logging.getLogger(__name__)

MAX_SNAPSHOT_BYTES = int(os.getenv("CAPTURE_MAX_SNAPSHOT_BYTES", str(8 * 1024 * 1024)))
THUMB_WIDTH = int(os.getenv("CAPTURE_THUMB_WIDTH", "1280"))
THUMB_HEIGHT = int(os.getenv("CAPTURE_THUMB_HEIGHT", "720"))
THUMB_QUALITY = int(os.getenv("CAPTURE_THUMB_QUALITY", "72"))

#: Capture must never dominate the tool's latency. Past this the capture is abandoned and
#: the tool result is returned without an artifact.
CAPTURE_TIMEOUT = float(os.getenv("CAPTURE_TIMEOUT_SECONDS", "20"))

#: Each step gets its own budget rather than sharing one.
#:
#: This matters most on the path the whole "capture on failure" rule exists for. A
#: navigation that timed out leaves the page still loading, and `Page.captureSnapshot`
#: then blocks until the load settles, so a single shared deadline burned the entire
#: budget on the snapshot and the *screenshot never happened*. The one case where the
#: evidence is most valuable produced no evidence at all. Now the screenshot is taken
#: first, under its own short deadline, and the snapshot gets what is left.
IDENTITY_TIMEOUT = float(os.getenv("CAPTURE_IDENTITY_TIMEOUT_SECONDS", "5"))
SCREENSHOT_TIMEOUT = float(os.getenv("CAPTURE_SCREENSHOT_TIMEOUT_SECONDS", "8"))
SNAPSHOT_TIMEOUT = float(os.getenv("CAPTURE_SNAPSHOT_TIMEOUT_SECONDS", "12"))

#: The only two tools after which a capture is taken, the two whose entire purpose is to
#: record what is on screen. Keep it that size. See the module docstring for what a
#: capture-after-every-tool list costs.
CAPTURING_TOOLS = frozenset({"browser_take_screenshot", "browser_snapshot"})


@dataclass
class CaptureResult:
    artifact_id: str | None = None
    status: str = artifacts.STATUS_OK
    detail: str = ""
    url: str = ""
    title: str = ""
    elapsed_ms: float = 0.0


def should_capture(tool_name: str) -> bool:
    return tool_name in CAPTURING_TOOLS


async def capture(
    chat: ChatBrowser,
    tool_name: str,
    username: str,
    failed: bool = False,
) -> CaptureResult:
    """Screenshot + snapshot the active page and write one `chat_artifacts` row.

    Never raises: a capture that fails must not turn a successful tool call into an error.
    """
    import asyncio

    started = time.monotonic()
    result = CaptureResult()
    try:
        result = await asyncio.wait_for(
            _capture(chat, tool_name, username, failed), timeout=CAPTURE_TIMEOUT
        )
    except asyncio.TimeoutError:
        # `str(TimeoutError())` is the empty string, so logging the exception alone
        # produced "capture after browser_navigate failed: " and said nothing.
        log.warning(
            "capture after %s exceeded its %.0fs budget", tool_name, CAPTURE_TIMEOUT
        )
        result.status = artifacts.STATUS_FAILED
        result.detail = f"capture timed out after {CAPTURE_TIMEOUT:g}s"
    except Exception as exc:  # noqa: BLE001 - see the docstring
        log.warning("capture after %s failed: %s", tool_name, exc)
        result.status = artifacts.STATUS_FAILED
        result.detail = str(exc)
    result.elapsed_ms = round((time.monotonic() - started) * 1000.0, 1)
    return result


async def _capture(
    chat: ChatBrowser, tool_name: str, username: str, failed: bool
) -> CaptureResult:
    tab = await _active_tab(chat)
    if tab is None:
        return CaptureResult(status=artifacts.STATUS_FAILED, detail="no active page")

    try:
        url, title = await asyncio.wait_for(_page_identity(tab), timeout=IDENTITY_TIMEOUT)
    except Exception:  # noqa: BLE001 - includes asyncio.TimeoutError
        # A page mid-navigation will not run our script. The target's own URL is still
        # worth recording, a capture that cannot say *which* page it is of is useless.
        url = getattr(getattr(tab, "target", None), "url", "") or ""
        title = ""

    result = CaptureResult(url=url, title=title)

    # 1. Screenshot FIRST, always, including on the failure path, and under its own
    #    deadline. See the module docstring and the note on SCREENSHOT_TIMEOUT.
    thumb: tuple[str, bytes, str] | None = None
    try:
        thumb_bytes = await asyncio.wait_for(_screenshot(tab), timeout=SCREENSHOT_TIMEOUT)
        if thumb_bytes:
            thumb = ("thumb.webp", thumb_bytes, "image/webp")
    except asyncio.TimeoutError:
        log.warning("screenshot for %s exceeded %.0fs", url, SCREENSHOT_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        log.warning("screenshot failed for %s: %s", url, exc)

    # 2. Snapshot. Always taken, with no change-detection reuse (see the module
    #    docstring): an explicit snapshot of a page already captured is a deliberate act,
    #    and quietly handing back the earlier bytes would make the second capture false
    #    about when it was taken.
    body: tuple[str, bytes, str] | None = None
    status, detail = artifacts.STATUS_OK, ""

    try:
        raw = await asyncio.wait_for(_snapshot_mhtml(tab), timeout=SNAPSHOT_TIMEOUT)
        if len(raw) > MAX_SNAPSHOT_BYTES:
            status = artifacts.STATUS_TOO_LARGE
            detail = (
                f"page snapshot is {len(raw) // 1024} kB, over the "
                f"{MAX_SNAPSHOT_BYTES // 1024} kB limit; only the screenshot was kept"
            )
            log.info("capture too large for %s: %s", url, detail)
        else:
            converted = mhtml_mod.convert(raw, captured_at=_now())
            html = converted.html.encode("utf-8")
            body = ("page.html", html, "text/html; charset=utf-8")
            if not result.title:
                result.title = mhtml_mod.page_title(converted.html)
    except asyncio.TimeoutError:
        # The page is still loading, which is exactly the situation a failed
        # navigation leaves behind. The screenshot above is the evidence; say so
        # rather than dropping the artifact.
        status = artifacts.STATUS_FAILED
        detail = (
            f"the page was still loading after {SNAPSHOT_TIMEOUT:g}s, so only the "
            "screenshot was kept"
        )
        log.info("snapshot for %s timed out; keeping the screenshot", url)
    except mhtml_mod.SnapshotTooLarge as exc:
        status, detail = artifacts.STATUS_TOO_LARGE, str(exc)
    except Exception as exc:  # noqa: BLE001
        status = artifacts.STATUS_FAILED
        detail = f"snapshot failed: {exc}"
        log.warning("snapshot failed for %s: %s", url, exc)

    if failed and not detail:
        # The screenshot is the evidence; say why it is here so the card can label it.
        detail = "captured after a failed tool call"

    # `to_thread`: `artifacts.write` is several synchronous S3 PUTs (screenshot, MHTML,
    # thumbnail) followed by a ClickHouse insert, and a page capture is megabytes. On the
    # event loop that stalls every other chat's browser I/O, including their navigation
    # timeouts, which then expire on a page that was never actually slow.
    artifact_id = await asyncio.to_thread(
        artifacts.write,
        artifacts.ArtifactRequest(
            session_id=chat.session_id,
            username=username,
            kind=artifacts.KIND_PAGE_CAPTURE,
            tool_name=tool_name,
            url=url,
            title=result.title,
            body=body,
            thumb=thumb,
            status=status,
            detail=detail,
        )
    )

    result.artifact_id = artifact_id
    result.status = status
    result.detail = detail
    return result


# ------------------------------------------------------------------ CDP calls

async def _active_tab(chat: ChatBrowser):
    """The tab the sidecar is driving.

    nodriver's `browser.tabs` is ordered by creation, and Playwright works on the last
    page it opened or focused, so the most recently created page target is the right
    guess. `browser.main_tab` is the fallback for a browser with a single tab.
    """
    browser = chat.browser
    if browser is None:
        return None
    try:
        await browser.update_targets()
    except Exception as exc:  # noqa: BLE001 - a stale target list is not fatal
        log.debug("update_targets failed: %s", exc)
    tabs = [t for t in getattr(browser, "tabs", []) if getattr(t, "target", None)]
    pages = [t for t in tabs if getattr(t.target, "type_", "") == "page"]
    if not pages:
        return getattr(browser, "main_tab", None)
    # A page with `about:blank` is the launch tab, not what the agent is looking at.
    real = [p for p in pages if (getattr(p.target, "url", "") or "").startswith("http")]
    return (real or pages)[-1]


async def _page_identity(tab) -> tuple[str, str]:
    """`(url, title)` in one round trip."""
    try:
        payload = await tab.evaluate(
            "JSON.stringify({u: location.href, t: document.title || ''})",
            await_promise=False,
            return_by_value=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("page identity read failed: %s", exc)
        return (getattr(getattr(tab, "target", None), "url", "") or ""), ""
    if not isinstance(payload, str):
        # The nodriver return-value trap: anything that is not the JSON string means the
        # script did not run. See the server module docstring.
        return (getattr(getattr(tab, "target", None), "url", "") or ""), ""
    import json

    try:
        data = json.loads(payload)
    except ValueError:
        return "", ""
    return data.get("u", ""), data.get("t", "")


async def _screenshot(tab) -> bytes:
    """A WebP thumbnail of the viewport, downscaled to at most 1280x720."""
    import nodriver.cdp.page as page_cdp

    data = await tab.send(page_cdp.capture_screenshot(format_="png", capture_beyond_viewport=False))
    raw = base64.b64decode(data) if isinstance(data, str) else bytes(data)
    return _to_webp(raw)


def _to_webp(png: bytes) -> bytes:
    """Downscale and re-encode. Falls back to the PNG when Pillow is unavailable, a
    larger thumbnail is better than no evidence."""
    try:
        from PIL import Image
    except ImportError:
        log.debug("Pillow not installed; storing the raw screenshot")
        return png
    with Image.open(io.BytesIO(png)) as image:
        image = image.convert("RGB")
        image.thumbnail((THUMB_WIDTH, THUMB_HEIGHT))
        out = io.BytesIO()
        image.save(out, format="WEBP", quality=THUMB_QUALITY, method=4)
        return out.getvalue()


async def _snapshot_mhtml(tab) -> bytes:
    import nodriver.cdp.page as page_cdp

    data = await tab.send(page_cdp.capture_snapshot(format_="mhtml"))
    if isinstance(data, bytes):
        return data
    return str(data or "").encode("utf-8", "replace")


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
