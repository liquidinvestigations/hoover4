"""Integration test: a permanently failed writer chunk must not inflate the shard ledger (I2 / B1).

Drives the IndexDatasetPlan failure path in-process: plan_shards reserves the
assignments, both writer activities fail (retries already exhausted, simulated by
a monkeypatched raise), the workflow records one processing_errors row per hash
per task, records NOTHING in index_state, and finalizes. The ledger — recomputed
from index_state, not from the reservations — must then claim zero documents
while the assignments table still holds the reservations (a later re-index
returns the documents to the same shard).

Requires the docker stack; run inside the worker container:
``docker exec -it hoover4-worker uv run pytest tests/integration --integration -q``
"""

import pytest

from database.clickhouse import get_collection_client
from database.manticore import drop_collection_tables
from tasks.P2_execute_plan.activities import (
    RecordProcessingErrorsParams,
    record_processing_errors,
)
from tasks.P6_index_data import activities as p5_activities
from tasks.P6_index_data import shard_planner
from tasks.P6_index_data.params import (
    FinalizeIndexBatchParams,
    PlanShardsParams,
    RecordIndexedParams,
)

from .helpers import ingest_dataset, wait_for_plans_finished

pytestmark = [pytest.mark.integration, pytest.mark.timeout(3600)]

PLAN_HASH = "0" * 40


def _raising_writer(params):
    raise RuntimeError("simulated writer failure (integration test I2)")


def test_failed_writer_chunk_does_not_inflate_ledger(temp_collection, tiny_dataset, monkeypatch):
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
    assert hashes, "fixture ingest must have produced assignments"

    # Reset the indexing layer only; keep the parsed content the writers read.
    drop_collection_tables(collectionname)
    with get_collection_client(collectionname) as client:
        client.command("TRUNCATE TABLE manticore_shards")
        client.command("TRUNCATE TABLE manticore_shard_assignments")
        client.command("TRUNCATE TABLE index_state")
        client.command("TRUNCATE TABLE processing_errors")

    # --- drive the IndexDatasetPlan failure path in-process ---
    assignments = shard_planner.plan_shards(
        PlanShardsParams(
            collectionname=collectionname,
            collection_dataset=collection_dataset,
            plan_hash=PLAN_HASH,
            hashes=hashes,
        )
    )
    assert sum(len(a.hashes) for a in assignments) == len(hashes)

    monkeypatch.setattr(p5_activities, "index_text_pages", _raising_writer)
    monkeypatch.setattr(p5_activities, "index_metadata", _raising_writer)
    with pytest.raises(RuntimeError, match="simulated writer failure"):
        p5_activities.index_text_pages(None)
    with pytest.raises(RuntimeError, match="simulated writer failure"):
        p5_activities.index_metadata(None)

    # Both writers fail for every chunk (what the workflow sees after Temporal
    # retries are exhausted): one processing_errors row per hash per task.
    errors = [
        {
            "collection_dataset": collection_dataset,
            "hash": item_hash,
            "task_name": task_name,
            "run_time_ms": 1,
            "error_logs": "simulated writer failure (integration test I2)",
        }
        for assignment in assignments
        for item_hash in assignment.hashes
        for task_name in ("P6_IndexTextPages", "P6_IndexMetadata")
    ]
    recorded = record_processing_errors(
        RecordProcessingErrorsParams(collectionname=collectionname, errors=errors)
    )
    assert recorded == 2 * len(hashes)

    # No writer committed, so the workflow records no index_state rows...
    assert shard_planner.record_indexed(
        RecordIndexedParams(
            collectionname=collectionname,
            collection_dataset=collection_dataset,
            plan_hash=PLAN_HASH,
            entries=[],
        )
    ) == "ok"
    # ...and finalizes, recomputing the ledger from index_state.
    assert shard_planner.finalize_index_batch(
        FinalizeIndexBatchParams(
            collectionname=collectionname,
            collection_dataset=collection_dataset,
            plan_hash=PLAN_HASH,
        )
    ) == "ok"

    with get_collection_client(collectionname) as client:
        # The reservations survive (re-index returns to the same shard)...
        assignment_count = client.query(
            "SELECT count() FROM manticore_shard_assignments FINAL"
        ).result_rows[0][0]
        # ...but nothing was recorded as indexed...
        index_state_count = client.query(
            "SELECT count() FROM index_state FINAL"
        ).result_rows[0][0]
        # ...so the ledger claims zero documents and zero bytes...
        ledger_rows = client.query(
            "SELECT sum(doc_count), sum(text_bytes) FROM manticore_shards FINAL"
        ).result_rows[0]
        # ...and every failed document is individually visible as an error.
        error_count = client.query(
            "SELECT count() FROM processing_errors"
        ).result_rows[0][0]

    assert int(assignment_count) == len(hashes)
    assert int(index_state_count) == 0
    assert int(ledger_rows[0] or 0) == 0, "failed writers must not inflate doc_count (B1)"
    assert int(ledger_rows[1] or 0) == 0, "failed writers must not inflate text_bytes (B1)"
    assert int(error_count) == 2 * len(hashes)
