"""Audio metadata extraction activity using ffprobe."""

from temporalio import activity
from typing import Dict, Any
from dataclasses import dataclass
import subprocess
import json
import os
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


def _duration_seconds(meta: Dict[str, Any]) -> float:
    try:
        fmt = meta.get("format") or {}
        dur = fmt.get("duration")
        if dur is not None:
            return float(dur)
    except Exception:
        pass
    # Fallback to max stream duration
    try:
        max_d = 0.0
        for s in (meta.get("streams") or []):
            d = s.get("duration")
            if d is not None:
                max_d = max(max_d, float(d))
        return max_d
    except Exception:
        return 0.0


@dataclass
class ParseAudioParams:
    collection_dataset: str
    file_hash: str
    file_path: str
    timeout_seconds: int


@activity.defn
def parse_audio_metadata_and_store(params: ParseAudioParams) -> str:
    from database.clickhouse import get_clickhouse_client
    import pyarrow as pa
    from datetime import datetime

    log.info("[P3] Parsing audio metadata for %s", params.file_path)

    # Timeout
    meta = _run_ffprobe_json(params.file_path, int(params.timeout_seconds))
    duration = _duration_seconds(meta)

    processed_at = datetime.utcnow()
    with get_clickhouse_client() as client:
        tbl_meta = pa.table({
            "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
            "hash": pa.array([params.file_hash], type=pa.string()),
            "audio_metadata_json": pa.array([json.dumps({"ffprobe": meta, "duration_seconds": duration})], type=pa.string()),
            "processed_at": pa.array([processed_at], type=pa.timestamp("s")),
        })
        client.insert_arrow("audio_metadata", tbl_meta)

    return "audio_ok"


