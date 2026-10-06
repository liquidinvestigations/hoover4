"""Shared parsing utilities for text chunking and error recording."""

from temporalio import activity
from typing import Dict, Any, List, Sequence
import logging
import json
import hashlib
import time
from dataclasses import dataclass
from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT
from tasks.payload_guard import MAX_PAYLOAD_BYTES, payload_size


log = logging.getLogger(__name__)


#: Segment size for text that has no pages of its own.
#:
#: This was 32 MB, which made ``page_id`` an ordinal over a blob nothing else could
#: address: the PDF viewer's page jump, the OCR unit and the chunk offsets all mean
#: "page", and one 32 MB segment answered none of them. At 256 KB a segment is a
#: plausible unit of retrieval, and for genuinely paged formats the page number is used
#: directly instead (see :func:`insert_text_pages`).
DEFAULT_TEXT_SEGMENT_BYTES = 256 * 1024
DELETE_PAGE_BATCH = 1000


# The largest encoded input of one record activity, as the payload guard measures it.
# Half the guard's limit leaves room for the other arguments of the workflow task.
ERROR_PAYLOAD_BUDGET_BYTES = MAX_PAYLOAD_BYTES // 2
ERROR_PAYLOAD_TRUNCATION_MARKER = "\n[error log truncated for the Temporal payload limit]"


def direct_error_fields(params: Any, task_name: str, item_hash: str) -> Dict[str, Any]:
    """Identify one source activity attempt across its recorder writes."""
    info = activity.info()
    source = (info.workflow_run_id, info.activity_id, info.attempt, task_name, item_hash)
    cached = getattr(params, "_direct_error_source", None)
    if cached is not None and cached[0] == source:
        return cached[1]
    fields = {
        "error_identity": hashlib.sha256(
            json.dumps(source, separators=(",", ":")).encode()
        ).hexdigest(),
        "attempt": info.attempt,
        "workflow_run_id": info.workflow_run_id,
    }
    params._direct_error_source = (source, fields)
    return fields


def _split_utf8_bytes_to_chunks(data: bytes, max_bytes: int) -> List[str]:
    chunks: List[str] = []
    for i in range(0, len(data), max_bytes):
        seg = data[i:i + max_bytes]
        if seg:
            chunks.append(seg.decode("utf-8", errors="ignore"))
    return chunks


def split_text_segments(text_or_bytes: Any,
                        max_bytes: int = DEFAULT_TEXT_SEGMENT_BYTES,
                        min_chars: int = 2) -> List[str]:
    """Split a blob of text into storage segments, without inserting anything.

    For callers that assemble pages from several sources (an email with several
    text parts) and must number them in one continuous sequence.
    """
    if isinstance(text_or_bytes, bytes):
        data = text_or_bytes
    else:
        data = (text_or_bytes or "").encode("utf-8", errors="ignore")
    data = data.strip()
    if len(data) < min_chars:
        return []
    return _split_utf8_bytes_to_chunks(data, max_bytes)


def _existing_page_ids(client: Any, collection_dataset: str, file_hash: str,
                       extracted_by: str) -> tuple[set[int], int]:
    """Read this source's current page identities before a successful replacement."""
    rows = client.query(
        "SELECT page_id, max(version) FROM text_content "
        "WHERE collection_dataset = {cd:String} AND file_hash = {fh:String} "
        "AND extracted_by = {eb:String} GROUP BY page_id",
        parameters={"cd": collection_dataset, "fh": file_hash, "eb": extracted_by},
    ).result_rows
    return {int(row[0]) for row in rows}, max((int(row[1]) for row in rows), default=0)


def _delete_obsolete_pages(client: Any, collection_dataset: str, file_hash: str,
                           extracted_by: str, page_ids: set[int]) -> None:
    """Wait for deletion of pages absent from a successful extraction."""
    if not page_ids:
        return
    ids = sorted(page_ids)
    for start in range(0, len(ids), DELETE_PAGE_BATCH):
        client.command(
            "DELETE FROM text_content "
            "WHERE collection_dataset = {cd:String} AND file_hash = {fh:String} "
            "AND extracted_by = {eb:String} AND page_id IN {ids:Array(UInt32)} "
            "SETTINGS mutations_sync = 2",
            parameters={"cd": collection_dataset, "fh": file_hash, "eb": extracted_by,
                        "ids": ids[start:start + DELETE_PAGE_BATCH]},
        )


def insert_text_pages(
    collectionname: str,
    collection_dataset: str,
    file_hash: str,
    extracted_by: str,
    pages: Sequence[tuple],
    *,
    min_chars: int = 2,
) -> int:
    """Insert ``(page_id, text)`` pairs into ``text_content`` as one batch.

    This is the paged path: the caller already knows the real page numbers, which for a
    paged format is a **1-based page number** and never 0 -- the document viewer's page
    jump and `search_document_pdf.rs` both read `page_id` as a page.

    Empty pages are absent from the new source. A successful call removes prior rows
    for their page numbers, including blank pages between retained pages.

    **Call this once per (file, extracted_by), with every page.** It replaces the
    source's prior page identities, so a second call would remove the first call's
    pages. Assemble the full page list first.
    :func:`split_text_segments` is there for callers that build one from several sources.

    ``text_bytes`` is ``len(body.encode("utf-8"))`` of the stored text, written here so
    readers that need size (ETA sampling) never scan the body.

    Each call assigns one version from the current clock or above the previous source version.
    The async insert waits for storage before obsolete pages are removed.
    """
    return insert_text_sources(collectionname, collection_dataset, file_hash,
                               {extracted_by: pages}, min_chars=min_chars)


def insert_text_sources(collectionname: str, collection_dataset: str, file_hash: str,
                        sources: dict[str, Sequence[tuple]], *, min_chars: int = 2) -> int:
    """Replace a file's text sources with one prior-page read and one waited insert."""
    import pyarrow as pa
    from database.clickhouse import get_collection_client, insert_arrow_durable

    rows = []
    for source, pages in sources.items():
        for page_id, text in pages:
            page_id = int(page_id)
            if page_id < 1:
                raise ValueError(f"page_id must be 1-based and never 0, got {page_id} for {file_hash}")
            body = (text or "").strip()
            if len(body) >= min_chars:
                rows.append((source, page_id, body, len(body.encode("utf-8"))))

    with get_collection_client(collectionname) as client:
        previous = {source: (set(), 0) for source in sources}
        if len(sources) == 1:
            source = next(iter(sources))
            previous[source] = _existing_page_ids(client, collection_dataset, file_hash, source)
        else:
            stored = client.query(
                "SELECT extracted_by, page_id, max(version) FROM text_content "
                "WHERE collection_dataset = {cd:String} AND file_hash = {fh:String} "
                "AND extracted_by IN {sources:Array(String)} GROUP BY extracted_by, page_id",
                parameters={"cd": collection_dataset, "fh": file_hash, "sources": list(sources)},
            ).result_rows
            for source, page_id, version in stored:
                ids, maximum = previous[source]
                ids.add(int(page_id))
                previous[source] = ids, max(maximum, int(version))
        clock_version = time.time_ns()
        versions = {source: max(clock_version, maximum + 1)
                    for source, (_, maximum) in previous.items()}
        if rows:
            table = pa.table({
                "collection_dataset": pa.array([collection_dataset] * len(rows), type=pa.string()),
                "file_hash": pa.array([file_hash] * len(rows), type=pa.string()),
                "extracted_by": pa.array([r[0] for r in rows], type=pa.string()),
                "page_id": pa.array([r[1] for r in rows], type=pa.uint32()),
                "text": pa.array([r[2] for r in rows], type=pa.string()),
                "text_bytes": pa.array([r[3] for r in rows], type=pa.uint64()),
                "version": pa.array([versions[r[0]] for r in rows], type=pa.uint64()),
            })
            insert_arrow_durable(client, "text_content", table)
        for source, (ids, _) in previous.items():
            ids.difference_update(r[1] for r in rows if r[0] == source)
            _delete_obsolete_pages(client, collection_dataset, file_hash, source, ids)
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
    function is for formats that genuinely have no pages. Successful empty text clears
    the prior source pages.
    """
    if isinstance(text_or_bytes, bytes):
        data = text_or_bytes
    else:
        data = (text_or_bytes or "").encode("utf-8", errors="ignore")
    data = data.strip()
    chunks = _split_utf8_bytes_to_chunks(data, max_bytes) if len(data) >= 2 else []

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


def source_execution_id(run_id: str, call_site: str, ordinal: int) -> str:
    """Return a stable identity for one scheduled workflow source."""
    if not run_id or not call_site or not isinstance(ordinal, int) or ordinal < 0:
        raise ValueError("A source needs a run id, call site and schedule ordinal")
    return json.dumps([run_id, call_site, ordinal], ensure_ascii=False,
                      separators=(",", ":"))


def error_identity(source_execution_id: str, task_name: str,
                   collection_dataset: str, item_hash: str) -> str:
    """Return the stable identity of one document failure row."""
    source = [source_execution_id, task_name, collection_dataset, item_hash]
    return hashlib.sha256(json.dumps(
        source, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


async def record_errors_from_results(
    results: Sequence[Any],
    *,
    task_ids: Sequence[str],
    starts: Sequence[Any],
    collectionname: str,
    collection_dataset: str,
    item_hashes: Sequence[str],
    source_execution_ids: Sequence[str],
    op_id: str,
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

    if len(source_execution_ids) != len(results) or any(not value for value in source_execution_ids):
        raise ValueError("Each result needs one nonempty source execution id")

    now_ts = _wf.now()
    try:
        run_id = _wf.info().run_id or ""
    except Exception:
        run_id = ""
    use_groups = _wf.in_workflow() and _wf.patched("error-groups-activity")
    error_rows: List[Dict[str, Any]] = []
    grouped: Dict[tuple[str, str], Dict[str, Any]] = {}
    for idx, res in enumerate(results):
        if isinstance(res, Exception):
            started_at = starts[idx] if idx < len(starts) else now_ts
            dur_ms = int((now_ts - started_at).total_seconds() * 1000)
            if dur_ms < 0:
                dur_ms = 0
            task_name = task_ids[idx] if idx < len(task_ids) else default_task_name
            item_hash = item_hashes[idx] if idx < len(item_hashes) else ""
            source_id = source_execution_ids[idx]
            if use_groups:
                key = (source_id, task_name)
                if key not in grouped:
                    grouped[key] = {
                        "task_name": task_name,
                        "source_execution_id": source_id,
                        "started_at": started_at,
                        "error_logs": format_temporal_exception_chain(res),
                        "item_hashes": [],
                    }
                group = grouped[key]
                group["item_hashes"].append(item_hash)
            else:
                err_str = format_temporal_exception_chain(res)
                error_rows.append({
                    "collection_dataset": collection_dataset,
                    "hash": item_hash,
                    "task_name": task_name,
                    "run_time_ms": dur_ms,
                    "error_logs": err_str,
                    "attempt": 0,
                    "workflow_run_id": run_id,
                    "op_id": op_id,
                    "error_identity": error_identity(
                        source_id, task_name, collection_dataset, item_hash),
                })

    if not error_rows and not grouped:
        return 0

    row_count = len(error_rows) if error_rows else sum(
        len(group["item_hashes"]) for group in grouped.values())
    log.info("[P3] Recording %d errors for %s", row_count, collection_dataset)

    with _wf.unsafe.imports_passed_through():
        from tasks.P2_execute_plan.activities import record_processing_errors as _record_processing_errors
        from tasks.P2_execute_plan.activities import RecordProcessingErrorsParams as _RecordProcessingErrorsParams
        from tasks.P2_execute_plan.activities import record_processing_error_groups as _record_processing_error_groups
        from tasks.P2_execute_plan.activities import ErrorGroup as _ErrorGroup
        from tasks.P2_execute_plan.activities import RecordErrorGroupsParams as _RecordErrorGroupsParams

    # Every size below is the encoded size that the payload guard measures. The JSON
    # converter writes each character outside ASCII as an escape of 6 or 12 bytes, so a
    # UTF-8 count is too small for such text. The encoded batch is the empty input, each
    # row, and one comma between two rows.
    if _wf.in_workflow():
        converter = _wf.payload_converter()
    else:
        from temporalio.converter import PayloadConverter
        converter = PayloadConverter.default

    def encoded_size(value: Any) -> int:
        return payload_size(converter.to_payloads([value])[0])

    if use_groups:
        groups = [_ErrorGroup(**group) for group in grouped.values()]
        empty_bytes = encoded_size(_RecordErrorGroupsParams(
            collectionname=collectionname, collection_dataset=collection_dataset,
            op_id=op_id, workflow_run_id=run_id, recorded_at=now_ts, groups=[]))

        def group_size(group: Any) -> int:
            return len(converter.to_payloads([group])[0].data)

        def truncate_group(group: Any) -> None:
            allowed = ERROR_PAYLOAD_BUDGET_BYTES - empty_bytes
            size = group_size(group)
            while size > allowed and group.error_logs:
                keep = (len(group.error_logs) * allowed // size
                        - len(ERROR_PAYLOAD_TRUNCATION_MARKER))
                group.error_logs = group.error_logs[:max(0, min(keep, len(group.error_logs) - 1))]
                group.error_logs += ERROR_PAYLOAD_TRUNCATION_MARKER
                size = group_size(group)

        async def record_groups(batch: List[Any]) -> None:
            await _wf.execute_activity(
                _record_processing_error_groups,
                _RecordErrorGroupsParams(
                    collectionname=collectionname, collection_dataset=collection_dataset,
                    op_id=op_id, workflow_run_id=run_id, recorded_at=now_ts, groups=batch),
                start_to_close_timeout=_td(seconds=start_to_close_timeout_seconds),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=_RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            )

        batch: List[Any] = []
        batch_bytes = empty_bytes
        for group in groups:
            truncate_group(group)
            group_bytes = group_size(group) + (1 if batch else 0)
            if batch and batch_bytes + group_bytes > ERROR_PAYLOAD_BUDGET_BYTES:
                await record_groups(batch)
                batch = []
                batch_bytes = empty_bytes
                group_bytes -= 1
            batch.append(group)
            batch_bytes += group_bytes
        if batch:
            await record_groups(batch)
        return row_count

    empty_batch_bytes = encoded_size(
        _RecordProcessingErrorsParams(collectionname=collectionname, errors=[]))

    def row_size_bytes(row: Dict[str, Any]) -> int:
        # The data of the row alone: the metadata of the payload is in the empty batch.
        return len(converter.to_payloads([row])[0].data)

    def truncate_error_logs(row: Dict[str, Any]) -> None:
        allowed = ERROR_PAYLOAD_BUDGET_BYTES - empty_batch_bytes
        error_log = str(row.get("error_logs") or "")
        size = row_size_bytes(row)
        while size > allowed and error_log:
            # Cut in proportion to the excess, then measure again. Each pass removes at
            # least one character, so the loop ends.
            keep = len(error_log) * allowed // size - len(ERROR_PAYLOAD_TRUNCATION_MARKER)
            error_log = error_log[:max(0, min(keep, len(error_log) - 1))]
            row["error_logs"] = error_log + ERROR_PAYLOAD_TRUNCATION_MARKER
            size = row_size_bytes(row)

    async def record_batch(rows: List[Dict[str, Any]]) -> None:
        await _wf.execute_activity(
            _record_processing_errors,
            _RecordProcessingErrorsParams(collectionname=collectionname, errors=rows),
            start_to_close_timeout=_td(seconds=start_to_close_timeout_seconds),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=_RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )

    batch: List[Dict[str, Any]] = []
    batch_size_bytes = empty_batch_bytes
    for error_row in error_rows:
        truncate_error_logs(error_row)
        error_row_size_bytes = row_size_bytes(error_row) + (1 if batch else 0)
        if batch and batch_size_bytes + error_row_size_bytes > ERROR_PAYLOAD_BUDGET_BYTES:
            await record_batch(batch)
            batch = []
            batch_size_bytes = empty_batch_bytes
            error_row_size_bytes -= 1
        batch.append(error_row)
        batch_size_bytes += error_row_size_bytes
    if batch:
        await record_batch(batch)

    return len(error_rows)
