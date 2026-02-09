"""Image metadata extraction activity using ffprobe."""

from temporalio import activity
from typing import Dict, Any
from dataclasses import dataclass
import subprocess
import json
import os
import math

import logging

log = logging.getLogger(__name__)

def _run_ffprobe_json(file_path: str, timeout_seconds: int) -> Dict[str, Any]:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        file_path,
    ]
    res = subprocess.run(cmd, capture_output=True, timeout=timeout_seconds)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {res.stderr[:200]} {res.stdout[:200]}")
    try:
        return json.loads((res.stdout or b"").decode("utf-8", errors="ignore"))
    except Exception:
        return {}


def _first_stream_resolution(meta: Dict[str, Any]) -> Any:
    try:
        for s in (meta.get("streams") or []):
            if s.get("codec_type") == "video":
                w = int(s.get("width") or 0)
                h = int(s.get("height") or 0)
                return w, h
    except Exception:
        pass
    return 0, 0


@dataclass
class ParseImageParams:
    collection_dataset: str
    file_hash: str
    file_path: str
    timeout_seconds: int


@activity.defn
def parse_image_metadata_and_store(params: ParseImageParams) -> str:
    from database.clickhouse import get_clickhouse_client
    import pyarrow as pa
    from datetime import datetime

    log.info("[P3] Parsing image metadata for %s", params.file_path)

    try:
        size_bytes = os.path.getsize(params.file_path)
    except Exception:
        size_bytes = 0

    meta = _run_ffprobe_json(params.file_path, int(params.timeout_seconds))
    width, height = _first_stream_resolution(meta)

    processed_at = datetime.utcnow()
    with get_clickhouse_client() as client:
        # Upsert into image table
        tbl_img = pa.table({
            "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
            "image_hash": pa.array([params.file_hash], type=pa.string()),
            "width_pixels": pa.array([int(width)], type=pa.uint32()),
            "height_pixels": pa.array([int(height)], type=pa.uint32()),
            "image_metadata": pa.array([json.dumps(meta)], type=pa.string()),
        })
        client.insert_arrow("image", tbl_img)

        # Also store raw metadata to image_metadata table if present in DB
        try:
            tbl_meta = pa.table({
                "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
                "hash": pa.array([params.file_hash], type=pa.string()),
                "image_metadata_json": pa.array([json.dumps(meta)], type=pa.string()),
                "processed_at": pa.array([processed_at], type=pa.timestamp("s")),
            })
            client.insert_arrow("image_metadata", tbl_meta)
        except Exception:
            # Table might not exist yet; ignore
            pass

    return "image_ok"


