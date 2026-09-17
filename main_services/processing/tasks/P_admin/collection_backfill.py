"""Activities that list finished plans for collection-wide backfill operations."""

from dataclasses import dataclass, field

from temporalio import activity

from tasks.heartbeat import with_heartbeat


@dataclass
class CollectionBackfillParams:
    """The operation that records plans selected for a collection backfill."""

    op_id: str
    collectionname: str
    cursor: list[str] = field(default_factory=list)
    total: int = 0


@dataclass
class FinishedPlanPage:
    plans: list[list[str]]
    cursor: list[str]
    total: int


def _record_finished_plans(params: CollectionBackfillParams) -> FinishedPlanPage:
    from database.clickhouse import get_collection_client
    from database.operation_ledger import insert_operation_plans

    with get_collection_client(params.collectionname) as client:
        total = params.total or int(client.query(
            "SELECT count() FROM processing_plan_finished FINAL"
        ).result_rows[0][0])
        where = ("WHERE (collection_dataset, plan_hash) > "
                 "({ds:String}, {hash:String}) " if params.cursor else "")
        rows = client.query(
            "SELECT collection_dataset, plan_hash FROM processing_plan_finished FINAL "
            + where + "ORDER BY collection_dataset, plan_hash LIMIT 100",
            parameters={"ds": params.cursor[0], "hash": params.cursor[1]}
            if params.cursor else {},
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
    return FinishedPlanPage(plans, plans[-1] if plans else params.cursor, total)


@activity.defn
@with_heartbeat
def clear_unattributed_entities(params: CollectionBackfillParams) -> None:
    """Delete unattributed entity rows before any plan runs."""
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
    return None


@activity.defn
@with_heartbeat
def list_finished_plans(params: CollectionBackfillParams) -> FinishedPlanPage:
    """Return at most 100 finished plans and record their operation ledger rows."""
    return _record_finished_plans(params)
