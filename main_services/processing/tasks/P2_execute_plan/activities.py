"""Activities to execute processing plans, download blobs, and record status."""

from temporalio import activity
from typing import Dict, Any, List
from dataclasses import dataclass
from datetime import datetime
import os
import shutil
import logging
import pyarrow as pa

import pyarrow.compute as pc

log = logging.getLogger(__name__)


def _escape(v: str) -> str:
    return v.replace("'", "''")


@dataclass
class ListPendingPlansParams:
    collection_dataset: str
    starting_plan_hash: str | None = None


@activity.defn
def list_pending_plans(params: ListPendingPlansParams) -> List[str]:
    """Activity that lists up to 1001 pending plan hashes to execute."""
    from database.clickhouse import get_clickhouse_client
    collection_dataset: str = params.collection_dataset
    starting_plan_hash: str = params.starting_plan_hash or ""

    cond_start = (
        f" AND p.plan_hash >= '{_escape(starting_plan_hash)}'" if starting_plan_hash else ""
    )
    sql = f"""
        SELECT p.plan_hash
        FROM processing_plans p
        WHERE p.collection_dataset = '{_escape(collection_dataset)}'
          AND NOT EXISTS (
            SELECT 1 FROM processing_plan_finished f
            WHERE f.collection_dataset = p.collection_dataset AND f.plan_hash = p.plan_hash
          )
          {cond_start}
        ORDER BY p.plan_hash ASC
        LIMIT 1001
    """
    with get_clickhouse_client() as client:
        tbl = client.query_arrow(sql)
        results: List[str] = []
        if tbl and tbl.num_rows:
            col = tbl.column(0)
            for i in range(tbl.num_rows):
                results.append(col[i].as_py())
        return results


@dataclass
class GetPlanItemsMetadataParams:
    collection_dataset: str
    plan_hash: str


@activity.defn
def get_plan_items_metadata(params: GetPlanItemsMetadataParams) -> List[Dict[str, Any]]:
    """Activity that joins plan hits with file types and blob metadata."""
    from database.clickhouse import get_clickhouse_client
    collection_dataset: str = params.collection_dataset
    plan_hash: str = params.plan_hash

    sql = f"""
        SELECT h.item_hash,
               b.blob_size_bytes,
               b.s3_path
        FROM processing_plan_hits h
        LEFT JOIN blobs b
          ON b.collection_dataset = h.collection_dataset AND b.blob_hash = h.item_hash
        WHERE h.collection_dataset = '{_escape(collection_dataset)}'
          AND h.plan_hash = '{_escape(plan_hash)}'
        ORDER BY h.item_hash ASC
    """

    with get_clickhouse_client() as client:
        tbl = client.query_arrow(sql)
        results: List[Dict[str, Any]] = []
        if not tbl or tbl.num_rows == 0:
            return results
        ch = tbl.column("item_hash")
        sz = tbl.column("blob_size_bytes") if "blob_size_bytes" in tbl.column_names else None
        sp = tbl.column("s3_path") if "s3_path" in tbl.column_names else None
        for i in range(tbl.num_rows):
            size_v = sz[i].as_py() if sz else None
            s3_v = sp[i].as_py() if sp else None
            results.append({
                "item_hash": ch[i].as_py(),
                "file_size_bytes": int(size_v) if (size_v is not None and size_v != "") else 0,
                "s3_url": s3_v if s3_v is not None else "",
            })
        return results


def _plan_dir(base_temp_dir: str, ds: str, plan_hash: str) -> str:
    return os.path.join(base_temp_dir, ds, plan_hash)


from typing import Tuple


def _parse_s3_url(s3_url: str) -> Tuple[str, str]:
    # s3://bucket/key...
    if not s3_url.startswith("s3://"):
        return "", ""
    rest = s3_url[len("s3://"):]
    parts = rest.split("/", 1)
    if len(parts) != 2:
        return "", ""
    return parts[0], parts[1]


@dataclass
class DownloadPlanFilesParams:
    collection_dataset: str
    plan_hash: str
    items: List[Dict[str, Any]]
    base_temp_dir: str


@activity.defn
def download_plan_files(params: DownloadPlanFilesParams) -> Dict[str, Any]:
    """Activity that downloads plan files locally from S3 or ClickHouse."""
    from database.minio import get_minio_client, ensure_bucket
    from database.clickhouse import get_clickhouse_client
    collection_dataset: str = params.collection_dataset
    plan_hash: str = params.plan_hash
    items: List[Dict[str, Any]] = params.items
    base_temp_dir: str = params.base_temp_dir

    out_dir = _plan_dir(base_temp_dir, collection_dataset, plan_hash)
    os.makedirs(out_dir, exist_ok=True)

    # Prepare ClickHouse client and S3 client once
    minio_client = get_minio_client()

    # Separate S3-backed and ClickHouse-backed items, track output paths
    hash_to_path = {}
    ch_hashes: List[str] = []
    s3_jobs: List[Dict[str, str]] = []
    s3_hashes = set()

    total_size = sum(it["file_size_bytes"] for it in items) / 1024 / 1024  # MB
    log.info("[P2] Downloading %s files (%s MB) for plan %s %s", len(items), total_size, collection_dataset, plan_hash)

    for it in items:
        h = it.get("item_hash")
        s3_url = (it.get("s3_url") or "").strip()
        target_path = os.path.join(out_dir, h)
        hash_to_path[h] = target_path

        if s3_url:
            bucket, key = _parse_s3_url(s3_url)
            if not bucket or not key:
                log.warning("Invalid s3 url for %s: %s", h, s3_url)
                ch_hashes.append(h)  # fallback to ClickHouse
            else:
                s3_jobs.append({"bucket": bucket, "key": key, "path": target_path, "hash": h})
                s3_hashes.add(h)
        else:
            ch_hashes.append(h)

    # Download S3-backed files
    for job in s3_jobs:
        minio_client.fget_object(job["bucket"], job["key"], job["path"])

    # Batch-fetch ClickHouse blobs in chunks of 100
    BATCH_SIZE = 100
    for i in range(0, len(ch_hashes), BATCH_SIZE):
        batch = ch_hashes[i:i + BATCH_SIZE]
        if not batch:
            continue
        in_list = ",".join([f"'{_escape(h)}'" for h in batch])
        sql = f"""
            SELECT blob_hash, blob_value
            FROM blob_values
            WHERE collection_dataset = '{_escape(collection_dataset)}'
              AND blob_hash IN ({in_list})
        """
        with get_clickhouse_client() as client:
            tbl = client.query_arrow(sql)
            if not tbl or tbl.num_rows == 0:
                continue
            col_hash = tbl.column("blob_hash").combine_chunks()
            col_val = tbl.column("blob_value")
            # Force to binary to get bytes reliably
            col_val_bin = pc.cast(col_val, pa.large_binary()).combine_chunks()
            hashes = col_hash.to_pylist()
            values = col_val_bin.to_pylist()  # list of bytes
            for bh, data in zip(hashes, values):
                outp = hash_to_path.get(bh)
                if not outp:
                    continue
                with open(outp, "wb") as f:
                    f.write(data)

    # Verify sizes of all downloaded files
    for it in items:
        ih = it.get("item_hash")
        expected = int(it["file_size_bytes"])
        path = hash_to_path.get(ih)
        if not path:
            raise RuntimeError(
                f"[P2] Missing output path for item {ih} in plan {collection_dataset}/{plan_hash}"
            )
        try:
            actual = os.path.getsize(path)
        except FileNotFoundError:
            src = "s3" if ih in s3_hashes else "clickhouse"
            raise RuntimeError(
                f"[P2] Downloaded file missing for {collection_dataset}/{plan_hash}/{ih} from {src}; expected {expected} bytes"
            )
        if actual != expected:
            src = "s3" if ih in s3_hashes else "clickhouse"
            raise RuntimeError(
                f"[P2] Size mismatch for {collection_dataset}/{plan_hash}/{ih} from {src}: expected {expected} bytes, got {actual} bytes at {path}"
            )

    return {"out_dir": out_dir, "count": len(items)}


# Removed: process_downloaded_files. Processing is now handled by P3 child workflows.


@dataclass
class CleanupPlanDirParams:
    collection_dataset: str
    plan_hash: str
    base_temp_dir: str


@activity.defn
def cleanup_plan_dir(params: CleanupPlanDirParams) -> str:
    """Activity that deletes a plan's temp directory after processing."""
    collection_dataset: str = params.collection_dataset
    plan_hash: str = params.plan_hash
    base_temp_dir: str = params.base_temp_dir
    out_dir = _plan_dir(base_temp_dir, collection_dataset, plan_hash)

    log.info("[P2] Cleaning up plan dir for %s %s", collection_dataset, plan_hash)
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir, ignore_errors=True)
    return out_dir


@dataclass
class EnsureTempDirExistsParams:
    base_temp_dir: str


@activity.defn
def ensure_temp_dir_exists(params: EnsureTempDirExistsParams) -> str:
    """Activity that ensures the base temp directory exists on disk."""
    base_temp_dir: str = params.base_temp_dir
    os.makedirs(base_temp_dir, exist_ok=True)
    return base_temp_dir


@dataclass
class MarkPlanFinishedParams:
    collection_dataset: str
    plan_hash: str


@activity.defn
def mark_plan_finished(params: MarkPlanFinishedParams) -> str:
    """Activity that records the completion of a processing plan."""
    from database.clickhouse import get_clickhouse_client
    collection_dataset: str = params.collection_dataset
    plan_hash: str = params.plan_hash
    now = datetime.utcnow()
    with get_clickhouse_client() as client:
        tbl = pa.table({
            "collection_dataset": pa.array([collection_dataset], type=pa.string()),
            "plan_hash": pa.array([plan_hash], type=pa.string()),
            "finished_at": pa.array([now], type=pa.timestamp("s")),
        })
        client.insert_arrow("processing_plan_finished", tbl)
    return plan_hash


@dataclass
class RecordProcessingErrorsParams:
    errors: List[Dict[str, Any]]


@activity.defn
def record_processing_errors(params: RecordProcessingErrorsParams) -> int:
    """Activity that records multiple processing error rows into ClickHouse in one insert.

    Expected params:
      - errors: List[Dict[str, Any]] where each item has keys:
          collection_dataset, hash, task_name, run_time_ms, error_logs
    """
    from database.clickhouse import get_clickhouse_client
    errors: List[Dict[str, Any]] = list(params.errors or [])
    if not errors:
        return 0

    coll_vals: List[str] = []
    hash_vals: List[str] = []
    task_vals: List[str] = []
    rt_vals: List[int] = []
    logs_vals: List[str] = []
    ts_vals: List[datetime] = []

    now = datetime.utcnow()

    for e in errors:
        coll_vals.append((e.get("collection_dataset") or ""))
        hash_vals.append((e.get("hash") or ""))
        task_vals.append((e.get("task_name") or ""))
        try:
            ms = int(e.get("run_time_ms") or 0)
            if ms < 0:
                ms = 0
        except Exception:
            ms = 0
        rt_vals.append(ms)
        logs_vals.append((e.get("error_logs") or ""))
        ts_vals.append(now)

    with get_clickhouse_client() as client:
        tbl = pa.table({
            "collection_dataset": pa.array(coll_vals, type=pa.string()),
            "hash": pa.array(hash_vals, type=pa.string()),
            "task_name": pa.array(task_vals, type=pa.string()),
            "run_time_ms": pa.array(rt_vals, type=pa.uint32()),
            "error_logs": pa.array(logs_vals, type=pa.string()),
            "timestamp": pa.array(ts_vals, type=pa.timestamp("s")),
        })
        client.insert_arrow("processing_errors", tbl)

    return len(errors)


