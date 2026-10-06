"""Regex entity scanning over parsed text content.

It lives beside NER rather than under a P-number of its own because it is the same
question asked with a different extractor, and because the stage numbers are a stored
contract: `STAGE_INDEX` is a value in `processing_eta_samples` and is mirrored in the
website, so inventing a stage between P4 and P5 would move a number that other rows
already hold.

The scan is one HTTP call per batch to a service with no fallback twin. A 503 from it is
admission control, which `tasks.remote.post_json` already raises as retryable. The right
answer to a full scan queue is to come back, never to scan somewhere else.

**A segment boundary loses an entity.** `text_content.page_id` is a ~256 KB segment
ordinal for unpaged formats, and a value that straddles two segments is seen by neither,
at most one per boundary. The scanner takes an `offset` parameter precisely so a windowed
caller can overlap and deduplicate; this stage does not window, so the loss is real and
bounded rather than mysterious.
"""

import json
import logging
import os
from datetime import datetime, timezone

import pyarrow as pa
from temporalio import activity

from database.clickhouse import get_collection_client, insert_arrow_durable
from tasks.heartbeat import HeartbeatClock, stop_if_worker_is_stopping, with_heartbeat
from tasks.plan_utils import clean_text
from tasks.regex_entities import (
    FACET_BY_ENTITY_TYPE,
    assert_parallel_value_arrays,
    money_bucket_from_value_json,
)
from tasks.remote import post_json, scanner_health
from tasks.text_sources import fetch_text_batch, ner_reads_variant, plan_text_batches
from tasks.P6_index_data.string_term_encodings import get_string_term_ids_by_field

from .params import ScanRegexEntitiesParams, ScanRegexEntitiesResult

log = logging.getLogger(__name__)

#: The scan runs on the common queue rather than on a queue of its own: it is CPU work in
#: another container, and the activity here only moves rows.
REGEX_TASK_QUEUE = "processing-common-queue"

#: Texts per request, and characters per request.
#:
#: The characters are the bound that matters. `NLP_BATCH_CHARS` is 250 000 because a GPU
#: slot must not be held for seconds by one request; the scanner is memory-light. 188 MB
#: at full load, with no per-request growth, and runs at about 0.85 MB/s per thread, so a
#: megabyte is roughly a second of one thread's work rather than a queue-blocking unit.
REGEX_BATCH_CHARS = 1_000_000
REGEX_BATCH_TEXTS = 64


@activity.defn
@with_heartbeat
def scan_regex_entities_for_hashes(params: ScanRegexEntitiesParams) -> ScanRegexEntitiesResult:
    """Scan the plan's text segments and write `regex_entity_hit` + watermark rows.

    The rule set version is read from the service once, before any batch, and every batch
    response is checked against it. An image swapped mid-activity would otherwise file the
    new rules' values under the old version's watermark, and nothing downstream would ever
    reconsider them.
    """
    collection_dataset: str = params.collection_dataset
    item_hashes: list[str] = params.hashes
    plan_hash: str = params.plan_hash
    heartbeat = HeartbeatClock()
    heartbeat.beat("reading the scanner rule set version")

    rule_set_version = scanner_health()["rule_set_version"]

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
            LEFT ANTI JOIN regex_scanned AS s
                ON s.collection_dataset = t.collection_dataset
                AND s.file_hash = t.file_hash
                AND s.extracted_by = t.extracted_by
                AND s.page_id = t.page_id
                AND s.rule_set_version = {rule_set_version:UInt32}
            WHERE t.collection_dataset = {collection_dataset:String}
            AND t.file_hash IN {item_hashes:Array(String)}
        """, {
            "collection_dataset": collection_dataset,
            "item_hashes": item_hashes,
            "rule_set_version": rule_set_version,
        }).to_pylist()

        if not text_segments:
            log.info(f"{collection_dataset} (plan {plan_hash[:8]}): nothing to scan")
            return ScanRegexEntitiesResult(0, 0, rule_set_version)

        # Which variants each file HAS, from the whole table: the anti-join has already
        # removed everything a previous run covered, so a file whose parsed body was done
        # last time would otherwise look like a file that has none, and its MIME envelope
        # would be scanned after all.
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

    rows: list[dict] = []
    term_values: dict[str, set[str]] = {}
    watermark_rows: list[dict] = []
    scanned_count = 0
    skipped_count = 0
    segment_batches = plan_text_batches([
        ((row['file_hash'], row['extracted_by'], row['page_id']), int(row['text_bytes']))
        for row in text_segments
    ])
    for segment_batch in segment_batches:
        with get_collection_client(params.collectionname) as client:
            text_content = fetch_text_batch(client, collection_dataset, segment_batch)
        cleaned_texts = [clean_text(row['text']) for row in text_content]
        scan_indices = [
            i for i, row in enumerate(text_content)
            if ner_reads_variant(row['extracted_by'], variants_present.get(row['file_hash'], ()))
        ]
        skipped_count += len(text_content) - len(scan_indices)
        scan_texts = [cleaned_texts[i] for i in scan_indices]
        scanned: list[dict] = []
        for batch in batch_texts_by_chars(scan_texts):
            stop_if_worker_is_stopping(f"scanned {scanned_count + len(scanned)}/{len(text_segments)} texts")
            result = post_json(
                [("regex-scanner", scanner_url("/scan_batch"))],
                {"texts": batch},
                service="regex_scan",
            )
            served_version = result.data.get("rule_set_version")
            if served_version != rule_set_version:
                raise RuntimeError(
                    f"the scanner reported rule set {rule_set_version} on /health and "
                    f"{served_version} on /scan_batch. The image changed mid-activity, and "
                    f"writing these rows would file them under the wrong version"
                )
            scanned.extend(result.data["results"])
            heartbeat.beat(f"scanned {scanned_count + len(scanned)}/{len(text_segments)} texts")
        scanned_count += len(scan_texts)
        result_by_index = dict(zip(scan_indices, scanned))
        for i, text_row in enumerate(text_content):
            for entity_type, values in (result_by_index.get(i) or {}).get("types", {}).items():
                row = {
                    "collection_dataset": text_row['collection_dataset'],
                    "file_hash": text_row['file_hash'],
                    "extracted_by": text_row['extracted_by'],
                    "page_id": text_row['page_id'],
                    "rule_set_version": rule_set_version,
                    "entity_type": entity_type,
                    "entity_values": [v["value"] for v in values],
                    "entity_rule_ids": [v["rule_id"] for v in values],
                    "entity_value_json": [_dumps(v["value_json"]) for v in values],
                    "entity_counts": [int(v["count"]) for v in values],
                    "entity_texts": [v.get("text", "") for v in values],
                }
                assert_parallel_value_arrays(row)
                rows.append(row)
                facet = FACET_BY_ENTITY_TYPE.get(entity_type)
                if facet is None:
                    continue
                if entity_type == "money":
                    keys = {
                        bucket for bucket in (
                            money_bucket_from_value_json(payload)
                            for payload in row["entity_value_json"]
                        ) if bucket
                    }
                else:
                    keys = set(row["entity_values"])
                term_values.setdefault(facet.term_field, set()).update(keys)
            watermark_rows.extend({
                "collection_dataset": text_row['collection_dataset'],
                "file_hash": text_row['file_hash'],
                "extracted_by": text_row['extracted_by'],
                "page_id": text_row['page_id'],
                "text_bytes": len(cleaned_texts[i].encode('utf-8')),
            } for i, text_row in enumerate(text_content))

    if skipped_count:
        log.info(
            f"{collection_dataset} (plan {plan_hash[:8]}): {skipped_count}/{len(text_segments)} "
            f"text segments are a redundant variant, not scanning them"
        )

    # Populate the term dictionary here. The indexing stage calls the same function with
    # the same values and gets cache hits; the ids are content-derived, so there is no
    # ordering dependency between the two.
    get_string_term_ids_by_field(params.collectionname, collection_dataset, term_values)

    with get_collection_client(params.collectionname) as client:
        if rows:
            insert_arrow_durable(client, "regex_entity_hit", pa.table({
                "collection_dataset": pa.array([r['collection_dataset'] for r in rows], type=pa.string()),
                "file_hash": pa.array([r['file_hash'] for r in rows], type=pa.string()),
                "extracted_by": pa.array([r['extracted_by'] for r in rows], type=pa.string()),
                "page_id": pa.array([r['page_id'] for r in rows], type=pa.uint32()),
                "rule_set_version": pa.array([r['rule_set_version'] for r in rows], type=pa.uint32()),
                "entity_type": pa.array([r['entity_type'] for r in rows], type=pa.string()),
                "entity_values": pa.array([r['entity_values'] for r in rows], type=pa.list_(pa.string())),
                "entity_rule_ids": pa.array([r['entity_rule_ids'] for r in rows], type=pa.list_(pa.string())),
                "entity_value_json": pa.array([r['entity_value_json'] for r in rows], type=pa.list_(pa.string())),
                "entity_counts": pa.array([r['entity_counts'] for r in rows], type=pa.list_(pa.uint32())),
                "entity_texts": pa.array([r['entity_texts'] for r in rows], type=pa.list_(pa.string())),
            }))

        # ClickHouse DateTime columns are naive UTC.
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        insert_arrow_durable(client, "regex_scanned", pa.table({
            "collection_dataset": pa.array([r['collection_dataset'] for r in watermark_rows], type=pa.string()),
            "file_hash": pa.array([r['file_hash'] for r in watermark_rows], type=pa.string()),
            "extracted_by": pa.array([r['extracted_by'] for r in watermark_rows], type=pa.string()),
            "page_id": pa.array([r['page_id'] for r in watermark_rows], type=pa.uint32()),
            "rule_set_version": pa.array([rule_set_version] * len(watermark_rows), type=pa.uint32()),
            "text_bytes": pa.array([r['text_bytes'] for r in watermark_rows], type=pa.uint64()),
            "scanned_at": pa.array([now] * len(watermark_rows), type=pa.timestamp("s")),
        }))

    log.info(
        f"{collection_dataset} (plan {plan_hash[:8]}): scanned {len(scan_texts)} of "
        f"{len(text_segments)} text segments under rule set {rule_set_version}, "
        f"writing {len(rows)} entity groups"
    )
    return ScanRegexEntitiesResult(len(text_segments), len(rows), rule_set_version)


def batch_texts_by_chars(texts, max_texts=REGEX_BATCH_TEXTS, max_chars=REGEX_BATCH_CHARS):
    """Split `texts` into request-sized batches, bounded by count AND by characters.

    A text longer than `max_chars` travels alone rather than being dropped: the service
    decides whether it is scannable, and silently skipping it here would lose that
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


def scanner_url(path: str) -> str:
    """The scanner endpoint. Always configured, so this never has to answer "absent"."""
    base = (os.getenv("REGEX_SCANNER_URL") or "http://hoover4-regex-entity-scanner:19705").rstrip("/")
    return f"{base}{path}"


def _dumps(value) -> str:
    """Sorted keys and no whitespace, so the same value produces the same string on every
    run. The column is part of a ReplacingMergeTree row that a re-scan must not change
    for no reason."""
    return json.dumps(value, separators=(",", ":"), sort_keys=True)
