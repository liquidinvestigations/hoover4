"""Session router: one :class:`ChatBrowser` per chat, created lazily, reaped on idle.

The lifetime rules, and why each number is what it is:

* ``BROWSER_MAX_CONTEXTS`` (8), a whole Chromium per chat costs a few hundred MB, so this
  is a memory ceiling, not a politeness limit. Past it the least recently used chat is
  evicted: both processes die and the profile directory goes. The evicted chat's next call
  transparently starts a fresh browser. Its cookies and tabs are gone, which is accepted.
* ``BROWSER_IDLE_SECONDS`` (900), a conversation the user has walked away from should not
  hold a browser. Fifteen minutes is long enough to survive reading an answer.
* ``BROWSER_MAX_TABS_PER_CHAT`` (6), a model that opens a tab per search result would
  otherwise exhaust the container through a single chat.

**The warm template session** is the part that is commonly left out and expensive to
miss. `list_tools` runs during graph construction, for every chat, including ones that
will never browse. Answering it from a template browser started at boot means tool
discovery costs nothing; answering it by spawning the caller's browser would start a
Chromium for every conversation on the site.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import OrderedDict

from browser_use_server import chat_browser
from browser_use_server.chat_browser import BrowserSpawnFailed, ChatBrowser

log = logging.getLogger(__name__)

MAX_CONTEXTS = int(os.getenv("BROWSER_MAX_CONTEXTS", "8"))
IDLE_SECONDS = float(os.getenv("BROWSER_IDLE_SECONDS", "900"))
REAP_INTERVAL_SECONDS = float(os.getenv("BROWSER_REAP_INTERVAL", "60"))
MAX_TABS_PER_CHAT = int(os.getenv("BROWSER_MAX_TABS_PER_CHAT", "6"))

#: Session id used by a caller that supplies no header. Pre-existing behaviour, kept so
#: `curl` and the host-side `.mcp.json` entry work, at the cost of no isolation between
#: such callers, which is what it always was.
ANONYMOUS = "_anonymous"

#: The session the template browser is filed under. Never handed to a caller: its whole
#: job is to answer `list_tools` without spawning anything.
TEMPLATE_SESSION = "_template"


class Router:
    def __init__(self) -> None:
        self._chats: "OrderedDict[str, ChatBrowser]" = OrderedDict()
        # Guards the map, not the browsers. Per-chat serialisation is each ChatBrowser's
        # own lock; a global lock here would make eight chats queue behind each other,
        # defeating the isolation a browser per chat exists to give.
        #
        # **Never hold this across a spawn, a stop or a sidecar restart.** Holding it
        # across `chat_browser.start()`, which is a cold Chromium launch plus a Node
        # sidecar (45 to 90 seconds) makes one chat's first browse block every other
        # chat's map lookup for that whole time. The cap says eight contexts; the lock
        # made it behave like one.
        self._lock = asyncio.Lock()
        # In-flight spawns, by chat key. This is what lets the lock be released during a
        # spawn without two callers racing to start two browsers for the same chat.
        self._spawning: dict[str, "asyncio.Future[ChatBrowser]"] = {}
        self._template: ChatBrowser | None = None
        self._reaper: asyncio.Task | None = None
        self.spawn_failures = 0
        self.started_at = time.monotonic()

    # ------------------------------------------------------------------ lifecycle

    async def ensure_reaper(self) -> None:
        """Start the idle reaper. Called on first use rather than at import: FastMCP owns
        the event loop, so there is no loop to attach a task to until a request arrives."""
        if self._reaper is None or self._reaper.done():
            self._reaper = asyncio.create_task(self._reap_forever())
            log.info("browser reaper started (idle %.0fs, cap %d)", IDLE_SECONDS, MAX_CONTEXTS)

    async def template(self) -> ChatBrowser:
        """The warm session `list_tools` is answered from. Started on first ask.

        Serialised through the same spawn-future machinery as :meth:`get`, so a cold
        template launch does not hold the map lock either: `list_tools` runs during graph
        construction for every chat on the site, and blocking all of them behind the first
        one's Chromium boot is the worst possible place to do it.
        """
        while True:
            template = self._template
            if template is not None and chat_browser.sidecar_alive(template):
                return template
            # `None` means we waited on someone else's spawn; re-read `_template`, which
            # their `_install_template` has now set.
            spawned = await self._spawn_once(TEMPLATE_SESSION, self._install_template)
            if spawned is not None:
                return spawned

    async def _install_template(self, chat: ChatBrowser) -> None:
        async with self._lock:
            stale, self._template = self._template, chat
        if stale is not None:
            await chat_browser.stop(stale)

    async def get(self, session_id: str | None) -> ChatBrowser:
        """This chat's browser, starting it if needed and evicting to stay under the cap.

        The map lock is held only for map operations, never across a spawn, an eviction
        stop, or a sidecar restart. Callers racing for the *same* chat still share one
        spawn (see `_spawning`); callers for different chats never wait on each other
        at all, which is what the eight-context cap is supposed to mean.
        """
        key = (session_id or "").strip() or ANONYMOUS

        while True:
            async with self._lock:
                chat = self._chats.get(key)
                if chat is not None:
                    self._chats.move_to_end(key)
                    chat.touch()
                    break
            spawned = await self._spawn_once(key, self._install_chat)
            if spawned is not None:
                chat = spawned
                break
            # The spawn we waited on was installed and then reaped before we looked. Rare,
            # and a re-loop is the whole handling: the next pass either finds a browser or
            # starts one.

        if not chat_browser.sidecar_alive(chat):
            # The sidecar died between calls. Restarting it here means the tool call the
            # user is waiting on succeeds rather than failing once to teach us the process
            # was gone. Under the chat's OWN lock, `server.py` takes it after this
            # returns, so there is no nesting, and two calls for one chat must not both
            # restart the sidecar.
            async with chat.lock:
                if not chat_browser.sidecar_alive(chat):
                    await chat_browser.restart_sidecar(chat)
        return chat

    async def _install_chat(self, chat: ChatBrowser) -> None:
        chat.touch()
        async with self._lock:
            self._chats[chat.session_id] = chat

    async def _spawn_once(self, key: str, install) -> ChatBrowser | None:
        """Start the browser for `key`, or wait for whoever already is.

        Returns the browser, or `None` when this caller waited on someone else's spawn and
        should re-check the map. `install` runs after a successful start and is what
        publishes the browser; it takes the map lock itself.
        """
        async with self._lock:
            pending = self._spawning.get(key)
            if pending is not None:
                owner = False
            else:
                pending = asyncio.get_running_loop().create_future()
                # An exception nobody awaits is an "exception was never retrieved"
                # warning at GC time; retrieving it in a callback keeps the log accurate.
                pending.add_done_callback(lambda f: f.cancelled() or f.exception())
                self._spawning[key] = pending
                owner = True
                doomed = self._take_over_limit_locked(making_room_for=1)

        if not owner:
            # `shield`: awaiting a future propagates the waiter's cancellation *into* it,
            # which would abort the owner's spawn for everyone.
            await asyncio.shield(pending)
            return None

        try:
            for victim in doomed:
                await chat_browser.stop(victim)
            chat = await chat_browser.start(key)
        except BaseException as exc:
            if isinstance(exc, BrowserSpawnFailed):
                self.spawn_failures += 1
            async with self._lock:
                self._spawning.pop(key, None)
            if not pending.done():
                pending.set_exception(exc) if isinstance(exc, Exception) else pending.cancel()
            raise

        await install(chat)
        async with self._lock:
            self._spawning.pop(key, None)
        if not pending.done():
            pending.set_result(chat)
        return chat

    async def close(self, session_id: str) -> bool:
        """Drop one chat's browser. Idempotent, an unknown session is a `False`, not an
        error: the caller's goal ("this session must not be open") is met either way."""
        async with self._lock:
            chat = self._chats.pop(session_id, None)
        if chat is None:
            return False
        await chat_browser.stop(chat)
        return True

    async def shutdown(self) -> None:
        if self._reaper is not None:
            self._reaper.cancel()
        async with self._lock:
            chats = list(self._chats.values())
            self._chats.clear()
            template, self._template = self._template, None
        for chat in chats:
            await chat_browser.stop(chat)
        if template is not None:
            await chat_browser.stop(template)

    # ------------------------------------------------------------------- reaping

    def _take_over_limit_locked(self, making_room_for: int = 0) -> list[ChatBrowser]:
        """Remove the least recently used chats from the map and hand them back to be
        stopped. Caller holds the lock; stopping happens **outside** it, the same split
        :meth:`sweep` has always used. Killing two processes and deleting a profile
        directory is not a map operation.
        """
        doomed: list[ChatBrowser] = []
        while len(self._chats) + making_room_for > MAX_CONTEXTS:
            key, chat = self._chats.popitem(last=False)
            log.info(
                "browser cap %d reached; evicting least recently used chat %s (idle %.0fs)",
                MAX_CONTEXTS, key, chat.idle_seconds(),
            )
            doomed.append(chat)
        return doomed

    async def _reap_forever(self) -> None:
        """Dispose idle chats forever. Exceptions are logged and swallowed: a reaper that
        dies leaves browsers leaking silently, which is worse than a noisy failed sweep."""
        while True:
            await asyncio.sleep(REAP_INTERVAL_SECONDS)
            try:
                await self.sweep()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("browser sweep failed")

    async def sweep(self, idle_limit: float | None = None) -> int:
        """Dispose every chat idle past the limit. Returns how many went."""
        limit = IDLE_SECONDS if idle_limit is None else idle_limit
        async with self._lock:
            doomed = [c for c in self._chats.values() if c.idle_seconds() >= limit]
            for chat in doomed:
                self._chats.pop(chat.session_id, None)
        for chat in doomed:
            log.info(
                "chat %s idle for %.0fs; reaping its browser", chat.session_id, chat.idle_seconds()
            )
            await chat_browser.stop(chat)
        return len(doomed)

    # -------------------------------------------------------------------- reporting

    def describe(self) -> list[dict]:
        return [
            c.describe()
            for c in sorted(self._chats.values(), key=lambda c: c.last_used, reverse=True)
        ]

    def health(self) -> dict:
        template = self._template
        return {
            "live_sessions": len(self._chats),
            "max_sessions": MAX_CONTEXTS,
            "idle_seconds": IDLE_SECONDS,
            "spawn_failures": self.spawn_failures,
            "sidecar_restarts": sum(c.sidecar_restarts for c in self._chats.values()),
            "template_ready": template is not None and chat_browser.sidecar_alive(template),
            "extensions": [os.path.basename(p) for p in chat_browser.extension_paths()],
            "uptime_seconds": round(time.monotonic() - self.started_at, 1),
        }


router = Router()
