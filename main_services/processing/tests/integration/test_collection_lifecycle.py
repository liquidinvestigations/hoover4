"""Integration test: full collection lifecycle on the live stack.

create -> ingest the tiny fixture dataset -> verify per-stage tables ->
delete -> verify the ClickHouse database and the Manticore tables are gone.

Requires the docker stack (and a reachable NER service for ``nlp_processed``);
run inside the worker container:
``docker exec -it hoover4-worker uv run pytest tests/integration --integration -q``
"""

import pytest

from database.clickhouse import (
    collection_db_name,
    drop_collection_db,
    get_collection_client,
    get_global_client,
)
from database.manticore import drop_collection_tables, list_shard_tables
from tasks.P0_scan_disk.submit_job import add_disk_dataset
from tasks.P1_compute_plans.submit_job import submit_compute_plans
from tasks.P2_execute_plan.submit_job import submit_execute_plans

from .helpers import ner_service_reachable, wait_for_plans_finished

pytestmark = [pytest.mark.integration, pytest.mark.timeout(3600)]


def _table_count(collectionname: str, table: str) -> int:
    # No FINAL: `processing_errors` is a plain MergeTree (FINAL is illegal there)
    # and every assertion below only cares about > 0.
    with get_collection_client(collectionname) as client:
        return client.query(f"SELECT count() FROM {table}").result_rows[0][0]


def test_collection_lifecycle(temp_collection, tiny_dataset):
    collectionname = temp_collection

    # --- ingest (same calls as `main.py add-disk-dataset`) ---
    add_disk_dataset(collectionname, "tiny", str(tiny_dataset))
    import asyncio

    collection_dataset = f"{collectionname}_tiny"
    asyncio.run(submit_compute_plans(collectionname, collection_dataset))
    asyncio.run(submit_execute_plans(collectionname, collection_dataset))
    wait_for_plans_finished(collectionname)

    # --- every pipeline stage left its rows in the collection database ---
    assert _table_count(collectionname, "vfs_files") > 0
    assert _table_count(collectionname, "text_content") > 0
    if ner_service_reachable():
        assert _table_count(collectionname, "nlp_processed") > 0
    else:
        # NER down: P4 must record its failures, never swallow them, and the
        # pipeline must still have reached indexing (asserted below).
        assert _table_count(collectionname, "processing_errors") > 0
    assert _table_count(collectionname, "manticore_shards") > 0
    assert _table_count(collectionname, "manticore_shard_assignments") > 0

    # --- shard tables exist in Manticore and hold the indexed documents ---
    shard_tables = list_shard_tables(collectionname)
    assert shard_tables, "expected Manticore shard tables for the collection"

    # --- delete: the same hooks the admin workflow uses ---
    drop_collection_tables(collectionname)
    db_name = drop_collection_db(collectionname)
    assert db_name == collection_db_name(collectionname)

    with get_global_client() as client:
        dbs = {row[0] for row in client.query("SHOW DATABASES").result_rows}
    assert db_name not in dbs
    assert list_shard_tables(collectionname) == []
