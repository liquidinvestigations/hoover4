"""One Chromium instance, driven over CDP by nodriver, serialised behind a lock.

Pages are opened in a **per-chat browser context** so cookies and storage do not leak
between conversations — see :mod:`.sessions` for the lifetime rules. The context is the
isolation boundary; the Chromium process and the lock below are still shared.

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

from browser_use_server.sessions import reaper, registry

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


async def with_page(url: str, action, timeout: float | None = None, session_id: str | None = None):
    """Open `url` in `session_id`'s browser context and run `action(tab)` against it.

    Serialised behind the module lock. On timeout the browser is destroyed rather than
    reused — see the module docstring.
    """
    limit = timeout or NAV_TIMEOUT
    async with _lock:
        session = registry.get(session_id)
        await _evict_over_limit()
        # Two attempts, because the *first* call after the instance has gone stale is
        # otherwise always wasted. Chromium's websocket can be dead while `_browser` is
        # still a live-looking handle — `cdp.page.navigate` then raises, `_stop()` clears
        # it, and only the *next* call succeeds. That was visible in a real agent run: a
        # perfectly good URL failed, the agent apologised and went somewhere else. The
        # retry runs against a guaranteed-fresh browser, so it distinguishes "stale
        # instance" from "this page genuinely will not load".
        for attempt in (1, 2):
            try:
                return await asyncio.wait_for(
                    _navigate_and_run(url, action, session), timeout=limit
                )
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


async def _navigate_and_run(url: str, action, session):
    browser = await _get()
    tab = await _open_in_session(browser, url, session)
    try:
        await tab.sleep(SETTLE_SECONDS)
        return await action(tab)
    finally:
        try:
            await tab.close()
        except Exception as exc:  # noqa: BLE001 - a tab that will not close is not fatal
            log.debug("tab close failed: %s", exc)


async def _open_in_session(browser, url: str, session):
    """Open a tab in this session's context, creating the context on first use.

    Falls back to the default context if the context cannot be created. The fallback
    loses isolation, which is worth saying out loud in the log — but refusing to fetch
    the page at all would turn a nodriver upgrade into an outage.
    """
    if session.context_id is None:
        try:
            # `new_window=True` is required, not cosmetic. With `False` Chromium answers
            # `Failed to open new tab - no browser is open [code: -32000]`: a fresh
            # context has no window, and a tab needs one to live in.
            tab = await browser.create_context(url, new_window=True)
            session.context_id = getattr(tab, "browser_context_id", None)
            log.info(
                "browser session %s bound to context %s", session.session_id, session.context_id
            )
            return tab
        except Exception as exc:  # noqa: BLE001 - degraded, not fatal
            log.warning(
                "could not create an isolated context for session %s (%s); "
                "falling back to the shared one",
                session.session_id,
                exc,
            )
            session.context_id = None
            return await browser.get(url)

    # Existing context: the tab must be created *in it*, addressing the context by id.
    # `browser.get(new_tab=True)` would open in the default context instead and quietly
    # undo the isolation — the tab would work, so nothing would look wrong.
    return await _open_target_in_context(browser, url, session.context_id)


async def _open_target_in_context(browser, url: str, context_id: str):
    """Create a page target inside `context_id` and return nodriver's Tab for it.

    Mirrors what `Browser.create_context` does after making the context, because
    nodriver exposes no "new tab in this existing context" call.
    """
    import nodriver.cdp.target as target

    target_id = await browser.send(
        target.create_target(url, browser_context_id=context_id, new_window=True)
    )
    await browser.sleep(0.5)
    for item in browser.targets:
        if item.target.type_ == "page" and item.target.target_id == target_id:
            return item
    # The target exists but nodriver has not mapped it yet. Raising here is right: the
    # caller retries once on a fresh instance, which is better than silently handing
    # back a tab from the wrong context.
    raise RuntimeError(f"created target {target_id} in context {context_id} but could not attach")


async def _dispose(session) -> None:
    """Dispose one session's Chromium context. Safe to call for a session with none."""
    context_id = session.context_id
    session.context_id = None
    if context_id is None or _browser is None:
        return
    try:
        import nodriver.cdp.target as target

        await _browser.connection.send(target.dispose_browser_context(context_id))
        log.info("disposed browser context %s (session %s)", context_id, session.session_id)
    except Exception as exc:  # noqa: BLE001 - a context we cannot dispose is not fatal
        log.warning("could not dispose context %s: %s", context_id, exc)


async def _evict_over_limit() -> None:
    for session in registry.over_limit():
        log.info("browser session cap reached; evicting %s", session.session_id)
        registry.forget(session.session_id)
        await _dispose(session)


async def close_session(session_id: str) -> bool:
    """Drop one chat's browser context. Returns False if it was not open.

    Called when a conversation ends, so state goes at the end of the chat rather than
    an hour later.
    """
    async with _lock:
        session = registry.forget(session_id)
        if session is None:
            return False
        await _dispose(session)
        return True


async def start_reaper() -> asyncio.Task:
    """Background task disposing sessions idle past the timeout."""
    return asyncio.create_task(reaper(_dispose_locked))


async def _dispose_locked(session) -> None:
    async with _lock:
        await _dispose(session)


async def shutdown():
    async with _lock:
        await _stop()
