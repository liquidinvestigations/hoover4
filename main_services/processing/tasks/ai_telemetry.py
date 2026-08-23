"""One `ai_service_telemetry` row per outbound call to an AI capability, worker side.

The twin of `main_services/agents/agent_common/agent_common/telemetry.py`. Two copies on
purpose: they run in different images, the worker already holds a ClickHouse client and
the agents do not, and neither runtime may depend on the other being present. Same table,
same column meanings. Keep them agreeing.

`/admin/ai_status` builds its use% strip and recent-traffic table from this table alone.
Until the worker wrote to it, OCR and NER (the two capabilities that do the most work in
this stack) rendered as "no traffic", which is indistinguishable from "broken".

Rows go through the same in-process buffer as `processing_task_runs` (`task_timing.py`):
a synchronous one-row insert on the activity path would add a ClickHouse round trip to
every OCR/NER call. The function signature is unchanged and still never raises.

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
    """Buffer one row onto the worker's task-timing daemon. Never raises."""
    if not service:
        return
    try:
        from tasks.task_timing import record_ai_service

        record_ai_service([
            service,
            provider or "",
            # The pipeline has no user: its work is not on anyone's behalf, and
            # the literal `guest` would be a lie rather than a default.
            username or "pipeline",
            session_id or "",
            max(0, int(latency_ms)),
            1 if ok else 0,
            (detail or "")[:200],
        ])
    except Exception as exc:  # noqa: BLE001 - telemetry is never worth a failed activity
        log.debug("ai_service_telemetry insert failed: %s", exc)
