"""Integration test: manticore_migrate self-heals a missing shard table (I6).

The documented recovery from a Manticore volume loss is: migrate recreates every
shard table recorded in a collection's ``manticore_shards`` ledger (EMPTY — the
documents come back via ``main.py reindex-collection``, covered by I5). This
drops one pages table, runs the migrate, and asserts the table is back and
empty while its sibling meta table is untouched.

Requires the docker stack; run inside the worker container:
``docker exec -it hoover4-worker uv run pytest tests/integration --integration -q``
"""

import pytest

from database.manticore import get_manticore_client, list_shard_tables, manticore_migrate

from .helpers import ingest_dataset, wait_for_plans_finished

pytestmark = [pytest.mark.integration, pytest.mark.timeout(3600)]


def _count(table: str) -> int:
    with get_manticore_client() as cnx:
        cursor = cnx.cursor()
        cursor.execute(f"SELECT count(*) FROM {table}")
        return int(cursor.fetchone()[0])


def test_manticore_migrate_recreates_missing_shard_table(temp_collection, tiny_dataset):
    collectionname = temp_collection
    ingest_dataset(collectionname, "tiny", str(tiny_dataset))
    wait_for_plans_finished(collectionname)

    pages_tables = [t for t in list_shard_tables(collectionname) if t.endswith("_pages")]
    assert pages_tables, "fixture ingest must have created shard tables"
    victim = pages_tables[0]
    meta_table = victim[:-len("_pages")] + "_meta"
    meta_rows_before = _count(meta_table)
    assert _count(victim) > 0

    with get_manticore_client() as cnx:
        cursor = cnx.cursor()
        cursor.execute(f"drop table if exists {victim}")
        cnx.commit()
    assert victim not in list_shard_tables(collectionname)

    manticore_migrate()

    assert victim in list_shard_tables(collectionname), "migrate must recreate the missing table"
    assert _count(victim) == 0, "a self-healed table comes back EMPTY (reindex refills it)"
    assert _count(meta_table) == meta_rows_before, "sibling tables must be untouched"
