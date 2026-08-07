"""One `ai_service_telemetry` row per outbound call to an AI capability, worker side.

The twin of `main_services/agents/agent_common/agent_common/telemetry.py`. Two copies on
purpose: they run in different images, the worker already holds a ClickHouse client and
the agents do not, and neither runtime may depend on the other being present. Same table,
same column meanings — keep them agreeing.

`/admin/ai_status` builds its use% strip and recent-traffic table from this table alone.
Until the worker wrote to it, OCR and NER — the two capabilities that do the most work in
this stack — rendered as "no traffic", which is indistinguishable from "broken".

**Never in the way.** Every failure here is swallowed: a telemetry row is not worth
failing an OCR page over, and this runs inside Temporal activities whose retries are
expensive.
"""

import logging

log = logging.getLogger(__name__)

#: Recognised `service` values, listed so the set is discoverable from one place.
SERVICES = ("llm", "embeddings", "rerank", "ner", "ocr", "browser", "catalog")


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
    """Insert one row. Never raises."""
    if not service:
        return
    try:
        from database.clickhouse import get_global_client

        with get_global_client() as client:
            client.insert(
                "ai_service_telemetry",
                [[
                    service,
                    provider or "",
                    # The pipeline has no user: its work is not on anyone's behalf, and
                    # the literal `guest` would be a lie rather than a default.
                    username or "pipeline",
                    session_id or "",
                    max(0, int(latency_ms)),
                    1 if ok else 0,
                    (detail or "")[:200],
                ]],
                column_names=["service", "provider", "username", "session_id",
                              "latency_ms", "ok", "detail"],
            )
    except Exception as exc:  # noqa: BLE001 - telemetry is never worth a failed activity
        log.debug("ai_service_telemetry insert failed: %s", exc)
