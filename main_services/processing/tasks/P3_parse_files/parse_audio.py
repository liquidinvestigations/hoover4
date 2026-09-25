"""Audio metadata extraction activity using ffprobe."""

from temporalio import activity
from typing import Dict, Any
from dataclasses import dataclass
import subprocess
import json
import os
import logging
from tasks.heartbeat import with_heartbeat
from tasks.P3_parse_files.batch_runner import (
    BatchFile, BatchResult, StageBatchParams, run_batch, try_budget_seconds,
)

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
    collectionname: str
    collection_dataset: str
    file_hash: str
    file_path: str
    timeout_seconds: int
    op_id: str = ""


@activity.defn
@with_heartbeat
def parse_audio_metadata_and_store(params: ParseAudioParams) -> str:
    from database.clickhouse import get_collection_client, insert_arrow_idempotent
    import pyarrow as pa
    from datetime import datetime, timezone

    log.info("[P3] Parsing audio metadata for %s", params.file_path)

    # Timeout
    meta = _run_ffprobe_json(params.file_path, int(params.timeout_seconds))
    duration = _duration_seconds(meta)

    processed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    with get_collection_client(params.collectionname) as client:
        tbl_meta = pa.table({
            "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
            "hash": pa.array([params.file_hash], type=pa.string()),
            "audio_metadata_json": pa.array([json.dumps({"ffprobe": meta, "duration_seconds": duration})], type=pa.string()),
            "processed_at": pa.array([processed_at], type=pa.timestamp("s")),
        })
        insert_arrow_idempotent(client, "audio_metadata", tbl_meta)

    return "audio_ok"


@activity.defn
@with_heartbeat
def parse_audio_metadata_batch(params: StageBatchParams) -> BatchResult:
    """The audio metadata of each file of a group, one `parse_audio_metadata_and_store` call a file."""
    def step(file: BatchFile) -> str:
        return parse_audio_metadata_and_store(ParseAudioParams(
            collectionname=params.collectionname,
            collection_dataset=params.collection_dataset,
            file_hash=file.item_hash,
            file_path=file.file_path,
            timeout_seconds=try_budget_seconds("parse_audio_metadata_batch",
                                               file.file_size_bytes),
            op_id=params.op_id,
        ))

    return run_batch("parse_audio_metadata_batch", params.files, key=lambda f: f.item_hash,
                     size=lambda f: f.file_size_bytes, step=step,
                     task_name="parse_audio_metadata_and_store")

