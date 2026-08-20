"""Shared parsing utilities for text chunking and error recording."""

from temporalio import activity
from typing import Dict, Any, List, Sequence
import logging
import json
from dataclasses import dataclass
from tasks.heartbeat import HEARTBEAT_TIMEOUT


log = logging.getLogger(__name__)


#: Segment size for text that has no pages of its own.
#:
#: This was 32 MB, which made ``page_id`` an ordinal over a blob nothing else could
#: address: the PDF viewer's page jump, the OCR unit and the chunk offsets all mean
#: "page", and one 32 MB segment answered none of them. At 256 KB a segment is a
#: plausible unit of retrieval, and for genuinely paged formats the page number is used
#: directly instead (see :func:`insert_text_pages`).
DEFAULT_TEXT_SEGMENT_BYTES = 256 * 1024


def _split_utf8_bytes_to_chunks(data: bytes, max_bytes: int) -> List[str]:
    chunks: List[str] = []
    for i in range(0, len(data), max_bytes):
        seg = data[i:i + max_bytes]
        if seg:
            chunks.append(seg.decode("utf-8", errors="ignore"))
    return chunks


def split_text_segments(text_or_bytes: Any,
                        max_bytes: int = DEFAULT_TEXT_SEGMENT_BYTES) -> List[str]:
    """Split a blob of text into storage segments, without inserting anything.

    For callers that assemble pages from several sources (an email with several
    text parts) and must number them in one continuous sequence.
    """
    if isinstance(text_or_bytes, bytes):
        data = text_or_bytes
    else:
        data = (text_or_bytes or "").encode("utf-8", errors="ignore")
    data = data.strip()
    if len(data) < 2:
        return []
    return _split_utf8_bytes_to_chunks(data, max_bytes)


def _trim_orphan_pages(client: Any, collection_dataset: str, file_hash: str,
                       extracted_by: str, highest_written: int) -> None:
    """Delete rows of this variant above ``highest_written``.

    ``text_content`` is a ReplacingMergeTree keyed by
    ``(collection_dataset, file_hash, extracted_by, page_id)``, so re-extracting a file
    replaces every page it rewrites. What it does *not* do is remove pages the new run
    no longer produces: a re-OCR that yields 8 pages where the previous run yielded 12
    leaves pages 9-12 behind, still readable, still indexed, and silently stale. That is
    the whole failure mode this function exists for.

    The check is a `max(page_id)` read rather than an unconditional delete because the
    normal case is a first extraction with nothing to trim, and a ClickHouse DELETE is
    an asynchronous mutation -- issuing one per file per variant across a dataset is
    thousands of mutations to remove nothing.
    """
    try:
        rows = client.query(
            "SELECT max(page_id) FROM text_content "
            "WHERE collection_dataset = {cd:String} AND file_hash = {fh:String} "
            "AND extracted_by = {eb:String}",
            parameters={"cd": collection_dataset, "fh": file_hash, "eb": extracted_by},
        ).result_rows
        previous_max = int(rows[0][0]) if rows and rows[0] and rows[0][0] is not None else 0
    except Exception:
        # A missing table or an unreadable count must not fail the extraction itself;
        # the worst case is the pre-existing orphan-page behaviour.
        log.warning("[P3] could not read previous page count for %s/%s", file_hash, extracted_by)
        return

    if previous_max <= highest_written:
        return

    log.info("[P3] trimming orphan pages %d..%d for %s/%s",
             highest_written + 1, previous_max, file_hash, extracted_by)
    client.command(
        "DELETE FROM text_content "
        "WHERE collection_dataset = {cd:String} AND file_hash = {fh:String} "
        "AND extracted_by = {eb:String} AND page_id > {hw:UInt32}",
        parameters={"cd": collection_dataset, "fh": file_hash, "eb": extracted_by,
                    "hw": highest_written},
    )


def insert_text_pages(
    collectionname: str,
    collection_dataset: str,
    file_hash: str,
    extracted_by: str,
    pages: Sequence[tuple],
) -> int:
    """Insert ``(page_id, text)`` pairs into ``text_content`` as one batch.

    This is the paged path: the caller already knows the real page numbers, which for a
    paged format is a **1-based page number** and never 0 -- the document viewer's page
    jump and `search_document_pdf.rs` both read `page_id` as a page.

    Empty pages are dropped rather than stored, but they still count towards the highest
    page number written, so a trailing run of blank pages does not look like shrinkage.

    **Call this once per (file, extracted_by), with every page.** It trims rows above the
    highest page number it writes, so calling it twice for the same variant makes the
    second call delete the first call's pages. Assemble the full page list first --
    :func:`split_text_segments` is there for callers that build one from several sources.

    ``text_bytes`` is ``len(body.encode("utf-8"))`` of the stored text, written here so
    readers that need size (ETA sampling) never scan the body.
    """
    from database.clickhouse import get_collection_client
    import pyarrow as pa

    rows: List[tuple] = []
    highest = 0
    for page_id, text in pages:
        page_id = int(page_id)
        if page_id < 1:
            raise ValueError(
                f"page_id must be 1-based and never 0, got {page_id} for {file_hash}"
            )
        highest = max(highest, page_id)
        body = (text or "").strip()
        if len(body) >= 2:
            rows.append((page_id, body, len(body.encode("utf-8"))))

    with get_collection_client(collectionname) as client:
        if rows:
            log.info("[P3] Inserting %d text pages for %s (%s)", len(rows), file_hash, extracted_by)
            tbl_t = pa.table({
                "collection_dataset": pa.array([collection_dataset] * len(rows), type=pa.string()),
                "file_hash": pa.array([file_hash] * len(rows), type=pa.string()),
                "extracted_by": pa.array([extracted_by] * len(rows), type=pa.string()),
                "page_id": pa.array([r[0] for r in rows], type=pa.uint32()),
                "text": pa.array([r[1] for r in rows], type=pa.string()),
                "text_bytes": pa.array([r[2] for r in rows], type=pa.uint64()),
            })
            client.insert_arrow("text_content", tbl_t)
        if highest:
            _trim_orphan_pages(client, collection_dataset, file_hash, extracted_by, highest)

    return len(rows)


def insert_text_chunks(
    collectionname: str,
    collection_dataset: str,
    file_hash: str,
    extracted_by: str,
    text_or_bytes: Any,
    *,
    start_page_id: int = 1,
    max_bytes: int = DEFAULT_TEXT_SEGMENT_BYTES,
) -> int:
    """Split unpaged text into <=max_bytes UTF-8 segments and insert into text_content.

    Writes to the collection database selected by ``collectionname``. Returns the number
    of segments inserted.

    ``page_id`` is a **1-based segment ordinal** here, and ``start_page_id`` defaults to
    1 accordingly: it shares a column with real page numbers, and a 0 in that column
    means "this file has a page zero" to every reader of `text_content`.

    Callers that know the real pages must use :func:`insert_text_pages` instead. This
    function is for formats that genuinely have no pages.
    """
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

    return insert_text_pages(
        collectionname, collection_dataset, file_hash, extracted_by,
        [(start_page_id + i, c) for i, c in enumerate(chunks)],
    )


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
    collectionname: str,
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
    try:
        run_id = _wf.info().run_id or ""
    except Exception:
        run_id = ""
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
                "attempt": 0,
                "workflow_run_id": run_id,
            })

    if not error_rows:
        return 0

    log.info("[P3] Recording %d errors for %s", len(error_rows), collection_dataset)

    with _wf.unsafe.imports_passed_through():
        from tasks.P2_execute_plan.activities import record_processing_errors as _record_processing_errors
        from tasks.P2_execute_plan.activities import RecordProcessingErrorsParams as _RecordProcessingErrorsParams

    await _wf.execute_activity(
        _record_processing_errors,
        _RecordProcessingErrorsParams(collectionname=collectionname, errors=error_rows),
        start_to_close_timeout=_td(seconds=start_to_close_timeout_seconds),
        heartbeat_timeout=HEARTBEAT_TIMEOUT,
        retry_policy=_RetryPolicy(maximum_attempts=3),
    )

    return len(error_rows)
