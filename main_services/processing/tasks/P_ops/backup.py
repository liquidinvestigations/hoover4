"""The collection backup format, and the activities that write one.

One directory per backup under the configured root, holding one artifact set per store
and a manifest naming everything in it:

    <root>/<destination>/
      manifest.json                      what is here, how big it is, and what it checks against
      garage/vol-000.tar ...             the collection's objects, uncompressed
      garage/objects.json.gz             key -> (volume, offset, size, etag)
      clickhouse/clickhouse-<op_id>.tar  BACKUP DATABASE, uncompressed
      manticore/<table>.tar.zst          one artifact per shard table, zstd

**Every format choice below is measured rather than aesthetic.**

* **The ClickHouse artifact is an uncompressed tar.** ClickHouse offers exactly two
  single-file shapes, uncompressed `.tar` and deflate `.zip`; there is no uncompressed
  zip and no zstd tar. A zip is the wrong one: its part files are already compressed
  internally, so deflating them again bought 1.38x for twenty percent more time, and a
  zip written here could not be written uncompressed at all.
* **The object payload is not compressed.** The blobs are already-compressed documents
  behind a write path that tops out around 27 MB/s, so re-compressing spends processor
  time on the wrong side of the bottleneck. Its key manifest *is* compressed, and that
  cost is negligible: a million entries is 109 MB raw and 8.3 MB gzipped.
* **Manticore artifacts are compressed**, because a Manticore table is a text index and
  compresses ~13x.
* **Order is object store, then ClickHouse, then Manticore.** Nothing gives cross-store
  consistency, so the order decides what the residue of a backup taken during ingestion
  looks like: an orphaned blob rather than a row pointing at a blob that was never
  copied.

**A backup copies bytes; it never links.** A hard link from a store mount to the backup
mount is refused even when both live on one filesystem, so no path here tries.

**The staging directory is what makes a failed export harmless.** Everything is written
into `<destination>.partial-<op_id>/` and renamed onto `<destination>/` only once the
manifest is complete. A failed, killed or cancelled export therefore leaves a directory
whose name says it is incomplete and which blocks no later attempt, including the
ClickHouse `.lock` file a failed `BACKUP` leaves behind, which is scoped to that
directory and to that operation id.
"""

import gzip
import hashlib
import json
import logging
import os
import re
import shutil
import tarfile
import time

from temporalio import activity

from ..heartbeat import with_heartbeat
from .params import ExportParams, ExportStoreResult

log = logging.getLogger(__name__)

#: Root of every backup directory, inside the operations container.
BACKUP_ROOT = os.environ.get("HOOVER4_BACKUP_ROOT", "/backups")

#: Read bytes per second ClickHouse may spend on a backup. 0 leaves it unthrottled.
#: The only throttle that does anything: `backup_threads` is an obsolete setting.
BACKUP_BANDWIDTH = int(os.environ.get("HOOVER4_BACKUP_BANDWIDTH_BYTES", "0") or 0)

#: Where the Manticore data directory is mounted here, and where the daemon sees it.
#: `FREEZE` answers with the daemon's own absolute paths, so one is translated into the
#: other rather than either being guessed from a table name.
MANTICORE_DATA_ROOT = "/stores/manticore"
MANTICORE_DAEMON_DATA_ROOT = "/var/lib/manticore"

#: How large one object volume grows before the next one is opened. Large enough that a
#: corpus does not become a directory of thousands of tars, small enough that a single
#: unreadable volume does not cost the whole object store. Reads
#: `HOOVER4_BACKUP_OBJECT_VOLUME_BYTES`, so a real export can prove the roll across
#: several volumes without changing the deployed default.
OBJECT_VOLUME_BYTES = int(os.environ.get("HOOVER4_BACKUP_OBJECT_VOLUME_BYTES", "")
                          or 8 * 1024 * 1024 * 1024)

#: How often a running ClickHouse backup is asked how far it has got.
CLICKHOUSE_POLL_SECONDS = 5

#: How often a phase's byte counters reach the operation row.
#:
#: Throttled rather than written per object, and the difference is not cosmetic: a row
#: update is a read and an insert against the same ClickHouse the backup is reading, and
#: a corpus of a million objects would otherwise spend more time reporting progress than
#: copying bytes.
PROGRESS_WRITE_SECONDS = 5

#: What a destination subdirectory may be called. **A caller names a subdirectory, never
#: an absolute path**, so a path that is not mounted cannot be requested and no traversal
#: out of the root is expressible.
_DESTINATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

#: The manifest's own version. A restore reads this before anything else and refuses a
#: number it does not know, rather than misreading a later layout as this one.
FORMAT = "hoover4-collection-backup"
FORMAT_VERSION = 1


def validate_destination(destination: str) -> str:
    """Check a caller-supplied backup directory name, or raise saying why."""
    if not _DESTINATION_RE.match(destination or ""):
        raise ValueError(
            f"{destination!r} is not a usable backup directory name. It names one "
            f"subdirectory of the backup root: letters, digits, dot, dash and "
            f"underscore, starting with a letter or a digit, and never a path."
        )
    return destination


def staging_name(destination: str, op_id: str) -> str:
    """The directory a run writes into before its manifest is complete."""
    return f"{destination}.partial-{op_id}"


class _HashingWriter:
    """A write-only file wrapper that sha256s and counts what passes through it.

    The checksum costs one pass over bytes that are being written anyway, so an artifact
    this process produces carries one for free. An artifact ClickHouse produces does not
    go through here and is recorded by size alone.
    """

    def __init__(self, fileobj):
        self._file = fileobj
        self._digest = hashlib.sha256()
        self.bytes_written = 0

    def write(self, data) -> int:
        self._digest.update(data)
        self.bytes_written += len(data)
        return self._file.write(data)

    def flush(self) -> None:
        self._file.flush()

    def tell(self) -> int:
        return self.bytes_written

    @property
    def hexdigest(self) -> str:
        return self._digest.hexdigest()


class _Phase:
    """One store's byte counters, on the operation row, named and throttled.

    **The fraction is per phase, and the phase is named on the row.** Each store knows
    how many bytes it is going to move before it moves them (the object listing, the
    ClickHouse part set, the frozen file list), but no store knows the other two's
    totals, so a single denominator across all three would only exist once the backup was
    over. A bar that restarts at each named phase reports what is actually known, and the
    per-store sizes accumulate in `detail` as each one lands.
    """

    def __init__(self, op_id: str, name: str):
        from database.operations import merge_detail

        self.op_id = op_id
        self.name = name
        self.started = time.time()
        self._last_write = 0.0
        merge_detail(op_id, phase=name)

    def report(self, done: int, total: int, force: bool = False) -> None:
        from database.operations import update_operation

        now = time.time()
        if not force and now - self._last_write < PROGRESS_WRITE_SECONDS:
            return
        self._last_write = now
        eta = 0
        if done and total > done:
            eta = int((now - self.started) / done * (total - done))
        update_operation(self.op_id, progress_done=done, progress_total=total,
                         eta_seconds=eta)

    def finish(self, result: "ExportStoreResult") -> "ExportStoreResult":
        """Record what this store produced onto the row, beside the other stores'.

        Read-modify-write over the whole `stores` map rather than a merge of one key,
        because `merge_detail` replaces the key it is given and would drop whichever
        stores had already finished.
        """
        from database.operations import get_operation, merge_detail

        result.seconds = round(time.time() - self.started, 3)
        row = get_operation(self.op_id) or {}
        try:
            detail = json.loads(row.get("detail") or "{}")
        except ValueError:
            detail = {}
        stores = detail.get("stores") if isinstance(detail.get("stores"), dict) else {}
        stores[result.store] = {
            "bytes_written": result.bytes_written,
            "seconds": result.seconds,
            **result.detail,
        }
        merge_detail(self.op_id, stores=stores)
        return result


def _configuration_rows(collectionname: str) -> dict:
    """The collection's own rows, which are what make a restore *configured*.

    Small, and not recoverable from any store artifact: the collection, who may read it,
    its datasets and their settings, and the server settings a deployment shares. Without
    them a restore produces a collection that exists and that nobody is allowed to open.
    """
    from database.clickhouse import get_collection_client, get_global_client

    def rows(client, sql, parameters=None) -> list[dict]:
        result = client.query(sql, parameters=parameters or {})
        names = list(result.column_names)
        return [dict(zip(names, row)) for row in result.result_rows]

    with get_global_client() as client:
        config = {
            "collections": rows(
                client, "SELECT * FROM collections FINAL "
                        "WHERE collectionname = {name:String}",
                {"name": collectionname}),
            "collection_group_permissions": rows(
                client, "SELECT * FROM collection_group_permissions FINAL "
                        "WHERE collectionname = {name:String}",
                {"name": collectionname}),
            "dataset": rows(
                client, "SELECT * FROM dataset FINAL "
                        "WHERE collectionname = {name:String}",
                {"name": collectionname}),
            # Keyed by dataset rather than by collection, so it is selected through the
            # registry: a `collectionname` column that this table does not have would
            # fail the whole manifest at the very end of a finished backup.
            "dataset_settings": rows(
                client, "SELECT * FROM dataset_settings FINAL WHERE collection_dataset "
                        "IN (SELECT collection_dataset FROM dataset FINAL "
                        "WHERE collectionname = {name:String})",
                {"name": collectionname}),
            "server_settings": rows(client, "SELECT * FROM server_settings FINAL"),
            "schema_version_global": rows(
                client, "SELECT max(version) AS version FROM schema_versions"),
        }
    with get_collection_client(collectionname) as client:
        config["schema_version_collection"] = rows(
            client, "SELECT max(version) AS version FROM schema_versions")
    return json.loads(json.dumps(config, default=str))


@activity.defn
@with_heartbeat
def begin_export(params: ExportParams) -> str:
    """Claim the backup's name and create the staging directory. Returns its path.

    The final directory is checked here rather than at the end: an export that would have
    to be thrown away because the name is taken should cost nothing, and a name claimed
    by a directory nobody wrote is exactly the failure this staging scheme removes.

    The staging tree is created world-writable because ClickHouse writes one of its
    subdirectories itself, as its own user, over a volume this container also holds.
    """
    destination = validate_destination(params.destination)
    final = os.path.join(BACKUP_ROOT, destination)
    if os.path.exists(final):
        raise ValueError(
            f"{destination} already exists under the backup root. Name another "
            f"destination, or remove that directory first."
        )
    staging = os.path.join(BACKUP_ROOT, staging_name(destination, params.op_id))
    if os.path.exists(staging):
        shutil.rmtree(staging)
    for name in ("", "garage", "clickhouse", "manticore"):
        path = os.path.join(staging, name) if name else staging
        os.makedirs(path, exist_ok=True)
        os.chmod(path, 0o777)
    log.info("[P_ops] export %s staging in %s", params.op_id, staging)
    return staging


@activity.defn
@with_heartbeat
def export_object_store(params: ExportParams) -> ExportStoreResult:
    """Copy a collection's bucket into object volumes with a compressed key manifest.

    **Enumerated first, then copied**, which is what gives this phase a real denominator:
    the listing knows the object count and total size before a byte is written. It is
    also the phase's one consistency caveat. An object written after the listing is not
    in the backup, and Garage offers nothing stronger over S3.

    Volumes are plain tars in PAX format, because an object key is longer and stranger
    than the original tar header allows and a silently truncated key is a blob that can
    never be found again.
    """
    from database.s3 import collection_bucket, get_s3_client

    phase = _Phase(params.op_id, "object store")
    client = get_s3_client()
    bucket = collection_bucket(params.collectionname)
    listing = [(obj.object_name, int(obj.size or 0), obj.etag or "")
               for obj in client.list_objects(bucket, recursive=True)]
    total_bytes = sum(size for _, size, _ in listing)
    phase.report(0, total_bytes, force=True)

    garage_dir = os.path.join(params.directory, "garage")
    entries: dict[str, list] = {}
    volumes: list[dict] = []
    done = 0
    volume_index = -1
    tar = writer = handle = None

    def close_volume():
        nonlocal tar, writer, handle
        if tar is None:
            return
        tar.close()
        handle.close()
        volumes[-1]["bytes"] = writer.bytes_written
        volumes[-1]["sha256"] = writer.hexdigest
        tar = writer = handle = None

    try:
        for key, size, etag in listing:
            if tar is None or writer.bytes_written >= OBJECT_VOLUME_BYTES:
                close_volume()
                volume_index += 1
                name = f"vol-{volume_index:03d}.tar"
                handle = open(os.path.join(garage_dir, name), "wb")
                writer = _HashingWriter(handle)
                tar = tarfile.open(fileobj=writer, mode="w|",
                                   format=tarfile.PAX_FORMAT)
                volumes.append({"path": f"garage/{name}", "bytes": 0, "sha256": ""})
            info = tarfile.TarInfo(name=key)
            info.size = size
            response = client.get_object(bucket, key)
            try:
                tar.addfile(info, response)
            finally:
                response.close()
                response.release_conn()
            entries[key] = [volume_index, info.offset_data, size, etag]
            done += size
            phase.report(done, total_bytes)
    finally:
        close_volume()
    phase.report(done, total_bytes, force=True)

    manifest = os.path.join(garage_dir, "objects.json.gz")
    with gzip.open(manifest, "wt", encoding="utf-8", compresslevel=6) as out:
        json.dump(entries, out)

    return phase.finish(ExportStoreResult(
        store="garage",
        bytes_written=sum(v["bytes"] for v in volumes) + os.path.getsize(manifest),
        detail={
            "bucket": bucket,
            "objects": len(listing),
            "source_bytes": total_bytes,
            "volumes": volumes,
            "key_manifest": "garage/objects.json.gz",
            "key_manifest_bytes": os.path.getsize(manifest),
        },
    ))


@activity.defn
@with_heartbeat
def export_clickhouse(params: ExportParams) -> ExportStoreResult:
    """Run `BACKUP DATABASE` into the backup directory and follow it to the end.

    **ClickHouse writes the artifact itself, into this very directory**, because the
    backup root is mounted onto its own `backups/` path as well. Nothing is copied
    afterwards, and the alternative (letting it write inside its data volume and copying
    the tar out) would both double the space and strand the original, since this
    container holds that volume read-only and has no way to delete anything in it.

    **`BACKUP` copies parts verbatim, and that is why it is the mechanism.** Most tables
    here are `ReplacingMergeTree` and most of those have no version column, so the
    surviving row for a duplicate key is decided by which part was inserted last. A
    `SELECT`-based dump loses part identity and can restore a *different* row than the
    source had, silently. Progress is ClickHouse's own byte counter, polled: the only
    honest fraction any of the three stores publishes about work in flight.
    """
    from database.clickhouse import collection_db_name, get_collection_client

    phase = _Phase(params.op_id, "clickhouse")
    destination = validate_destination(params.destination)
    relative = (f"{staging_name(destination, params.op_id)}/clickhouse/"
                f"clickhouse-{params.op_id}.tar")
    database = collection_db_name(params.collectionname)
    settings = [f"id='{params.op_id}'", "async=1"]
    if BACKUP_BANDWIDTH:
        settings.append(f"max_backup_bandwidth={BACKUP_BANDWIDTH}")

    status = "CREATING_BACKUP"
    error = ""
    numbers: dict = {}
    with get_collection_client(params.collectionname) as client:
        client.query(f"BACKUP DATABASE `{database}` TO File('{relative}') "
                     f"SETTINGS {', '.join(settings)}")
        while status in ("CREATING_BACKUP", ""):
            time.sleep(CLICKHOUSE_POLL_SECONDS)
            rows = client.query(
                "SELECT status, error, num_files, total_size, uncompressed_size, "
                "compressed_size, files_read, bytes_read FROM system.backups "
                "WHERE id = {id:String}", parameters={"id": params.op_id},
            ).result_rows
            if not rows:
                # The row appears as the backup is registered; an empty answer this
                # early is "not yet", not "gone".
                continue
            (status, error, num_files, total_size, uncompressed, compressed,
             files_read, bytes_read) = rows[0]
            numbers = {
                "num_files": int(num_files), "total_size": int(total_size),
                "uncompressed_size": int(uncompressed),
                "compressed_size": int(compressed),
            }
            phase.report(int(bytes_read), max(int(total_size), int(bytes_read)))

    if status != "BACKUP_CREATED":
        raise RuntimeError(f"ClickHouse backup of {database} ended {status}: {error}")

    artifact = os.path.join(params.directory, "clickhouse",
                            f"clickhouse-{params.op_id}.tar")
    size = os.path.getsize(artifact)
    phase.report(size, size, force=True)
    return phase.finish(ExportStoreResult(
        store="clickhouse",
        bytes_written=size,
        detail={
            "database": database,
            "artifact": f"clickhouse/clickhouse-{params.op_id}.tar",
            "bytes": size,
            # No sha256: the tar carries ClickHouse's own per-file checksums inside it,
            # so an outer digest would cost a second full read of the largest artifact in
            # the backup and guarantee nothing the inner ones do not.
            "checksums": "internal to the ClickHouse archive",
            **numbers,
        },
    ))


@activity.defn
@with_heartbeat
def export_manticore(params: ExportParams) -> ExportStoreResult:
    """Freeze each of the collection's tables in turn and copy it out compressed.

    `FREEZE` is what makes this safe against a live daemon: it flushes the table's RAM
    chunk, holds it read-only, and answers with the exact list of files that make up the
    table on disk. Copying a live table's directory without it captures an unflushed
    chunk mid-write. **Every freeze is released**, including on the way out of a failure,
    because a table left frozen accepts no more writes.

    The daemon reports its own absolute paths, which this container sees under a
    different, read-only mount; the prefix is translated rather than the path being
    rebuilt from the table name.

    One artifact per table, zstd, because a text index compresses about thirteen times.
    Progress is the frozen files' bytes: known before the copy starts, and real.
    """
    import zstandard

    from database.manticore import get_manticore_client, list_collection_tables

    phase = _Phase(params.op_id, "manticore")
    manticore_dir = os.path.join(params.directory, "manticore")
    tables = list_collection_tables(params.collectionname)
    artifacts: list[dict] = []
    done = 0
    total = 0

    with get_manticore_client() as cnx:
        cursor = cnx.cursor()
        # Every table's size is known before any of them is copied, so the phase has one
        # denominator rather than one per table. A freeze is taken and released per
        # table, so this pass reads sizes from the mount instead of freezing them all.
        for table in tables:
            directory = os.path.join(MANTICORE_DATA_ROOT, table)
            if not os.path.isdir(directory):
                continue
            for entry in os.scandir(directory):
                if entry.is_file():
                    total += entry.stat().st_size
        phase.report(0, total, force=True)

        for table in tables:
            cursor.execute(f"FREEZE {table}")
            files = [row[0] for row in cursor.fetchall()]
            try:
                path = os.path.join(manticore_dir, f"{table}.tar.zst")
                raw = 0
                with open(path, "wb") as handle:
                    writer = _HashingWriter(handle)
                    compressor = zstandard.ZstdCompressor(level=3)
                    with compressor.stream_writer(writer, closefd=False) as stream:
                        with tarfile.open(fileobj=stream, mode="w|",
                                          format=tarfile.PAX_FORMAT) as tar:
                            for source in files:
                                local = source.replace(MANTICORE_DAEMON_DATA_ROOT,
                                                       MANTICORE_DATA_ROOT, 1)
                                size = os.path.getsize(local)
                                tar.add(local, arcname=os.path.basename(local))
                                raw += size
                                done += size
                                phase.report(done, total)
            finally:
                cursor.execute(f"UNFREEZE {table}")
            artifacts.append({
                "table": table,
                "path": f"manticore/{table}.tar.zst",
                "source_bytes": raw,
                "bytes": writer.bytes_written,
                "sha256": writer.hexdigest,
            })

    phase.report(done, total, force=True)
    return phase.finish(ExportStoreResult(
        store="manticore",
        bytes_written=sum(a["bytes"] for a in artifacts),
        detail={"tables": artifacts, "source_bytes": total},
    ))


@activity.defn
@with_heartbeat
def finish_export(params: ExportParams) -> str:
    """Write the manifest, then rename the staging directory onto its final name.

    The rename is the commit. Until it happens the backup is a `.partial-<op_id>`
    directory that no later export has to work around; after it, the directory holds a
    manifest describing everything beside it, which is what a restore reads first.
    """
    from database.operations import get_operation

    destination = validate_destination(params.destination)
    final = os.path.join(BACKUP_ROOT, destination)
    if os.path.exists(final):
        raise ValueError(
            f"{destination} appeared under the backup root while this export ran. "
            f"The staging directory is at {params.directory} and holds the backup."
        )
    row = get_operation(params.op_id) or {}
    detail = json.loads(row.get("detail") or "{}")
    stores = detail.get("stores", {})
    manifest = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "collectionname": params.collectionname,
        "op_id": params.op_id,
        "destination": destination,
        "bytes": sum(int(s.get("bytes_written", 0)) for s in stores.values()),
        "stores": stores,
        "configuration": _configuration_rows(params.collectionname),
    }
    with open(os.path.join(params.directory, "manifest.json"), "w",
              encoding="utf-8") as out:
        json.dump(manifest, out, indent=2, sort_keys=True, default=str)
    os.rename(params.directory, final)
    log.info("[P_ops] export %s committed to %s", params.op_id, final)
    return final
