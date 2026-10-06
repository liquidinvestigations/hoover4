"""Regex entity scanning over parsed text content.

It lives beside NER rather than under a P-number of its own because it is the same
question asked with a different extractor, and because the stage numbers are a stored
contract: `STAGE_INDEX` is a value in `processing_eta_samples` and is mirrored in the
website, so inventing a stage between P4 and P5 would move a number that other rows
already hold.

The scan makes one HTTP call per batch. A busy response preserves ordinary failure tries.
The activity keeps its first busy time across retries and uses a bounded busy budget.

**A segment boundary loses an entity.** `text_content.page_id` is a ~256 KB segment
ordinal for unpaged formats, and a value that straddles two segments is seen by neither,
at most one per boundary. The scanner takes an `offset` parameter precisely so a windowed
caller can overlap and deduplicate; this stage does not window, so the loss is real and
bounded rather than mysterious.
"""

import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timezone

import pyarrow as pa
from temporalio import activity

from database.clickhouse import get_collection_client, insert_arrow_durable
from tasks.remote_busy_retry import with_remote_busy_retry
from tasks.heartbeat import HeartbeatClock, stop_if_worker_is_stopping, with_heartbeat
from tasks.plan_utils import clean_text
from tasks.regex_entities import (
    FACET_BY_ENTITY_TYPE,
    assert_parallel_value_arrays,
    money_bucket_from_value_json,
)
from tasks.red_flags import load_calibration, text_digest
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
@with_remote_busy_retry
@with_heartbeat
def scan_regex_entities_for_hashes(params: ScanRegexEntitiesParams) -> ScanRegexEntitiesResult:
    """Scan missing regex and signal versions from each current text segment.

    Verify scanner versions and spans before writing completion watermarks.
    Store signal hits durably before their completion watermark.
    """
    collection_dataset: str = params.collection_dataset
    item_hashes: list[str] = params.hashes
    plan_hash: str = params.plan_hash
    heartbeat = HeartbeatClock()
    heartbeat.beat("reading the scanner rule set version")

    health = scanner_health()
    rule_set_version = health["rule_set_version"]
    signal_set_version = health["signal_set_version"]

    with get_collection_client(params.collectionname) as client:
        text_segments = client.query_arrow("""
            SELECT file_hash, extracted_by, page_id, argMax(text_bytes, version) AS text_bytes,
                   max(version) AS text_version
            FROM text_content
            WHERE collection_dataset = {collection_dataset:String}
              AND file_hash IN {item_hashes:Array(String)}
            GROUP BY file_hash, extracted_by, page_id
        """, {"collection_dataset": collection_dataset, "item_hashes": item_hashes}).to_pylist()
        bound = {"ds": collection_dataset, "hashes": item_hashes,
                 "rule": rule_set_version, "signal": signal_set_version}
        regex_done = {segment_key(row) for row in client.query_arrow("""
            SELECT file_hash, extracted_by, page_id FROM regex_scanned
            WHERE collection_dataset = {ds:String} AND file_hash IN {hashes:Array(String)}
              AND rule_set_version = {rule:UInt32}
        """, bound).to_pylist()}
        signal_done = {segment_key(row): int(row["text_version"]) for row in client.query_arrow("""
            SELECT file_hash, extracted_by, page_id, argMax(text_version, scan_version) AS text_version
            FROM signal_scanned
            WHERE collection_dataset = {ds:String} AND file_hash IN {hashes:Array(String)}
              AND signal_set_version = {signal:String}
            GROUP BY file_hash, extracted_by, page_id
        """, bound).to_pylist()}
        text_segments = [row for row in text_segments if segment_key(row) not in regex_done
                         or signal_done.get(segment_key(row)) != int(row["text_version"])]
        if not text_segments:
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
    signal_rows = []
    signal_watermarks = []
    scan_version = time.time_ns()
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
        selected = [i for i, row in enumerate(text_content)
                    if ner_reads_variant(row['extracted_by'], variants_present.get(row['file_hash'], ()))]
        skipped_count += len(text_content) - len(selected)
        regex_indices = [i for i in selected if segment_key(text_content[i]) not in regex_done]
        signal_indices = [i for i in selected
                          if signal_done.get(segment_key(text_content[i])) != int(text_content[i]["text_version"])]
        scanned = scan_batches([cleaned_texts[i] for i in regex_indices], "/scan_batch",
                               "rule_set_version", rule_set_version)
        signals = scan_batches([cleaned_texts[i] for i in signal_indices], "/signal_batch",
                               "signal_set_version", signal_set_version, spans=True)
        result_by_index = dict(zip(regex_indices, scanned))
        signal_by_index = dict(zip(signal_indices, signals))
        scanned_count += len(set(regex_indices) | set(signal_indices))
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
            if segment_key(text_row) not in regex_done:
                watermark_rows.append({**{name: text_row[name] for name in
                    ("collection_dataset", "file_hash", "extracted_by", "page_id")},
                    "text_bytes": len(cleaned_texts[i].encode("utf-8"))})
            if signal_done.get(segment_key(text_row)) != int(text_row["text_version"]):
                digest = text_digest(cleaned_texts[i])
                common = {name: text_row[name] for name in ("collection_dataset", "file_hash", "extracted_by", "page_id")}
                common.update(signal_set_version=signal_set_version, text_digest=digest, scan_version=scan_version)
                by_category = defaultdict(list)
                encoded = cleaned_texts[i].encode("utf-8")
                for hit in signal_by_index.get(i, {}).get("hits", []):
                    validate_signal_hit(encoded, hit)
                    by_category[hit["category"]].append(hit)
                for category, hits in by_category.items():
                    row = dict(common, category=category)
                    for column, field in SIGNAL_ARRAYS.items():
                        row[column] = [hit.get(field, []) if field == "flags" else hit[field] for hit in hits]
                    signal_rows.append(row)
                signal_watermarks.append(dict(common, text_version=int(text_row["text_version"])))
        heartbeat.beat(f"scanned {scanned_count}/{len(text_segments)} texts")

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
        if watermark_rows:
            insert_arrow_durable(client, "regex_scanned", pa.table({
                "collection_dataset": pa.array([r['collection_dataset'] for r in watermark_rows], type=pa.string()),
                "file_hash": pa.array([r['file_hash'] for r in watermark_rows], type=pa.string()),
                "extracted_by": pa.array([r['extracted_by'] for r in watermark_rows], type=pa.string()),
                "page_id": pa.array([r['page_id'] for r in watermark_rows], type=pa.uint32()),
                "rule_set_version": pa.array([rule_set_version] * len(watermark_rows), type=pa.uint32()),
                "text_bytes": pa.array([r['text_bytes'] for r in watermark_rows], type=pa.uint64()),
                "scanned_at": pa.array([now] * len(watermark_rows), type=pa.timestamp("s")),
            }))
        write_signal_rows(client, signal_rows, signal_watermarks)


    log.info(
        f"{collection_dataset} (plan {plan_hash[:8]}): scanned {scanned_count} of "
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


SIGNAL_ARRAYS = {"starts": "start", "ends": "end", "terms": "term", "concepts": "concept",
                 "languages": "lang", "tiers": "tier", "speakers": "speaker", "flags": "flags", "texts": "text"}


def segment_key(row):
    return row["file_hash"], row["extracted_by"], row["page_id"]


def scan_batches(texts, route, version_field, version, *, spans=False):
    results = []
    for batch in batch_texts_by_chars(texts):
        stop_if_worker_is_stopping()
        request = {"texts": batch}
        if spans:
            request["spans"] = True
        reply = post_json([("regex-scanner", scanner_url(route))], request, service="regex_scan").data
        if reply.get(version_field) != version:
            raise RuntimeError("The scanner version changed during the activity.")
        if spans and reply.get("spans_served") is not True:
            raise RuntimeError("The scanner did not serve the requested signal spans.")
        rows = reply.get("results", [])
        if len(rows) != len(batch) or any(row.get("error") for row in rows):
            raise RuntimeError("The scanner did not complete every requested text.")
        if spans and any(not isinstance(row.get("hits"), list) for row in rows):
            raise RuntimeError("The scanner reply has no signal hit list.")
        results.extend(rows)
    return results


def validate_signal_hit(encoded: bytes, hit):
    start, end = hit["start"], hit["end"]
    if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= len(encoded):
        raise ValueError("The scanner returned invalid signal offsets.")
    if encoded[start:end].decode("utf-8") != hit["text"]:
        raise ValueError("The scanner signal does not match its source bytes.")
    if hit["category"] not in load_calibration()["categories"] or hit["tier"] not in ("L", "M", "H"):
        raise ValueError("The scanner returned an unknown signal category or tier.")


def write_signal_rows(client, hits, watermarks):
    if hits:
        types = {"page_id": pa.uint32(), "scan_version": pa.uint64(),
                 "starts": pa.list_(pa.uint32()), "ends": pa.list_(pa.uint32()),
                 "flags": pa.list_(pa.list_(pa.string()))}
        for name in SIGNAL_ARRAYS:
            types.setdefault(name, pa.list_(pa.string()))
        for row in hits:
            if len({len(row[name]) for name in SIGNAL_ARRAYS}) != 1:
                raise ValueError("Signal occurrence arrays have different lengths.")
        insert_arrow_durable(client, "signal_hit", pa.table({
            name: pa.array([row[name] for row in hits], type=types.get(name, pa.string()))
            for name in hits[0]}))
    if watermarks:
        types = {"page_id": pa.uint32(), "text_version": pa.uint64(), "scan_version": pa.uint64()}
        insert_arrow_durable(client, "signal_scanned", pa.table({
            name: pa.array([row[name] for row in watermarks], type=types.get(name, pa.string()))
            for name in watermarks[0]}))
