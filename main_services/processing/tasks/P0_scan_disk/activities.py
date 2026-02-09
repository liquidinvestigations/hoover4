"""Disk ingestion activities for listing, hashing, and storing file metadata."""

from temporalio import activity
import os
import re
import hashlib
import subprocess
import mimetypes
from typing import Dict, Tuple, List, Any, Set
import pyarrow as pa
from dataclasses import dataclass
import logging
log = logging.getLogger(__name__)

from database.clickhouse import get_clickhouse_client
from database.minio import BUCKET_NAME, get_minio_client, ensure_bucket


SMALL_BLOB_THRESHOLD_BYTES = 600 * 1024
FILE_BATCH_MAX_COUNT = 100
FILE_BATCH_MAX_BYTES = 50 * 1024 * 1024


def _compute_hashes_streaming(file_path: str) -> Tuple[Dict[str, str], int]:
    """Compute primary and secondary hashes in a single streaming pass.

    Primary: sha3_256
    Secondary: md5, sha1, sha256
    Returns a mapping and total size in bytes.
    """
    h_sha3_256 = hashlib.sha3_256()
    h_sha256 = hashlib.sha256()
    h_md5 = hashlib.md5()
    h_sha1 = hashlib.sha1()
    total_size = 0
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(8 * 1024 * 1024)
            if not chunk:
                break
            h_sha3_256.update(chunk)
            h_sha256.update(chunk)
            h_md5.update(chunk)
            h_sha1.update(chunk)
            total_size += len(chunk)
    return {
        "sha3_256": h_sha3_256.hexdigest(),
        "sha256": h_sha256.hexdigest(),
        "md5": h_md5.hexdigest(),
        "sha1": h_sha1.hexdigest(),
    }, total_size


def _detect_mime_and_encoding(file_path: str) -> Tuple[str, str]:
    mime_type = "application/octet-stream"
    encoding = "binary"
    try:
        res = subprocess.run(["file", "--mime-type", file_path], capture_output=True, text=True)
        if res.returncode == 0 and ": " in res.stdout:
            mime_type = res.stdout.strip().split(": ", 1)[1]
        res_enc = subprocess.run(["file", "--mime-encoding", file_path], capture_output=True, text=True)
        if res_enc.returncode == 0 and ": " in res_enc.stdout:
            encoding = res_enc.stdout.strip().split(": ", 1)[1]
    except Exception:
        guessed, enc = mimetypes.guess_type(file_path)
        if guessed:
            mime_type = guessed
        if enc:
            encoding = enc
    return mime_type, encoding


def _s3_client():
    return get_minio_client()


def _s3_bucket_name() -> str:
    return BUCKET_NAME


def _rel_to_abs(dataset_path: str, rel_path: str) -> str:
    if rel_path == "/":
        return dataset_path
    return os.path.join(dataset_path, rel_path.lstrip("/"))


@dataclass
class ListDiskFolderParams:
    collection_dataset: str
    dataset_path: str
    folder_path: str


@activity.defn
def list_disk_folder(params: ListDiskFolderParams) -> Dict[str, List[Dict[str, Any]]]:
    """Activity that lists a folder and returns dir and file metadata."""
    abs_dir = _rel_to_abs(params.dataset_path, params.folder_path)
    if not os.path.isdir(abs_dir):
        return {"dirs": [], "files": []}

    dirs: List[Dict[str, Any]] = []
    files: List[Dict[str, Any]] = []

    with os.scandir(abs_dir) as it:
        for entry in it:
            try:
                stat = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            # if surrogate is contained in path, skip the path.

            if re.search(r'[\uD800-\uDFFF]', entry.path):
                log.warning("Found path with non-utf8 character: '%s' ", entry.path, "  -- skipping path from processing!")
                continue
            
            rel_child = os.path.relpath(entry.path, params.dataset_path).replace(os.sep, "/")
            if entry.is_dir(follow_symlinks=False):
                dirs.append({
                    "path": "/" if rel_child == "." else ("/" + rel_child if not rel_child.startswith("/") else rel_child),
                    "mtime": int(stat.st_mtime),
                    "ctime": int(getattr(stat, "st_ctime", stat.st_mtime)),
                })
            elif entry.is_file(follow_symlinks=False):
                files.append({
                    "path": "/" + rel_child if not rel_child.startswith("/") else rel_child,
                    "size": int(stat.st_size),
                    "mtime": int(stat.st_mtime),
                    "ctime": int(getattr(stat, "st_ctime", stat.st_mtime)),
                })

    return {"dirs": dirs, "files": files}


@dataclass
class InsertVfsDirectoriesParams:
    collection_dataset: str
    dir_paths: List[str]
    container_hash: str = ""


@activity.defn
def insert_vfs_directories(params: InsertVfsDirectoriesParams) -> int:
    """Activity that inserts new VFS directories, skipping existing paths."""
    collection_dataset: str = params.collection_dataset
    dir_paths: List[str] = list(params.dir_paths or [])
    container_hash: str = params.container_hash or ""
    if not dir_paths:
        return 0

    def _escape(v: str) -> str:
        return v.replace("'", "''")

    # Deduplicate against existing
    existing_paths: Set[str] = set()
    with get_clickhouse_client() as client:
        in_list = ",".join([f"'{_escape(p)}'" for p in dir_paths])
        sql = f"""
            SELECT path
            FROM vfs_directories
            WHERE collection_dataset = '{_escape(collection_dataset)}'
              AND container_hash = '{_escape(container_hash)}'
              AND path IN ({in_list})
        """
        tbl = client.query_arrow(sql)
        if tbl and tbl.num_rows:
            col = tbl.column("path")
            for i in range(tbl.num_rows):
                existing_paths.add(col[i].as_py())

    to_insert = [p for p in dir_paths if p not in existing_paths]
    if not to_insert:
        return 0

    table = pa.table({
        "collection_dataset": pa.array([collection_dataset] * len(to_insert), type=pa.string()),
        "container_hash": pa.array([container_hash] * len(to_insert), type=pa.string()),
        "path": pa.array(to_insert, type=pa.string()),
        "user_id": pa.array(["system"] * len(to_insert), type=pa.string()),
    })
    with get_clickhouse_client() as client:
        client.insert_arrow("vfs_directories", table)
    return len(to_insert)


@dataclass
class IngestFilesBatchParams:
    collection_dataset: str
    dataset_path: str
    file_paths: List[str]
    container_hash: str = ""
    root_path_prefix: str = ""


@activity.defn
def ingest_files_batch(params: IngestFilesBatchParams) -> str:
    """Activity that ingests a batch of files into blobs, types, and VFS."""
    collection_dataset: str = params.collection_dataset
    dataset_path: str = params.dataset_path
    file_paths: List[str] = list(params.file_paths or [])
    container_hash: str = params.container_hash or ""
    root_path_prefix: str = params.root_path_prefix or ""

    def _escape(v: str) -> str:
        return v.replace("'", "''")

    # 1) Filter out vfs_files duplicates by path
    existing_paths: Set[str] = set()
    if file_paths:
        with get_clickhouse_client() as client:
            in_list = ",".join([f"'{_escape(p)}'" for p in file_paths])
            sql = f"""
                SELECT path
                FROM vfs_files
                WHERE collection_dataset = '{_escape(collection_dataset)}'
                  AND path IN ({in_list})
            """
            tbl = client.query_arrow(sql)
            if tbl and tbl.num_rows:
                col = tbl.column("path")
                for i in range(tbl.num_rows):
                    existing_paths.add(col[i].as_py())

    todo_paths = [p for p in file_paths if p not in existing_paths]
    if not todo_paths:
        return "0 files (all duplicates)"

    # 2) Compute metadata for remaining files
    user_id = "system"
    hashes: List[str] = []
    hashes_md5: List[str] = []
    hashes_sha1: List[str] = []
    hashes_sha256: List[str] = []
    sizes: List[int] = []
    # MIME detection moved to P3 parse_mime; keep only structural metadata here
    abs_paths: List[str] = []

    for rel in todo_paths:
        abs_p = _rel_to_abs(dataset_path, rel)
        abs_paths.append(abs_p)
        hm, size = _compute_hashes_streaming(abs_p)
        hashes.append(hm["sha3_256"])  # primary
        hashes_md5.append(hm["md5"])
        hashes_sha1.append(hm["sha1"])
        hashes_sha256.append(hm["sha256"])
        sizes.append(size)
        # Defer MIME/type detection to P3

    # 3) Dedup blobs and blob_values
    unique_hashes = list(dict.fromkeys(hashes))
    existing_blob_hashes: Set[str] = set()
    existing_blob_values: Set[str] = set()
    with get_clickhouse_client() as client:
        if unique_hashes:
            in_hashes = ",".join([f"'{_escape(h)}'" for h in unique_hashes])
            # Existing blobs for this dataset
            sql_blobs = f"""
                SELECT blob_hash, stored_in_clickhouse, s3_path
                FROM blobs
                WHERE collection_dataset = '{_escape(collection_dataset)}'
                  AND blob_hash IN ({in_hashes})
            """
            tbl_b = client.query_arrow(sql_blobs)
            existing_blob_meta: Dict[str, Dict[str, Any]] = {}
            if tbl_b and tbl_b.num_rows:
                hh = tbl_b.column("blob_hash")
                sic = tbl_b.column("stored_in_clickhouse")
                s3p = tbl_b.column("s3_path")
                for i in range(tbl_b.num_rows):
                    h = hh[i].as_py()
                    existing_blob_hashes.add(h)
                    s3_val = s3p[i].as_py()
                    existing_blob_meta[h] = {
                        "in_ch": int(sic[i].as_py() or 0),
                        "s3": s3_val if s3_val is not None else None,
                    }

            # Existing blob_values for this dataset
            sql_bv = f"""
                SELECT blob_hash
                FROM blob_values
                WHERE collection_dataset = '{_escape(collection_dataset)}'
                  AND blob_hash IN ({in_hashes})
            """
            tbl_v = client.query_arrow(sql_bv)
            if tbl_v and tbl_v.num_rows:
                col = tbl_v.column("blob_hash")
                for i in range(tbl_v.num_rows):
                    existing_blob_values.add(col[i].as_py())

    # 4) Upload S3 or gather small values; Build blobs inserts for new hashes only
    new_blob_hashes: Set[str] = set(h for h in unique_hashes if h not in existing_blob_hashes)
    blob_rows_cd: List[str] = []
    blob_rows_hash: List[str] = []
    blob_rows_size: List[int] = []
    blob_rows_md5: List[str] = []
    blob_rows_sha1: List[str] = []
    blob_rows_sha256: List[str] = []
    blob_rows_s3: List[str] = []
    blob_rows_inch: List[int] = []

    # For small values to insert into blob_values (only those not already in blob_values)
    bv_hash: List[str] = []
    bv_len: List[int] = []
    bv_val: List[bytes] = []

    # Map from hash to size and abs path for processing
    hash_to_size: Dict[str, int] = {}
    hash_to_abs: Dict[str, str] = {}
    for rel, h, s, ap in zip(todo_paths, hashes, sizes, abs_paths):
        if h not in hash_to_size:
            hash_to_size[h] = s
            hash_to_abs[h] = ap

    for h in new_blob_hashes:
        size = hash_to_size[h]
        if size <= SMALL_BLOB_THRESHOLD_BYTES:
            if h not in existing_blob_values:
                with open(hash_to_abs[h], "rb") as f:
                    data = f.read()
                bv_hash.append(h)
                bv_len.append(size)
                bv_val.append(data)
            blob_rows_cd.append(collection_dataset)
            blob_rows_hash.append(h)
            blob_rows_size.append(size)
            # Map h to indexes in todo_paths to fetch secondary hashes; build a lookup once
            # Fallback to empty strings if not found (should not happen)
            try:
                idx = hashes.index(h)
                blob_rows_md5.append(hashes_md5[idx])
                blob_rows_sha1.append(hashes_sha1[idx])
                blob_rows_sha256.append(hashes_sha256[idx])
            except ValueError:
                blob_rows_md5.append("")
                blob_rows_sha1.append("")
                blob_rows_sha256.append("")
            blob_rows_s3.append("")
            blob_rows_inch.append(1)
        else:
            # Upload to S3 only if completely new blob
            s3_key = f"{collection_dataset}/{h}"
            client_s3 = _s3_client()
            ensure_bucket(_s3_bucket_name())
            client_s3.fput_object(_s3_bucket_name(), s3_key, hash_to_abs[h])
            s3_uri = f"s3://{_s3_bucket_name()}/{s3_key}"
            blob_rows_cd.append(collection_dataset)
            blob_rows_hash.append(h)
            blob_rows_size.append(size)
            try:
                idx = hashes.index(h)
                blob_rows_md5.append(hashes_md5[idx])
                blob_rows_sha1.append(hashes_sha1[idx])
                blob_rows_sha256.append(hashes_sha256[idx])
            except ValueError:
                blob_rows_md5.append("")
                blob_rows_sha1.append("")
                blob_rows_sha256.append("")
            blob_rows_s3.append(s3_uri)
            blob_rows_inch.append(0)

    # 5) Insert blobs and blob_values
    with get_clickhouse_client() as client:
        if blob_rows_hash:
            table_blobs = pa.table({
                "collection_dataset": pa.array(blob_rows_cd, type=pa.string()),
                "blob_hash": pa.array(blob_rows_hash, type=pa.string()),
                "blob_size_bytes": pa.array(blob_rows_size, type=pa.uint64()),
                "md5": pa.array(blob_rows_md5, type=pa.string()),
                "sha1": pa.array(blob_rows_sha1, type=pa.string()),
                "sha256": pa.array(blob_rows_sha256, type=pa.string()),
                "s3_path": pa.array(blob_rows_s3, type=pa.string()),
                "stored_in_clickhouse": pa.array(blob_rows_inch, type=pa.uint8()),
            })
            client.insert_arrow("blobs", table_blobs)

        if bv_hash:
            table_bv = pa.table({
                "collection_dataset": pa.array([collection_dataset] * len(bv_hash), type=pa.string()),
                "blob_hash": pa.array(bv_hash, type=pa.string()),
                "blob_length": pa.array(bv_len, type=pa.uint64()),
                "blob_value": pa.array(bv_val, type=pa.binary()),
            })
            client.insert_arrow("blob_values", table_bv)

    # 6) MIME/type insertion moved to P3; no file_types writes here

    # 7) Insert vfs_files for remaining
    final_paths = [
        (root_path_prefix.rstrip("/") + p) if root_path_prefix else p
        for p in todo_paths
    ]
    with get_clickhouse_client() as client:
        table_files = pa.table({
            "collection_dataset": pa.array([collection_dataset] * len(final_paths), type=pa.string()),
            "container_hash": pa.array([container_hash] * len(final_paths), type=pa.string()),
            "path": pa.array(final_paths, type=pa.string()),
            "hash": pa.array(hashes, type=pa.string()),
            "user_id": pa.array([user_id] * len(final_paths), type=pa.string()),
            "file_size_bytes": pa.array(sizes, type=pa.uint64()),
        })
        client.insert_arrow("vfs_files", table_files)

    return f"ingested {len(todo_paths)} files (skipped {len(existing_paths)})"