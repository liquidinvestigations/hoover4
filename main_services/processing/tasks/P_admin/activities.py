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
    ClickHouse TTL cannot delete MinIO objects, so dropping the rows first would leak the
    bytes permanently.
    """
    from tasks.P_admin.artifact_sweeper import sweep_json

    return sweep_json()
