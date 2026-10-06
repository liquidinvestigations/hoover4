"""Collect AI service telemetry and write waited batches each minute."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextlib import contextmanager

log = logging.getLogger(__name__)

GLOBAL_DB = os.getenv("CLICKHOUSE_DATABASE", "Hoover4_Processing")

#: Short, because this runs on a request path. A telemetry write that takes longer than this has
#: already cost more than the row is worth.
WRITE_TIMEOUT_SECONDS = float(os.getenv("AI_TELEMETRY_TIMEOUT", "2"))

#: Recognised `service` values. Not enforced (a new capability should be able to write
#: before this list is updated), but listed so the set is discoverable from one place.
SERVICES = ("llm", "embeddings", "rerank", "ner", "ocr", "browser", "catalog")


def enabled() -> bool:
    return bool((os.getenv("CLICKHOUSE_URL") or "").strip())


def _auth():
    user = os.getenv("CLICKHOUSE_USER") or "hoover4"
    password = os.getenv("CLICKHOUSE_PASSWORD") or "hoover4"
    return (user, password)


def record(
    service: str,
    *,
    provider: str = "",
    latency_ms: float = 0.0,
    ok: bool = True,
    detail: str = "",
    username: str = "",
    session_id: str = "",
) -> None:
    """Collect one telemetry row. Never raises."""
    base = (os.getenv("CLICKHOUSE_URL") or "").rstrip("/")
    if not base:
        return
    row = {
        "service": service,
        "provider": provider or "",
        # The literal `guest`, never an empty string: an empty username is
        # indistinguishable from a column nobody filled in.
        "username": username or "guest",
        "session_id": session_id or "",
        "latency_ms": max(0, int(latency_ms)),
        "ok": 1 if ok else 0,
        # Free-form and short. A model id, or an error class, never a stack trace.
        "detail": (detail or "")[:200],
    }
    try:
        from agent_common.clickhouse_buffer import record as buffer_record

        buffer_record(base, GLOBAL_DB, _auth(), 'ai_service_telemetry', row)
    except Exception as exc:
        log.debug("ai_service_telemetry insert failed: %s", exc)


def record_async(service: str, **kwargs) -> None:
    """Collect telemetry for a caller on an event loop."""
    record(service, **kwargs)


@contextmanager
def timed(service: str, *, provider: str = "", detail: str = "", username: str = "",
          session_id: str = ""):
    """Time a call and record it either way.

    The failure path is the reason this is a context manager: a hand-written
    `record(ok=True)` after the call records only the successes, and "no rows" then means
    both "healthy and idle" and "failing every time".
    """
    started = time.monotonic()
    try:
        yield
    except BaseException as exc:
        record_async(
            service,
            provider=provider,
            latency_ms=(time.monotonic() - started) * 1000.0,
            ok=False,
            detail=f"{type(exc).__name__}: {exc}"[:200] or detail,
            username=username,
            session_id=session_id,
        )
        raise
    record_async(
        service,
        provider=provider,
        latency_ms=(time.monotonic() - started) * 1000.0,
        ok=True,
        detail=detail,
        username=username,
        session_id=session_id,
    )
