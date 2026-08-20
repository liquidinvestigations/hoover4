"""Email parsing activities and workflow for headers and attachments."""

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from typing import Dict, Any, List
from dataclasses import dataclass
import json
import os
import logging
from datetime import timedelta
from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT, with_heartbeat

log = logging.getLogger(__name__)


#: The four participant headers, in the order the viewer shows them. `role` is a
#: ClickHouse Enum8 on `email_addresses`, so these strings are the schema.
ADDRESS_ROLES = ("from", "to", "cc", "bcc")


def header_pairs(msg) -> list[list[str]]:
    """Every header of a message as ``[name, value]`` pairs, in the order it carried them.

    A LIST, not a dict, and this is the whole point: ``dict(msg.items())`` keeps only the
    LAST value of a repeated header, and the header repeated most is ``Received:`` -- five
    to ten lines on a normal message, the delivery path, and the single most useful
    forensic header a mail file has. Collapsing it to one line is not a lossy display, it
    is lost data. The same applies to repeated ``X-`` headers and to ``Cc:``.

    Order is preserved for the same reason: a ``Received:`` chain read out of order says
    the message travelled the other way.
    """
    return [[str(name), str(value)] for name, value in msg.items()]


def header_pairs_from_json(raw: str) -> list[tuple[str, str]]:
    """Read `email_headers.raw_headers_json` back, in either shape it can have.

    The column held ``{"Name": "value"}`` before it held ``[["Name", "value"], ...]``, and
    a document only gets the new shape when it is re-parsed. Both shapes are read here so
    a caller never has to know how old a row is; the dict shape simply has the repeated
    headers already thrown away.
    """
    if not raw:
        return []
    try:
        loaded = json.loads(raw)
    except ValueError:
        return []
    if isinstance(loaded, dict):
        return [(str(k), str(v)) for k, v in loaded.items()]
    if isinstance(loaded, list):
        pairs = []
        for entry in loaded:
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                pairs.append((str(entry[0]), str(entry[1])))
        return pairs
    return []


def first_header(pairs, name: str) -> str:
    """The first value of `name`, case-insensitively, or the empty string."""
    wanted = name.lower()
    for header_name, value in pairs:
        if header_name.lower() == wanted:
            return value
    return ""


def extract_email_addresses(
    headers_by_role: dict[str, list[str]]
) -> list[tuple[str, str, str]]:
    """Parse participant headers into ``(role, address, display_name)`` triples.

    Pure, because every interesting case here is a parsing case and none of them needs a
    stack: folded headers, RFC 2822 group syntax (``undisclosed-recipients:;``), display
    names containing the comma that would otherwise split the list, and the same header
    appearing twice.

    ``headers_by_role`` maps a role to the RAW header strings -- plural, because
    ``msg.get(hdr)`` returns only the FIRST of a repeated header and mail in the wild
    repeats ``Cc:``. Callers pass ``msg.get_all(hdr)``.

    Addresses are lower-cased so ``E.Brandt@BlakeLaw.net`` and ``e.brandt@blakelaw.net``
    are one facet value; the display name keeps its original casing in its own column.
    Results are deduplicated on ``(role, address)`` -- the first display name seen for an
    address wins, so a later bare ``To: a@b.com`` does not blank a name -- and returned
    in a stable order.
    """
    from email.utils import getaddresses

    seen: dict[tuple[str, str], tuple[str, str, str]] = {}
    for role in ADDRESS_ROLES:
        raw_values = [v for v in (headers_by_role.get(role) or []) if v]
        if not raw_values:
            continue
        for display_name, address in getaddresses([str(v) for v in raw_values]):
            address = (address or "").strip().lower()
            display_name = (display_name or "").strip()
            # Group syntax yields ('', '') for the group label itself. A header holding
            # only a display name is worse than empty: `getaddresses(["Just A Name"])`
            # hands back the bare atom `Just` as an ADDRESS, which would become a facet
            # value that matches nothing and looks like a person. Require a real
            # `local@domain`.
            local, _, domain = address.partition("@")
            if not local or not domain or "@" in domain:
                continue
            key = (role, address)
            if key not in seen:
                seen[key] = (role, address, display_name)
    return list(seen.values())



def _message_bytes(file_path: str) -> bytes:
    """The RFC 822 message, with anything wrapped around it removed.

    Two wrappers reach this code. A UTF-8 BOM, and Apple Mail's `.emlx` byte-count line —
    a decimal number on its own first line, which `email`'s parser has never heard of and
    reads as the start of a body, losing every header in the file.
    """
    from tasks.P3_parse_files.sniff_email import strip_email_envelope

    with open(file_path, "rb") as handle:
        return strip_email_envelope(handle.read())


@dataclass
class ParseEmailHeadersParams:
    collectionname: str
    collection_dataset: str
    email_hash: str
    file_path: str


@activity.defn
@with_heartbeat
def parse_email_extract_text_headers(params: ParseEmailHeadersParams) -> str:
    """Activity that parses .eml, stores headers, and extracts text parts."""
    from email import policy
    from email.parser import BytesParser
    from email.utils import parsedate_to_datetime
    from datetime import datetime, timezone
    from database.clickhouse import get_collection_client, insert_arrow_idempotent
    import pyarrow as pa
    log.info("[P3] Parsing email headers for %s", params.file_path)
    msg = BytesParser(policy=policy.default).parsebytes(_message_bytes(params.file_path))

    subject = msg["subject"] or ""
    # Parse RFC 2822 Date header and convert to UTC naive datetime for ClickHouse.
    #
    # `date_sent` is not nullable, so an absent or unparseable header still writes the
    # epoch -- and 1970-01-01 is a real date a real email can carry. `date_sent_known`
    # is what tells the two apart; the date resolver ignores `date_sent` without it.
    date_header = msg.get("date")
    date_sent_known = 0
    try:
        parsed_dt = parsedate_to_datetime(str(date_header)) if date_header else None
        if parsed_dt is None:
            raise ValueError("no date")
        if parsed_dt.tzinfo is not None:
            parsed_dt = parsed_dt.astimezone(timezone.utc).replace(tzinfo=None)
        date_sent_dt = parsed_dt
        date_sent_known = 1
    except Exception:
        # Fallback to epoch if invalid/missing to satisfy non-nullable DateTime
        date_sent_dt = datetime.utcfromtimestamp(0)

    # `get_all`, not `get`: `get` returns only the first of a repeated header, and mail
    # in the wild repeats Cc:. The flat `addresses` column keeps its old shape for
    # display; the structured rows below are what search and the viewer read.
    headers_by_role = {role: (msg.get_all(role) or []) for role in ADDRESS_ROLES}
    addresses_str = "; ".join(
        f"{role}: {', '.join(str(v) for v in values)}"
        for role, values in headers_by_role.items() if values
    )
    address_rows = extract_email_addresses(headers_by_role)

    # Save email container row
    with get_collection_client(params.collectionname) as client:
        tbl_e = pa.table({
            "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
            "email_hash": pa.array([params.email_hash], type=pa.string()),
            "email_type": pa.array(["eml"], type=pa.string()),
        })
        insert_arrow_idempotent(client, "emails", tbl_e)
        tbl_h = pa.table({
            "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
            "email_hash": pa.array([params.email_hash], type=pa.string()),
            "raw_headers_json": pa.array([json.dumps(header_pairs(msg))], type=pa.string()),
            "subject": pa.array([subject], type=pa.string()),
            "addresses": pa.array([addresses_str], type=pa.string()),
            "date_sent": pa.array([date_sent_dt], type=pa.timestamp("s")),
            "date_sent_known": pa.array([date_sent_known], type=pa.uint8()),
        })
        insert_arrow_idempotent(client, "email_headers", tbl_h)
        if address_rows:
            insert_arrow_idempotent(client, "email_addresses", pa.table({
                "collection_dataset": pa.array([params.collection_dataset] * len(address_rows), type=pa.string()),
                "email_hash": pa.array([params.email_hash] * len(address_rows), type=pa.string()),
                "role": pa.array([r[0] for r in address_rows], type=pa.string()),
                "address": pa.array([r[1] for r in address_rows], type=pa.string()),
                "display_name": pa.array([r[2] for r in address_rows], type=pa.string()),
            }))

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
        from tasks.P3_parse_files.parse_common import insert_text_pages, split_text_segments
        # One continuous 1-based page sequence over every text/plain part, inserted in a
        # single call. The previous version called the inserter once per part and used a
        # running total as the next start page, which reused a page number whenever a
        # part produced no segments -- and would now also make each call trim the pages
        # written by the one before it.
        pages: list[tuple[int, str]] = []
        for t in texts:
            for seg in split_text_segments(t or ""):
                pages.append((len(pages) + 1, seg))
        insert_text_pages(params.collectionname, params.collection_dataset,
                          params.email_hash, "email_parser", pages)

    return f"email {params.email_hash}"



@dataclass
class ExtractEmailAttachmentsParams:
    collectionname: str
    collection_dataset: str
    email_hash: str
    file_path: str
    timeout_seconds: int


@activity.defn
@with_heartbeat
def extract_email_attachments_to_temp(params: ExtractEmailAttachmentsParams) -> Dict[str, Any]:
    """Extract all attachments from an .eml to a temp directory.

    Params:
      - collection_dataset: str
      - email_hash: str
      - file_path: str (path to .eml)
    Returns:
      - { "out_dir": str, "attachment_count": int }

    The count is what lets the caller skip the scan entirely. Most messages in a mail
    corpus carry no attachment at all, and scanning the empty directory anyway costs a
    child workflow and two activities per message to discover nothing.
    """
    import os as _os
    from tasks.P3_parse_files.temp_dirs import make_temp_dir
    from email import policy
    from email.parser import BytesParser

    out_dir = make_temp_dir(params.collection_dataset, "email", params.email_hash)
    log.info("[P3] Extracting email attachments for %s to %s", params.file_path, out_dir)

    msg = BytesParser(policy=policy.default).parsebytes(_message_bytes(params.file_path))

    attachment_index = 0
    written = 0
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
        written += 1

    if written == 0:
        # Remove it here rather than leaving the caller a cleanup activity to run for
        # a directory that was never used.
        try:
            _os.rmdir(out_dir)
        except OSError:
            pass
    return {"out_dir": out_dir, "attachment_count": written}


@dataclass
class EmailExtractionWorkflowParams:
    collectionname: str
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
            ParseEmailHeadersParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, email_hash=params.email_hash, file_path=file_path),
            start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )

        # 2) Extract attachments to temp dir
        res = await workflow.execute_activity(
            extract_email_attachments_to_temp,
            ExtractEmailAttachmentsParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, email_hash=params.email_hash, file_path=file_path, timeout_seconds=params.timeout_seconds),
            start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        out_dir = res.get("out_dir")

        # A message with no attachments is the common case in a mail corpus, and the
        # activity above has already removed the empty directory. Scanning it anyway
        # costs a child workflow and a cleanup activity per message to find nothing --
        # on a maildir that is about a third of every Temporal execution the ingest
        # makes. `attachment_count` is absent only on a result written by an older
        # worker mid-upgrade, where the old unconditional behaviour is still correct.
        if res.get("attachment_count", 1) == 0:
            return out_dir

        # 3) Scan extracted attachments via P0 as child workflow
        with workflow.unsafe.imports_passed_through():
            from tasks.P0_scan_disk.workflows import HandleFolders, HandleFoldersParams
            from tasks.visibility import dataset_search_attributes
        await workflow.execute_child_workflow(
            HandleFolders.run,
            HandleFoldersParams(
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                dataset_path=out_dir,
                folder_paths=["/"],
                container_hash=params.email_hash,
                root_path_prefix="",
            ),
            id=f"scan-email-{params.collection_dataset}-{params.email_hash}",
            task_queue="processing-common-queue",
            search_attributes=dataset_search_attributes(params.collection_dataset),
        )

        # 4) Cleanup temp dir (reuse cleanup_temp_dir from archives module)
        with workflow.unsafe.imports_passed_through():
            from tasks.P3_parse_files.parse_archives import cleanup_temp_dir, CleanupTempDirParams
        await workflow.execute_activity(
            cleanup_temp_dir,
            CleanupTempDirParams(out_dir=out_dir),
            start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )

        return out_dir
