"""NLP stage activities: named-entity extraction over parsed text content.

Runs on ``processing-nlp-queue``. Failure policy: NER errors are NOT swallowed.
An exception fails the activity so Temporal retries it; only after the retries
are exhausted does the workflow record the failure in ``processing_errors``.
A document with no entities must be visible as a failure, never as a silently
empty result.
"""

import logging
import os
from datetime import datetime, timezone

import pyarrow as pa
from temporalio import activity

from database.clickhouse import get_collection_client
from tasks.heartbeat import HeartbeatClock, with_heartbeat
from tasks.plan_utils import clean_text
from tasks.P6_index_data.string_term_encodings import get_string_term_ids

from .extract_ner_from_text import NLP_MODEL_BY_PROVIDER, extract_ner_from_texts
from .params import ExtractEntitiesParams, ExtractEntitiesResult

log = logging.getLogger(__name__)

# Texts per NER-service request. Bounds request size and makes partial progress
# possible (today's alternative is the whole activity chunk in one request).
NLP_BATCH_TEXTS = 64

# Characters per NER-service request, and the limit that actually matters.
#
# A count alone does not bound anything: a text may be up to the service's
# NER_MAX_TEXT_CHARS (1 M), so 64 of them is up to 64 MB of text in one request — and the
# NER server holds a parsed document for every text in the batch at once. On a corpus of
# large plain-text files that drove the spaCy container past a 4 GB limit, then past a
# 12 GB one; the cgroup killed uvicorn and every in-flight activity failed with
# `Connection refused` against a container that looked healthy by the time anyone looked.
#
# Budgeting by characters makes the peak a property of this constant instead of a
# property of the corpus. The value equals the service's per-text ceiling, so the worst
# batch is the same size as the worst single text — a document already too large to batch
# with anything simply travels alone.
NLP_BATCH_CHARS = 1_000_000


def batch_texts_by_chars(texts, max_texts=NLP_BATCH_TEXTS, max_chars=NLP_BATCH_CHARS):
    """Split `texts` into request-sized batches, bounded by count AND by characters.

    A text longer than `max_chars` is emitted on its own rather than dropped: the service
    decides whether it is processable, and silently skipping it here would lose that
    document's entities with no error anywhere.
    """
    batch: list[str] = []
    chars = 0
    for text in texts:
        if batch and (len(batch) >= max_texts or chars + len(text) > max_chars):
            yield batch
            batch, chars = [], 0
        batch.append(text)
        chars += len(text)
    if batch:
        yield batch


def configured_nlp_model() -> str:
    """The ``nlp_model`` this worker *intends* to write.

    Used for the left-anti join only. What actually gets written is whatever
    provider served the request, which differs under fallback -- and that is the
    designed behaviour, not a bug: segments processed on the CPU twin during a
    GPU outage still have no GPU watermark, so they reprocess correctly under
    ``ner-gpu-xlmr`` once the host returns. Both sets coexist by design.
    """
    provider = (os.getenv("NER_PROVIDER") or "gpu").strip() or "gpu"
    if provider == "both":
        provider = "gpu"
    return NLP_MODEL_BY_PROVIDER.get(provider, f"ner-{provider}")


@activity.defn
@with_heartbeat
def extract_entities_for_hashes(params: ExtractEntitiesParams) -> ExtractEntitiesResult:
    """Run NER over the plan's text segments and write entity_hit + watermark rows.

    Segments already present in ``nlp_processed`` for this ``nlp_model`` are
    skipped (left-anti join), which makes the stage cheaply re-runnable.
    """
    collection_dataset: str = params.collection_dataset
    item_hashes: list[str] = params.hashes
    plan_hash: str = params.plan_hash
    nlp_model = configured_nlp_model()
    heartbeat = HeartbeatClock()
    heartbeat.beat("querying text_content")

    with get_collection_client(params.collectionname) as client:
        # FINAL for the same reason P5 and P6 need it: a re-parse leaves a second
        # ReplacingMergeTree row for the segment until the background merge collapses it,
        # and the anti-join cannot tell the copies apart — so the page is sent to the NER
        # model twice and writes two sets of `entity_hit` rows.
        text_content = client.query_arrow("""
            SELECT t.collection_dataset, t.file_hash, t.extracted_by, t.page_id, t.text
            FROM text_content AS t FINAL
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
            "nlp_model": nlp_model,
        }).to_pylist()

    if not text_content:
        log.info(f"{collection_dataset} (plan {plan_hash[:8]}): nothing to NER-process")
        return ExtractEntitiesResult(text_segments=0, entity_groups=0)

    cleaned_texts = [clean_text(t['text']) for t in text_content]

    ner_results: list[dict[str, list[str]]] = []
    # One model per text, not one per activity: the circuit breaker can open
    # part-way through, so batch 1 may be served by the GPU and batch 2 by the
    # CPU twin. Recording a single activity-wide model would attribute rows to a
    # provider that never saw them.
    served_models: list[str] = []
    for batch in batch_texts_by_chars(cleaned_texts):
        batch_results, batch_model = extract_ner_from_texts(batch)
        ner_results.extend(batch_results)
        served_models.extend([batch_model] * len(batch))
        # In-loop heartbeat: evidence of forward progress, not merely of a live
        # thread. This is the loop whose stalls are measured in tens of minutes
        # when only start_to_close_timeout guards it.
        heartbeat.beat(f"NER {len(ner_results)}/{len(cleaned_texts)} texts")
        log.info(
            f"{collection_dataset} (plan {plan_hash[:8]}): "
            f"NER processed {len(ner_results)}/{len(cleaned_texts)} texts "
            f"via {batch_model}"
        )

    clickhouse_ner_rows = []
    ner_values = set()
    for text_row, ner_result, served_model in zip(text_content, ner_results, served_models):
        for entity_type, entity_values in ner_result.items():
            clickhouse_ner_rows.append({
                "collection_dataset": text_row['collection_dataset'],
                "file_hash": text_row['file_hash'],
                "extracted_by": text_row['extracted_by'],
                "page_id": text_row['page_id'],
                # Per row, and the provider that actually served it. entity_hit has
                # nlp_model in its ORDER BY, so two providers' hits for the same
                # (file, variant, page, type) coexist. Leaving it empty would collapse
                # them onto one key and make whichever provider ran last the only one
                # with entities -- silently, with no error and simply fewer facets.
                "nlp_model": served_model,
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
                "nlp_model": pa.array([row['nlp_model'] for row in clickhouse_ner_rows], type=pa.string()),
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
            # The provider that ACTUALLY served each text, never the configured
            # one -- under fallback they differ, and that difference is the only
            # record that a GPU outage happened at all.
            "nlp_model": pa.array(served_models, type=pa.string()),
            "text_bytes": pa.array([len(text.encode('utf-8')) for text in cleaned_texts], type=pa.uint64()),
            "processed_at": pa.array([now] * len(text_content), type=pa.timestamp("s")),
        })
        client.insert_arrow("nlp_processed", tbl_processed)

    log.info(
        f"{collection_dataset} (plan {plan_hash[:8]}): extracted "
        f"{len(clickhouse_ner_rows)} entity groups from {len(text_content)} text segments"
    )
    return ExtractEntitiesResult(text_segments=len(text_content), entity_groups=len(clickhouse_ner_rows))
