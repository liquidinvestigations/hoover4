"""One Chromium instance, driven over CDP by nodriver, serialised behind a lock.

Two rules hold this together, and both are load-bearing:

**One browser, one call at a time.** Concurrent CDP sessions in a single container is
how this server falls over — tabs leak, the websocket interleaves responses, and the
whole thing wedges. Every tool call takes :data:`_lock`, so the server is deliberately a
throughput bottleneck. It is a research tool called a handful of times per question, not
a crawler.

**A timeout kills the browser rather than leaving it wedged.** A hung navigation leaves
Chromium in a state the next call inherits, and the failure then looks intermittent and
unrelated. On timeout the instance is torn down and the next call starts a fresh one.
"""

from __future__ import annotations

import asyncio
import logging
import os

log = logging.getLogger(__name__)

NAV_TIMEOUT = float(os.getenv("BROWSER_NAV_TIMEOUT", "30"))
WINDOW_WIDTH = int(os.getenv("BROWSER_WINDOW_WIDTH", "1280"))
WINDOW_HEIGHT = int(os.getenv("BROWSER_WINDOW_HEIGHT", "900"))

#: How long to let a page settle after load before reading it. Enough for the common
#: "render the body with JS" case without turning every fetch into a wait.
SETTLE_SECONDS = float(os.getenv("BROWSER_SETTLE_SECONDS", "1.5"))

_lock = asyncio.Lock()
_browser = None


async def _start():
    global _browser
    import nodriver

    log.info("starting chromium")
    _browser = await nodriver.start(
        headless=True,
        browser_args=[
            # Required in a container: Chromium's sandbox needs privileges the image
            # does not have, and without this it exits immediately.
            "--no-sandbox",
            "--disable-dev-shm-usage",  # /dev/shm is 64 MB by default and Chromium fills it
            "--disable-gpu",
            f"--window-size={WINDOW_WIDTH},{WINDOW_HEIGHT}",
        ],
    )
    return _browser


async def _stop():
    """Tear the instance down, tolerating a browser that is already broken."""
    global _browser
    if _browser is None:
        return
    try:
        _browser.stop()
    except Exception as exc:  # noqa: BLE001 - we are already in the failure path
        log.warning("could not stop chromium cleanly: %s", exc)
    finally:
        _browser = None


async def _get():
    global _browser
    if _browser is None:
        await _start()
    return _browser


async def with_page(url: str, action, timeout: float | None = None):
    """Open `url` in the shared browser and run `action(tab)` against it.

    Serialised behind the module lock. On timeout the browser is destroyed rather than
    reused — see the module docstring.
    """
    limit = timeout or NAV_TIMEOUT
    async with _lock:
        # Two attempts, because the *first* call after the instance has gone stale is
        # otherwise always wasted. Chromium's websocket can be dead while `_browser` is
        # still a live-looking handle — `cdp.page.navigate` then raises, `_stop()` clears
        # it, and only the *next* call succeeds. That was visible in a real agent run: a
        # perfectly good URL failed, the agent apologised and went somewhere else. The
        # retry runs against a guaranteed-fresh browser, so it distinguishes "stale
        # instance" from "this page genuinely will not load".
        for attempt in (1, 2):
            try:
                return await asyncio.wait_for(_navigate_and_run(url, action), timeout=limit)
            except asyncio.TimeoutError:
                # A timeout is about the page, not the instance, so it is not retried —
                # but the browser still goes, because a hung navigation leaves state the
                # next call would inherit.
                log.warning("navigation to %s exceeded %ss; restarting chromium", url, limit)
                await _stop()
                raise TimeoutError(f"timed out after {limit:g}s loading {url}") from None
            except Exception as exc:  # noqa: BLE001 - retried once, then surfaced
                await _stop()
                if attempt == 2:
                    raise
                log.warning("browser call failed (%s); retrying once on a fresh instance", exc)


async def _navigate_and_run(url: str, action):
    browser = await _get()
    tab = await browser.get(url)
    try:
        await tab.sleep(SETTLE_SECONDS)
        return await action(tab)
    finally:
        try:
            await tab.close()
        except Exception as exc:  # noqa: BLE001 - a tab that will not close is not fatal
            log.debug("tab close failed: %s", exc)


async def shutdown():
    async with _lock:
        await _stop()
