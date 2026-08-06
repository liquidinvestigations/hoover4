"""Tika/Extractous parsing activity for text and metadata extraction."""

from temporalio import activity
from typing import Dict, Any, List
from dataclasses import dataclass
import json
import logging

from tasks.heartbeat import heartbeat_pump, with_heartbeat

log = logging.getLogger(__name__)

@dataclass
class RunTikaParams:
    collectionname: str
    collection_dataset: str
    file_hash: str
    file_path: str
    timeout_seconds: int
    content_type: str | None = None


def _coarse_from_mime(mime: str) -> str:
    try:
        from tasks.P0_scan_disk.mime_type_mapper import coarse_file_type
        return coarse_file_type(mime)
    except Exception:
        return ""


# Hard cap for a single Extractous call, regardless of the activity timeout.
_EXTRACTOUS_SUBPROCESS_TIMEOUT_S = 600


def _extract_with_extractous(file_path: str) -> tuple[str, dict]:
    """Run Extractous in a subprocess with a hard timeout.

    Extractous (native Tika + Tesseract) wedges forever on some formats (camera
    RAW, PSD, TGA, ...). A stuck native call cannot be interrupted from Python
    and blocks the worker's activity threads — and every later Extractor() call
    with it. A subprocess can always be killed. A timeout is raised as a
    non-retryable ApplicationError so the file lands in processing_errors after
    one attempt instead of stalling the batch for hours.
    """
    import subprocess
    import sys
    from temporalio.exceptions import ApplicationError

    helper = (
        "import json, sys;"
        "from extractous import Extractor, TesseractOcrConfig;"
        "ex = Extractor().set_ocr_config(TesseractOcrConfig().set_language('eng'));"
        "text, meta = ex.extract_file_to_string(sys.argv[1]);"
        "sys.stdout.write(json.dumps({'text': text or '', 'metadata': meta or {}}, default=str))"
    )
    # Pump, not an in-loop beat: this blocks in a subprocess and has no loop of
    # its own. KEEP the subprocess timeout below -- the pump proves the pump
    # thread is alive, not that Extractous is progressing.
    try:
        with heartbeat_pump("extractous"):
            res = subprocess.run(
                [sys.executable, "-c", helper, file_path],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=_EXTRACTOUS_SUBPROCESS_TIMEOUT_S,
            )
    except subprocess.TimeoutExpired:
        raise ApplicationError(
            f"extractous timed out after {_EXTRACTOUS_SUBPROCESS_TIMEOUT_S}s for {file_path}",
            non_retryable=True,
        )
    if res.returncode != 0:
        raise RuntimeError(f"extractous failed for {file_path}: {res.stderr[-300:]!r}")
    out = json.loads(res.stdout.decode("utf-8", "replace") or "{}")
    return out.get("text") or "", out.get("metadata") or {}


@activity.defn
@with_heartbeat
def run_tika_and_store(params: RunTikaParams) -> Dict[str, Any]:
    """Activity that uses Extractous to extract text and metadata and stores results.

    Also writes detected file types to file_types with extracted_by='tika' and returns lists.
    """
    from database.clickhouse import get_collection_client
    import pyarrow as pa

    log.info("[P3] Running Extractous for %s", params.file_path)

    # Extract text and metadata using Extractous (subprocess: interruptible)
    result_text, meta_parsed = _extract_with_extractous(params.file_path)
    content_text = result_text or ""

    # Single ClickHouse session for both inserts
    from datetime import datetime, timezone
    processed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    with get_collection_client(params.collectionname) as client:
        if content_text.strip():
            from tasks.P3_parse_files.parse_common import insert_text_chunks
            insert_text_chunks(params.collectionname, params.collection_dataset, params.file_hash, "extractous", content_text)

        tbl_m = pa.table({
            "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
            "hash": pa.array([params.file_hash], type=pa.string()),
            "tika_metadata_json": pa.array([json.dumps(meta_parsed)], type=pa.string()),
            "processed_at": pa.array([processed_at], type=pa.timestamp("s")),
        })
        client.insert_arrow("tika_metadata", tbl_m)

        # Extract MIME/type from metadata if present and write to file_types
        mime_candidates: List[str] = []
        enc_candidates: List[str] = []
        extensions: List[str] = []
        try:
            # Common keys from Tika-like outputs
            for key in ["Content-Type", "content-type", "ContentType", "mime" ]:
                val = meta_parsed.get(key)
                if isinstance(val, str) and val:
                    mime_candidates.append(val.strip())
            for key in ["Content-Encoding", "content-encoding", "encoding"]:
                val = meta_parsed.get(key)
                if isinstance(val, str) and val:
                    enc_candidates.append(val.strip())
            for key in ["resourceName", "X-Parsed-By-Filename", "filename"]:
                val = meta_parsed.get(key)
                if isinstance(val, str) and "." in val:
                    name = val.strip()
                    base = name.lower()
                    parts = base.split('.')
                    if len(parts) > 1:
                        last_ext = '.' + parts[-1]
                        extensions.append(last_ext)
                        full_ext = '.' + '.'.join(parts[1:])
                        if full_ext not in extensions:
                            extensions.append(full_ext)
        except Exception:
            pass

        mime_types = sorted({m for m in mime_candidates if m})
        mime_encodings = sorted({e for e in enc_candidates if e})
        coarse_types = sorted({_coarse_from_mime(m) for m in mime_types if m})

        if mime_types or mime_encodings or coarse_types or extensions:
            tbl_ft = pa.table({
                "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
                "hash": pa.array([params.file_hash], type=pa.string()),
                "mime_type": pa.array([mime_types], type=pa.list_(pa.string())),
                "mime_encoding": pa.array([mime_encodings], type=pa.list_(pa.string())),
                "file_type": pa.array([coarse_types], type=pa.list_(pa.string())),
                "extensions": pa.array([extensions], type=pa.list_(pa.string())),
                "extracted_by": pa.array(["tika"], type=pa.large_string()),
            })
            client.insert_arrow("file_types", tbl_ft)

    return {
        "mime_types": mime_types,
        "mime_encodings": mime_encodings,
        "coarse_types": coarse_types,
        "extensions": extensions,
    }


