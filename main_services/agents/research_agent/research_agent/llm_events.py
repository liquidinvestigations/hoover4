"""Write one `llm_call_events` (+ `ai_service_telemetry`) row per LLM call.

The agent is the only place that knows which model actually answered, how long it took,
and how many reasoning tokens were billed. Failures here must never fail a chat turn —
telemetry is best-effort over ClickHouse HTTP.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)

GLOBAL_DB = os.getenv("CLICKHOUSE_DATABASE", "Hoover4_Processing")


@dataclass
class LlmCallStats:
    provider: str
    model_id: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    reply_bytes: int = 0
    latency_ms: int = 0
    ok: bool = True
    error: str = ""
    kind: str = "chat"
    tool_call_count: int = 0


def _clickhouse_url() -> str:
    return (os.getenv("CLICKHOUSE_URL") or "").rstrip("/")


def _auth() -> Optional[tuple[str, str]]:
    user = os.getenv("CLICKHOUSE_USER") or "hoover4"
    password = os.getenv("CLICKHOUSE_PASSWORD") or ""
    return (user, password)


def provider_from_base_url(base_url: Optional[str] = None) -> str:
    """Stable label for the endpoint that served the call."""
    name = (os.getenv("LLM_PROVIDER_NAME") or "").strip()
    if name:
        return name
    url = (base_url or os.getenv("LLM_BASE_URL") or "").strip()
    if not url:
        return "unknown"
    host = re.sub(r"^https?://", "", url).split("/")[0]
    if host.count(".") >= 1:
        return host.split(".")[-2]
    return host or "unknown"


def telemetry_username(username: Optional[str]) -> str:
    """Guests are recorded as the literal `guest`, never as an empty string."""
    raw = (username or "").strip()
    if not raw:
        return "guest"
    if raw.startswith("guest-") or raw == "guest":
        return "guest"
    return raw


def _extract_usage(message: Any) -> tuple[int, int, int]:
    """Pull token counts out of a LangChain AIMessage / response metadata."""
    usage = {}
    if message is None:
        return 0, 0, 0
    meta = getattr(message, "usage_metadata", None) or {}
    if isinstance(meta, dict) and meta:
        usage = meta
    else:
        resp = getattr(message, "response_metadata", None) or {}
        if isinstance(resp, dict):
            usage = resp.get("token_usage") or resp.get("usage") or {}
    prompt = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    completion = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    reasoning = 0
    details = usage.get("output_token_details") or usage.get("completion_tokens_details") or {}
    if isinstance(details, dict):
        reasoning = int(details.get("reasoning_tokens") or details.get("reasoning") or 0)
    if not reasoning:
        reasoning = int(usage.get("reasoning_tokens") or 0)
    return prompt, completion, reasoning


def _reply_bytes(message: Any) -> int:
    content = getattr(message, "content", "") or ""
    if isinstance(content, list):
        content = "".join(
            x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text"
        )
    if not isinstance(content, str):
        content = str(content)
    return len(content.encode("utf-8", errors="replace"))


def stats_from_message(
    message: Any,
    *,
    model_id: str,
    provider: str,
    latency_ms: int,
    ok: bool = True,
    error: str = "",
    kind: str = "chat",
) -> LlmCallStats:
    prompt, completion, reasoning = _extract_usage(message)
    tool_calls = getattr(message, "tool_calls", None) or []
    return LlmCallStats(
        provider=provider,
        model_id=model_id,
        prompt_tokens=prompt,
        completion_tokens=completion,
        reasoning_tokens=reasoning,
        reply_bytes=_reply_bytes(message),
        latency_ms=max(0, int(latency_ms)),
        ok=ok,
        error=(error or "")[:500],
        kind=kind,
        tool_call_count=len(tool_calls) if isinstance(tool_calls, list) else 0,
    )


def record_llm_call(
    stats: LlmCallStats,
    *,
    username: Optional[str],
    session_id: Optional[str] = None,
) -> None:
    """Best-effort insert. Never raises."""
    base = _clickhouse_url()
    if not base:
        return
    # Values go in the request BODY as JSON, never interpolated into the SQL.
    #
    # These used to be f-string quoting with a `.replace("'", "")` per field, and
    # `username` — which arrives from an HTTP header — got no quoting at all. A quote in
    # it either broke every telemetry insert for that user or appended SQL of the caller's
    # choosing to a statement running as the ClickHouse admin. `FORMAT JSONEachRow` is what
    # `agent_common/artifacts.py` already uses and it has no quoting to get wrong.
    ok = 1 if stats.ok else 0
    row = {
        "username": telemetry_username(username),
        "session_id": session_id or "",
        "kind": stats.kind or "chat",
        "provider": stats.provider or "unknown",
        "model_id": stats.model_id or "",
        "prompt_tokens": int(stats.prompt_tokens),
        "completion_tokens": int(stats.completion_tokens),
        "reasoning_tokens": int(stats.reasoning_tokens),
        "reply_bytes": int(stats.reply_bytes),
        "latency_ms": int(stats.latency_ms),
        "ok": ok,
        "error": stats.error or "",
    }
    telem_row = {
        "service": "llm",
        "provider": row["provider"],
        "username": row["username"],
        "session_id": row["session_id"],
        "latency_ms": row["latency_ms"],
        "ok": ok,
        "detail": row["model_id"],
    }
    inserts = (
        ("llm_call_events", row),
        ("ai_service_telemetry", telem_row),
    )
    try:
        with httpx.Client(timeout=2.0, auth=_auth()) as client:
            for table, payload in inserts:
                r = client.post(
                    f"{base}/",
                    params={
                        "database": GLOBAL_DB,
                        "query": f"INSERT INTO {table} FORMAT JSONEachRow",
                    },
                    content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                )
                if r.status_code >= 300:
                    log.warning(
                        "llm_events insert failed status=%s body=%s",
                        r.status_code,
                        r.text[:200],
                    )
                    return
    except Exception as exc:  # noqa: BLE001 — telemetry must not break chat
        log.warning("llm_events insert failed: %s", exc)


class CallTimer:
    """Wall-clock helper for one LLM invocation."""

    def __init__(self) -> None:
        self.started = time.monotonic()

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)


def quote_ident(value: str) -> str:
    """URL-escape a value for a query parameter.

    Not an SQL escaper and never was: inserts go through `FORMAT JSONEachRow` with the row
    in the request body, so there is no SQL string for a value to escape into.
    """
    return quote(value, safe="")
