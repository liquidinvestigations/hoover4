"""Helpers shared by more than one pipeline stage (P4 NLP, P5 indexing).

Neither stage owns these; keep them stage-neutral.
"""

from dataclasses import dataclass

from temporalio import activity


@dataclass
class FetchPlanHashesParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str


@activity.defn
def fetch_plan_hashes(params: FetchPlanHashesParams) -> list[str]:
    """Return the sorted, de-duplicated item hashes of one processing plan."""
    collection_dataset: str = params.collection_dataset
    plan_hash: str = params.plan_hash
    from database.clickhouse import get_collection_client
    with get_collection_client(params.collectionname) as client:
        hashes = client.query_arrow("""
            SELECT item_hashes
            FROM processing_plans
            WHERE collection_dataset = {collection_dataset:String} AND plan_hash = {plan_hash:String}
        """, {
            "collection_dataset": collection_dataset,
            "plan_hash": plan_hash
        }).to_pylist()[0]['item_hashes']
    return sorted(set(hashes))


def clean_text(text: str) -> str:
    """Normalize text the same way in every stage that stores or measures it.

    The NLP stage records ``len(clean_text(text).encode('utf-8'))`` as
    ``nlp_processed.text_bytes`` and the indexing stage indexes exactly this
    cleaned text, so the byte count and the indexed content never diverge.
    """
    if not text:
        return ''
    # TODO: try different encoding on utf-8 errors
    return text.encode('utf-8', errors='replace').decode('utf-8').strip()
