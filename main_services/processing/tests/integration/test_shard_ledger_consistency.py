"""Integration test: shard ledger consistency after indexing.

Two phases on one ingested temp collection:

1. the ledger, the assignments and the actual Manticore shard tables agree with
   each other (sum of per-shard docs == assigned docs == indexed docs);
2. re-planning with a tiny ``MAX_SHARD_TEXT_BYTES`` (monkeypatched in-process —
   the planner is invoked directly, not via the worker) splits the documents over
   >=2 shards, never exceeds the budget except for single-document shards, and
   keeps every ``file_hash`` in exactly one shard.

Requires the docker stack; run inside the worker container:
``docker exec -it hoover4-worker uv run pytest tests/integration --integration -q``
"""

import asyncio

import pytest

from database.clickhouse import get_collection_client
from database.manticore import get_manticore_client, list_shard_tables
from tasks.P0_scan_disk.submit_job import add_disk_dataset
from tasks.P1_compute_plans.submit_job import submit_compute_plans
from tasks.P2_execute_plan.submit_job import submit_execute_plans
from tasks.P6_index_data import shard_planner
from tasks.P6_index_data.params import PlanShardsParams

from .helpers import wait_for_plans_finished

pytestmark = [pytest.mark.integration, pytest.mark.timeout(3600)]


def _manticore_doc_counts_by_shard_table(collectionname: str) -> dict[str, int]:
    """Distinct ``(collection_dataset, file_hash)`` pairs per ``<shard>_meta`` table.

    Manticore has no ``count(distinct concat(...))``: GROUP BY the pair and count
    the rows. Document identity is the pair, not file_hash alone."""
    counts = {}
    with get_manticore_client() as cnx:
        cursor = cnx.cursor()
        for table in list_shard_tables(collectionname):
            if not table.endswith("_meta"):
                continue
            cursor.execute(
                f"SELECT collection_dataset, file_hash FROM {table} "
                "GROUP BY collection_dataset, file_hash LIMIT 100000"
            )
            counts[table] = len(cursor.fetchall())
    return counts


def test_shard_ledger_consistency(temp_collection, tiny_dataset, monkeypatch):
    collectionname = temp_collection
    collection_dataset = f"{collectionname}_tiny"

    add_disk_dataset(collectionname, "tiny", str(tiny_dataset))
    asyncio.run(submit_compute_plans(collectionname, collection_dataset))
    asyncio.run(submit_execute_plans(collectionname, collection_dataset))
    wait_for_plans_finished(collectionname)

    with get_collection_client(collectionname) as client:
        assignments = client.query(
            "SELECT collection_dataset, file_hash, shard_name FROM manticore_shard_assignments FINAL"
        ).result_rows
        ledger = client.query(
            "SELECT shard_name, text_bytes, doc_count, is_open "
            "FROM manticore_shards FINAL ORDER BY shard_index"
        ).result_rows
        index_state_count = client.query(
            "SELECT count() FROM index_state FINAL"
        ).result_rows[0][0]

    assert assignments, "expected shard assignments after ingest"
    assert ledger, "expected a shard ledger after ingest"

    # Phase 1: ledger <-> assignments <-> index_state <-> Manticore tables agree.
    # Document identity is the (collection_dataset, file_hash) PAIR: the same
    # content in two datasets of one collection is indexed twice (B2 contract).
    pairs = sorted({(row[0], row[1]) for row in assignments})
    hashes = sorted({row[1] for row in assignments})
    assert len(assignments) == len(pairs), "every (dataset, file_hash) pair must appear exactly once"
    assert sum(int(row[2]) for row in ledger) == len(pairs)
    assert int(index_state_count) == len(pairs), "index_state must record every indexed pair"
    manticore_counts = _manticore_doc_counts_by_shard_table(collectionname)
    assert manticore_counts, "expected Manticore shard meta tables"
    assert sum(manticore_counts.values()) == len(pairs)

    # Phase 2: re-plan with a tiny budget, in-process (monkeypatch only affects
    # this process — that is exactly why the planner is called directly here).
    small_budget = 200
    monkeypatch.setattr(shard_planner, "MAX_SHARD_TEXT_BYTES", small_budget)
    with get_collection_client(collectionname) as client:
        client.command("TRUNCATE TABLE manticore_shards")
        client.command("TRUNCATE TABLE manticore_shard_assignments")

    shard_planner.plan_shards(
        PlanShardsParams(
            collectionname=collectionname,
            collection_dataset=collection_dataset,
            plan_hash="ledgerconsistencytest",
            hashes=hashes,
        )
    )

    with get_collection_client(collectionname) as client:
        ledger = client.query(
            "SELECT shard_name, text_bytes, doc_count FROM manticore_shards FINAL "
            "ORDER BY shard_index"
        ).result_rows
        per_pair = client.query(
            "SELECT collection_dataset, file_hash, uniqExact(shard_name) AS n "
            "FROM manticore_shard_assignments FINAL "
            "GROUP BY collection_dataset, file_hash"
        ).result_rows

    assert len(ledger) >= 2, "tiny budget must force multiple shards"
    for shard_name, text_bytes, doc_count in ledger:
        assert int(text_bytes) <= small_budget or int(doc_count) == 1, (
            f"shard {shard_name} over budget with {doc_count} docs"
        )
    assert sum(int(row[2]) for row in ledger) == len(hashes)
    assert all(int(n) == 1 for _cd, _file_hash, n in per_pair), (
        "every (dataset, file_hash) pair must live in exactly one shard"
    )
    assert len(per_pair) == len(hashes)
