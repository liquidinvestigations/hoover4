"""Plaintext extraction activity for raw text files."""

from temporalio import activity
from typing import Dict, Any
from dataclasses import dataclass
import logging
from tasks.heartbeat import with_heartbeat

log = logging.getLogger(__name__)

@dataclass
class ExtractPlaintextParams:
    collectionname: str
    collection_dataset: str
    file_hash: str
    file_path: str
    timeout_seconds: int


@activity.defn
@with_heartbeat
def extract_plaintext_chunks(params: ExtractPlaintextParams) -> int:
    """Activity that reads text files and inserts into text_content in 3MB chunks."""
    from tasks.P3_parse_files.parse_common import insert_text_chunks
    log.info("[P3] Extracting plaintext chunks for %s", params.file_path)
    with open(params.file_path, "rb") as f:
        data = f.read()
    return insert_text_chunks(params.collectionname, params.collection_dataset, params.file_hash, "raw_text", data)


