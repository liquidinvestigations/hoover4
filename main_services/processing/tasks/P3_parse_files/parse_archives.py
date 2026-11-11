"""Archive extraction activities, and the archive stage activity of the group workflow."""

from temporalio import activity
from typing import Dict, Any, List
from dataclasses import dataclass
import os
import json
import sys
import time
import signal

from tasks import sandbox
import logging
from tasks.heartbeat import heartbeat_pump, with_heartbeat, worker_is_stopping
from tasks.P3_parse_files.batch_runner import BatchFile, BatchResult, StageBatchParams, run_batch

log = logging.getLogger(__name__)

#: The error type of a file that 7-Zip cannot open as any archive.
ARCHIVE_NOT_OPENED = "ArchiveNotOpened"

@dataclass
class ExtractArchiveParams:
    collectionname: str
    collection_dataset: str
    archive_hash: str
    archive_types: List[str]
    archive_path: str


@activity.defn
@with_heartbeat
def extract_archive_to_temp(params: ExtractArchiveParams) -> Dict[str, Any]:
    """Activity that extracts an archive to a temp directory using 7z."""
    import os
    import shutil
    import subprocess
    from tasks.P3_parse_files.result_samples import short_name
    from tasks.P3_parse_files.temp_dirs import make_attempt_dir
    from tasks.P3_parse_files.mail_containers import mail_format
    out_dir = make_attempt_dir(params.collection_dataset, "extract", params.archive_hash)

    kind = mail_format(params.archive_path, params.archive_types)
    if kind:
        # Retries must not scan members left by an earlier interrupted attempt.
        shutil.rmtree(out_dir, ignore_errors=True)
        os.makedirs(out_dir)
        cmd = [sys.executable, "-m", "tasks.P3_parse_files.mail_containers",
               params.archive_path, out_dir, kind]
        child = sandbox.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 stdin=subprocess.DEVNULL, start_new_session=True)
        started = time.monotonic()
        try:
            with heartbeat_pump(f"mail {params.archive_hash[:8]}"):
                while True:
                    try:
                        stdout, stderr = child.communicate(timeout=1)
                        break
                    except subprocess.TimeoutExpired:
                        if worker_is_stopping():
                            raise RuntimeError("mail extraction stopped with the worker")
                        if time.monotonic() - started >= 3600:
                            raise RuntimeError("mail extraction exceeded 3600 seconds")
        except BaseException:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.communicate()
            shutil.rmtree(out_dir, ignore_errors=True)
            raise
        entry_count = count_member_files(out_dir)
        if child.returncode:
            if not entry_count:
                shutil.rmtree(out_dir, ignore_errors=True)
                raise RuntimeError(f"{kind} extraction failed: {stderr[:300]!r}")
            return {"out_dir": out_dir, "entry_count": entry_count,
                    "partial_errors": [short_name(f"{kind} reader exited {child.returncode}: {stderr[:300]!r}")],
                    "partial_error_count": 1}
        try:
            details = json.loads(stdout)
        except (UnicodeDecodeError, ValueError) as exc:
            shutil.rmtree(out_dir, ignore_errors=True)
            raise RuntimeError(f"{kind} reader returned no result") from exc
        if not entry_count:
            shutil.rmtree(out_dir, ignore_errors=True)
            if details.get("partial_errors"):
                from temporalio.exceptions import ApplicationError
                raise ApplicationError(
                    f"{kind} reader found no member: {short_name(details['partial_errors'][0])}",
                    type=ARCHIVE_NOT_OPENED,
                    non_retryable=True,
                )
        return {"out_dir": out_dir, "entry_count": entry_count,
                "partial_errors": [short_name(error) for error in details.get("partial_errors", [])[:20]],
                "partial_error_count": int(details.get("partial_error_count", len(details.get("partial_errors", []))))}

    log.info("[P3] Extracting archive to %s", out_dir)
    cmd = ["7z", "x", "-y", f"-o{out_dir}", params.archive_path]
    # stdin=DEVNULL: 7z prompts interactively for missing volumes of split
    # archives and would block the worker thread forever waiting on stdin.
    # timeout: belt-and-braces so a wedged extractor fails instead of hanging.
    # KEEP THIS TIMEOUT. The heartbeat pump below proves the pump THREAD is
    # alive, which is not the same as proving 7z is making progress -- on a
    # corrupt archive the pump would keep heartbeating forever. Removing a
    # subprocess timeout because "we heartbeat now" is the one way this change
    # makes reliability worse.
    try:
        with heartbeat_pump(f"7z {params.archive_hash[:8]}"):
            res = sandbox.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, timeout=3600)
    except subprocess.TimeoutExpired:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise RuntimeError(f"7z extraction timed out for {params.archive_path}")
    except BaseException:
        # Heartbeating is how Temporal DELIVERS cancellation to a sync activity,
        # so this path is reachable on cancellation, not only on error. Without the
        # cleanup, a retry finds a half-extracted directory from the previous
        # attempt and two 7z processes write to the same path.
        shutil.rmtree(out_dir, ignore_errors=True)
        raise
    if res.returncode != 0:
        shutil.rmtree(out_dir, ignore_errors=True)
        # 7z's own, unambiguous statement that the bytes it read are not an archive of
        # any kind it recognises. The routing that calls into this module fires whenever
        # any one detector's guess includes "archive", even when the other detectors
        # disagree, so this is the expected shape for a document a weaker detector
        # mistyped: retrying does not change what 7z reads.
        if b"Cannot open the file as archive" in (res.stderr or b""):
            from temporalio.exceptions import ApplicationError
            raise ApplicationError(
                f"7z extraction failed for {params.archive_path}: {res.stderr[:200]}\n{res.stdout[:200]}",
                type=ARCHIVE_NOT_OPENED,
                non_retryable=True,
            )
        raise RuntimeError(f"7z extraction failed for {params.archive_path}: {res.stderr[:200]}\n{res.stdout[:200]}")

    # Counted here so the group gives the member scan no folder for an archive that
    # holds nothing. 7z exits 0 on an empty archive, so a zero count is not an error.
    entry_count = sum(len(files) for _root, _dirs, files in os.walk(out_dir))
    if entry_count == 0:
        shutil.rmtree(out_dir, ignore_errors=True)
    return {"out_dir": out_dir, "entry_count": entry_count}


@dataclass
class RecordArchiveContainerParams:
    collectionname: str
    collection_dataset: str
    archive_hash: str
    archive_types: List[str]


@activity.defn
@with_heartbeat
def record_archive_container(params: RecordArchiveContainerParams) -> str:
    """Activity that inserts a single archive container row into ClickHouse."""
    from database.clickhouse import get_collection_client, insert_parser_arrow
    import pyarrow as pa
    log.info("[P3] Recording archive container for %s", params.archive_hash)
    with get_collection_client(params.collectionname) as client:
        tbl_arch = pa.table({
            "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
            "archive_hash": pa.array([params.archive_hash], type=pa.string()),
            # Store space-separated list of MIME types
            "archive_type": pa.array([" ".join([t for t in (params.archive_types or []) if t])], type=pa.string()),
        })
        insert_parser_arrow(client, "archives", tbl_arch)
    return params.archive_hash


@dataclass
class CleanupTempDirParams:
    out_dir: str


@activity.defn
@with_heartbeat
def cleanup_temp_dir(params: CleanupTempDirParams) -> str:
    """Activity that deletes a temporary directory recursively."""
    import shutil
    log.info("[P3] Cleaning up temp dir: %s", params.out_dir)
    if os.path.isdir(params.out_dir):
        shutil.rmtree(params.out_dir, ignore_errors=True)
    return params.out_dir




def count_member_files(out_dir: str) -> int:
    """The files under `out_dir`, at every level. A folder that does not exist has none.

    An extraction stage puts this count in its value, and the member scan sets the time
    limit of the folder from it.
    """
    if not out_dir:
        return 0
    return sum(len(files) for _root, _dirs, files in os.walk(out_dir))


def _split_error(error_type: str, message: str):
    from temporalio.exceptions import ApplicationError
    return ApplicationError(message, type=error_type, non_retryable=True)


def _incomplete_reason(stderr: bytes) -> bool:
    """Whether 7-Zip says that a volume is missing or that the set ends early."""
    text = (stderr or b"").decode("utf-8", "replace")
    return any(marker in text for marker in (
        "Missing volume", "Unexpected end of archive", "Unexpected end of data",
        "There are some data after the end of the payload data", "Cannot open the file as archive",
        "Can not open the file as archive", "is not archive"))


def split_extraction_seconds(set_size: int) -> int:
    """The 7-Zip time limit of a split set: the archive try budget of the whole set,
    less a margin, so the batch heartbeat outlives the subprocess."""
    from tasks.P3_parse_files.batch_runner import try_budget_seconds
    return max(60, try_budget_seconds("extract_archive_batch", set_size) - 30)


def extract_split_set(collectionname: str, volume_set, entry_hash: str) -> Dict[str, Any]:
    """Write every volume of `volume_set` under its own name, run 7-Zip on the entry
    volume, and remove the transfer files. Each attempt has a separate member folder.

    A missing or truncated volume raises `SplitArchiveIncomplete`.
    The member scan reconciles removed members after successful publication.
    """
    import shutil
    import subprocess

    from tasks.P2_execute_plan.activities import write_blob_files
    from tasks.P3_parse_files.split_volumes import (
        SPLIT_ARCHIVE_INCOMPLETE, has_archive_signature, safe_volume_name)
    from tasks.P3_parse_files.temp_dirs import make_attempt_dir

    out_dir = make_attempt_dir(volume_set.collection_dataset, "extract", entry_hash)
    volumes_dir = make_attempt_dir(volume_set.collection_dataset, "volumes", entry_hash)
    shutil.rmtree(out_dir, ignore_errors=True)
    shutil.rmtree(volumes_dir, ignore_errors=True)
    os.makedirs(out_dir)
    os.makedirs(volumes_dir)
    entry = volume_set.entry
    try:
        write_blob_files(collectionname, volume_set.collection_dataset, [
            {"item_hash": file_hash, "file_size_bytes": size, "s3_url": s3_path,
             "path": os.path.join(volumes_dir, safe_volume_name(name))}
            for _, name, file_hash, size, s3_path in volume_set.volumes],
            context=f"{volume_set.collection_dataset} split set {volume_set.folder}/{entry[1]}")
        entry_path = os.path.join(volumes_dir, entry[1])
        with open(entry_path, "rb") as handle:
            signature = has_archive_signature(handle.read(16))
        cmd = ["7z", "x", "-y", f"-o{out_dir}", entry_path]
        try:
            # stdin=DEVNULL: 7-Zip asks for a missing volume on stdin otherwise.
            with heartbeat_pump(f"7z set {entry_hash[:8]}"):
                res = sandbox.run(cmd, capture_output=True, stdin=subprocess.DEVNULL,
                                     timeout=split_extraction_seconds(volume_set.size))
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"7z extraction timed out for the split set of {entry[1]}")
        if res.returncode != 0:
            if not signature:
                from tasks.task_timing import SkippedOutcome
                shutil.rmtree(out_dir, ignore_errors=True)
                return {"skipped": SkippedOutcome({"status": "skipped",
                                                   "reason": "numbered files that are not a split archive"})}
            if _incomplete_reason(res.stderr) or _incomplete_reason(res.stdout):
                missing = volume_set.next_name() or "a later volume"
                raise _split_error(SPLIT_ARCHIVE_INCOMPLETE,
                                   f"Split archive {volume_set.folder}/{entry[1]} is incomplete: "
                                   f"7-Zip reports a missing or truncated volume after {volume_set.names[-1]}. "
                                   f"Expected next volume: {missing}. {res.stderr[:200]!r}")
            raise RuntimeError(f"7z extraction failed for the split set of {entry[1]}: "
                               f"{res.stderr[:200]}\n{res.stdout[:200]}")
    except BaseException:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(volumes_dir, ignore_errors=True)
    entry_count = count_member_files(out_dir)
    return {"out_dir": out_dir, "entry_count": entry_count, "container_hash": entry_hash,
            "volumes": volume_set.names, "reconcile_members": True,
            "archive_manifest_identity": volume_set.manifest_identity()}


def _tombstone_absent_members(collectionname: str, collection_dataset: str, container_hash: str,
                              out_dir: str) -> int:
    """Tombstone the stored members of `container_hash` that the new extraction lacks."""
    from datetime import datetime, timezone

    from database.clickhouse import get_collection_client
    from tasks.P0_scan_disk.activities import _tombstone_paths

    present = set()
    for root, _dirs, files in os.walk(out_dir):
        for name in files:
            present.add("/" + os.path.relpath(os.path.join(root, name), out_dir).replace(os.sep, "/"))
    with get_collection_client(collectionname) as client:
        rows = client.query(
            "SELECT container_hash, path, hash, file_size_bytes, toUnixTimestamp(mtime), mtime_source "
            "FROM vfs_files FINAL WHERE collection_dataset = {cd:String} AND container_hash = {ch:String} "
            "", parameters={"cd": collection_dataset, "ch": container_hash}).result_rows
        gone = [{"container_hash": r[0], "path": r[1], "hash": r[2], "file_size_bytes": r[3],
                 "mtime": r[4], "mtime_source": r[5]} for r in rows if r[1] not in present]
        if gone:
            _tombstone_paths(client, collection_dataset, gone,
                             datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0), durable=True)
            import hashlib
            from database.clickhouse import insert_durable
            identity = hashlib.sha256(out_dir.encode()).hexdigest()
            insert_durable(client, "processing_output_receipts",
                [[collection_dataset, file_hash, "archive_removed_root", identity, "archive-cleanup-1", "pending", ""]
                 for file_hash in sorted({row["hash"] for row in gone})],
                column_names=["collection_dataset", "file_hash", "output_kind", "output_identity", "fingerprint", "stage", "op_id"])
    return len(gone)


def _reconcile_removed_descendants(client, collection_dataset: str, removed: set[str],
                                   candidate_hashes: set[str] | None = None) -> int:
    """Tombstone removed descendants while preserving all reachable occurrences."""
    from datetime import datetime, timezone
    from tasks.P0_scan_disk.activities import _tombstone_paths

    candidates = {}
    pending, visited = set(removed), set()
    while pending:
        batch = sorted(pending)[:500]
        pending.difference_update(batch)
        visited.update(batch)
        rows = client.query(
            "SELECT container_hash, path, hash, file_size_bytes, toUnixTimestamp(mtime), mtime_source "
            "FROM vfs_files FINAL WHERE collection_dataset = {cd:String} "
            "AND container_hash IN {parents:Array(String)}",
            parameters={"cd": collection_dataset, "parents": batch}).result_rows
        for row in rows:
            candidates[row[0], row[1]] = row
            if row[2] not in visited:
                pending.add(row[2])
    if candidate_hashes is not None:
        candidate_hashes.update(row[2] for row in candidates.values())
    if not candidates:
        return 0
    reachable, pending = set(), {""}
    while pending:
        batch = sorted(pending)[:500]
        pending.difference_update(batch)
        rows = client.query(
            "SELECT DISTINCT hash FROM vfs_files FINAL WHERE collection_dataset = {cd:String} "
            "AND container_hash IN {parents:Array(String)} AND is_deleted = 0",
            parameters={"cd": collection_dataset, "parents": batch}).result_rows
        for (file_hash,) in rows:
            if file_hash not in reachable:
                reachable.add(file_hash)
                pending.add(file_hash)
    gone = [{"container_hash": r[0], "path": r[1], "hash": r[2], "file_size_bytes": r[3],
             "mtime": r[4], "mtime_source": r[5]} for r in candidates.values() if r[0] not in reachable]
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    for start in range(0, len(gone), 500):
        _tombstone_paths(client, collection_dataset, gone[start:start + 500], now, durable=True)
    return len(gone)


def _remove_unreachable_output(client, collection_dataset: str, candidates: set[str]) -> None:
    """Remove dataset output only after all live occurrences of its content disappear."""
    tables = {row[0] for row in client.query("SHOW TABLES").result_rows}
    hashes = sorted(candidates)
    for start in range(0, len(hashes), 500):
        rows = client.query(
            "SELECT arrayJoin({hashes:Array(String)}) AS hash WHERE hash NOT IN ("
            "SELECT hash FROM vfs_files FINAL WHERE collection_dataset = {cd:String} AND is_deleted = 0)",
            parameters={"hashes": hashes[start:start + 500], "cd": collection_dataset}).result_rows
        missing = [row[0] for row in rows]
        if not missing:
            continue
        parameters = {"cd": collection_dataset, "hashes": missing}
        for table in ("text_content", "entity_hit", "nlp_processed", "regex_entity_hit", "regex_scanned",
                      "signal_hit", "signal_scanned", "signal_cluster", "text_chunks", "text_chunk_vectors",
                      "table_documents", "table_sheets", "table_columns",
                      "email_identity", "email_clusters"):
            if table not in tables:
                continue
            column = "hash" if table.startswith("table_") else "email_hash" if table.startswith("email_") else "file_hash"
            client.command(f"DELETE FROM {table} WHERE collection_dataset = {{cd:String}} "
                           f"AND {column} IN {{hashes:Array(String)}} SETTINGS mutations_sync = 2",
                           parameters=parameters)
        if "email_edges" in tables:
            client.command(
                "DELETE FROM email_edges WHERE (src_dataset = {cd:String} AND src_hash IN {hashes:Array(String)}) "
                "OR (dst_dataset = {cd:String} AND dst_hash IN {hashes:Array(String)}) SETTINGS mutations_sync = 2",
                parameters=parameters)


def split_step(collectionname: str, collection_dataset: str, file: BatchFile, batch_hashes: set,
               extracted: set):
    """The archive outcome of a file with a volume name. None means: extract as before.

    `batch_hashes` are the files of this stage batch, and `extracted` collects the entry
    hashes that this batch already extracted, so one set extracts once per batch.
    """
    from database.clickhouse import get_collection_client
    from tasks.P3_parse_files.split_volumes import (
        SPLIT_ARCHIVE_AMBIGUOUS, SPLIT_ARCHIVE_INCOMPLETE, resolve_volume_sets)
    from tasks.task_timing import SkippedOutcome

    with get_collection_client(collectionname) as client:
        sets = resolve_volume_sets(client, collection_dataset, file.item_hash)
    if not sets:
        return None
    # Resolve every occurrence of each entry before accepting any volume.
    entry_hashes = {volume_set.entry[2] for volume_set in sets if volume_set.entry is not None}
    with get_collection_client(collectionname) as client:
        for entry_hash in sorted(entry_hashes - {file.item_hash}):
            sets.extend(resolve_volume_sets(client, collection_dataset, entry_hash))
    complete = {}
    incomplete = []
    for volume_set in sets:
        if volume_set.entry is not None and not volume_set.missing():
            complete.setdefault(volume_set.key(), volume_set)
        else:
            incomplete.append(volume_set)
    for entry_hash in entry_hashes:
        alternatives = [s for s in complete.values() if s.entry[2] == entry_hash]
        if len(alternatives) > 1:
            folders = ", ".join(sorted(s.folder for s in alternatives))
            raise _split_error(SPLIT_ARCHIVE_AMBIGUOUS,
                               f"The first volume occurs in {len(alternatives)} folders with different later volumes "
                               f"({folders}). Its members cannot be stored under one container.")
    as_entry = [s for s in complete.values() if s.entry[2] == file.item_hash]
    if as_entry:
        value = extract_split_set(collectionname, as_entry[0], file.item_hash)
        extracted.add(file.item_hash)
        return value
    later = [s for s in complete.values() if s.entry[2] != file.item_hash]
    if later:
        volume_set = later[0]
        if volume_set.entry[2] in batch_hashes or volume_set.entry[2] in extracted:
            return SkippedOutcome({"status": "skipped", "reason": "volume of a split archive",
                                   "entry": volume_set.entry[1]})
        from temporalio.exceptions import ApplicationError
        try:
            value = extract_split_set(collectionname, volume_set, volume_set.entry[2])
        except ApplicationError as exc:
            if exc.type != SPLIT_ARCHIVE_INCOMPLETE:
                raise
            # The entry volume carries the error of an incomplete set.
            return SkippedOutcome({"status": "skipped", "reason": "volume of an incomplete split archive",
                                   "detail": str(exc)[:500]})
        extracted.add(volume_set.entry[2])
        return value
    volume_set = incomplete[0]
    missing = volume_set.missing()
    entry = volume_set.entry
    first_present = volume_set.volumes[0][2] == file.item_hash
    if (entry is not None and entry[2] == file.item_hash) or (entry is None and first_present):
        raise _split_error(SPLIT_ARCHIVE_INCOMPLETE,
                           f"Split archive {volume_set.folder}/{volume_set.stem} is incomplete. "
                           f"Missing volume count: {volume_set.missing_count()}. "
                           f"First missing volumes: {', '.join(missing) or 'unknown'}.")
    return SkippedOutcome({"status": "skipped", "reason": "volume of an incomplete split archive",
                           "missing": missing})


@activity.defn
@with_heartbeat
def extract_archive_batch(params: StageBatchParams) -> BatchResult:
    """Extract each archive of a group into its own temporary folder, then record it.

    The value of a file is the dictionary of `extract_archive_to_temp` with `member_count`
    added. A file whose extraction fails gets no archive row. A file with a volume name
    goes through `split_step` first (see `split_volumes`). Its members belong to the
    entry volume, which the value names as `container_hash`.
    """
    from temporalio.exceptions import ApplicationError
    from tasks.P3_parse_files.split_volumes import is_volume_name
    from tasks.task_timing import SkippedOutcome

    batch_hashes = {file.item_hash for file in params.files}
    extracted: set = set()

    def read(file: BatchFile) -> Dict[str, Any]:
        if is_volume_name(file.file_names) or any(n.lower().endswith((".rar", ".zip")) for n in file.file_names):
            outcome = split_step(params.collectionname, params.collection_dataset, file, batch_hashes, extracted)
            if isinstance(outcome, SkippedOutcome):
                return outcome
            if isinstance(outcome, dict) and "skipped" in outcome:
                return outcome["skipped"]
            if outcome is not None:
                record_archive_container(RecordArchiveContainerParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    archive_hash=outcome["container_hash"],
                    archive_types=list(file.mime_types),
                ))
                return {**outcome, "member_count": count_member_files(outcome.get("out_dir") or "")}
        value = extract_archive_to_temp(ExtractArchiveParams(
            collectionname=params.collectionname,
            collection_dataset=params.collection_dataset,
            archive_hash=file.item_hash,
            archive_types=list(file.mime_types),
            archive_path=file.file_path,
        ))
        record_archive_container(RecordArchiveContainerParams(
            collectionname=params.collectionname,
            collection_dataset=params.collection_dataset,
            archive_hash=file.item_hash,
            archive_types=list(file.mime_types),
        ))
        return {**value, "member_count": count_member_files(value.get("out_dir") or "")}

    def step(file: BatchFile) -> Dict[str, Any] | SkippedOutcome:
        try:
            return read(file)
        except ApplicationError as exc:
            if exc.type != ARCHIVE_NOT_OPENED:
                raise
            log.info("[P3] Archive %s does not open: %s", file.item_hash, exc)
            return SkippedOutcome({"out_dir": "", "entry_count": 0})

    return run_batch("extract_archive_batch", params.files, key=lambda f: f.item_hash,
                     size=lambda f: f.file_size_bytes, step=step,
                     task_name="extract_archive_to_temp")


#: The workflow patch that routes volume names to the archive stage and sizes its budget
#: by the resolved set.
SPLIT_VOLUME_PATCH = "split-volume-sets"


@activity.defn
@with_heartbeat
def split_set_sizes(params: StageBatchParams) -> Dict[str, int]:
    """The bytes of the largest resolved volume set of each file with a volume name.

    The group gives the archive stage these sizes, so the stage timeout, the try budget
    of the file and the 7-Zip time limit all follow the same set size.
    """
    from database.clickhouse import get_collection_client
    from tasks.P3_parse_files.split_volumes import resolve_volume_sets

    sizes: Dict[str, int] = {}
    with get_collection_client(params.collectionname) as client:
        for file in params.files:
            sets = resolve_volume_sets(client, params.collection_dataset, file.item_hash)
            if sets:
                sizes[file.item_hash] = max(s.size for s in sets)
    return sizes
