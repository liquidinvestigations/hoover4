"""Tika/Extractous parsing activity for text and metadata extraction."""

from temporalio import activity
from typing import Dict, Any, List
from dataclasses import dataclass
import json
import logging

log = logging.getLogger(__name__)

@dataclass
class RunTikaParams:
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


@activity.defn
def run_tika_and_store(params: RunTikaParams) -> Dict[str, Any]:
    """Activity that uses Extractous to extract text and metadata and stores results.

    Also writes detected file types to file_types with extracted_by='tika' and returns lists.
    """
    from extractous import Extractor, TesseractOcrConfig
    from database.clickhouse import get_clickhouse_client
    import pyarrow as pa

    log.info("[P3] Running Extractous for %s", params.file_path)

    # Extract text and metadata using Extractous
    extractor = Extractor().set_ocr_config(TesseractOcrConfig().set_language("eng"))
    result_text, metadata = extractor.extract_file_to_string(params.file_path)
    content_text = result_text or ""
    meta_parsed = metadata or {}

    # Single ClickHouse session for both inserts
    from datetime import datetime
    processed_at = datetime.utcnow()
    with get_clickhouse_client() as client:
        if content_text.strip():
            from tasks.P3_parse_files.parse_common import insert_text_chunks
            insert_text_chunks(params.collection_dataset, params.file_hash, "extractous", content_text)

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


