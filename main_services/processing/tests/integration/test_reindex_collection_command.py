"""Integration test: ``main.py reindex-collection`` recovers a lost Manticore volume (I5).

Drops the collection's shard tables out from under the index, invokes the CLI
command's callback (which truncates the shard ledger / assignments / index_state
and queues IndexDatasetPlan workflows on the real workers), then waits until
every document is back and asserts the Manticore row counts are restored.

Requires the docker stack; run inside the worker container:
``docker exec -it hoover4-worker uv run pytest tests/integration --integration -q``
"""

import time

import pytest

from database.clickhouse import get_collection_client
from database.manticore import drop_collection_tables, get_manticore_client, list_shard_tables
from main import reindex_collection

from .helpers import ingest_dataset, wait_for_plans_finished

pytestmark = [pytest.mark.integration, pytest.mark.timeout(3600)]


def _manticore_pair_count(collectionname: str) -> int:
    # Manticore has no count(distinct concat(...)): GROUP BY the pair, count rows.
    total = 0
    with get_manticore_client() as cnx:
        cursor = cnx.cursor()
        for table in list_shard_tables(collectionname):
            if not table.endswith("_meta"):
                continue
            cursor.execute(
                f"SELECT collection_dataset, file_hash FROM {table} "
                "GROUP BY collection_dataset, file_hash LIMIT 100000"
            )
            total += len(cursor.fetchall())
    return total


def test_reindex_collection_command(temp_collection, tiny_dataset):
    collectionname = temp_collection
    ingest_dataset(collectionname, "tiny", str(tiny_dataset))
    wait_for_plans_finished(collectionname)

    with get_collection_client(collectionname) as client:
        expected_docs = int(client.query(
            "SELECT count() FROM index_state FINAL"
        ).result_rows[0][0])
    assert expected_docs > 0
    assert _manticore_pair_count(collectionname) == expected_docs

    # Simulate the lost Manticore volume, then run the recovery command.
    dropped = drop_collection_tables(collectionname)
    assert dropped, "expected shard tables to drop"
    assert list_shard_tables(collectionname) == []
    reindex_collection.callback(collectionname)

    # The command queues real IndexDatasetPlan workflows; wait until every
    # document is recorded as indexed again.
    deadline = time.monotonic() + 600
    while True:
        with get_collection_client(collectionname) as client:
            indexed = int(client.query("SELECT count() FROM index_state FINAL").result_rows[0][0])
        if indexed == expected_docs:
            break
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"reindex of {collectionname} did not finish within 600s: "
                f"{indexed}/{expected_docs} documents indexed"
            )
        time.sleep(5)

    assert list_shard_tables(collectionname), "reindex must recreate the shard tables"
    assert _manticore_pair_count(collectionname) == expected_docs
