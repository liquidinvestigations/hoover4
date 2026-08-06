"""Per-chat browser sessions: one isolated Chromium context per conversation.

## Why isolate at all

Before this, every chat shared one browser and therefore one cookie jar. Two problems
follow. A site that sets a consent cookie or logs someone in during one conversation
carries that state into the next user's — a cross-tenant leak through a component whose
whole job is fetching untrusted pages. And a site that rate-limits or blocks the shared
identity blocks it for everybody at once.

## Why contexts and not browsers

A separate Chromium per chat is a few hundred MB each and would put the container into
swap on the third concurrent conversation. A **browser context** is Chromium's own
isolation boundary — separate cookies, storage and cache, shared process and shared
memory — which is exactly the boundary needed here and costs almost nothing.

## Lifetime

A session is created on first use and disposed on whichever comes first:

* the chat finishes, and the website calls ``POST /sessions/{id}/close``;
* :data:`SESSION_IDLE_SECONDS` (1 h) pass with no call, and the reaper takes it;
* the server restarts, which disposes everything by definition.

Callers that supply no session id share one anonymous session. That keeps the tool
usable from `curl` and from an agent that has not been taught the header, at the cost of
no isolation — which is the pre-existing behaviour, not a new hole.

Concurrency is unchanged: one call at a time across all sessions, behind the module lock
in :mod:`.browser`. Sessions partition *state*, not throughput.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

#: Drop a session after this long with no tool call. The brief says one hour.
SESSION_IDLE_SECONDS = float(os.getenv("BROWSER_SESSION_IDLE_SECONDS", str(60 * 60)))

#: How often the reaper looks. A tenth of the idle window: fine-grained enough that
#: "an hour" is honest, cheap enough to ignore.
REAP_INTERVAL_SECONDS = float(os.getenv("BROWSER_SESSION_REAP_INTERVAL", "360"))

#: Ceiling on live contexts. Each is cheap but not free, and an agent looping on new
#: session ids must not be able to exhaust the container. At the limit the
#: least-recently-used session is dropped.
MAX_SESSIONS = int(os.getenv("BROWSER_MAX_SESSIONS", "32"))

#: Session id used when the caller supplies none.
ANONYMOUS = "_anonymous"


@dataclass
class BrowserSession:
    session_id: str
    #: Chromium's own context id, the handle used to dispose it.
    context_id: str | None = None
    last_used: float = field(default_factory=time.monotonic)
    calls: int = 0

    def touch(self) -> None:
        self.last_used = time.monotonic()
        self.calls += 1

    def idle_seconds(self) -> float:
        return time.monotonic() - self.last_used


class SessionRegistry:
    """Chat session id -> Chromium browser context.

    Not internally locked: every method is called from inside :mod:`.browser`'s module
    lock, which already serialises the whole server. Adding a second lock here would
    only create an ordering to get wrong.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, BrowserSession] = {}

    def __len__(self) -> int:
        return len(self._sessions)

    def get(self, session_id: str | None) -> BrowserSession:
        key = (session_id or ANONYMOUS).strip() or ANONYMOUS
        session = self._sessions.get(key)
        if session is None:
            session = BrowserSession(session_id=key)
            self._sessions[key] = session
            log.info("browser session %s created (%d live)", key, len(self._sessions))
        session.touch()
        return session

    def forget(self, session_id: str) -> BrowserSession | None:
        """Remove a session from the registry and hand it back for disposal."""
        return self._sessions.pop(session_id, None)

    def expired(self, now_idle_limit: float = SESSION_IDLE_SECONDS) -> list[BrowserSession]:
        return [s for s in self._sessions.values() if s.idle_seconds() >= now_idle_limit]

    def over_limit(self) -> list[BrowserSession]:
        """Sessions to evict to get back under :data:`MAX_SESSIONS`, oldest first."""
        excess = len(self._sessions) - MAX_SESSIONS
        if excess <= 0:
            return []
        by_age = sorted(self._sessions.values(), key=lambda s: s.last_used)
        return by_age[:excess]

    def describe(self) -> list[dict]:
        """Snapshot for the health endpoint."""
        return [
            {
                "session_id": s.session_id,
                "calls": s.calls,
                "idle_seconds": round(s.idle_seconds(), 1),
                "has_context": s.context_id is not None,
            }
            for s in sorted(self._sessions.values(), key=lambda s: s.last_used, reverse=True)
        ]


registry = SessionRegistry()


async def reaper(dispose, interval: float = REAP_INTERVAL_SECONDS) -> None:
    """Dispose idle sessions forever. Started as a background task by the server.

    `dispose` is injected rather than imported so this can be tested without Chromium.
    Exceptions are logged and swallowed: a reaper that dies leaves contexts leaking
    silently, which is worse than a noisy failed sweep.
    """
    while True:
        await asyncio.sleep(interval)
        try:
            await sweep(dispose)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the reaper must outlive one bad sweep
            log.exception("browser session sweep failed")


async def sweep(dispose) -> int:
    """Dispose every expired session. Returns how many went."""
    doomed = registry.expired()
    for session in doomed:
        log.info(
            "browser session %s idle for %.0fs; disposing",
            session.session_id,
            session.idle_seconds(),
        )
        registry.forget(session.session_id)
        await dispose(session)
    return len(doomed)
