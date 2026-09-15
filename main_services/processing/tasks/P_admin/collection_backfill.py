"""Activities that list finished plans for collection-wide backfill operations."""

from dataclasses import dataclass

from temporalio import activity

from tasks.heartbeat import with_heartbeat


@dataclass
class CollectionBackfillParams:
    """The operation that records plans selected for a collection backfill."""

    op_id: str
    collectionname: str


def _record_finished_plans(params: CollectionBackfillParams) -> list[list[str]]:
    from database.clickhouse import get_collection_client
    from database.operation_ledger import insert_operation_plans

    with get_collection_client(params.collectionname) as client:
        rows = client.query(
            "SELECT collection_dataset, plan_hash FROM processing_plan_finished FINAL "
            "ORDER BY collection_dataset, plan_hash"
        ).result_rows
    plans = [[str(collection_dataset), str(plan_hash)] for collection_dataset, plan_hash in rows]
    by_dataset: dict[str, list[str]] = {}
    for collection_dataset, plan_hash in plans:
        by_dataset.setdefault(collection_dataset, []).append(plan_hash)
    for collection_dataset, plan_hashes in by_dataset.items():
        insert_operation_plans(
            params.collectionname,
            params.op_id,
            collection_dataset,
            plan_hashes,
            "backfill",
        )
    return plans


@activity.defn
@with_heartbeat
def clear_unattributed_entities(params: CollectionBackfillParams) -> list[list[str]]:
    """Delete unattributed entity rows and return the finished plans to re-run."""
    from database.clickhouse import get_collection_client

    with get_collection_client(params.collectionname) as client:
        settings = {"mutations_sync": 2}
        client.command("""
            ALTER TABLE nlp_processed DELETE WHERE (file_hash, extracted_by, page_id) IN (
                SELECT file_hash, extracted_by, page_id FROM entity_hit FINAL
                WHERE nlp_model = ''
            )
        """, settings=settings)
        client.command(
            "ALTER TABLE entity_hit DELETE WHERE nlp_model = ''", settings=settings
        )
    return _record_finished_plans(params)


@activity.defn
@with_heartbeat
def list_finished_plans(params: CollectionBackfillParams) -> list[list[str]]:
    """Return the finished plans that require vector backfill."""
    return _record_finished_plans(params)
