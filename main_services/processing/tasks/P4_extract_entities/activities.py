"""NLP stage activities: named-entity extraction over parsed text content.

Runs on ``processing-nlp-queue``. Failure policy: NER errors are NOT swallowed.
An exception fails the activity so Temporal retries it; only after the retries
are exhausted does the workflow record the failure in ``processing_errors``.
A document with no entities must be visible as a failure, never as a silently
empty result.
"""

import logging
from datetime import datetime, timezone

import pyarrow as pa
from temporalio import activity

from database.clickhouse import get_collection_client
from tasks.plan_utils import clean_text
from tasks.P5_index_data.string_term_encodings import get_string_term_ids

from .extract_ner_from_text import extract_ner_from_texts
from .params import ExtractEntitiesParams, ExtractEntitiesResult

log = logging.getLogger(__name__)

# Texts per NER-service request. Bounds request size and makes partial progress
# possible (today's alternative is the whole activity chunk in one request).
NLP_BATCH_TEXTS = 64

# Identifier written to nlp_processed.nlp_model. Bump it when the NER model or
# service changes so every segment is reprocessed under the new identifier.
NLP_MODEL = "ner-default"


@activity.defn
def extract_entities_for_hashes(params: ExtractEntitiesParams) -> ExtractEntitiesResult:
    """Run NER over the plan's text segments and write entity_hit + watermark rows.

    Segments already present in ``nlp_processed`` for this ``nlp_model`` are
    skipped (left-anti join), which makes the stage cheaply re-runnable.
    """
    collection_dataset: str = params.collection_dataset
    item_hashes: list[str] = params.hashes
    plan_hash: str = params.plan_hash

    with get_collection_client(params.collectionname) as client:
        text_content = client.query_arrow("""
            SELECT t.collection_dataset, t.file_hash, t.extracted_by, t.page_id, t.text
            FROM text_content AS t
            LEFT ANTI JOIN nlp_processed AS n
                ON n.collection_dataset = t.collection_dataset
                AND n.file_hash = t.file_hash
                AND n.extracted_by = t.extracted_by
                AND n.page_id = t.page_id
                AND n.nlp_model = {nlp_model:String}
            WHERE t.collection_dataset = {collection_dataset:String}
            AND t.file_hash IN {item_hashes:Array(String)}
        """, {
            "collection_dataset": collection_dataset,
            "item_hashes": item_hashes,
            "nlp_model": NLP_MODEL,
        }).to_pylist()

    if not text_content:
        log.info(f"{collection_dataset} (plan {plan_hash[:8]}): nothing to NER-process")
        return ExtractEntitiesResult(text_segments=0, entity_groups=0)

    cleaned_texts = [clean_text(t['text']) for t in text_content]

    ner_results: list[dict[str, list[str]]] = []
    for i in range(0, len(cleaned_texts), NLP_BATCH_TEXTS):
        batch = cleaned_texts[i:i + NLP_BATCH_TEXTS]
        ner_results.extend(extract_ner_from_texts(batch))
        log.info(
            f"{collection_dataset} (plan {plan_hash[:8]}): "
            f"NER processed {len(ner_results)}/{len(cleaned_texts)} texts"
        )

    clickhouse_ner_rows = []
    ner_values = set()
    for text_row, ner_result in zip(text_content, ner_results):
        for entity_type, entity_values in ner_result.items():
            clickhouse_ner_rows.append({
                "collection_dataset": text_row['collection_dataset'],
                "file_hash": text_row['file_hash'],
                "extracted_by": text_row['extracted_by'],
                "page_id": text_row['page_id'],
                "entity_type": entity_type,
                "entity_values": entity_values,
            })
            ner_values.update(entity_values)

    # Populate the term dictionary here. The indexing stage calls the same
    # function with the same values and gets cache hits; the ids are
    # content-derived (hash_string_to_uint63), so there is no ordering dependency.
    get_string_term_ids(params.collectionname, collection_dataset, 'ner', ner_values)

    with get_collection_client(params.collectionname) as client:
        if clickhouse_ner_rows:
            tbl_ner = pa.table({
                "collection_dataset": pa.array([row['collection_dataset'] for row in clickhouse_ner_rows], type=pa.string()),
                "file_hash": pa.array([row['file_hash'] for row in clickhouse_ner_rows], type=pa.string()),
                "extracted_by": pa.array([row['extracted_by'] for row in clickhouse_ner_rows], type=pa.string()),
                "page_id": pa.array([row['page_id'] for row in clickhouse_ner_rows], type=pa.uint32()),
                "entity_type": pa.array([row['entity_type'] for row in clickhouse_ner_rows], type=pa.string()),
                "entity_values": pa.array([row['entity_values'] for row in clickhouse_ner_rows], type=pa.list_(pa.string())),
            })
            client.insert_arrow("entity_hit", tbl_ner)

        # Watermark rows, one per processed segment. text_bytes is the byte
        # length of the cleaned text actually indexed - part 6's shard planner
        # reads it from here. ClickHouse DateTime columns are naive UTC.
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        tbl_processed = pa.table({
            "collection_dataset": pa.array([row['collection_dataset'] for row in text_content], type=pa.string()),
            "file_hash": pa.array([row['file_hash'] for row in text_content], type=pa.string()),
            "extracted_by": pa.array([row['extracted_by'] for row in text_content], type=pa.string()),
            "page_id": pa.array([row['page_id'] for row in text_content], type=pa.uint32()),
            "nlp_model": pa.array([NLP_MODEL] * len(text_content), type=pa.string()),
            "text_bytes": pa.array([len(text.encode('utf-8')) for text in cleaned_texts], type=pa.uint64()),
            "processed_at": pa.array([now] * len(text_content), type=pa.timestamp("s")),
        })
        client.insert_arrow("nlp_processed", tbl_processed)

    log.info(
        f"{collection_dataset} (plan {plan_hash[:8]}): extracted "
        f"{len(clickhouse_ner_rows)} entity groups from {len(text_content)} text segments"
    )
    return ExtractEntitiesResult(text_segments=len(text_content), entity_groups=len(clickhouse_ner_rows))
