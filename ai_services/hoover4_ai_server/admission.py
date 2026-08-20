"""Bounded admission for one GPU capability.

A ``ThreadPoolExecutor`` sized to the measured concurrency, plus a semaphore of
``concurrency + queue_depth`` acquired non-blocking. Refusal is the caller's
problem: the HTTP layer turns it into 503 + Retry-After so Temporal retries
rather than queueing without bound on the event loop.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

T = TypeVar("T")


class CapabilityGate:
    def __init__(self, concurrency: int, queue_depth: int, name: str):
        if concurrency < 1:
            raise ValueError(f"{name} concurrency must be >= 1")
        if queue_depth < 0:
            raise ValueError(f"{name} queue_depth must be >= 0")
        self.concurrency = concurrency
        self.queue_depth = queue_depth
        self.name = name
        self.pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix=name)
        self.slots = threading.Semaphore(concurrency + queue_depth)

    def try_acquire(self) -> bool:
        return self.slots.acquire(blocking=False)

    def release(self) -> None:
        self.slots.release()

    def submit(self, fn: Callable[..., T], *args, **kwargs) -> T:
        return self.pool.submit(fn, *args, **kwargs).result()
