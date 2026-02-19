"""Shared parsing utilities for text chunking and error recording."""

from temporalio import activity
from typing import Dict, Any, List, Sequence
import logging
import json
from dataclasses import dataclass


log = logging.getLogger(__name__)


DEFAULT_TEXT_CHUNK_BYTES = 32 * 1024 * 1024


def _split_utf8_bytes_to_chunks(data: bytes, max_bytes: int) -> List[str]:
    chunks: List[str] = []
    for i in range(0, len(data), max_bytes):
        seg = data[i:i + max_bytes]
        if seg:
            chunks.append(seg.decode("utf-8", errors="ignore"))
    return chunks


def insert_text_chunks(
    collection_dataset: str,
    file_hash: str,
    extracted_by: str,
    text_or_bytes: Any,
    *,
    start_page_id: int = 0,
    max_bytes: int = DEFAULT_TEXT_CHUNK_BYTES,
) -> int:
    """Split text into <=max_bytes UTF-8 chunks and insert into text_content.

    Returns number of chunks inserted. Page IDs start at start_page_id.
    """
    from database.clickhouse import get_clickhouse_client
    import pyarrow as pa

    if isinstance(text_or_bytes, bytes):
        data = text_or_bytes
    else:
        data = (text_or_bytes or "").encode("utf-8", errors="ignore")
    data = data.strip()
    if len(data) < 2:
        return 0

    chunks = _split_utf8_bytes_to_chunks(data, max_bytes)
    if not chunks:
        return 0

    log.info("[P3] Inserting %d text chunks for %s", len(chunks), file_hash)

    with get_clickhouse_client() as client:
        rows_cd = [collection_dataset] * len(chunks)
        rows_hash = [file_hash] * len(chunks)
        rows_src = [extracted_by] * len(chunks)
        rows_page = list(range(start_page_id, start_page_id + len(chunks)))
        tbl_t = pa.table({
            "collection_dataset": pa.array(rows_cd, type=pa.string()),
            "file_hash": pa.array(rows_hash, type=pa.string()),
            "extracted_by": pa.array(rows_src, type=pa.string()),
            "page_id": pa.array(rows_page, type=pa.uint32()),
            "text": pa.array(chunks, type=pa.string()),
        })
        client.insert_arrow("text_content", tbl_t)
    return len(chunks)


def _safe_get(obj: Any, name: str) -> Any:
    try:
        return getattr(obj, name)
    except Exception:
        return None


def _stringify_details(details: Any) -> str:
    try:
        if details is None:
            return ""
        if isinstance(details, (list, tuple)):
            parts = []
            for d in details:
                try:
                    parts.append(str(d))
                except Exception:
                    parts.append("<unprintable>")
            return "; ".join(parts)
        return str(details)
    except Exception:
        return ""


def format_temporal_exception_chain(err: BaseException) -> str:
    """Return a verbose, multi-line description of a Temporal exception chain.

    Includes common attributes: message, details, type, category, retry_state, ids, etc.,
    and walks the .cause chain recursively.
    """
    import traceback as _tb

    lines: List[str] = []
    seen: set = set()
    level = 0
    cur: BaseException | None = err
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        prefix = f"\r\n [level {level}]\r\n"
        cls_name = type(cur).__name__
        message = _safe_get(cur, "message") or str(cur)
        type_attr = _safe_get(cur, "type")
        category = _safe_get(cur, "category")
        retry_state = _safe_get(cur, "retry_state")
        details = _stringify_details(_safe_get(cur, "details"))

        # Activity-specific
        activity_type = _safe_get(cur, "activity_type")
        activity_id = _safe_get(cur, "activity_id")
        identity = _safe_get(cur, "identity")
        scheduled_event_id = _safe_get(cur, "scheduled_event_id")
        started_event_id = _safe_get(cur, "started_event_id")

        # Child-workflow-specific
        workflow_id = _safe_get(cur, "workflow_id")
        workflow_type = _safe_get(cur, "workflow_type")
        run_id = _safe_get(cur, "run_id")
        namespace = _safe_get(cur, "namespace")

        parts = [
            f"{prefix} {cls_name}",
            f"message={message}",
        ]
        if type_attr:
            parts.append(f"type={type_attr}")
        if category:
            parts.append(f"category={category}")
        if retry_state:
            parts.append(f"retry_state={retry_state}")
        if details:
            parts.append(f"details={details}")
        if activity_type or activity_id or identity:
            parts.append(f"activity_type={activity_type} activity_id={activity_id} identity={identity}")
        if scheduled_event_id is not None or started_event_id is not None:
            parts.append(f"scheduled_event_id={scheduled_event_id} started_event_id={started_event_id}")
        if workflow_id or workflow_type or run_id or namespace:
            parts.append(f"workflow_id={workflow_id} \n workflow_type={workflow_type} \n run_id={run_id} \n namespace={namespace}")

        lines.append("\n".join(parts))

        # Best-effort traceback for local exceptions
        try:
            if cur.__traceback__ is not None:
                lines.append("\n traceback:")
                lines.extend(_tb.format_exception(type(cur), cur, cur.__traceback__))
        except Exception:
            pass

        cur = _safe_get(cur, "cause")
        level += 1

    return "\n".join(lines)


async def record_errors_from_results(
    results: Sequence[Any],
    *,
    task_ids: Sequence[str],
    starts: Sequence[Any],
    collection_dataset: str,
    item_hashes: Sequence[str],
    default_task_name: str = "unknown_task",
    start_to_close_timeout_seconds: int = 120,
) -> int:
    """Build error rows from gather() results and insert into processing_errors.

    Returns the number of rows inserted.
    Must be called from within a workflow context.
    """
    from datetime import timedelta as _td
    from temporalio.common import RetryPolicy as _RetryPolicy
    from temporalio import workflow as _wf

    now_ts = _wf.now()
    error_rows: List[Dict[str, Any]] = []
    for idx, res in enumerate(results):
        if isinstance(res, Exception):
            started_at = starts[idx] if idx < len(starts) else now_ts
            dur_ms = int((now_ts - started_at).total_seconds() * 1000)
            if dur_ms < 0:
                dur_ms = 0
            err_str = format_temporal_exception_chain(res)
            task_name = task_ids[idx] if idx < len(task_ids) else default_task_name
            item_hash = item_hashes[idx] if idx < len(item_hashes) else ""
            error_rows.append({
                "collection_dataset": collection_dataset,
                "hash": item_hash,
                "task_name": task_name,
                "run_time_ms": dur_ms,
                "error_logs": err_str,
            })

    if not error_rows:
        return 0

    log.info("[P3] Recording %d errors for %s", len(error_rows), collection_dataset)

    with _wf.unsafe.imports_passed_through():
        from tasks.P2_execute_plan.activities import record_processing_errors as _record_processing_errors
        from tasks.P2_execute_plan.activities import RecordProcessingErrorsParams as _RecordProcessingErrorsParams

    await _wf.execute_activity(
        _record_processing_errors,
        _RecordProcessingErrorsParams(errors=error_rows),
        start_to_close_timeout=_td(seconds=start_to_close_timeout_seconds),
        retry_policy=_RetryPolicy(maximum_attempts=3),
    )

    return len(error_rows)
