"""Integration test: the NLP success path, with a stubbed NER service.

The real NER service is a GPU box that is not reachable from every environment,
which left the P4 success path — entity_hit rows, nlp_processed watermarks with
text_bytes, and the ner_* MVAs in the shard pages tables — with no end-to-end
coverage anywhere. This stubs the service client in-process (and uses a
dedicated nlp_model id so the left-anti join reprocesses every segment) and
drives the activity against a real temp collection, then re-runs the pages
writer and asserts the entities reached Manticore.

Requires the docker stack; run inside the worker container:
``docker exec -it hoover4-worker uv run pytest tests/integration --integration -q``
"""

import pytest

from database.clickhouse import get_collection_client
from database.manticore import get_manticore_client, list_shard_tables
from tasks.P4_extract_entities import activities as p4_activities
from tasks.P4_extract_entities.params import ExtractEntitiesParams
from tasks.P6_index_data import shard_planner
from tasks.P6_index_data.activities import index_text_pages
from tasks.P6_index_data.params import IndexShardParams, PlanShardsParams

from .helpers import ingest_dataset, wait_for_plans_finished

pytestmark = [pytest.mark.integration, pytest.mark.timeout(3600)]

PLAN_HASH = "0" * 40
STUB_MODEL = "ner-stub-test"


def _stub_ner(texts):
    # Same shape as the real client: (entities_per_text, serving nlp_model).
    return [
        {"PER": ["Alice"], "ORG": ["Acme"], "LOC": [], "MISC": []}
        for _ in texts
    ], STUB_MODEL


def _mva_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def test_nlp_success_path_with_stubbed_ner(temp_collection, tiny_dataset, monkeypatch):
    collectionname = temp_collection
    collection_dataset = ingest_dataset(collectionname, "tiny", str(tiny_dataset))
    wait_for_plans_finished(collectionname)

    with get_collection_client(collectionname) as client:
        segment_count = int(client.query(
            "SELECT count() FROM text_content FINAL WHERE collection_dataset = {cd:String}",
            parameters={"cd": collection_dataset},
        ).result_rows[0][0])
        hashes = [
            row[0]
            for row in client.query(
                "SELECT DISTINCT file_hash FROM text_content FINAL "
                "WHERE collection_dataset = {cd:String}",
                parameters={"cd": collection_dataset},
            ).result_rows
        ]
    assert segment_count > 0 and hashes

    # A dedicated model id makes the left-anti join reprocess every segment,
    # whether or not the real NER service succeeded during ingest. The stub
    # returns it as the *serving* model too, so the watermark is written under
    # STUB_MODEL exactly as a real provider would write its own id.
    monkeypatch.setattr(p4_activities, "configured_nlp_model", lambda: STUB_MODEL)
    monkeypatch.setattr(p4_activities, "extract_ner_from_texts", _stub_ner)

    result = p4_activities.extract_entities_for_hashes(
        ExtractEntitiesParams(
            collectionname=collectionname,
            collection_dataset=collection_dataset,
            plan_hash=PLAN_HASH,
            hashes=hashes,
        )
    )
    assert result.text_segments == segment_count
    assert result.entity_groups > 0

    with get_collection_client(collectionname) as client:
        entity_rows = int(client.query(
            "SELECT count() FROM entity_hit FINAL WHERE collection_dataset = {cd:String} "
            "AND entity_type = 'PER'",
            parameters={"cd": collection_dataset},
        ).result_rows[0][0])
        watermark_rows, watermark_bytes = client.query(
            "SELECT count(), sum(text_bytes) FROM nlp_processed FINAL "
            "WHERE collection_dataset = {cd:String} AND nlp_model = {model:String}",
            parameters={"cd": collection_dataset, "model": STUB_MODEL},
        ).result_rows[0]
    assert entity_rows > 0, "stub entities must land in entity_hit"
    assert int(watermark_rows) == segment_count, "every segment must get a watermark"
    assert int(watermark_bytes or 0) > 0, "nlp_processed.text_bytes feeds the shard planner"

    # Re-run the pages writer: the pages rows must pick up the entity MVAs.
    assignments = shard_planner.plan_shards(
        PlanShardsParams(
            collectionname=collectionname,
            collection_dataset=collection_dataset,
            plan_hash=PLAN_HASH,
            hashes=hashes,
        )
    )
    for assignment in assignments:
        for chunk_start in range(0, len(assignment.hashes), 100):
            index_text_pages(
                IndexShardParams(
                    collectionname=collectionname,
                    collection_dataset=collection_dataset,
                    plan_hash=PLAN_HASH,
                    shard_name=assignment.shard_name,
                    hashes=assignment.hashes[chunk_start:chunk_start + 100],
                )
            )

    pages_tables = [t for t in list_shard_tables(collectionname) if t.endswith("_pages")]
    assert pages_tables
    non_empty = 0
    with get_manticore_client() as cnx:
        cursor = cnx.cursor()
        for table in pages_tables:
            cursor.execute(f"SELECT ner_per FROM {table} LIMIT 50")
            for (value,) in cursor.fetchall():
                if _mva_str(value) not in ("", "()"):
                    non_empty += 1
    assert non_empty > 0, "no pages row carries the stub entities in ner_per"
