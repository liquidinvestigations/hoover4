"""One `ai_service_telemetry` row per outbound call to an AI capability.

`/admin/ai_status` shows a use% strip and a recent-traffic table built entirely from this
table. Until now only the LLM path wrote to it, so those panels described one capability
and implied five: embeddings, rerank, NER, OCR and the browser were all rendered as
"no traffic", which reads as *idle* and is indistinguishable from *broken*. A dashboard
that cannot tell those apart is worse than one that admits it has no data.

**Best-effort, and never in the way.** Every function here swallows its own failures: a
ClickHouse hiccup must not fail the search it is describing. Writes are fire-and-forget
over the HTTP interface with a short timeout, the same shape `research_agent/llm_events.py`
uses for the LLM half — the two are deliberately separate because they run in different
images, and neither may depend on the other being present.

The worker has its own copy in `main_services/processing/tasks/ai_telemetry.py`: it holds
a real ClickHouse client already and does not vendor this package. Same table, same column
meanings; keep them agreeing.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextlib import contextmanager

log = logging.getLogger(__name__)

GLOBAL_DB = os.getenv("CLICKHOUSE_DATABASE", "Hoover4_Processing")

#: Short — this runs on a request path. A telemetry write that takes longer than this has
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
    """Insert one row. Never raises, never blocks longer than `WRITE_TIMEOUT_SECONDS`."""
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
        # Free-form and short. A model id, or an error class — never a stack trace.
        "detail": (detail or "")[:200],
    }
    try:
        import httpx

        with httpx.Client(timeout=WRITE_TIMEOUT_SECONDS, auth=_auth()) as client:
            response = client.post(
                f"{base}/",
                params={
                    "database": GLOBAL_DB,
                    "query": "INSERT INTO ai_service_telemetry FORMAT JSONEachRow",
                },
                content=json.dumps(row, ensure_ascii=False).encode("utf-8"),
            )
            if response.status_code >= 300:
                log.warning(
                    "ai_service_telemetry insert failed status=%s body=%s",
                    response.status_code, response.text[:200],
                )
    except Exception as exc:  # noqa: BLE001 - telemetry is never worth a failed call
        log.debug("ai_service_telemetry insert failed: %s", exc)


def record_async(service: str, **kwargs) -> None:
    """`record` on a daemon thread, for callers on an event loop.

    The clients that call this are synchronous (`requests`) inside async servers, so the
    natural fix — `asyncio.to_thread` — is not available at the call site. A daemon thread
    per call is cheap next to the model call it is describing, and a dropped row at
    shutdown is the correct trade for never delaying an answer.
    """
    if not enabled():
        return
    threading.Thread(
        target=record, args=(service,), kwargs=kwargs, daemon=True,
        name=f"ai-telemetry-{service}",
    ).start()


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
