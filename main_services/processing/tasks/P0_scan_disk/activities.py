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

from database.clickhouse import get_collection_client
from database.s3 import collection_bucket, get_s3_client, ensure_bucket
from tasks.heartbeat import with_heartbeat


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
    return get_s3_client()


def _rel_to_abs(dataset_path: str, rel_path: str) -> str:
    if rel_path == "/":
        return dataset_path
    return os.path.join(dataset_path, rel_path.lstrip("/"))


@dataclass
class ListDiskFolderParams:
    collectionname: str
    collection_dataset: str
    dataset_path: str
    folder_path: str


@activity.defn
@with_heartbeat
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
    collectionname: str
    collection_dataset: str
    dir_paths: List[str]
    container_hash: str = ""


@activity.defn
@with_heartbeat
def insert_vfs_directories(params: InsertVfsDirectoriesParams) -> int:
    """Activity that inserts new VFS directories, skipping existing paths."""
    collection_dataset: str = params.collection_dataset
    dir_paths: List[str] = list(params.dir_paths or [])
    container_hash: str = params.container_hash or ""
    if not dir_paths:
        return 0

    def _escape(v: str) -> str:
        return v.replace("'", "''")

    # Deduplicate against existing. FINAL: vfs_directories is a ReplacingMergeTree and an
    # unmerged part would hide a row from this read, so the path is inserted a second time.
    existing_paths: Set[str] = set()
    with get_collection_client(params.collectionname) as client:
        in_list = ",".join([f"'{_escape(p)}'" for p in dir_paths])
        sql = f"""
            SELECT path
            FROM vfs_directories FINAL
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
    with get_collection_client(params.collectionname) as client:
        client.insert_arrow("vfs_directories", table)
    return len(to_insert)


#: How far a `vfs_files.mtime` can be trusted. Written next to the timestamp because the
#: number alone says nothing: the same field means "the archive recorded this in 2013"
#: in one row and "the worker wrote this temp file a second ago" in the next.
MTIME_SOURCE_ARCHIVE = "archive"        # 7z restored a stored timestamp: historical.
MTIME_SOURCE_UNTRUSTED = "untrusted"    # email attachment, re-written by the worker.
MTIME_SOURCE_FILESYSTEM = "filesystem"  # top level: the clone/save time of the corpus.


def resolve_mtime_source(container_hash: str, is_archive: bool, is_email: bool) -> str:
    """Which trust level applies to the mtimes of one batch. See the constants above.

    Pure so the trust decision is testable: getting it backwards would index the
    worker's own clock as a document date for every email attachment in the corpus,
    which is invisible in the data and obvious only as "every attachment is dated today".
    """
    if not container_hash:
        return MTIME_SOURCE_FILESYSTEM
    if is_archive:
        return MTIME_SOURCE_ARCHIVE
    if is_email:
        return MTIME_SOURCE_UNTRUSTED
    # A container we do not recognise (a PDF's extracted images, a video's frames): the
    # mtime is the worker's, so it is not filesystem-level either. Empty means unknown.
    return ""


@dataclass
class IngestFilesBatchParams:
    collectionname: str
    collection_dataset: str
    dataset_path: str
    file_paths: List[str]
    container_hash: str = ""
    root_path_prefix: str = ""
    #: Positionally aligned with ``file_paths``; empty when the caller has no stat data.
    file_mtimes: List[int] = None  # type: ignore[assignment]
    #: Positionally aligned with ``file_paths``; empty when the caller has no stat data.
    file_sizes: List[int] = None  # type: ignore[assignment]


def _now_naive_utc():
    """ClickHouse DateTime columns are naive UTC."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _touch_vfs_rows(collectionname: str, collection_dataset: str, container_hash: str,
                    rows: List[Dict[str, Any]]) -> None:
    """Re-write unchanged rows with a fresh ``updated_at``.

    A file whose mtime moved but whose content did not is still current, and the
    deletion sweep decides what is current by when it was last confirmed. Without this
    touch a copy or a restore — which moves every mtime and changes no content — would
    make the sweep tombstone the whole dataset.
    """
    if not rows:
        return
    now = _now_naive_utc()
    with get_collection_client(collectionname) as client:
        client.insert_arrow("vfs_files", pa.table({
            "collection_dataset": pa.array([collection_dataset] * len(rows), type=pa.string()),
            "container_hash": pa.array([container_hash] * len(rows), type=pa.string()),
            "path": pa.array([r["path"] for r in rows], type=pa.string()),
            "hash": pa.array([r["hash"] for r in rows], type=pa.string()),
            "user_id": pa.array(["system"] * len(rows), type=pa.string()),
            "file_size_bytes": pa.array([int(r["file_size_bytes"]) for r in rows], type=pa.uint64()),
            "mtime": pa.array([int(r["mtime"] or 0) for r in rows], type=pa.timestamp("s")),
            "mtime_source": pa.array([r.get("mtime_source", "")  or "" for r in rows], type=pa.string()),
            "updated_at": pa.array([now] * len(rows), type=pa.timestamp("s")),
            "is_deleted": pa.array([0] * len(rows), type=pa.uint8()),
        }))


@activity.defn
@with_heartbeat
def ingest_files_batch(params: IngestFilesBatchParams) -> str:
    """Activity that ingests a batch of files into blobs, types, and VFS."""
    collection_dataset: str = params.collection_dataset
    dataset_path: str = params.dataset_path
    file_paths: List[str] = list(params.file_paths or [])
    container_hash: str = params.container_hash or ""
    root_path_prefix: str = params.root_path_prefix or ""
    mtime_by_path: Dict[str, int] = {
        p: int(m or 0) for p, m in zip(file_paths, list(params.file_mtimes or []))
    }
    # Separate from `mtime_by_path`, which defaults a missing value to 0 because the
    # column is not nullable. Change detection has to be able to tell "the caller did not
    # stat this" from "the file's mtime is the epoch", so these keep None.
    file_mtimes_by_path: Dict[str, Any] = dict(zip(file_paths, list(params.file_mtimes or [])))
    file_sizes_by_path: Dict[str, Any] = dict(zip(file_paths, list(params.file_sizes or [])))

    def _escape(v: str) -> str:
        return v.replace("'", "''")

    # 1) Decide, per path, whether there is anything to do.
    #
    # Comparing paths alone is what a rescan used to do, and it is wrong in the direction
    # that loses data: a file whose CONTENT changed at the same path was skipped for ever,
    # with no new blob, no new plan and nothing downstream noticing. Size and mtime are
    # already in the table and already collected by the scan, so the comparison costs
    # nothing beyond two more columns on a read that happens anyway.
    #
    # Two things this read has to get right, both of which it used to get wrong:
    #   * it must compare the SAME strings step 7 inserts, i.e. prefixed with
    #     `root_path_prefix`. `file_paths` here is relative to the container root, so an
    #     archive or email member never matched and every re-run re-ingested it.
    #   * it must scope by `container_hash`. Two containers holding the same inner path
    #     (the `zip-in-multiple-locations` fixture) are distinct rows, and matching on the
    #     path alone would drop the second container's children.
    # FINAL because vfs_files is a ReplacingMergeTree: an unmerged part hides rows.
    def _prefixed(p: str) -> str:
        return (root_path_prefix.rstrip("/") + p) if root_path_prefix else p

    known: Dict[str, Dict[str, Any]] = {}
    if file_paths:
        with get_collection_client(params.collectionname) as client:
            in_list = ",".join([f"'{_escape(_prefixed(p))}'" for p in file_paths])
            sql = f"""
                SELECT path, hash, file_size_bytes, mtime_source,
                       toUnixTimestamp(mtime) AS mtime
                FROM vfs_files FINAL
                WHERE collection_dataset = '{_escape(collection_dataset)}'
                  AND container_hash = '{_escape(container_hash)}'
                  AND path IN ({in_list})
                  AND is_deleted = 0
            """
            for row in client.query_arrow(sql).to_pylist():
                known[row["path"]] = row

    # A path whose size AND mtime both match its row is unchanged: no read, no hash.
    # A size that differs settles it without reading the file at all. An mtime that moved
    # with the size unchanged is the only case that has to hash to find out, and it is
    # the common one after a copy or a restore — so it is hashed and then compared,
    # rather than assumed either way.
    unchanged: Set[str] = set()
    maybe_changed: List[str] = []
    todo_paths: List[str] = []
    for rel in file_paths:
        row = known.get(_prefixed(rel))
        if row is None:
            todo_paths.append(rel)
            continue
        if file_sizes_by_path.get(rel) is None or file_mtimes_by_path.get(rel) is None:
            # No stat data from the caller: fall back to the path-only behaviour rather
            # than re-hashing every known file on every scan.
            unchanged.add(rel)
            continue
        if int(row["file_size_bytes"]) != file_sizes_by_path[rel]:
            todo_paths.append(rel)
        elif int(row["mtime"] or 0) != file_mtimes_by_path[rel]:
            maybe_changed.append(rel)
        else:
            unchanged.add(rel)

    # The rehash. A file whose content is the same after all only needs its row touched,
    # so the scan that found it counts as authoritative for that path and the deletion
    # sweep does not tombstone it.
    touched: List[str] = []
    for rel in maybe_changed:
        current_hash, _ = _compute_hashes_streaming(_rel_to_abs(dataset_path, rel))
        if current_hash["sha3_256"] != known[_prefixed(rel)]["hash"]:
            todo_paths.append(rel)
        else:
            touched.append(rel)

    # **Every path this scan saw is touched, not only the rehashed ones.** The deletion
    # sweep decides what is still there by when a row was last confirmed, so a file that
    # matched on size and mtime — the overwhelmingly common case, and the one that costs
    # nothing to check — is exactly the file that has been confirmed. Touching only the
    # rehashed subset tombstones and de-indexes every unmodified file on the second scan
    # of a dataset, which looks like the corpus deleting itself.
    confirmed = sorted(set(touched) | unchanged)
    if confirmed:
        _touch_vfs_rows(params.collectionname, collection_dataset, container_hash,
                        [known[_prefixed(rel)] for rel in confirmed if _prefixed(rel) in known])

    skipped = len(unchanged) + len(touched)
    if not todo_paths:
        return f"0 files ({skipped} unchanged)"

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
    # The collection's own bucket. Named once here rather than at each upload so that a
    # blob and its `s3_path` can never disagree about which bucket it is in.
    bucket = collection_bucket(params.collectionname)
    unique_hashes = list(dict.fromkeys(hashes))
    existing_blob_hashes: Set[str] = set()
    existing_blob_values: Set[str] = set()
    with get_collection_client(params.collectionname) as client:
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
            ensure_bucket(bucket)
            client_s3.fput_object(bucket, s3_key, hash_to_abs[h])
            s3_uri = f"s3://{bucket}/{s3_key}"
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
    with get_collection_client(params.collectionname) as client:
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

    # 7) Insert vfs_files for remaining.
    #
    # The mtime trust level is a property of the CONTAINER, so it costs one lookup per
    # batch rather than one per file. FINAL on both: the archives/emails row is written
    # by the P3 stage that spawned this scan, moments ago, and an unmerged part would
    # silently demote a whole archive's members to "unknown".
    final_paths = [_prefixed(p) for p in todo_paths]
    is_archive = is_email = False
    if container_hash:
        with get_collection_client(params.collectionname) as client:
            is_archive = bool(client.query(
                "SELECT 1 FROM archives FINAL WHERE collection_dataset = {cd:String} "
                "AND archive_hash = {ch:String} LIMIT 1",
                {"cd": collection_dataset, "ch": container_hash},
            ).result_rows)
            if not is_archive:
                is_email = bool(client.query(
                    "SELECT 1 FROM emails FINAL WHERE collection_dataset = {cd:String} "
                    "AND email_hash = {ch:String} LIMIT 1",
                    {"cd": collection_dataset, "ch": container_hash},
                ).result_rows)
    mtime_source = resolve_mtime_source(container_hash, is_archive, is_email)
    mtimes = [mtime_by_path.get(p, 0) for p in todo_paths]

    with get_collection_client(params.collectionname) as client:
        table_files = pa.table({
            "collection_dataset": pa.array([collection_dataset] * len(final_paths), type=pa.string()),
            "container_hash": pa.array([container_hash] * len(final_paths), type=pa.string()),
            "path": pa.array(final_paths, type=pa.string()),
            "hash": pa.array(hashes, type=pa.string()),
            "user_id": pa.array([user_id] * len(final_paths), type=pa.string()),
            "file_size_bytes": pa.array(sizes, type=pa.uint64()),
            "mtime": pa.array(mtimes, type=pa.timestamp("s")),
            "mtime_source": pa.array([mtime_source] * len(final_paths), type=pa.string()),
            # The version column. A path has one current row, so an edited file replaces
            # its predecessor in place rather than sitting beside it.
            "updated_at": pa.array([_now_naive_utc()] * len(final_paths), type=pa.timestamp("s")),
            "is_deleted": pa.array([0] * len(final_paths), type=pa.uint8()),
        })
        client.insert_arrow("vfs_files", table_files)

    return f"ingested {len(todo_paths)} files (skipped {skipped} unchanged)"

#: Hashes per DELETE while de-indexing. A statement naming every hash of a large deletion
#: at once is a parse cost that grows with the deletion rather than with the table.
DEINDEX_HASH_BATCH = 500


@dataclass
class ReconcileDeletedFilesParams:
    collectionname: str
    collection_dataset: str
    #: When the scan that is being reconciled started, as epoch seconds. Every top-level
    #: row it did not touch is older than this and is therefore a path it did not find.
    scan_started_at: int


@dataclass
class ReconcileDeletedFilesResult:
    tombstoned: int
    deindexed: int


def _tombstone_paths(client, collection_dataset: str, gone: list, now) -> None:
    """Write an `is_deleted = 1` version of each path the scan stopped finding.

    The row is replaced in place rather than removed: `vfs_files` is a
    `ReplacingMergeTree` keyed on the path, so a tombstone is how a path says it is gone
    and still says what used to be there.
    """
    client.insert_arrow("vfs_files", pa.table({
        "collection_dataset": pa.array([collection_dataset] * len(gone), type=pa.string()),
        "container_hash": pa.array([""] * len(gone), type=pa.string()),
        "path": pa.array([r["path"] for r in gone], type=pa.string()),
        "hash": pa.array([r["hash"] for r in gone], type=pa.string()),
        "user_id": pa.array(["system"] * len(gone), type=pa.string()),
        "file_size_bytes": pa.array([int(r["file_size_bytes"]) for r in gone], type=pa.uint64()),
        "mtime": pa.array([int(r["mtime"] or 0) for r in gone], type=pa.timestamp("s")),
        "mtime_source": pa.array([r["mtime_source"] or "" for r in gone], type=pa.string()),
        "updated_at": pa.array([now] * len(gone), type=pa.timestamp("s")),
        "is_deleted": pa.array([1] * len(gone), type=pa.uint8()),
    }))


@activity.defn
@with_heartbeat
def reconcile_deleted_files(params: ReconcileDeletedFilesParams) -> ReconcileDeletedFilesResult:
    """Tombstone the paths a completed scan did not find, and de-index their content.

    **A scan is authoritative for the paths under its root.** Every path it saw was either
    ingested or touched, so every live top-level row older than the scan's start is a file
    that is no longer there. Comparing timestamps rather than re-walking the tree is what
    makes deletion detectable without a second traversal.

    Only `container_hash = ''` rows are considered. An archive or email member is not a
    path on disk; it exists because its container does, and it disappears when the
    container's own row is tombstoned.

    **The blob is kept.** Only the index rows go, so search stops answering with content
    that is no longer in the corpus, immediately. The blob, its extracted text and its
    derived work stay where they are — reclaiming those is a separate decision about
    storage, not about what a search should return, and a deletion that also destroyed
    them could not be undone.

    **De-indexing is driven by reachability, not by the tombstones.** A hash reachable
    from any live path is still in the corpus — the same content at two paths losing one
    of them must not vanish from search — and a hash no live path reaches is stale
    whatever made it so. That covers the edited file as well as the deleted one: an edit
    tombstones no path, it replaces the path's row with a new hash, so a sweep driven by
    the tombstones alone leaves the previous version of every edited document searchable.
    """
    from datetime import datetime, timezone

    from database.manticore import get_manticore_client, list_shard_tables, vfs_table_name

    cutoff = datetime.fromtimestamp(params.scan_started_at, timezone.utc).replace(tzinfo=None)
    with get_collection_client(params.collectionname) as client:
        gone = client.query_arrow("""
            SELECT path, hash, file_size_bytes, mtime_source,
                   toUnixTimestamp(mtime) AS mtime
            FROM vfs_files FINAL
            WHERE collection_dataset = {cd:String}
            AND container_hash = ''
            AND is_deleted = 0
            AND updated_at < {cutoff:DateTime}
        """, {"cd": params.collection_dataset, "cutoff": cutoff}).to_pylist()

        now = _now_naive_utc()
        if gone:
            _tombstone_paths(client, params.collection_dataset, gone, now)

        # **Everything indexed that no live path reaches**, which is a wider question
        # than "what did this scan stop finding". A deleted file leaves an orphaned
        # hash; so does an EDITED one, whose path now carries a new hash while the old
        # one is still in the shard tables — and an edit tombstones no path at all, so a
        # sweep driven by the tombstones alone leaves the previous version of every
        # edited document searchable for ever.
        #
        # `index_state` is the list of what has been indexed, so the difference between
        # it and the live paths is exactly the set to remove. Newly ingested files are
        # not in it yet — this runs at the end of the walk, before P2-P6 index anything
        # — so nothing in flight is caught by it.
        orphaned = [row[0] for row in client.query("""
            SELECT DISTINCT file_hash FROM index_state
            WHERE collection_dataset = {cd:String}
            AND file_hash NOT IN (
                SELECT DISTINCT hash FROM vfs_files FINAL
                WHERE collection_dataset = {cd:String} AND is_deleted = 0
            )
        """, {"cd": params.collection_dataset}).result_rows]

        if orphaned:
            client.command(
                "DELETE FROM index_state WHERE collection_dataset = {cd:String} "
                "AND file_hash IN {hashes:Array(String)}",
                parameters={"cd": params.collection_dataset, "hashes": orphaned},
            )

    deindexed = 0
    if orphaned:
        # The shard tables and the VFS tree, which are the tables keyed by file_hash. The
        # facet-term index is not: it holds one row per term, and a term stops being
        # searchable when its own reconciliation pass finds it gone from ClickHouse.
        tables = list_shard_tables(params.collectionname) + [vfs_table_name(params.collectionname)]
        with get_manticore_client() as cnx:
            cursor = cnx.cursor()
            for table in tables:
                for chunk_start in range(0, len(orphaned), DEINDEX_HASH_BATCH):
                    chunk = orphaned[chunk_start:chunk_start + DEINDEX_HASH_BATCH]
                    placeholders = ",".join(["%s"] * len(chunk))
                    # Identifiers come from list_collection_tables (regex-validated);
                    # only the values are bound.
                    cursor.execute(
                        f"DELETE FROM {table} WHERE collection_dataset = %s "
                        f"AND file_hash IN ({placeholders})",
                        (params.collection_dataset, *chunk),
                    )
            cnx.commit()
        deindexed = len(orphaned)

    log.info(
        "[P0] %s: %d paths gone, %d documents de-indexed",
        params.collection_dataset, len(gone), deindexed,
    )
    return ReconcileDeletedFilesResult(len(gone), deindexed)
