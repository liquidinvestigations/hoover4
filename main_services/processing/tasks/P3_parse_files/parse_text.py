"""Plaintext extraction activity for raw text files."""

from temporalio import activity
from typing import Dict, Any
from dataclasses import dataclass, field
import logging
from tasks.heartbeat import with_heartbeat
from tasks.P3_parse_files.batch_runner import (
    BatchFile, BatchResult, StageBatchParams, run_batch, try_budget_seconds,
)

log = logging.getLogger(__name__)

@dataclass
class ExtractPlaintextParams:
    collectionname: str
    collection_dataset: str
    file_hash: str
    file_path: str
    timeout_seconds: int
    op_id: str = ""
    mime_types: list[str] = field(default_factory=list)
    sniff_mime_type: str = ""


@activity.defn
@with_heartbeat
def extract_plaintext_chunks(params: ExtractPlaintextParams) -> int:
    """Store decoded source text in segments, with structured mail and card handling."""
    from tasks.P3_parse_files.parse_common import insert_text_chunks
    from tasks.P3_parse_files.temp_dirs import require_input_file
    log.info("[P3] Extracting plaintext chunks for %s", params.file_path)
    require_input_file(params.file_path)
    with open(params.file_path, "rb") as f:
        data = f.read()
    from tasks.P3_parse_files.email_parts import mail_raw_text
    from tasks.P3_parse_files.structured_text import structured_text

    if params.sniff_mime_type == "text/vcard":
        data = structured_text(data, "vcard")
    elif "text/calendar" in params.mime_types:
        data = structured_text(data, "ical")
    elif "message/rfc822" in params.mime_types:
        data = mail_raw_text(data)
    return insert_text_chunks(params.collectionname, params.collection_dataset, params.file_hash, "raw_text", data)


@activity.defn
@with_heartbeat
def extract_plaintext_batch(params: StageBatchParams) -> BatchResult:
    """The raw text of each file of a group, one `extract_plaintext_chunks` call a file."""
    def step(file: BatchFile) -> int:
        return extract_plaintext_chunks(ExtractPlaintextParams(
            collectionname=params.collectionname,
            collection_dataset=params.collection_dataset,
            file_hash=file.item_hash,
            file_path=file.file_path,
            timeout_seconds=try_budget_seconds("extract_plaintext_batch",
                                               file.file_size_bytes),
            op_id=params.op_id,
            mime_types=file.mime_types,
            sniff_mime_type=file.sniff_mime_type,
        ))

    return run_batch("extract_plaintext_batch", params.files, key=lambda f: f.item_hash,
                     size=lambda f: f.file_size_bytes, step=step,
                     task_name="extract_plaintext_chunks")

