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

from database.clickhouse import get_collection_client, insert_arrow_durable
from tasks.entity_stoplist import filter_entity_values
from tasks.remote_busy_retry import with_remote_busy_retry
from tasks.heartbeat import HeartbeatClock, stop_if_worker_is_stopping, with_heartbeat
from tasks.plan_utils import clean_text
from tasks.text_sources import fetch_text_batch, ner_reads_variant, plan_text_batches
from tasks.P6_index_data.string_term_encodings import get_string_term_ids

from .extract_ner_from_text import NLP_MODEL_BY_PROVIDER, extract_ner_from_texts
from .params import ExtractEntitiesParams, ExtractEntitiesResult

log = logging.getLogger(__name__)

# Texts per NER-service request. Aligns with the server's advertised
# ``optimal_batch_size`` (32). Bounds request size and makes partial progress
# possible (today's alternative is the whole activity chunk in one request).
NLP_BATCH_TEXTS = 32

# Characters per NER-service request, and the limit that actually matters.
#
# A count alone does not bound anything: a text may be up to the service's
# NER_MAX_TEXT_CHARS (1 M), so 32 of them is up to 32 MB of text in one request, and the
# NER server holds a parsed document for every text in the batch at once. On a corpus of
# large plain-text files that drove the spaCy container past a 4 GB limit, then past a
# 12 GB one; the cgroup killed uvicorn and every in-flight activity failed with
# `Connection refused` against a container that looked healthy by the time anyone looked.
#
# Budgeting by characters makes the peak a property of this constant instead of a
# property of the corpus. The budget is well below one megabyte so a single request
# cannot occupy a GPU slot for seconds; a document already too large to batch with
# anything travels alone.
NLP_BATCH_CHARS = 250_000


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
@with_remote_busy_retry
@with_heartbeat
def extract_entities_for_hashes(params: ExtractEntitiesParams) -> ExtractEntitiesResult:
    """Run NER over the plan's text segments and write entity_hit + watermark rows.

    Segments already present in ``nlp_processed`` for this ``nlp_model`` are
    skipped (left-anti join), which makes the stage cheaply re-runnable.

    Not every stored segment is worth reading: ``text_sources.ner_reads_variant``
    drops a variant that is a worse copy of another variant of the same document
    (a mail file's MIME envelope beside its parsed body). What survives is
    filtered again by ``entity_stoplist``, which rejects the debris the model
    labels as confidently as a name. Both are write-time decisions, so every
    reader of ``entity_hit`` sees the same thing.
    """
    collection_dataset: str = params.collection_dataset
    item_hashes: list[str] = params.hashes
    plan_hash: str = params.plan_hash
    base_url = (os.getenv("NER_URL") or "").strip().rstrip("/")
    if not base_url:
        log.info(
            "%s (plan %s): NER_URL is empty (ner_provider = none or the GPU tier is off); "
            "skipping entity extraction",
            collection_dataset, plan_hash[:8],
        )
        return ExtractEntitiesResult(text_segments=0, entity_groups=0)
    nlp_model = configured_nlp_model()
    heartbeat = HeartbeatClock()
    heartbeat.beat("querying text_content")

    with get_collection_client(params.collectionname) as client:
        # Select one latest size for each segment before the watermark join.
        text_segments = client.query_arrow("""
            SELECT t.file_hash, t.extracted_by, t.page_id, t.text_bytes
            FROM (
                SELECT collection_dataset, file_hash, extracted_by, page_id,
                       argMax(text_bytes, version) AS text_bytes
                FROM text_content
                WHERE collection_dataset = {collection_dataset:String}
                  AND file_hash IN {item_hashes:Array(String)}
                GROUP BY collection_dataset, file_hash, extracted_by, page_id
            ) AS t
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

        if not text_segments:
            log.info(f"{collection_dataset} (plan {plan_hash[:8]}): nothing to NER-process")
            return ExtractEntitiesResult(text_segments=0, entity_groups=0)

        # Which variants each file HAS, from the whole table rather than from the rows
        # above: the anti-join has already removed everything a previous run processed, so
        # a file whose `email_parser` pages were done last time would otherwise look like
        # a file that has none -- and its envelope would be sent to the model after all.
        variants_present: dict[str, set[str]] = {}
        for row in client.query_arrow("""
            SELECT file_hash, groupUniqArray(extracted_by) AS variants
            FROM text_content
            WHERE collection_dataset = {collection_dataset:String}
            AND file_hash IN {item_hashes:Array(String)}
            GROUP BY file_hash
        """, {
            "collection_dataset": collection_dataset,
            "item_hashes": item_hashes,
        }).to_pylist():
            variants_present[row['file_hash']] = set(row['variants'])

    clickhouse_ner_rows = []
    ner_values = set()
    stopped_values = 0
    processed_rows: list[dict] = []
    processed_by_ner = 0
    skipped_count = 0
    segment_batches = plan_text_batches([
        ((row['file_hash'], row['extracted_by'], row['page_id']), int(row['text_bytes']))
        for row in text_segments
    ])
    for segment_batch in segment_batches:
        with get_collection_client(params.collectionname) as client:
            text_content = fetch_text_batch(client, collection_dataset, segment_batch)
        cleaned_texts = [clean_text(row['text']) for row in text_content]
        ner_indices = [
            i for i, row in enumerate(text_content)
            if ner_reads_variant(row['extracted_by'], variants_present.get(row['file_hash'], ()))
        ]
        skipped_count += len(text_content) - len(ner_indices)
        ner_texts = [cleaned_texts[i] for i in ner_indices]
        ner_results: list[dict[str, list[str]]] = []
        served_models: list[str] = []
        for batch in batch_texts_by_chars(ner_texts):
            stop_if_worker_is_stopping(f"NER {processed_by_ner + len(ner_results)}/{len(text_segments)} texts")
            batch_results, batch_model = extract_ner_from_texts(batch)
            ner_results.extend(batch_results)
            served_models.extend([batch_model] * len(batch))
            heartbeat.beat(f"NER {processed_by_ner + len(ner_results)}/{len(text_segments)} texts")
            log.info(
                f"{collection_dataset} (plan {plan_hash[:8]}): "
                f"NER processed {processed_by_ner + len(ner_results)}/{len(text_segments)} texts "
                f"via {batch_model}"
            )
        processed_by_ner += len(ner_texts)
        result_by_index: dict[int, dict[str, list[str]]] = dict(zip(ner_indices, ner_results))
        model_by_index: dict[int, str] = dict(zip(ner_indices, served_models))
        segment_models = [model_by_index.get(i, nlp_model) for i in range(len(text_content))]
        for i, (text_row, served_model) in enumerate(zip(text_content, segment_models)):
            for entity_type, raw_values in result_by_index.get(i, {}).items():
                entity_values = filter_entity_values(raw_values)
                stopped_values += len(raw_values) - len(entity_values)
                clickhouse_ner_rows.append({
                    "collection_dataset": text_row['collection_dataset'],
                    "file_hash": text_row['file_hash'],
                    "extracted_by": text_row['extracted_by'],
                    "page_id": text_row['page_id'],
                    "nlp_model": served_model,
                    "entity_type": entity_type,
                    "entity_values": entity_values,
                })
                ner_values.update(entity_values)
            processed_rows.append({
                "collection_dataset": text_row['collection_dataset'],
                "file_hash": text_row['file_hash'],
                "extracted_by": text_row['extracted_by'],
                "page_id": text_row['page_id'],
                "nlp_model": served_model,
                "text_bytes": len(cleaned_texts[i].encode('utf-8')),
            })

    if skipped_count:
        log.info(
            f"{collection_dataset} (plan {plan_hash[:8]}): {skipped_count}/{len(text_segments)} "
            f"text segments are a redundant variant, not sending them to NER"
        )

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
            insert_arrow_durable(client, "entity_hit", tbl_ner)

        # Watermark rows, one per processed segment. text_bytes is the byte
        # length of the cleaned text actually indexed - part 6's shard planner
        # reads it from here. ClickHouse DateTime columns are naive UTC.
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        tbl_processed = pa.table({
            "collection_dataset": pa.array([row['collection_dataset'] for row in processed_rows], type=pa.string()),
            "file_hash": pa.array([row['file_hash'] for row in processed_rows], type=pa.string()),
            "extracted_by": pa.array([row['extracted_by'] for row in processed_rows], type=pa.string()),
            "page_id": pa.array([row['page_id'] for row in processed_rows], type=pa.uint32()),
            # The provider that ACTUALLY served each text, never the configured
            # one -- under fallback they differ, and that difference is the only
            # record that a GPU outage happened at all. Segments no provider saw
            # carry the configured model; see segment_models.
            "nlp_model": pa.array([row['nlp_model'] for row in processed_rows], type=pa.string()),
            "text_bytes": pa.array([row['text_bytes'] for row in processed_rows], type=pa.uint64()),
            "processed_at": pa.array([now] * len(processed_rows), type=pa.timestamp("s")),
        })
        insert_arrow_durable(client, "nlp_processed", tbl_processed)

    log.info(
        f"{collection_dataset} (plan {plan_hash[:8]}): extracted "
        f"{len(clickhouse_ner_rows)} entity groups from {processed_by_ner} of "
        f"{len(text_segments)} text segments, dropping {stopped_values} stop-listed values"
    )
    return ExtractEntitiesResult(text_segments=len(text_segments), entity_groups=len(clickhouse_ner_rows))
