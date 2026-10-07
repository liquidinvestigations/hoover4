"""A special browser: a Chromium of its own with a queue of tab slots.

`read_page` reads in the special session `_reader`. A special browser has these
properties:

* It has its own Chromium, with the launch settings and extensions of a normal session,
  and no playwright-mcp sidecar. So no `browser_*` tool can act in it, and it shares no
  cookies with a normal session.
* A queue of `slots` tab slots limits the tabs open at the same time. Each unit of work,
  for example one URL of a `read_page` call, takes one slot and one tab. A wait for a slot
  ends at the deadline of the caller.
* The router does not count it in `BROWSER_MAX_CONTEXTS`, and the LRU cap never evicts
  it. The browser starts on first use.
* When its Chromium stops, every tab lease of that Chromium sees `died`, and the next
  lease starts a new Chromium.
* `sweep_tabs()` closes the page tabs that no lease holds, for example a pop-up window
  or a tab whose close did not finish.
* A watchdog checks each new tab. The creation of the tab and a trivial `Runtime.evaluate`
  in it must each answer within `TAB_ANSWER_S`. A tab that does not answer fails its lease.
  After `TAB_FAILURES` such tabs in a row, the special browser restarts its Chromium. Every
  lease of the old Chromium sees `died`, and the next lease uses the new Chromium. A
  Chromium that cannot start a renderer gives this symptom, for example when the container
  reaches its process limit.
* `context_tab()` opens a second tab for a lease in a new CDP browser context with its own
  proxy, and disposes the context after use. `read_page` reads over Tor in it. The
  extensions named in `context_extensions` are loaded again at each start with
  `Extensions.loadUnpacked(enableInIncognito)`, because an extension of the launch acts in
  no CDP browser context. Measured: uBlock Origin Lite then acts in a new context. "I
  still don't care about cookies" does not, because it follows the tabs of the default
  context only.

Only the text cache `page_reads` belongs to `read_page`. A second special session uses this
class with its own name and slot count.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from dataclasses import dataclass

from browser_use_server import chat_browser
from browser_use_server.chat_browser import ChatBrowser

log = logging.getLogger(__name__)

#: How long the close of a tab may take. A browser that stops answering must not keep the
#: caller past its deadline.
CLOSE_TIMEOUT_S = 5.0

#: How long the creation of a new tab, and then a trivial script in it, may each take. See
#: the module text.
TAB_ANSWER_S = float(os.getenv("SPECIAL_BROWSER_TAB_ANSWER_S", "5"))

#: How many new tabs in a row may fail to answer before the Chromium restarts.
TAB_FAILURES = max(1, int(os.getenv("SPECIAL_BROWSER_TAB_FAILURES", "3")))

#: The script of the watchdog check. It needs a renderer, and nothing else.
PROBE_EXPRESSION = "1"


class SlotWaitTimeout(Exception):
    """The deadline came before a slot was free."""


class TabNotAnswering(RuntimeError):
    """A new tab was not made, or did not run a trivial script, within `TAB_ANSWER_S`."""


@dataclass
class Lease:
    """One tab of a special browser, held by one unit of work."""

    tab: object
    target_id: str
    #: Set when the Chromium of this tab stops.
    died: asyncio.Event
    #: The CDP port of that Chromium, or 0 when it is not known.
    cdp_port: int = 0
    #: The nodriver browser connection of that Chromium. `context_tab` needs it.
    browser: object = None
    #: Seconds that the lease waited for a free slot.
    slot_wait_s: float = 0.0
    #: Seconds from the slot to a tab that answers: a cold start of the browser, the
    #: creation of the tab and the watchdog probe.
    tab_open_s: float = 0.0


class SpecialBrowser:
    """One Chromium without a sidecar, and a queue of `slots` tabs. See the module text."""

    def __init__(self, name: str, slots: int, context_extensions: tuple[str, ...] = ()) -> None:
        self.name = name
        self.slots = max(1, slots)
        #: The folder names of the extensions that act in a context of `context_tab`.
        self.context_extensions = tuple(context_extensions)
        self._slots = asyncio.Semaphore(self.slots)
        self._chat: ChatBrowser | None = None
        self._died = asyncio.Event()
        self._starting: asyncio.Task | None = None
        self._watcher: asyncio.Task | None = None
        #: The targets that a lease holds now. `sweep_tabs` closes no target in this set.
        self._leased: set[str] = set()
        #: Tab creations in flight. A new target is in no set until its creation answers,
        #: so `sweep_tabs` closes no unknown target while this is above 0.
        self._creating = 0
        #: The page targets that existed when the browser started. They are never closed,
        #: so the browser always keeps a tab.
        self._initial: set[str] = set()
        #: The `read_page` text cache, by `(URL, links)`. Each value is `(expiry, title,
        #: final_url, text, version, route)`. See `read_page.read`. Another use of this
        #: class leaves it empty.
        self.page_reads: dict[tuple[str, bool], tuple[float, str, str, str, str, str]] = {}
        #: Contexts made by `context_tab`, and the extensions that `_start` loaded for them.
        self.contexts = 0
        self.context_extensions_loaded = 0
        self.in_use = 0
        self.max_waiting = max(0, int(os.getenv("SPECIAL_BROWSER_MAX_WAITING", "32")))
        self.waiting = 0
        self.peak_in_use = 0
        self.peak_waiting = 0
        self.leases = 0
        self.wait_timeouts = 0
        self.wait_total_s = 0.0
        self.wait_max_s = 0.0
        self.wait_last_s = 0.0
        self.starts = 0
        self.deaths = 0
        self.spawn_failures = 0
        self.tabs_swept = 0
        #: New tabs that did not answer, in a row and in total. See the module text.
        self._tabs_not_answering = 0
        self.tabs_not_answering = 0
        #: Restarts of the Chromium by the watchdog. `deaths` does not count them.
        self.watchdog_restarts = 0
        #: The stops of replaced Chromium processes that are still running.
        self._stopping: set[asyncio.Task] = set()

    # ---------------------------------------------------------------- the browser

    def alive(self) -> bool:
        chat = self._chat
        return chat is not None and chat_browser.chromium_alive(chat)

    async def _browser(self, deadline: float) -> tuple[ChatBrowser, asyncio.Event]:
        """The live Chromium and its `died` event. Starts it when it is not running.

        Callers share one start. A caller that reaches its deadline stops waiting, and the
        start continues for the others. Raises `asyncio.TimeoutError` at the deadline and
        `BrowserSpawnFailed` when the start fails.
        """
        while True:
            chat = self._chat
            if chat is not None and chat_browser.chromium_alive(chat):
                return chat, self._died
            if self._starting is None or self._starting.done():
                self._starting = asyncio.ensure_future(self._start())
                # A caller that stopped waiting leaves the exception unread. Read it here,
                # so the log has no "exception was never retrieved" line.
                self._starting.add_done_callback(lambda f: f.cancelled() or f.exception())
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError
            await asyncio.wait_for(asyncio.shield(self._starting), remaining)

    async def _start(self) -> None:
        stale, self._chat = self._chat, None
        if stale is not None:
            await chat_browser.stop(stale)
        # A Chromium that the watchdog replaced ends first, so the two do not run together.
        await self._stopped()
        try:
            chat = await chat_browser.start(self.name, sidecar=False)
        except chat_browser.BrowserSpawnFailed:
            self.spawn_failures += 1
            raise
        try:
            self.starts += 1
            self._initial = await _page_targets(chat)
            await self._load_context_extensions(chat)
            self._died = asyncio.Event()
            self._chat = chat
            self._watcher = asyncio.ensure_future(self._watch(chat, self._died))
        except BaseException:
            await chat_browser.stop(chat)
            raise

    async def _load_context_extensions(self, chat: ChatBrowser) -> None:
        """Load the extensions of `context_extensions` so they act in new contexts. A
        failure is logged, and the contexts then read without them."""
        if not self.context_extensions:
            return
        from nodriver import cdp

        loaded = 0
        for path in chat_browser.extension_paths():
            if os.path.basename(path) not in self.context_extensions:
                continue
            try:
                await asyncio.wait_for(chat.browser.send(
                    cdp.extensions.load_unpacked(path, enable_in_incognito=True)), TAB_ANSWER_S)
                loaded += 1
            except Exception as exc:  # noqa: BLE001 - a browser without the CDP domain
                log.warning("special browser %s: %s does not act in new contexts: %s",
                            self.name, path, exc)
        self.context_extensions_loaded = loaded

    async def _watch(self, chat: ChatBrowser, died: asyncio.Event) -> None:
        """Wait for the Chromium process to end, then tell its leases and clean up."""
        proc = chat.chromium
        if proc is None:
            return
        await proc.wait()
        died.set()
        if self._chat is chat:
            self._chat = None
            self.deaths += 1
            log.warning("special browser %s: chromium ended (code %s); the next lease "
                        "starts a new one", self.name, proc.returncode)
        # Ends the other processes of the group and removes the profile folder.
        await chat_browser.stop(chat)

    # ------------------------------------------------------------------ the slots

    @contextlib.asynccontextmanager
    async def lease(self, deadline: float):
        """Hold one slot and one new tab until the block ends. The tab is then closed.

        Raises `SlotWaitTimeout` when no slot is free by `deadline`, which is a
        `time.monotonic()` value. The start of the browser also counts against the
        deadline, and raises `asyncio.TimeoutError` at it.
        """
        asked = time.monotonic()
        if self._slots.locked() and self.waiting >= self.max_waiting:
            self.wait_timeouts += 1
            raise SlotWaitTimeout("The browser queue is full.")
        self.waiting += 1
        self.peak_waiting = max(self.peak_waiting, self.waiting)
        try:
            await asyncio.wait_for(self._slots.acquire(), max(0.0, deadline - asked))
        except asyncio.TimeoutError:
            self.wait_timeouts += 1
            raise SlotWaitTimeout from None
        finally:
            self.waiting -= 1
        waited = time.monotonic() - asked
        self.leases += 1
        self.wait_total_s += waited
        self.wait_last_s = waited
        self.wait_max_s = max(self.wait_max_s, waited)
        self.in_use += 1
        self.peak_in_use = max(self.peak_in_use, self.in_use)
        try:
            chat, died = await self._browser(deadline)
            async with self._tab(chat, died) as (tab, target_id):
                yield Lease(tab=tab, target_id=target_id, died=died, cdp_port=chat.cdp_port,
                            browser=chat.browser, slot_wait_s=waited,
                            tab_open_s=time.monotonic() - asked - waited)
        finally:
            self.in_use -= 1
            self._slots.release()

    @contextlib.asynccontextmanager
    async def _tab(self, chat: ChatBrowser, died: asyncio.Event):
        """A new tab in a window of its own, closed when the block ends.

        A tab behind another tab of its window is hidden. A hidden page slows its timers
        and its rendering. Raises `TabNotAnswering` when the watchdog check fails. See the
        module text.
        """
        from nodriver import Tab, cdp

        browser = chat.browser
        if browser is None:
            raise RuntimeError("the browser is not running")
        self._creating += 1
        create = asyncio.ensure_future(
            browser.send(cdp.target.create_target("about:blank", new_window=True))
        )
        try:
            target_id = await asyncio.wait_for(asyncio.shield(create), TAB_ANSWER_S)
        except (asyncio.CancelledError, asyncio.TimeoutError) as exc:
            # The target can still be made after the cancel. `_close_late` closes it then.
            create.add_done_callback(lambda done: _close_late(browser, done))
            if isinstance(exc, asyncio.TimeoutError):
                self._not_answering(chat, died)
                raise TabNotAnswering(
                    f"no new tab of the {self.name} browser within {TAB_ANSWER_S:g} s"
                ) from None
            raise
        else:
            self._leased.add(str(target_id))
        finally:
            self._creating -= 1
        tab = Tab(target=target_id, parent=browser)
        try:
            await self._check(chat, died, tab)
            yield tab, str(target_id)
        finally:
            await asyncio.shield(_release(browser, tab, target_id, self._leased))

    @contextlib.asynccontextmanager
    async def context_tab(self, lease: Lease, proxy_server: str, bypass: str):
        """A tab in a new browser context of the Chromium of `lease`, for the same slot.

        The context sends its requests to `proxy_server`, except the hosts of `bypass` (a
        Chromium bypass list). It shares no cookies or connections with the default context
        or another context. The PAC script of the launch does not act in it. The block end
        closes the tab and disposes the context, within `CLOSE_TIMEOUT_S`. Raises
        `TabNotAnswering` when the context or the tab is not made within `TAB_ANSWER_S`.
        """
        from nodriver import Tab, cdp

        browser = lease.browser
        if browser is None:
            raise RuntimeError("the browser is not running")
        self._creating += 1
        made: dict[str, object] = {}

        async def create():
            made["context"] = await browser.send(cdp.target.create_browser_context(
                dispose_on_detach=True, proxy_server=proxy_server, proxy_bypass_list=bypass))
            made["target"] = await browser.send(cdp.target.create_target(
                "about:blank", browser_context_id=made["context"], new_window=True))

        creating = asyncio.ensure_future(create())
        try:
            await asyncio.wait_for(asyncio.shield(creating), TAB_ANSWER_S)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception) as exc:
            # The creation can still finish after the cancel. The callback then removes it.
            creating.add_done_callback(lambda _done: asyncio.ensure_future(
                _dispose(browser, None, made.get("target"), made.get("context"), None)))
            if isinstance(exc, asyncio.TimeoutError):
                raise TabNotAnswering(
                    f"no new context of the {self.name} browser within {TAB_ANSWER_S:g} s"
                ) from None
            raise
        else:
            self._leased.add(str(made["target"]))
            self.contexts += 1
        finally:
            self._creating -= 1
        tab = Tab(target=made["target"], parent=browser)
        try:
            yield tab
        finally:
            await asyncio.shield(_dispose(browser, tab, made["target"], made["context"],
                                          self._leased))

    async def _check(self, chat: ChatBrowser, died: asyncio.Event, tab) -> None:
        """Run `PROBE_EXPRESSION` in the new `tab` within `TAB_ANSWER_S`. Raises
        `TabNotAnswering` when it does not answer."""
        from nodriver import cdp

        try:
            await asyncio.wait_for(tab.send(cdp.runtime.evaluate(PROBE_EXPRESSION)),
                                   TAB_ANSWER_S)
        except Exception as exc:  # noqa: BLE001 - a timeout or a closed connection
            self._not_answering(chat, died)
            reason = (f"within {TAB_ANSWER_S:g} s" if isinstance(exc, asyncio.TimeoutError)
                      else f"({exc})")
            raise TabNotAnswering(
                f"a new tab of the {self.name} browser did not run a script {reason}"
            ) from None
        if self._chat is chat:
            self._tabs_not_answering = 0

    def _not_answering(self, chat: ChatBrowser, died: asyncio.Event) -> None:
        """Count a new tab that did not answer, and restart `chat` after `TAB_FAILURES`."""
        self.tabs_not_answering += 1
        if self._chat is not chat:
            return  # The watchdog or the watcher replaced this Chromium already.
        self._tabs_not_answering += 1
        if self._tabs_not_answering < TAB_FAILURES:
            return
        self._tabs_not_answering = 0
        self.watchdog_restarts += 1
        log.warning("special browser %s: %d new tabs in a row did not answer within %gs; "
                    "restarting its chromium", self.name, TAB_FAILURES, TAB_ANSWER_S)
        self._chat = None
        if self._watcher is not None:
            self._watcher.cancel()
        # The leases of the old Chromium end now, with the error of a stopped browser.
        died.set()
        stopping = asyncio.ensure_future(chat_browser.stop(chat))
        self._stopping.add(stopping)
        stopping.add_done_callback(self._stopping.discard)

    async def sweep_tabs(self) -> int:
        """Close the page tabs that no lease holds. Returns how many went. Never raises."""
        chat = self._chat
        if chat is None or not chat_browser.chromium_alive(chat):
            return 0
        from nodriver import cdp

        try:
            targets = await chat.browser.send(cdp.target.get_targets())
        except Exception as exc:  # noqa: BLE001
            log.debug("special browser %s: could not list targets: %s", self.name, exc)
            return 0
        closed = 0
        for info in targets:
            target_id = str(info.target_id)
            if (info.type_ != "page" or target_id in self._leased
                    or target_id in self._initial or self._creating):
                continue
            try:
                await asyncio.wait_for(
                    chat.browser.send(cdp.target.close_target(info.target_id)),
                    CLOSE_TIMEOUT_S,
                )
                closed += 1
            except Exception as exc:  # noqa: BLE001 - the tab can be gone already
                log.debug("special browser %s: could not close %s: %s",
                          self.name, target_id, exc)
        if closed:
            self.tabs_swept += closed
            log.info("special browser %s: closed %d idle tabs", self.name, closed)
        return closed

    async def shutdown(self) -> None:
        if self._starting is not None and not self._starting.done():
            self._starting.cancel()
            await asyncio.gather(self._starting, return_exceptions=True)
        self._died.set()
        chat, self._chat = self._chat, None
        if self._watcher is not None:
            self._watcher.cancel()
            await asyncio.gather(self._watcher, return_exceptions=True)
        if chat is not None:
            await chat_browser.stop(chat)
        await self._stopped()

    async def _stopped(self) -> None:
        """Wait for the stops of the replaced Chromium processes."""
        if self._stopping:
            await asyncio.gather(*list(self._stopping), return_exceptions=True)

    def health(self) -> dict:
        return {
            "slots": self.slots,
            "in_use": self.in_use,
            "waiting": self.waiting,
            "max_waiting": self.max_waiting,
            "peak_in_use": self.peak_in_use,
            "peak_waiting": self.peak_waiting,
            "leases": self.leases,
            "wait_mean_s": round(self.wait_total_s / self.leases, 3) if self.leases else 0.0,
            "wait_max_s": round(self.wait_max_s, 3),
            "wait_last_s": round(self.wait_last_s, 3),
            "wait_timeouts": self.wait_timeouts,
            "chromium_alive": self.alive(),
            "starts": self.starts,
            "deaths": self.deaths,
            "spawn_failures": self.spawn_failures,
            "tabs_swept": self.tabs_swept,
            "tabs_not_answering": self.tabs_not_answering,
            "watchdog_restarts": self.watchdog_restarts,
            "contexts": self.contexts,
            "context_extensions_loaded": self.context_extensions_loaded,
        }


async def _page_targets(chat: ChatBrowser) -> set[str]:
    """The ids of the page targets of `chat`. Empty when they cannot be listed."""
    from nodriver import cdp

    try:
        targets = await chat.browser.send(cdp.target.get_targets())
    except Exception as exc:  # noqa: BLE001
        log.debug("could not list the targets of %s: %s", chat.session_id, exc)
        return set()
    return {str(t.target_id) for t in targets if t.type_ == "page"}


def _close_late(browser, done: asyncio.Future) -> None:
    """Close the target of a cancelled `_tab` when its creation finishes."""
    if done.cancelled() or done.exception() is not None:
        return
    asyncio.ensure_future(_release(browser, None, done.result(), None))


async def _release(browser, tab, target_id, leased: set[str] | None) -> None:
    """Close a tab and its CDP connection within `CLOSE_TIMEOUT_S`. Never raises. A tab
    that did not close is left to `sweep_tabs`."""
    try:
        await asyncio.wait_for(_close(browser, tab, target_id), CLOSE_TIMEOUT_S)
    except asyncio.TimeoutError:
        log.warning("tab %s did not close within %gs", target_id, CLOSE_TIMEOUT_S)
    finally:
        if leased is not None:
            leased.discard(str(target_id))


async def _dispose(browser, tab, target_id, context_id, leased: set[str] | None) -> None:
    """Close a tab of `context_tab` and dispose its context within `CLOSE_TIMEOUT_S`.
    Never raises."""
    from nodriver import cdp

    try:
        if target_id is not None:
            await _release(browser, tab, target_id, leased)
        if context_id is not None:
            await asyncio.wait_for(
                browser.send(cdp.target.dispose_browser_context(context_id)), CLOSE_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - a timeout, or a browser that is gone
        log.warning("context %s was not disposed: %s", context_id, exc)


async def _close(browser, tab, target_id) -> None:
    from nodriver import cdp

    try:
        await browser.send(cdp.target.close_target(target_id))
    except Exception as exc:  # noqa: BLE001 - the browser can be gone
        log.debug("could not close tab %s: %s", target_id, exc)
    if tab is None:
        return
    try:
        await tab.aclose()
    except Exception as exc:  # noqa: BLE001
        log.debug("could not close the connection of tab %s: %s", target_id, exc)
