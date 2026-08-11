"""Integration test: re-indexing a plan must not duplicate Manticore rows.

The deterministic-id / REPLACE INTO design (pages/meta row ids derived from the
(document, segment) identity) exists so that re-running the planner plus both
writers over the same plan overwrites rows in place. This pins it: row counts
in every shard table, in index_state and in manticore_shard_assignments must be
unchanged after a full second pass.

Requires the docker stack; run inside the worker container:
``docker exec -it hoover4-worker uv run pytest tests/integration --integration -q``
"""

import pytest

from database.clickhouse import get_collection_client
from database.manticore import get_manticore_client, list_shard_tables
from tasks.P6_index_data import shard_planner
from tasks.P6_index_data.activities import index_metadata, index_text_pages
from tasks.P6_index_data.params import (
    FinalizeIndexBatchParams,
    IndexShardParams,
    PlanShardsParams,
    RecordIndexedParams,
)

from .helpers import ingest_dataset, wait_for_plans_finished

pytestmark = [pytest.mark.integration, pytest.mark.timeout(3600)]

PLAN_HASH = "0" * 40
INDEXING_CHUNK_SIZE = 100


def _manticore_counts(collectionname: str) -> dict[str, int]:
    """Row count of every shard table of the collection."""
    counts = {}
    with get_manticore_client() as cnx:
        cursor = cnx.cursor()
        for table in list_shard_tables(collectionname):
            cursor.execute(f"SELECT count(*) FROM {table}")
            counts[table] = int(cursor.fetchone()[0])
    return counts


def _run_indexing_pass(collectionname: str, collection_dataset: str, hashes: list[str]) -> None:
    """One full indexing pass, driven in-process: plan -> writers -> record -> finalize."""
    assignments = shard_planner.plan_shards(
        PlanShardsParams(
            collectionname=collectionname,
            collection_dataset=collection_dataset,
            plan_hash=PLAN_HASH,
            hashes=hashes,
        )
    )
    indexed_entries: set[tuple[str, str]] = set()
    for assignment in assignments:
        for chunk_start in range(0, len(assignment.hashes), INDEXING_CHUNK_SIZE):
            chunk_hashes = assignment.hashes[chunk_start:chunk_start + INDEXING_CHUNK_SIZE]
            shard_params = IndexShardParams(
                collectionname=collectionname,
                collection_dataset=collection_dataset,
                plan_hash=PLAN_HASH,
                shard_name=assignment.shard_name,
                hashes=chunk_hashes,
            )
            for file_hash in index_text_pages(shard_params):
                indexed_entries.add((assignment.shard_name, file_hash))
            for file_hash in index_metadata(shard_params):
                indexed_entries.add((assignment.shard_name, file_hash))
    shard_planner.record_indexed(
        RecordIndexedParams(
            collectionname=collectionname,
            collection_dataset=collection_dataset,
            plan_hash=PLAN_HASH,
            entries=sorted(indexed_entries),
        )
    )
    shard_planner.finalize_index_batch(
        FinalizeIndexBatchParams(
            collectionname=collectionname,
            collection_dataset=collection_dataset,
            plan_hash=PLAN_HASH,
        )
    )


def test_reindex_is_idempotent(temp_collection, tiny_dataset):
    collectionname = temp_collection
    collection_dataset = ingest_dataset(collectionname, "tiny", str(tiny_dataset))
    wait_for_plans_finished(collectionname)

    with get_collection_client(collectionname) as client:
        hashes = [
            row[0]
            for row in client.query(
                "SELECT DISTINCT file_hash FROM manticore_shard_assignments FINAL "
                "WHERE collection_dataset = {cd:String}",
                parameters={"cd": collection_dataset},
            ).result_rows
        ]
    assert hashes

    before_manticore = _manticore_counts(collectionname)
    assert any(count > 0 for count in before_manticore.values())

    # Full second pass over the same hashes.
    _run_indexing_pass(collectionname, collection_dataset, hashes)

    after_manticore = _manticore_counts(collectionname)
    assert after_manticore == before_manticore, (
        f"re-indexing duplicated rows: {before_manticore} -> {after_manticore}"
    )

    with get_collection_client(collectionname) as client:
        # index_state is keyed on (collection_dataset, file_hash): the second
        # pass replaces rows, it does not add them.
        index_state_count = client.query(
            "SELECT count() FROM index_state FINAL"
        ).result_rows[0][0]
        assignment_count = client.query(
            "SELECT count() FROM manticore_shard_assignments FINAL"
        ).result_rows[0][0]
        ledger_docs = client.query(
            "SELECT sum(doc_count) FROM manticore_shards FINAL"
        ).result_rows[0][0]
    assert int(index_state_count) == len(hashes)
    assert int(assignment_count) == len(hashes)
    assert int(ledger_docs or 0) == len(hashes)
