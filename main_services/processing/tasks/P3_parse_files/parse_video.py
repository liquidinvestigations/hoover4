"""Video parsing activities and workflow for ffprobe and frame extraction."""

from temporalio import workflow, activity
from temporalio.common import RetryPolicy
from datetime import timedelta
from typing import Dict, Any, List
from dataclasses import dataclass
import subprocess
import json
import os
import math
import tempfile
import logging

log = logging.getLogger(__name__)

from tasks.P3_parse_files.parse_archives import CleanupTempDirParams, RecordArchiveContainerParams
from tasks.P0_scan_disk.workflows import HandleFoldersParams


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


def _resolution(meta: Dict[str, Any]) -> Any:
    try:
        for s in (meta.get("streams") or []):
            if s.get("codec_type") == "video":
                w = int(s.get("width") or 0)
                h = int(s.get("height") or 0)
                return w, h
    except Exception:
        pass
    return 0, 0


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
class VideoMetaParams:
    collection_dataset: str
    video_hash: str
    file_path: str


@activity.defn
def video_ffprobe_and_store(params: VideoMetaParams) -> Dict[str, Any]:
    from database.clickhouse import get_clickhouse_client
    import pyarrow as pa
    from datetime import datetime

    collection_dataset: str = params.collection_dataset
    video_hash: str = params.video_hash
    file_path: str = params.file_path

    try:
        size_bytes = os.path.getsize(file_path)
    except Exception:
        size_bytes = 0

    log.info("[P3] Running ffprobe for video %s", file_path)

    # Timeout: 90s + size/20KBps
    BPS_20_K = 20_000
    timeout_seconds = 90 + math.ceil(size_bytes / BPS_20_K)

    meta = _run_ffprobe_json(file_path, timeout_seconds)
    width, height = _resolution(meta)
    duration = _duration_seconds(meta)

    processed_at = datetime.utcnow()
    with get_clickhouse_client() as client:
        tbl_meta = pa.table({
            "collection_dataset": pa.array([collection_dataset], type=pa.string()),
            "hash": pa.array([video_hash], type=pa.string()),
            "video_metadata_json": pa.array([json.dumps({"ffprobe": meta, "duration_seconds": duration, "width": width, "height": height})], type=pa.string()),
            "processed_at": pa.array([processed_at], type=pa.timestamp("s")),
        })
        client.insert_arrow("video_metadata", tbl_meta)

    return {"duration": duration, "width": width, "height": height, "size_bytes": size_bytes}


@dataclass
class VideoExtractParams:
    collection_dataset: str
    video_hash: str
    file_path: str


@activity.defn
def video_extract_frames_and_subtitles(params: VideoExtractParams) -> Dict[str, Any]:
    """Extract one frame every 4 seconds and any subtitle streams into a temp directory."""
    collection_dataset: str = params.collection_dataset
    video_hash: str = params.video_hash
    file_path: str = params.file_path

    try:
        size_bytes = os.path.getsize(file_path)
    except Exception:
        size_bytes = 0

    log.info("[P3] Extracting frames and subtitles for video %s", file_path)

    # Timeout: base 2 min + scaled by file size (10 KBps)
    BPS_10_K = 10_000
    timeout_seconds = 120 + math.ceil(size_bytes / BPS_10_K)

    from tasks.P3_parse_files.temp_dirs import make_temp_dir
    out_dir = make_temp_dir(collection_dataset, "video", video_hash)

    # 1) Extract frames: one per 4 seconds using fps=1/4
    frames_dir = os.path.join(out_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    frame_pattern = os.path.join(frames_dir, "frame_%06d.jpg")
    cmd_frames = [
        "ffmpeg", "-y",
        "-i", file_path,
        "-vf", "fps=1/4",
        "-qscale:v", "2",
        frame_pattern,
    ]
    subprocess.run(cmd_frames, capture_output=True, timeout=timeout_seconds)

    # 2) Extract subtitles (if present) to .srt files
    # We first probe for subtitle streams and then extract each one.
    probe = _run_ffprobe_json(file_path, timeout_seconds)
    subtitle_indices: List[int] = []
    for s in (probe.get("streams") or []):
        if s.get("codec_type") == "subtitle":
            idx = s.get("index")
            if isinstance(idx, int):
                subtitle_indices.append(idx)
    subs_dir = os.path.join(out_dir, "subtitles")
    if subtitle_indices:
        os.makedirs(subs_dir, exist_ok=True)
    for i, idx in enumerate(subtitle_indices):
        # Map stream index to a single output .srt
        out_srt = os.path.join(subs_dir, f"subtitle_{i+1}.srt")
        cmd_sub = [
            "ffmpeg", "-y",
            "-i", file_path,
            "-map", f"0:{idx}",
            out_srt,
        ]
        subprocess.run(cmd_sub, capture_output=True, timeout=timeout_seconds)

    return {"out_dir": out_dir}



@dataclass
class VideoProcessingWorkflowParams:
    collection_dataset: str
    video_hash: str
    file_path: str
    timeout_seconds: int




@workflow.defn
class VideoProcessingAndScan:
    @workflow.run
    async def run(self, params: VideoProcessingWorkflowParams) -> str:
        collection_dataset: str = params.collection_dataset
        video_hash: str = params.video_hash
        file_path: str = params.file_path

        # 1) ffprobe and store metadata
        _ = await workflow.execute_activity(
            video_ffprobe_and_store,
            VideoMetaParams(
                collection_dataset=collection_dataset,
                video_hash=video_hash,
                file_path=file_path,
            ),
            start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # 2) Extract frames and subtitles
        res = await workflow.execute_activity(
            video_extract_frames_and_subtitles,
            VideoExtractParams(
                collection_dataset=collection_dataset,
                video_hash=video_hash,
                file_path=file_path,
            ),
            start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        out_dir = res.get("out_dir")

        # 3) Record an archive-like container and scan folder
        if out_dir:
            args = HandleFoldersParams(
                collection_dataset=collection_dataset,
                dataset_path=out_dir,
                folder_paths=["/"],
                container_hash=video_hash,
                root_path_prefix="",
            )
            with workflow.unsafe.imports_passed_through():
                from tasks.P0_scan_disk.workflows import HandleFolders
                from tasks.P3_parse_files.parse_archives import cleanup_temp_dir
                from tasks.P3_parse_files.parse_archives import record_archive_container

            await workflow.execute_activity(
                record_archive_container,
                RecordArchiveContainerParams(
                    collection_dataset=collection_dataset,
                    archive_hash=video_hash,
                    archive_types=["video"],
                ),
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            await workflow.execute_child_workflow(
                HandleFolders.run,
                args,
                id=f"scan-video-{collection_dataset}-{video_hash}",
                task_queue="processing-common-queue",
            )

            await workflow.execute_activity(
                cleanup_temp_dir,
                CleanupTempDirParams(out_dir=out_dir),
                start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

        return "video_ok"
