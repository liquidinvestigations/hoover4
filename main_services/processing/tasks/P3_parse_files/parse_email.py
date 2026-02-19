"""Email parsing activities and workflow for headers and attachments."""

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from typing import Dict, Any, List
from dataclasses import dataclass
import json
import os
import logging
from datetime import timedelta

log = logging.getLogger(__name__)


@dataclass
class ParseEmailHeadersParams:
    collection_dataset: str
    email_hash: str
    file_path: str


@activity.defn
def parse_email_extract_text_headers(params: ParseEmailHeadersParams) -> str:
    """Activity that parses .eml, stores headers, and extracts text parts."""
    from email import policy
    from email.parser import BytesParser
    from email.utils import parsedate_to_datetime
    from datetime import datetime, timezone
    from database.clickhouse import get_clickhouse_client
    import pyarrow as pa
    log.info("[P3] Parsing email headers for %s", params.file_path)
    with open(params.file_path, "rb") as f:
        msg = BytesParser(policy=policy.default).parse(f)

    subject = msg["subject"] or ""
    # Parse RFC 2822 Date header and convert to UTC naive datetime for ClickHouse
    date_header = msg.get("date")
    try:
        parsed_dt = parsedate_to_datetime(str(date_header)) if date_header else None
        if parsed_dt is None:
            raise ValueError("no date")
        if parsed_dt.tzinfo is not None:
            parsed_dt = parsed_dt.astimezone(timezone.utc).replace(tzinfo=None)
        date_sent_dt = parsed_dt
    except Exception:
        # Fallback to epoch if invalid/missing to satisfy non-nullable DateTime
        date_sent_dt = datetime.utcfromtimestamp(0)
    # Simple address aggregation
    addresses = []
    for hdr in ["from", "to", "cc", "bcc"]:
        v = msg.get(hdr)
        if v:
            addresses.append(f"{hdr}: {v}")
    addresses_str = "; ".join(addresses)

    # Save email container row
    with get_clickhouse_client() as client:
        tbl_e = pa.table({
            "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
            "email_hash": pa.array([params.email_hash], type=pa.string()),
            "email_type": pa.array(["eml"], type=pa.string()),
        })
        client.insert_arrow("emails", tbl_e)
        tbl_h = pa.table({
            "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
            "email_hash": pa.array([params.email_hash], type=pa.string()),
            "raw_headers_json": pa.array([json.dumps(dict(msg.items()))], type=pa.string()),
            "subject": pa.array([subject], type=pa.string()),
            "addresses": pa.array([addresses_str], type=pa.string()),
            "date_sent": pa.array([date_sent_dt], type=pa.timestamp("s")),
        })
        client.insert_arrow("email_headers", tbl_h)

    # Extract plaintext parts
    texts: List[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                try:
                    texts.append(part.get_content())
                except Exception:
                    pass
    else:
        if msg.get_content_type() == "text/plain":
            try:
                texts.append(msg.get_content())
            except Exception:
                pass

    if texts:
        from tasks.P3_parse_files.parse_common import insert_text_chunks
        page_id = 0
        total = 0
        for t in texts:
            total += insert_text_chunks(params.collection_dataset, params.email_hash, "email_parser", t or "", start_page_id=page_id)
            page_id = total

    return f"email {params.email_hash}"



@dataclass
class ExtractEmailAttachmentsParams:
    collection_dataset: str
    email_hash: str
    file_path: str
    timeout_seconds: int


@activity.defn
def extract_email_attachments_to_temp(params: ExtractEmailAttachmentsParams) -> Dict[str, Any]:
    """Extract all attachments from an .eml to a temp directory.

    Params:
      - collection_dataset: str
      - email_hash: str
      - file_path: str (path to .eml)
    Returns:
      - { "out_dir": str }
    """
    from tasks.P3_parse_files.temp_dirs import make_temp_dir
    from email import policy
    from email.parser import BytesParser

    out_dir = make_temp_dir(params.collection_dataset, "email", params.email_hash)
    log.info("[P3] Extracting email attachments for %s to %s", params.file_path, out_dir)

    with open(params.file_path, "rb") as f:
        msg = BytesParser(policy=policy.default).parse(f)

    attachment_index = 0
    for part in msg.walk():
        # Skip containers
        if part.is_multipart():
            continue
        filename = part.get_filename()
        content_disposition = (part.get("Content-Disposition") or "").lower()
        is_attachment = "attachment" in content_disposition or filename
        if not is_attachment:
            continue
        if not filename:
            attachment_index += 1
            filename = f"attachment_{attachment_index}"
        # Sanitize filename minimally
        safe_name = filename.replace("/", "_").replace("\\", "_")
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        target_path = os.path.join(out_dir, safe_name)
        try:
            with open(target_path, "wb") as out_f:
                out_f.write(payload)
        except Exception:
            # Best-effort: skip on error
            continue

    return {"out_dir": out_dir}


@dataclass
class EmailExtractionWorkflowParams:
    collection_dataset: str
    email_hash: str
    timeout_seconds: int
    file_path: str | None = None
    archive_path: str | None = None



@workflow.defn
class EmailExtractionAndScan:
    """Workflow that extracts email headers/text, unpacks attachments, scans via P0, and cleans up."""
    @workflow.run
    async def run(self, params: EmailExtractionWorkflowParams) -> str:
        # Defensive read of file_path to avoid KeyError on older histories
        file_path: str = (params.file_path or params.archive_path or "")
        if not file_path:
            from temporalio.exceptions import ApplicationError
            raise ApplicationError("EmailExtractionAndScan missing file_path", non_retryable=True)

        # 1) Extract headers + text content
        await workflow.execute_activity(
            parse_email_extract_text_headers,
            ParseEmailHeadersParams(collection_dataset=params.collection_dataset, email_hash=params.email_hash, file_path=file_path),
            start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # 2) Extract attachments to temp dir
        res = await workflow.execute_activity(
            extract_email_attachments_to_temp,
            ExtractEmailAttachmentsParams(collection_dataset=params.collection_dataset, email_hash=params.email_hash, file_path=file_path, timeout_seconds=params.timeout_seconds),
            start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        out_dir = res.get("out_dir")

        # 3) Scan extracted attachments via P0 as child workflow
        with workflow.unsafe.imports_passed_through():
            from tasks.P0_scan_disk.workflows import HandleFolders, HandleFoldersParams
        await workflow.execute_child_workflow(
            HandleFolders.run,
            HandleFoldersParams(
                collection_dataset=params.collection_dataset,
                dataset_path=out_dir,
                folder_paths=["/"],
                container_hash=params.email_hash,
                root_path_prefix="",
            ),
            id=f"scan-email-{params.collection_dataset}-{params.email_hash}",
            task_queue="processing-common-queue",
        )

        # 4) Cleanup temp dir (reuse cleanup_temp_dir from archives module)
        with workflow.unsafe.imports_passed_through():
            from tasks.P3_parse_files.parse_archives import cleanup_temp_dir, CleanupTempDirParams
        await workflow.execute_activity(
            cleanup_temp_dir,
            CleanupTempDirParams(out_dir=out_dir),
            start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        return out_dir
