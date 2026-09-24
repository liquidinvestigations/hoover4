"""Log the resident size of a worker process, with the activities it runs.

Each worker process runs ``watch_memory`` beside its workers. Every 30 s it reads the
``VmRSS`` line of ``/proc/self/status``. It logs one ``WARNING`` line when the resident
size first reaches ``THRESHOLD_BYTES``, and at each further ``STEP_BYTES``. The line holds
the worker type, the resident size and the activities in flight. It tells an operator
which activity input was in the process when its memory grew.

``ActivityMemoryInterceptor`` keeps the set of activities in flight. Each entry holds the
activity type. It also holds the file hash or the dataset when the input has one.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from typing import Any, Callable, Dict, Optional

from temporalio import activity
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    Interceptor,
)

from .task_timing import identify

log = logging.getLogger(__name__)

THRESHOLD_BYTES = 4 * 1024**3
STEP_BYTES = 1024**3
INTERVAL_SECONDS = 30

#: The activities in flight in this process, keyed by a counter value.
IN_FLIGHT: Dict[int, str] = {}
_next_key = itertools.count()


def read_rss_bytes() -> Optional[int]:
    """The ``VmRSS`` of this process in bytes, or ``None`` when the file has no value."""
    with open("/proc/self/status", encoding="ascii", errors="replace") as status:
        for line in status:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return None


def describe(in_flight: Dict[int, str]) -> str:
    """The entries of ``in_flight`` as one comma-separated text, or ``none``."""
    entries = list(in_flight.values())
    return ", ".join(entries) if entries else "none"


def check_memory(worker_type: str, in_flight: Dict[int, str], next_level: int,
                 read_rss: Callable[[], Optional[int]] = read_rss_bytes) -> int:
    """Log once when the resident size reaches ``next_level``. Returns the next level."""
    rss = read_rss()
    if rss is not None and rss >= next_level:
        log.warning("worker %s resident size %d MB, activities in flight: %s",
                    worker_type, rss // 2**20, describe(in_flight))
        next_level = (rss // STEP_BYTES + 1) * STEP_BYTES
    return next_level


async def watch_memory(worker_type: str, in_flight: Dict[int, str] = IN_FLIGHT,
                       threshold: int = THRESHOLD_BYTES,
                       read_rss: Callable[[], Optional[int]] = read_rss_bytes,
                       interval: float = INTERVAL_SECONDS) -> None:
    """Check the resident size every ``interval`` seconds until the task is cancelled."""
    next_level = threshold
    while True:
        try:
            next_level = check_memory(worker_type, in_flight, next_level, read_rss)
        except Exception:  # noqa: BLE001 - the log is never worth a stopped worker
            log.debug("worker_memory: cannot read the resident size", exc_info=True)
        await asyncio.sleep(interval)


def _entry(input: ExecuteActivityInput) -> str:
    name = activity.info().activity_type
    _collection, dataset, item_hash = identify(input.args)
    if item_hash:
        return f"{name} {item_hash}"
    if dataset:
        return f"{name} {dataset}"
    return name


class _MemoryActivityInbound(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        key = next(_next_key)
        try:
            IN_FLIGHT[key] = _entry(input)
        except Exception:  # noqa: BLE001 - the log is never worth a failed activity
            IN_FLIGHT[key] = "unknown"
        try:
            return await self.next.execute_activity(input)
        finally:
            IN_FLIGHT.pop(key, None)


class ActivityMemoryInterceptor(Interceptor):
    """Install on every ``Worker`` so that the memory log names the activities in flight."""

    def intercept_activity(
        self, next: ActivityInboundInterceptor
    ) -> ActivityInboundInterceptor:
        return _MemoryActivityInbound(next)
