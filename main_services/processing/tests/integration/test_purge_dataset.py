"""Integration test: PurgeDataset removes a dataset everywhere and shrinks the ledger.

Ingests the same content as two datasets of one collection, purges the second,
and asserts: its rows are gone from every relevant collection-DB table and from
every Manticore shard table, the surviving dataset is untouched, and the shard
ledger's counters shrink to exactly the surviving dataset's documents.

Requires the docker stack; run inside the worker container:
``docker exec -it hoover4-worker uv run pytest tests/integration --integration -q``
"""

import time

import pytest

from database.clickhouse import get_collection_client
from database.manticore import get_manticore_client, list_shard_tables
from tasks.P_admin.activities import (
    CollectionDatabaseParams,
    PurgeDatasetParams,
    purge_dataset_from_clickhouse,
    purge_dataset_from_manticore,
    recompute_shard_ledger_activity,
)

from .helpers import ingest_dataset, wait_for_plans_finished

pytestmark = [pytest.mark.integration, pytest.mark.timeout(3600)]

# Collection-DB tables the assertions care about (all keyed on collection_dataset).
# text_chunks / text_chunk_vectors are the durable vector store — purge must
# clear them the same way it clears text_content, or a re-ingest of the same hashes
# would skip embedding via the left-anti join and leave the corpus unsearchable.
PURGED_TABLES = [
    "vfs_files",
    "text_content",
    "text_chunks",
    "text_chunk_vectors",
    "manticore_shard_assignments",
    "index_state",
]


def _cd_count(client, table: str, collection_dataset: str) -> int:
    return int(client.query(
        f"SELECT count() FROM {table} FINAL WHERE collection_dataset = {{cd:String}}",
        parameters={"cd": collection_dataset},
    ).result_rows[0][0])


def _wait_for_lightweight_deletes(collectionname: str, collection_dataset: str, timeout_s: int = 120) -> None:
    """ClickHouse ``DELETE FROM`` is an async mutation: poll until the rows are gone."""
    deadline = time.monotonic() + timeout_s
    while True:
        with get_collection_client(collectionname) as client:
            remaining = sum(_cd_count(client, table, collection_dataset) for table in PURGED_TABLES)
        if remaining == 0:
            return
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"purge of {collection_dataset} not visible after {timeout_s}s "
                f"({remaining} rows left)"
            )
        time.sleep(2)


def test_purge_dataset(temp_collection, tiny_dataset):
    collectionname = temp_collection
    cd1 = ingest_dataset(collectionname, "tiny", str(tiny_dataset))
    cd2 = ingest_dataset(collectionname, "tiny2", str(tiny_dataset))
    wait_for_plans_finished(collectionname)

    with get_collection_client(collectionname) as client:
        cd1_docs = _cd_count(client, "index_state", cd1)
        assert cd1_docs > 0
        assert _cd_count(client, "index_state", cd2) == cd1_docs  # same content

    purge_dataset_from_manticore(PurgeDatasetParams(collectionname=collectionname, collection_dataset=cd2))
    purge_dataset_from_clickhouse(PurgeDatasetParams(collectionname=collectionname, collection_dataset=cd2))
    _wait_for_lightweight_deletes(collectionname, cd2)
    recompute_shard_ledger_activity(CollectionDatabaseParams(collectionname=collectionname))

    # --- ClickHouse: cd2 gone, cd1 intact ---
    with get_collection_client(collectionname) as client:
        for table in PURGED_TABLES:
            assert _cd_count(client, table, cd2) == 0, f"{table} still has {cd2} rows"
            assert _cd_count(client, table, cd1) > 0, f"{table} lost {cd1} rows"
        ledger_docs = client.query(
            "SELECT sum(doc_count) FROM manticore_shards FINAL"
        ).result_rows[0][0]

    # --- Manticore: cd2 gone from every shard table, cd1 intact ---
    shard_tables = list_shard_tables(collectionname)
    assert shard_tables
    with get_manticore_client() as cnx:
        cursor = cnx.cursor()
        for table in shard_tables:
            cursor.execute(
                f"SELECT count(*) FROM {table} WHERE collection_dataset = %s",
                (cd2,),
            )
            assert int(cursor.fetchone()[0]) == 0, f"{table} still has {cd2} rows"
            cursor.execute(
                f"SELECT count(*) FROM {table} WHERE collection_dataset = %s",
                (cd1,),
            )
            assert int(cursor.fetchone()[0]) > 0, f"{table} lost {cd1} rows"

    # --- the ledger shrank to exactly the surviving dataset ---
    assert int(ledger_docs or 0) == cd1_docs
