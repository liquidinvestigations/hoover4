"""Image metadata extraction activity using ffprobe."""

from temporalio import activity
from typing import Dict, Any
from dataclasses import dataclass
import subprocess
import json
import os
import math

import logging
from tasks.heartbeat import with_heartbeat

log = logging.getLogger(__name__)

#: ffprobe's own, unambiguous statement that the bytes it read are not a media
#: container it recognises. The routing that calls into this activity fires whenever
#: any one detector's guess includes "image", even when the other detectors disagree,
#: so this is the expected shape for a document a weaker detector mistyped: retrying
#: does not change what ffprobe reads.
_NOT_MEDIA_MARKER = b"Invalid data found when processing input"


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
        if _NOT_MEDIA_MARKER in (res.stderr or b""):
            from temporalio.exceptions import ApplicationError
            raise ApplicationError(
                f"ffprobe failed: {res.stderr[:200]} {res.stdout[:200]}",
                non_retryable=True,
            )
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
    collectionname: str
    collection_dataset: str
    file_hash: str
    file_path: str
    timeout_seconds: int


@activity.defn
@with_heartbeat
def parse_image_metadata_and_store(params: ParseImageParams) -> str:
    from database.clickhouse import get_collection_client, insert_arrow_idempotent
    import pyarrow as pa
    from datetime import datetime, timezone

    log.info("[P3] Parsing image metadata for %s", params.file_path)

    try:
        size_bytes = os.path.getsize(params.file_path)
    except Exception:
        size_bytes = 0

    meta = _run_ffprobe_json(params.file_path, int(params.timeout_seconds))
    width, height = _first_stream_resolution(meta)
    # TODO: if ffprobe reports a 0x0 resolution here the image
    # may be undecodable; consider routing it through
    # tasks/P3_parse_files/image_loader.load_image_rgb like parse_ocr.py does.

    processed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    with get_collection_client(params.collectionname) as client:
        # Upsert into image table
        tbl_img = pa.table({
            "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
            "image_hash": pa.array([params.file_hash], type=pa.string()),
            "width_pixels": pa.array([int(width)], type=pa.uint32()),
            "height_pixels": pa.array([int(height)], type=pa.uint32()),
            "image_metadata": pa.array([json.dumps(meta)], type=pa.string()),
        })
        insert_arrow_idempotent(client, "image", tbl_img)

        # Also store raw metadata to image_metadata table if present in DB
        try:
            tbl_meta = pa.table({
                "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
                "hash": pa.array([params.file_hash], type=pa.string()),
                "image_metadata_json": pa.array([json.dumps(meta)], type=pa.string()),
                "processed_at": pa.array([processed_at], type=pa.timestamp("s")),
            })
            insert_arrow_idempotent(client, "image_metadata", tbl_meta)
        except Exception:
            # Table might not exist yet; ignore
            pass

    return "image_ok"


