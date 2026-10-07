"""The server-wide limit on `web_search` calls that run at the same time.

At most `METASEARCH_MAX_CONCURRENT` calls run (default 4). A further call waits in a
first-in, first-out queue with at most 16 waiting calls. A call that gets no slot within `METASEARCH_QUEUE_WAIT_SECONDS`
(default 60) raises :class:`Busy`, and the tool returns a busy result.

The gate counts calls in one process. `/health` reports :meth:`Gate.state`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

log = logging.getLogger(__name__)

MAX_CONCURRENT = int(os.getenv("METASEARCH_MAX_CONCURRENT", "4"))
MAX_WAITING = int(os.getenv("METASEARCH_MAX_WAITING", "16"))
QUEUE_WAIT_SECONDS = float(os.getenv("METASEARCH_QUEUE_WAIT_SECONDS", "60"))


class Busy(RuntimeError):
    """No slot became free within the queue wait."""


class Gate:
    def __init__(self, limit: int = MAX_CONCURRENT, wait_seconds: float = QUEUE_WAIT_SECONDS,
                 max_waiting: int = MAX_WAITING):
        self.limit = max(1, limit)
        self.wait_seconds = max(0.0, wait_seconds)
        self.max_waiting = max(0, max_waiting)
        self._semaphore = asyncio.Semaphore(self.limit)
        self.running = 0
        self.waiting = 0
        self.peak_running = 0
        self.peak_waiting = 0
        self.admitted = 0
        self.queued = 0
        self.refused = 0
        self.max_wait_ms = 0.0

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[float]:
        """Hold one slot for the body of the `async with`. Yields the wait in ms."""
        started = time.monotonic()
        must_wait = self._semaphore.locked()
        if must_wait:
            if self.waiting >= self.max_waiting:
                self.refused += 1
                raise Busy("The search queue is full. Try the search again later.")
            self.queued += 1
        self.waiting += 1
        self.peak_waiting = max(self.peak_waiting, self.waiting)
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self.wait_seconds)
        except asyncio.TimeoutError:
            self.refused += 1
            log.warning(
                "web_search refused: busy after %.0fs (running=%d waiting=%d)",
                self.wait_seconds, self.running, self.waiting - 1,
            )
            raise Busy(
                f"metasearch is busy: {self.limit} searches are running and this call "
                f"waited {self.wait_seconds:g} s for a free slot. Try the search again later."
            ) from None
        finally:
            self.waiting -= 1
        waited_ms = (time.monotonic() - started) * 1000.0
        self.running += 1
        self.admitted += 1
        self.peak_running = max(self.peak_running, self.running)
        self.max_wait_ms = max(self.max_wait_ms, waited_ms)
        log.info(
            "web_search admitted: waited=%.0fms running=%d waiting=%d",
            waited_ms, self.running, self.waiting,
        )
        try:
            yield waited_ms
        finally:
            self.running -= 1
            self._semaphore.release()

    def state(self) -> dict:
        return {
            "limit": self.limit,
            "queue_wait_seconds": self.wait_seconds,
            "max_waiting": self.max_waiting,
            "running": self.running,
            "waiting": self.waiting,
            "peak_running": self.peak_running,
            "peak_waiting": self.peak_waiting,
            "admitted": self.admitted,
            "queued": self.queued,
            "refused_busy": self.refused,
            "max_wait_ms": round(self.max_wait_ms, 1),
        }
