"""Activities for collection database lifecycle, triggered from the admin UI or the CLI.

The website must not own the migration SQL, so provisioning and dropping a collection
database run here, in the one place the schema is defined.
"""

from dataclasses import dataclass

import logging

from temporalio import activity

from tasks.P_admin.eta_collector import CollectEtaSamplesParams, CollectEtaSamplesResult
from tasks.heartbeat import with_heartbeat

log = logging.getLogger(__name__)


@dataclass
class CollectionDatabaseParams:
    collectionname: str


@dataclass
class PurgeDatasetParams:
    collectionname: str
    collection_dataset: str


@activity.defn
@with_heartbeat
def ensure_collection_database(params: CollectionDatabaseParams) -> str:
    """Create the collection's ClickHouse database if missing and migrate it.

    Idempotent: running it against an already-migrated collection is a no-op.
    """
    from database.clickhouse import migrate_collection

    db_name = migrate_collection(params.collectionname)
    log.info("[P_admin] Ensured collection database %s", db_name)
    return db_name


@activity.defn
@with_heartbeat
def drop_collection_database(params: CollectionDatabaseParams) -> str:
    """Drop the collection's ClickHouse database and Manticore tables. Destructive.

    Only reachable from `admin_delete_collection`, which is gated on the collection
    having no datasets assigned.
    """
    from database.clickhouse import drop_collection_db
    from database.manticore import drop_collection_tables

    dropped_tables = drop_collection_tables(params.collectionname)
    db_name = drop_collection_db(params.collectionname)
    log.warning(
        "[P_admin] Dropped collection database %s and %d Manticore shard tables",
        db_name, len(dropped_tables),
    )
    return db_name


def count_dataset_rows(collectionname: str, collection_dataset: str) -> dict[str, dict[str, int]]:
    """What a purge of `collection_dataset` would delete, per store and table.

    Read-only. It walks exactly the table lists the two purge activities below walk, so
    the report and the deletion can never disagree about what is in scope — a table the
    purge would miss is missing from the report too, rather than the operator being told
    a number nothing acts on.

    Counts are physical rows, not `FINAL` rows: `FINAL` over a large collection is
    expensive, and the honest answer to "what will this delete" is the row count.
    """
    from database.clickhouse import get_collection_client
    from database.manticore import get_manticore_client, list_collection_tables

    manticore: dict[str, int] = {}
    for table in list_collection_tables(collectionname):
        with get_manticore_client() as cnx:
            cursor = cnx.cursor()
            cursor.execute(
                f"SELECT count(*) FROM {table} WHERE collection_dataset = %s",
                (collection_dataset,),
            )
            row = cursor.fetchone()
        manticore[table] = int(row[0]) if row else 0

    clickhouse: dict[str, int] = {}
    with get_collection_client(collectionname) as client:
        for (table,) in client.query("SHOW TABLES").result_rows:
            columns = {row[0] for row in client.query(f"DESCRIBE TABLE `{table}`").result_rows}
            if 'collection_dataset' not in columns:
                continue
            count = client.query(
                f"SELECT count() FROM `{table}` WHERE collection_dataset = {{cd:String}}",
                parameters={"cd": collection_dataset},
            ).result_rows
            clickhouse[table] = int(count[0][0]) if count else 0

    return {"manticore": manticore, "clickhouse": clickhouse}


@activity.defn
@with_heartbeat
def purge_dataset_from_manticore(params: PurgeDatasetParams) -> str:
    """Delete a dataset's rows from every Manticore table of its collection.

    Every table, not every SHARD table: the collection's `<name>_vfs` structure index
    holds one row per VFS node scoped by `collection_dataset` too, and a purge that
    skipped it would leave the purged dataset's folders in the tree sidebar.
    """
    from database.manticore import get_manticore_client, list_collection_tables

    tables = list_collection_tables(params.collectionname)
    with get_manticore_client() as cnx:
        cursor = cnx.cursor()
        for table in tables:
            # Identifiers come from list_shard_tables (regex-validated); only the
            # collection_dataset value is bound.
            cursor.execute(
                f"DELETE FROM {table} WHERE collection_dataset = %s",
                (params.collection_dataset,),
            )
        cnx.commit()
    log.info(
        "[P_admin] Purged %s from %d Manticore tables of %s",
        params.collection_dataset, len(tables), params.collectionname,
    )
    return "ok"


@activity.defn
@with_heartbeat
def purge_dataset_from_clickhouse(params: PurgeDatasetParams) -> str:
    """Delete a dataset's rows from every collection-DB table that has a
    ``collection_dataset`` column (lightweight deletes)."""
    from database.clickhouse import get_collection_client

    with get_collection_client(params.collectionname) as client:
        tables = [row[0] for row in client.query("SHOW TABLES").result_rows]
        purged = []
        for table in tables:
            columns = {row[0] for row in client.query(f"DESCRIBE TABLE `{table}`").result_rows}
            if 'collection_dataset' not in columns:
                continue
            client.command(
                f"DELETE FROM `{table}` WHERE collection_dataset = {{cd:String}}",
                parameters={"cd": params.collection_dataset},
            )
            purged.append(table)
    log.info(
        "[P_admin] Purged %s from collection-DB tables of %s: %s",
        params.collection_dataset, params.collectionname, purged,
    )
    return "ok"


#: Cell batches one sweep pass releases. Bounded so a purge of a large dataset does not
#: turn into a single unbounded DELETE over the whole cell table.
SWEEP_ORPHAN_HASH_BATCH = 1000

#: Passes one sweep runs before it stops and leaves the rest to the next one.
SWEEP_ORPHAN_MAX_BATCHES = 100


@activity.defn
@with_heartbeat
def sweep_orphan_table_cells(params: CollectionDatabaseParams) -> str:
    """Release cells no dataset claims any more.

    `table_cells` is keyed by hash alone so one parse serves every dataset in the
    collection that holds the same file. The price is that `purge_dataset_from_clickhouse`
    cannot see the table at all -- it enumerates tables by their `collection_dataset`
    column -- so a purged dataset leaves its cells behind unless something looks for them.
    That something is this.

    It refuses to run against an empty manifest, and says so. An authority table with no
    rows is a symptom -- a migration that has not applied, a collection whose datasets
    were all purged in the same breath, a query that failed -- and never a licence to
    delete every cell in the collection.

    `parsing` counts as a claim, so a sweep cannot race an in-flight parse. A `parsing`
    row that has outlived any plausible parse is tombstoned to `failed` first, which is
    what releases a genuinely abandoned parse's cells on the following pass.
    """
    from database.clickhouse import get_collection_client

    with get_collection_client(params.collectionname) as client:
        tables = {row[0] for row in client.query("SHOW TABLES").result_rows}
        if not {"table_cells", "table_documents"} <= tables:
            log.info("[P_admin] %s has no table storage, nothing to sweep",
                     params.collectionname)
            return "ok"

        client.command("""
            ALTER TABLE table_documents UPDATE status = 'failed',
                parse_error = 'abandoned parse, no cells claimed'
            WHERE status = 'parsing' AND updated_at < now() - INTERVAL 1 DAY
        """)

        claimed = client.query(
            "SELECT count() FROM table_documents FINAL WHERE status = 'ok'"
        ).result_rows[0][0]
        if not claimed:
            log.warning(
                "[P_admin] %s: table_documents holds no completed parse, refusing to "
                "sweep table_cells -- an empty authority table is a symptom, not a "
                "licence to delete every cell in the collection",
                params.collectionname,
            )
            return "refused: empty manifest"

        released = 0
        for _ in range(SWEEP_ORPHAN_MAX_BATCHES):
            orphans = [row[0] for row in client.query("""
                SELECT DISTINCT file_hash FROM table_cells
                WHERE file_hash NOT IN (
                    SELECT hash FROM table_documents FINAL
                    WHERE status IN ('ok', 'parsing')
                )
                LIMIT {n:UInt32}
            """, parameters={"n": SWEEP_ORPHAN_HASH_BATCH}).result_rows]
            if not orphans:
                break
            client.command(
                "DELETE FROM table_cells WHERE file_hash IN {hashes:Array(String)}",
                parameters={"hashes": orphans},
            )
            released += len(orphans)

    log.info("[P_admin] %s: released the cells of %d unclaimed table document(s)",
             params.collectionname, released)
    return f"released {released}"


@activity.defn
@with_heartbeat
def recompute_shard_ledger_activity(params: CollectionDatabaseParams) -> str:
    """Recompute the shard ledger's fill levels from ``index_state``.

    Runs after a dataset purge: shrinks ``text_bytes``/``doc_count`` of the shards the
    deleted dataset contributed to. Never re-opens sealed shards, compacts, or
    renumbers.
    """
    from tasks.P6_index_data.shard_planner import recompute_shard_ledger

    recompute_shard_ledger(params.collectionname)
    return "ok"


@activity.defn
@with_heartbeat
def collect_eta_samples(params: "CollectEtaSamplesParams") -> "CollectEtaSamplesResult":
    """One ETA sampling pass over all collections (see ``eta_collector``)."""
    from tasks.P_admin.eta_collector import run_collection_pass

    return run_collection_pass(params)


@activity.defn
@with_heartbeat
def sweep_chat_artifacts() -> str:
    """One chat-artifact retention pass: objects first, then rows.

    See ``tasks/P_admin/artifact_sweeper`` for why the order is not interchangeable — a
    ClickHouse TTL cannot delete Garage objects, so dropping the rows first would leak the
    bytes permanently.
    """
    from tasks.P_admin.artifact_sweeper import sweep_json

    return sweep_json()
