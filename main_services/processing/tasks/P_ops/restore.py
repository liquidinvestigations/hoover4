"""Restoring a collection from a backup directory, store by store.

The mirror of `backup.py`: it reads the manifest that file writes, and puts each store's
artifacts back through that store's own protocol rather than by copying files into a live
data directory.

Three rules decide everything here, and none of them is a preference:

* **Clean target only.** The collection must be absent, or present and empty, in all
  three stores. A restore into tables that already hold rows would insert a second copy
  of every row into version-less `ReplacingMergeTree` tables, where nothing afterwards
  can tell which copy is real. ClickHouse's `allow_non_empty_tables` is what would permit
  it and it is never set; the check is made before a byte is written, and the refusal
  names exactly what is in the way.
* **Same name only.** The collection name is baked into the database name, every
  `collection_dataset`, every Manticore table name, every object key and every stored
  path. Restoring under another name is a cross-store rewrite wearing a restore's
  clothes.
* **Order is object store, then ClickHouse, then Manticore**, the same as on the way out,
  so a restore that stops half way leaves blobs nothing points at rather than rows
  pointing at blobs that were never written.

**The configuration rows are restored last, and that ordering is the point.** They are
what makes the collection visible and usable — the collection itself, who may read it,
its datasets and their settings — so writing them at the end means a half-finished
restore is a collection nobody is offered rather than one that is offered and broken.

**A failed import leaves the target empty rather than half full**, in the sense that
matters: nothing is renamed into place, no configuration row is written, and re-running
the import over the residue is refused by the same clean-target check that guards the
first attempt. Clearing the residue is `drop_collection_database`, which is the same
command that prepares any other clean target.
"""

import json
import logging
import os
import shutil
import time

from temporalio import activity

from ..heartbeat import with_heartbeat
from .backup import (
    BACKUP_ROOT, CLICKHOUSE_POLL_SECONDS, FORMAT, FORMAT_VERSION,
    MANTICORE_DAEMON_DATA_ROOT, _Phase, validate_destination,
)
from .params import ExportStoreResult, ImportParams

log = logging.getLogger(__name__)

#: The Manticore data directory again, but read-write, and used for one thing only:
#: staging a table's files where the daemon can `IMPORT TABLE` them.
#:
#: It has to be this volume rather than a staging area of its own, because `IMPORT TABLE`
#: **moves** the files into the data directory and a move across filesystems is not a
#: rename. The read-only mount beside it stays: the export path reads through that one,
#: and nothing outside the two functions below writes through this one.
MANTICORE_RESTORE_ROOT = "/stores/manticore-restore"

#: Where a restore stages one table's files before handing them to the daemon.
#:
#: Inside the data directory but named for the operation, because the directory has to be
#: on the data directory's filesystem and must not be the destination — `IMPORT TABLE`
#: refuses a destination that already exists, and moves out of the staging directory it
#: is given.
#:
#: **No leading dot.** `IMPORT TABLE` does not take the absolute path it is handed
#: verbatim when the path contains a dot-prefixed component: it rebuilds one under the
#: table's own directory, and the error then names a file nothing ever wrote.
MANTICORE_STAGING_PREFIX = "restore-"


class _VerifyingReader:
    """A read-only file wrapper that checks an artifact's recorded sha256 as it streams.

    The manifest records a digest taken as each volume was written, so a restore can
    check the bytes it is about to trust without a second pass over them: the hash is
    computed from the same bytes that are being read anyway, and compared when the stream
    ends.
    """

    def __init__(self, fileobj, expected: str, name: str):
        import hashlib

        self._file = fileobj
        self._digest = hashlib.sha256()
        self._expected = expected
        self._name = name

    def read(self, size: int = -1) -> bytes:
        data = self._file.read(size)
        self._digest.update(data)
        return data

    def verify(self) -> None:
        if not self._expected:
            return
        actual = self._digest.hexdigest()
        if actual != self._expected:
            raise RuntimeError(
                f"{self._name} does not match the checksum in the manifest: expected "
                f"{self._expected}, read {actual}. The artifact is damaged; restore "
                f"from another backup."
            )


def read_manifest(directory: str) -> dict:
    """Load a backup's manifest, refusing a format this code does not know.

    Read before anything else and before any store is touched: a manifest from a later
    layout misread as this one would put the wrong bytes into the right-looking places.
    """
    path = os.path.join(directory, "manifest.json")
    if not os.path.isfile(path):
        raise ValueError(
            f"{directory} holds no manifest.json, so it is not a finished backup. A "
            f"directory whose name ends in .partial-<op_id> is an export that never "
            f"completed and cannot be restored."
        )
    with open(path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("format") != FORMAT or manifest.get("format_version") != FORMAT_VERSION:
        raise ValueError(
            f"{path} is {manifest.get('format')} version "
            f"{manifest.get('format_version')}, and this deployment reads {FORMAT} "
            f"version {FORMAT_VERSION}."
        )
    return manifest


#: How many of a store's occupied tables the refusal names one by one.
#:
#: A collection database has forty-odd tables and naming every populated one produces a
#: paragraph nobody reads and no interface can show. The count and the biggest few say
#: the same thing — the target is not empty, and here is the shape of what is in it.
OCCUPANCY_EXAMPLES = 3


def _largest(occupied: list[tuple[str, int]]) -> str:
    """The few fullest tables of a store, as one clause naming the rest by count."""
    ranked = sorted(occupied, key=lambda pair: pair[1], reverse=True)
    shown = ", ".join(f"{table} {rows}" for table, rows in ranked[:OCCUPANCY_EXAMPLES])
    rest = len(ranked) - OCCUPANCY_EXAMPLES
    return f"largest {shown}" + (f" and {rest} more" if rest > 0 else "")


def _occupancy(collectionname: str, backed_up_datasets: set[str]) -> list[str]:
    """What a restore into this collection would land on top of, store by store.

    Every store is asked, and all of the answers are collected rather than the first one
    returned, because the useful sentence is the whole of what is in the way rather than
    whichever store happened to be checked first.

    **A registered dataset is only in the way when the backup does not contain it.** A
    collection whose stores have been emptied still has its datasets registered — that is
    what dropping a collection database leaves behind, and restoring over it is the case
    this whole operation exists for. A dataset the backup has never heard of is different:
    restoring would leave it registered, offered, and pointing at nothing.
    """
    from database.clickhouse import (
        collection_db_name, get_dedicated_collection_client, get_global_client,
    )
    from database.manticore import get_manticore_client, list_collection_tables
    from database.s3 import collection_bucket, get_s3_client

    blockers: list[str] = []
    database = collection_db_name(collectionname)
    with get_global_client() as client:
        exists = client.query(
            "SELECT count() FROM system.databases WHERE name = {db:String}",
            parameters={"db": database},
        ).result_rows[0][0]
    if exists:
        occupied: list[tuple[str, int]] = []
        with get_dedicated_collection_client(collectionname) as client:
            for (table,) in client.query("SHOW TABLES").result_rows:
                rows = int(client.query(f"SELECT count() FROM `{table}`").result_rows[0][0])
                if rows:
                    occupied.append((table, rows))
        if occupied:
            blockers.append(f"ClickHouse database {database} holds "
                            f"{sum(r for _, r in occupied)} row(s) across "
                            f"{len(occupied)} table(s), " + _largest(occupied))

    occupied = []
    for table in list_collection_tables(collectionname):
        with get_manticore_client() as cnx:
            cursor = cnx.cursor()
            cursor.execute(f"SELECT count(*) FROM {table}")
            row = cursor.fetchone()
        if row and int(row[0]):
            occupied.append((table, int(row[0])))
    if occupied:
        blockers.append(f"Manticore holds {sum(r for _, r in occupied)} row(s) across "
                        f"{len(occupied)} table(s), " + _largest(occupied))

    bucket = collection_bucket(collectionname)
    client = get_s3_client()
    if client.bucket_exists(bucket):
        objects = sum(1 for _ in client.list_objects(bucket, recursive=True))
        if objects:
            blockers.append(f"object bucket {bucket} holds {objects} object(s)")

    with get_global_client() as client:
        registered = [row[0] for row in client.query(
            "SELECT collection_dataset FROM dataset FINAL WHERE "
            "collectionname = {name:String} AND is_deleted = 0",
            parameters={"name": collectionname},
        ).result_rows]
    unknown = sorted(set(registered) - backed_up_datasets)
    if unknown:
        blockers.append(f"{len(unknown)} registered dataset(s) are not in this backup: "
                        + ", ".join(unknown[:OCCUPANCY_EXAMPLES])
                        + (" and more" if len(unknown) > OCCUPANCY_EXAMPLES else ""))
    return blockers


@activity.defn
@with_heartbeat
def begin_import(params: ImportParams) -> str:
    """Check the backup and the target, then clear the empty shell. Returns the directory.

    Everything that can refuse the import happens here, before a byte moves: the manifest
    is read and its format checked, the collection it names is compared with the one
    being restored into, the target is checked for anything a restore would land on top
    of, and the backup's schema version is compared with this deployment's.

    What it then removes is only ever empty: an empty collection database, whose presence
    would make `RESTORE DATABASE` fail, and empty Manticore tables with the directories
    `DROP TABLE` leaves behind, which `IMPORT TABLE` refuses to overwrite. The bucket is
    kept — an empty bucket is exactly what the object phase wants.
    """
    from database.clickhouse import drop_collection_db, get_global_client
    from database.manticore import drop_collection_tables, list_collection_tables
    from database.s3 import collection_bucket, ensure_bucket

    source = validate_destination(params.source)
    directory = os.path.join(BACKUP_ROOT, source)
    manifest = read_manifest(directory)

    if manifest.get("collectionname") != params.collectionname:
        raise ValueError(
            f"{source} is a backup of {manifest.get('collectionname')!r}, not of "
            f"{params.collectionname!r}. A collection is restored under its own name: "
            f"the name is part of the database name, of every dataset id, of every "
            f"search table and of every object key."
        )

    with get_global_client() as client:
        current = int(client.query(
            "SELECT max(version) FROM schema_versions").result_rows[0][0] or 0)
    recorded = manifest.get("configuration", {}).get("schema_version_global") or []
    backed_up = int((recorded[0] or {}).get("version") or 0) if recorded else 0
    if backed_up > current:
        raise ValueError(
            f"{source} was taken at global schema version {backed_up} and this "
            f"deployment is at {current}. Upgrade this deployment before restoring a "
            f"backup taken from a later one."
        )

    configuration = manifest.get("configuration") or {}
    backed_up_datasets = {str(row.get("collection_dataset"))
                          for row in (configuration.get("dataset") or [])}
    blockers = _occupancy(params.collectionname, backed_up_datasets)
    if blockers:
        raise ValueError(
            f"{params.collectionname} is not an empty target: "
            + "; ".join(blockers)
            + ". A restore only ever writes into an empty collection, because writing "
              "into populated tables leaves two copies of every row with no way to tell "
              "which is real. Either delete the collection first with "
              "`main.py operations` / the admin page's delete, or do not import."
        )

    drop_collection_db(params.collectionname)
    tables = list_collection_tables(params.collectionname)
    drop_collection_tables(params.collectionname)
    for table in tables:
        # `DROP TABLE` leaves the table's directory behind, and `IMPORT TABLE` refuses a
        # destination that already exists — with an error about a directory rather than
        # about a table.
        shutil.rmtree(os.path.join(MANTICORE_RESTORE_ROOT, table), ignore_errors=True)
    ensure_bucket(collection_bucket(params.collectionname))
    log.info("[P_ops] import %s restoring %s from %s",
             params.op_id, params.collectionname, directory)
    return directory


@activity.defn
@with_heartbeat
def import_object_store(params: ImportParams) -> ExportStoreResult:
    """Put every object in the backup's volumes back into the collection's bucket.

    **Every volume is read, in order, and there may be many.** A volume rolls at a fixed
    size, so a corpus larger than that size is several tars whose members continue from
    one into the next; a restore that opened only the first would silently return a
    fraction of the collection.

    The volumes are streamed rather than indexed: the key manifest's offsets exist so a
    single blob can be pulled out of a backup without reading it all, which is the
    opposite of what a whole-collection restore does. Streaming also means each volume's
    recorded sha256 is checked against the bytes actually read, for free.
    """
    from database.s3 import collection_bucket, get_s3_client

    import tarfile

    manifest = read_manifest(params.directory)
    garage = manifest["stores"]["garage"]
    volumes = garage.get("volumes") or []
    total = int(garage.get("source_bytes") or 0)
    expected_objects = int(garage.get("objects") or 0)

    phase = _Phase(params.op_id, "object store")
    phase.report(0, total, force=True)
    client = get_s3_client()
    bucket = collection_bucket(params.collectionname)
    done = 0
    restored = 0

    for volume in volumes:
        path = os.path.join(params.directory, volume["path"])
        with open(path, "rb") as raw:
            reader = _VerifyingReader(raw, volume.get("sha256", ""), volume["path"])
            with tarfile.open(fileobj=reader, mode="r|") as tar:
                for member in tar:
                    if not member.isfile():
                        continue
                    stream = tar.extractfile(member)
                    if stream is None:
                        continue
                    client.put_object(bucket, member.name, stream, member.size)
                    restored += 1
                    done += member.size
                    phase.report(done, total)
            reader.verify()

    phase.report(done, total, force=True)
    if expected_objects and restored != expected_objects:
        raise RuntimeError(
            f"the manifest records {expected_objects} object(s) and {restored} were "
            f"restored from {len(volumes)} volume(s)."
        )
    return phase.finish(ExportStoreResult(
        store="garage",
        bytes_written=done,
        detail={"bucket": bucket, "objects": restored, "volumes": len(volumes)},
    ))


@activity.defn
@with_heartbeat
def import_clickhouse(params: ImportParams) -> ExportStoreResult:
    """`RESTORE DATABASE` the collection's archive, then migrate it forward.

    The archive holds the parts as they were written, which is the reason `BACKUP` is the
    mechanism on the way out: most tables here are `ReplacingMergeTree` without a version
    column, and which row survives a duplicate key is decided by part order. Restoring
    parts preserves that decision; re-inserting rows from a dump would not.

    **The migration afterwards is what makes an older backup usable.** The restored
    database carries its own `schema_versions`, so a backup taken before a migration is
    brought up to this deployment's schema by running the same migrations any other
    collection database runs, and one taken at the current version is a no-op.
    """
    from database.clickhouse import collection_db_name, get_global_client, migrate_collection

    manifest = read_manifest(params.directory)
    block = manifest["stores"]["clickhouse"]
    database = collection_db_name(params.collectionname)
    relative = f"{validate_destination(params.source)}/{block['artifact']}"
    total = int(block.get("total_size") or block.get("bytes") or 0)

    phase = _Phase(params.op_id, "clickhouse")
    phase.report(0, total, force=True)
    status = ""
    error = ""
    with get_global_client() as client:
        client.query(f"RESTORE DATABASE `{database}` FROM File('{relative}') "
                     f"SETTINGS id='{params.op_id}', async=1")
        while status in ("RESTORING", ""):
            time.sleep(CLICKHOUSE_POLL_SECONDS)
            rows = client.query(
                "SELECT status, error, bytes_read, total_size FROM system.backups "
                "WHERE id = {id:String}", parameters={"id": params.op_id},
            ).result_rows
            if not rows:
                # The row appears as the restore is registered; an empty answer this
                # early is "not yet", not "gone".
                continue
            status, error, bytes_read, total_size = rows[0]
            phase.report(int(bytes_read), max(int(total_size), int(bytes_read), total))

    if status != "RESTORED":
        raise RuntimeError(f"ClickHouse restore of {database} ended {status}: {error}")

    migrate_collection(params.collectionname)
    with get_global_client() as client:
        version = int(client.query(
            f"SELECT max(version) FROM `{database}`.schema_versions"
        ).result_rows[0][0] or 0)
    phase.report(total, total, force=True)
    return phase.finish(ExportStoreResult(
        store="clickhouse",
        bytes_written=total,
        detail={"database": database, "artifact": block["artifact"],
                "schema_version": version},
    ))


@activity.defn
@with_heartbeat
def import_manticore(params: ImportParams) -> ExportStoreResult:
    """Stage each shard's files beside the data directory and `IMPORT TABLE` them.

    **Manticore's own restore tool cannot be used**: it restores configuration and data
    together into an empty instance, and refuses one that is already serving. The
    per-table path is the one that works against a live daemon — stage the table's files,
    then hand the daemon the staging directory — and it needs no restart.

    Two constraints shape the rest: the destination directory must not already exist,
    and the staging directory must not *be* the destination, because
    `IMPORT TABLE` moves the files rather than copying them. The staging directory lives
    on the data directory's own filesystem for the same reason — a move across
    filesystems is not a rename.

    Decompression happens here rather than in the Manticore container, which has no zstd.
    """
    import tarfile

    import zstandard

    from database.manticore import get_manticore_client

    manifest = read_manifest(params.directory)
    block = manifest["stores"]["manticore"]
    artifacts = block.get("tables") or []
    total = int(block.get("source_bytes") or 0)

    phase = _Phase(params.op_id, "manticore")
    phase.report(0, total, force=True)
    staging_root = os.path.join(MANTICORE_RESTORE_ROOT,
                                f"{MANTICORE_STAGING_PREFIX}{params.op_id}")
    daemon_root = os.path.join(MANTICORE_DAEMON_DATA_ROOT,
                               f"{MANTICORE_STAGING_PREFIX}{params.op_id}")
    done = 0
    restored: list[str] = []
    try:
        for artifact in artifacts:
            table = artifact["table"]
            staging = os.path.join(staging_root, table)
            os.makedirs(staging, exist_ok=True)
            os.chmod(staging_root, 0o777)
            os.chmod(staging, 0o777)
            path = os.path.join(params.directory, artifact["path"])
            with open(path, "rb") as raw:
                reader = _VerifyingReader(raw, artifact.get("sha256", ""),
                                          artifact["path"])
                decompressor = zstandard.ZstdDecompressor()
                with decompressor.stream_reader(reader) as stream:
                    with tarfile.open(fileobj=stream, mode="r|") as tar:
                        tar.extractall(staging, filter="data")
                reader.verify()
            # The daemon runs as its own user and has to both read these files and move
            # them out; the modes inside the archive are the ones the daemon wrote for
            # itself, which say nothing about who is reading them here.
            for entry in os.scandir(staging):
                os.chmod(entry.path, 0o666)
            done += int(artifact.get("source_bytes") or 0)
            with get_manticore_client() as cnx:
                cursor = cnx.cursor()
                cursor.execute(f"DROP TABLE IF EXISTS {table}")
                shutil.rmtree(os.path.join(MANTICORE_RESTORE_ROOT, table),
                              ignore_errors=True)
                cursor.execute(
                    f"IMPORT TABLE {table} FROM "
                    f"'{os.path.join(daemon_root, table, table)}'")
                cnx.commit()
            restored.append(table)
            phase.report(done, total)
    finally:
        # `IMPORT TABLE` moves the files out, so what is left is empty directories --
        # but a failure part way leaves a staged copy of a whole table, which is real
        # space inside the data directory and belongs to nothing.
        shutil.rmtree(staging_root, ignore_errors=True)

    phase.report(total, total, force=True)
    return phase.finish(ExportStoreResult(
        store="manticore",
        bytes_written=done,
        detail={"tables": restored},
    ))


def _restore_configuration(collectionname: str, configuration: dict) -> dict[str, int]:
    """Write the collection's own rows back into the global database.

    These are what make a restored collection *configured* rather than merely present:
    the collection, who may read it, its datasets and their settings. They are inserted
    as `JSONEachRow` rather than as typed values because they were serialised through
    JSON on the way out, and letting ClickHouse parse its own text back into its own
    columns is one conversion instead of a table of them.

    **`server_settings` is deliberately not restored.** It is the deployment's, not the
    collection's — the probed embedding dimension, the model catalogue — and a backup
    carrying one deployment's settings into another would reconfigure everything else
    running there as a side effect of restoring one collection.

    All four tables are `ReplacingMergeTree` with a version column, so the rows go back
    with the versions they were taken with. The one exception is the collection row when
    the target already had one: that row is the only thing a restore can land on top of,
    and the restore is the newer writer, so it is stamped as such rather than left to
    lose to whatever was there.
    """
    from datetime import datetime, timezone

    from database.clickhouse import get_global_client

    written: dict[str, int] = {}
    versions = {"collections": "updated_at", "collection_group_permissions": "updated_at",
                "dataset": "date_modified", "dataset_settings": "updated_at"}
    now = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    with get_global_client() as client:
        existing = int(client.query(
            "SELECT count() FROM collections FINAL WHERE collectionname = {name:String}",
            parameters={"name": collectionname},
        ).result_rows[0][0])
        for table, version_column in versions.items():
            rows = configuration.get(table) or []
            if not rows:
                written[table] = 0
                continue
            if table == "collections" and existing:
                rows = [{**row, version_column: now} for row in rows]
            block = "\n".join(json.dumps(row, default=str) for row in rows)
            client.raw_insert(table, insert_block=block.encode("utf-8"),
                              fmt="JSONEachRow")
            written[table] = len(rows)
    return written


@activity.defn
@with_heartbeat
def finish_import(params: ImportParams) -> str:
    """Restore the configuration rows, which is what makes the collection usable.

    Last, because these rows are what offers the collection to everything else: a restore
    that stopped before this point left a collection nobody is shown rather than one that
    is shown and half empty.
    """
    from database.operations import merge_detail

    manifest = read_manifest(params.directory)
    written = _restore_configuration(params.collectionname,
                                     manifest.get("configuration") or {})
    merge_detail(params.op_id, configuration=written)
    log.info("[P_ops] import %s restored configuration rows %s", params.op_id, written)
    return (f"restored {params.collectionname} from {params.source} "
            f"({sum(written.values())} configuration row(s))")
