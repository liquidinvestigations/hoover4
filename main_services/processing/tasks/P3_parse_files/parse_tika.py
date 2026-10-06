"""Parse document metadata and text with the Tika server."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import math
import os
from urllib.parse import quote

import requests
from temporalio import activity
from temporalio.exceptions import ApplicationError

from tasks.heartbeat import heartbeat_pump, with_heartbeat
from tasks.P3_parse_files.batch_runner import (
    BatchFile, BatchResult, FILE_BYTES_PER_SECOND, StageBatchParams, run_batch,
    try_budget_seconds,
)

log = logging.getLogger(__name__)
TIKA_PARSE_FAILED = "TikaParseFailed"
TIKA_SERVICE_FAILED = "TikaServiceFailed"
TIKA_OUTPUT_TOO_LARGE = "TikaOutputTooLarge"
_NO_TIKA_TYPES = {"application/x-hoover-pst", "application/vnd.ms-outlook-pst", "application/mbox"}
_META_TYPES = {"text/vcard", "text/x-vcard", "text/calendar"}


@dataclass
class RunTikaParams:
    collectionname: str
    collection_dataset: str
    file_hash: str
    file_path: str
    timeout_seconds: int
    op_id: str = ""
    mime_types: list[str] = field(default_factory=list)
    routes: list[str] = field(default_factory=list)
    file_mime_type: str = ""
    file_name: str = ""


@dataclass
class TikaAnswer:
    text: str = ""
    metadata: dict = field(default_factory=dict)
    error: ApplicationError | None = None


def document_type(metadata: dict) -> str:
    """Read the document type from the JSON metadata."""
    value = metadata.get("Content-Type", "")
    if isinstance(value, list):
        value = value[0] if value else ""
    return value.split(";", 1)[0].strip().lower() if isinstance(value, str) else ""


def endpoint_for(params: RunTikaParams) -> str | None:
    """Select the endpoint from the local types and routes."""
    if set(params.mime_types) & _NO_TIKA_TYPES:
        return None
    if (set(params.routes) & {"email", "archive"}
            or set(params.mime_types) & _META_TYPES
            or any(t.startswith("image/") and t != "image/svg+xml" for t in params.mime_types)):
        return "/meta"
    return "/tika/json/text"


def _answer(response) -> TikaAnswer:
    """Map a server response to text, metadata, and a typed failure."""
    status = response.status_code
    if status == 429:
        from tasks.remote import RemoteBusy
        raise RemoteBusy(response.headers.get("Retry-After"))
    if status != 200:
        error_type = {422: TIKA_PARSE_FAILED, 413: TIKA_OUTPUT_TOO_LARGE}.get(status, TIKA_SERVICE_FAILED)
        return TikaAnswer(error=ApplicationError(
            f"Tika HTTP {status}: {response.text[:4000]}", type=error_type,
            non_retryable=status != 500))
    metadata = response.json()
    if isinstance(metadata, list):
        metadata = metadata[0] if metadata else {}
    if not isinstance(metadata, dict):
        raise ValueError("Tika returned no metadata object")
    metadata = dict(metadata)
    text = metadata.pop("tk:content", "") or ""
    exception = metadata.get("tk:exception:container-exception")
    cut = str(metadata.get("tk:exception:write-limit-reached", "")).lower() == "true"
    error = None
    if exception and not (cut and "WriteLimitReachedException" in str(exception)):
        error = ApplicationError(str(exception)[:4000], type=TIKA_PARSE_FAILED, non_retryable=True)
    return TikaAnswer(text=text, metadata=metadata, error=error)


def parse_document(params: RunTikaParams) -> TikaAnswer:
    """Stream a file and retry one parse failure with its local file type."""
    endpoint = endpoint_for(params)
    if endpoint is None:
        return TikaAnswer()
    headers = {"Accept": "application/json"}
    if params.file_name:
        name = os.path.basename(params.file_name.replace("\\", "/"))
        headers["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(name, safe="")
    read_timeout = 360 + math.ceil(os.path.getsize(params.file_path) / FILE_BYTES_PER_SECOND)
    if read_timeout + 10 >= params.timeout_seconds:
        raise ValueError("Tika read timeout exceeds the file try budget")
    url = os.environ.get("TIKA_URL", "http://hoover4-tika:9998").rstrip("/") + endpoint

    def request():
        with open(params.file_path, "rb") as data, heartbeat_pump("tika"):
            return _answer(requests.put(url, data=data, headers=headers, timeout=(10, read_timeout)))

    answer = request()
    if answer.error and answer.error.type == TIKA_SERVICE_FAILED and not answer.error.non_retryable:
        answer = request()
        if answer.error and answer.error.type == TIKA_SERVICE_FAILED:
            answer.error = ApplicationError(answer.error.message, type=TIKA_SERVICE_FAILED, non_retryable=True)
    if (endpoint == "/tika/json/text" and answer.error
            and answer.error.type == TIKA_PARSE_FAILED and params.file_mime_type
            and params.file_mime_type != document_type(answer.metadata)):
        first = answer
        headers["Content-Type"] = params.file_mime_type
        answer = request()
        if answer.error:
            answer.error = ApplicationError(
                f"Tika detected type {document_type(first.metadata)!r}: {first.error.message}; "
                f"Tika requested type {params.file_mime_type!r}: {answer.error.message}",
                type=answer.error.type, non_retryable=answer.error.non_retryable)
    return answer


def _store_answer(params: RunTikaParams, answer: TikaAnswer) -> dict:
    from database.clickhouse import get_collection_client, insert_parser_arrow
    from tasks.P0_scan_disk.mime_type_mapper import coarse_file_type
    from tasks.P3_parse_files.parse_common import insert_text_chunks
    import pyarrow as pa

    mime = document_type(answer.metadata)
    types = [mime] if mime else []
    coarse = [coarse_file_type(mime)] if mime else []
    encoding = answer.metadata.get("Content-Encoding", "")
    encodings = [encoding] if isinstance(encoding, str) and encoding else []
    if answer.metadata:
        with get_collection_client(params.collectionname) as client:
            insert_parser_arrow(client, "tika_metadata", pa.table({
                "collection_dataset": [params.collection_dataset], "hash": [params.file_hash],
                "tika_metadata_json": [json.dumps(answer.metadata)],
                "processed_at": pa.array([datetime.now(timezone.utc).replace(tzinfo=None)], type=pa.timestamp("s")),
            }))
            if types:
                insert_parser_arrow(client, "file_types", pa.table({
                    "collection_dataset": [params.collection_dataset], "hash": [params.file_hash],
                    "mime_type": pa.array([types], type=pa.list_(pa.string())),
                    "mime_encoding": pa.array([encodings], type=pa.list_(pa.string())),
                    "file_type": pa.array([coarse], type=pa.list_(pa.string())),
                    "extensions": pa.array([[]], type=pa.list_(pa.string())),
                    "extracted_by": pa.array(["tika"], type=pa.large_string()),
                }))
    if not answer.error and endpoint_for(params) == "/tika/json/text":
        insert_text_chunks(params.collectionname, params.collection_dataset,
                           params.file_hash, "extractous", answer.text)
    return {"mime_types": types, "mime_encodings": encodings, "coarse_types": coarse, "extensions": []}


@activity.defn
@with_heartbeat
def run_tika_and_store(params: RunTikaParams) -> dict:
    """Store binary Word text, then store the Tika result before reporting its failure."""
    from tasks.P3_parse_files.temp_dirs import require_input_file
    from tasks.P3_parse_files.word_binary import extract_binary_word_text
    from tasks.P3_parse_files.parse_common import insert_text_chunks
    from tasks.text_sources import BINARY_WORD
    from tasks.heartbeat import worker_is_stopping

    require_input_file(params.file_path)
    try:
        word_text = extract_binary_word_text(params.file_path)
    except Exception as exc:
        if worker_is_stopping():
            raise
        log.warning("[P3] binary Word source unavailable for %s: %s", params.file_path, exc)
        word_text = None
    if word_text:
        insert_text_chunks(params.collectionname, params.collection_dataset,
                           params.file_hash, BINARY_WORD, word_text)
    answer = parse_document(params)
    result = _store_answer(params, answer)
    if answer.error:
        raise answer.error
    return result


@activity.defn
@with_heartbeat
def tika_text_batch(params: StageBatchParams) -> BatchResult:
    """Parse text and metadata for each file of a group."""
    def step(file: BatchFile) -> dict:
        return run_tika_and_store(RunTikaParams(
            collectionname=params.collectionname, collection_dataset=params.collection_dataset,
            file_hash=file.item_hash, file_path=file.file_path,
            timeout_seconds=try_budget_seconds("tika_text_batch", file.file_size_bytes),
            op_id=params.op_id, mime_types=file.mime_types, routes=file.routes,
            file_mime_type=file.file_mime_type, file_name=(file.file_names or [""])[0],
        ))
    return run_batch("tika_text_batch", params.files, key=lambda f: f.item_hash,
                     size=lambda f: f.file_size_bytes, step=step, task_name="run_tika_and_store")
