"""Rolling ETA sampling for the admin processing page.

Why this exists: the website used to derive an ETA per request with a naive
linear extrapolation over a fixed 10-minute wall-clock window, counting rows
regardless of size. That put ``uniqExact``/``FINAL`` scans of every collection
database in the website request path and produced estimates with no memory.

This module moves the computation here, into a self-scheduling Temporal
workflow (:class:`CollectEtaSamples`), and writes one sample row per
(collection, dataset, stage) into the global ``processing_eta_samples`` table.
The website then only reads that table — a cheap, indexed query.

The estimate, in words:

* one rate per stage (P1 plan, P2/P3 execute, P4 NLP, P6 index), measured over
  the trailing 100 watermark *events* (plans created, plans finished, segments
  NLP-processed, documents indexed), not over a wall-clock window;
* each stage's rate is measured in every unit the raw data offers — items/s
  (blobs, plans, segments, documents) and, where the schema carries sizes,
  bytes/s (``blobs.blob_size_bytes``, ``processing_plans.plan_size_bytes``,
  ``nlp_processed.text_bytes``, ``text_content.text_bytes``);
* a remaining-time projection is computed from each unit and combined into one
  figure by taking the **more pessimistic** (larger) of the two. A defensible
  simple rule: the two units disagree most when item sizes are uneven, and the
  admin hurt by an optimistic ETA is worse than the hurt by a pessimistic one;
* retries re-emit watermarks for work already counted, so every count is a
  ``uniqExact`` over distinct watermark keys, never a row count;
* recursion (archives fanning out into more blobs) raises the denominator
  mid-run, so ``total`` is re-read on every sample and never cached;
* P0 (scan) is not sampled: ``blobs`` has no timestamp column and the stage has
  no knowable denominator, so no event-based rate is possible. The live count
  stays on the existing stage bar.

Throttling (rule: never put the pipeline's own storage under load to report on
the pipeline):

* every collection pass is timed; the workflow keeps the last 10 pass durations
  and waits at least ``20 x mean(last 10)`` before the next pass
  (:func:`next_interval_seconds`);
* a collection whose every stage is complete is skipped entirely — no queries,
  no sample rows, no throttle bookkeeping beyond the finished-set entry. It is
  re-validated every :data:`FINISHED_RECHECK_SECONDS` so a rescan of a
  "finished" collection eventually gets fresh estimates.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# Mirrors the STAGE_* constants in website/common/src/processing_types.rs.
# Duplicated deliberately: the two runtimes share no constants.
STAGE_PLAN = "P1_plan"
STAGE_EXECUTE = "P2_execute"
STAGE_NLP = "P4_nlp"
STAGE_INDEX = "P6_index"

#: Events per rate sample. A wall-clock window with three completions in it is a
#: rate with no information; 100 events is a sample.
RATE_WINDOW_EVENTS = 100

#: Multiplier for the self-throttle: wait at least this many times the mean cost
#: of the recent passes before running another one.
THROTTLE_FACTOR = 20

#: Pass durations kept for the throttle mean.
THROTTLE_HISTORY = 10

#: Lower bound on the interval, so an all-finished cluster (pass cost ~0) does
#: not busy-loop. The finished-set skip makes such passes nearly free, but they
#: still query the dataset registry.
MIN_INTERVAL_SECONDS = 60

#: How long a fully-complete collection is skipped before one re-validation
#: pass, so a rescan started against a "finished" collection gets ETAs again.
#: Five minutes: the skip is what honors "never recompute for a finished
#: collection" within the cadence; the recheck costs one pass at most this
#: often instead of every pass.
FINISHED_RECHECK_SECONDS = 300

#: Bound workflow history: continue-as-new after this many passes.
CONTINUE_AS_NEW_PASSES = 50


@dataclass
class CollectEtaSamplesParams:
    """Collections to skip this pass (recently observed fully complete)."""

    skip_collections: list[str] = field(default_factory=list)


@dataclass
class CollectEtaSamplesResult:
    duration_ms: int
    #: Collections observed fully complete this pass (join the skip set).
    completed_collections: list[str] = field(default_factory=list)
    #: Collections still making progress (leave the skip set).
    active_collections: list[str] = field(default_factory=list)


@dataclass
class EtaCollectorState:
    """Workflow state carried across continue-as-new."""

    recent_durations_ms: list[int] = field(default_factory=list)
    #: collectionname -> unix epoch after which it may be re-validated once.
    finished: dict[str, float] = field(default_factory=dict)
    passes: int = 0


@dataclass
class StageSample:
    stage: str
    done: int
    total: int
    rate_items_per_sec: float
    rate_bytes_per_sec: float
    eta_seconds: int


def rate_from_events(events: list[tuple[float, int, int]]) -> tuple[float, float]:
    """``(items/s, bytes/s)`` over a set of ``(epoch_ts, items, bytes)`` events.

    The rate is the sums divided by the span between the oldest and newest
    event. Fewer than two events, or events stamped inside the same second,
    carry no rate information and return ``(0, 0)``.
    """
    if len(events) < 2:
        return (0.0, 0.0)
    span = max(e[0] for e in events) - min(e[0] for e in events)
    if span <= 0:
        return (0.0, 0.0)
    items = sum(e[1] for e in events)
    nbytes = sum(e[2] for e in events)
    return (items / span, nbytes / span)


def combine_eta(eta_items: float, eta_bytes: float) -> int:
    """Combine the per-unit projections into one ETA in seconds (0 = no estimate).

    The rule is deliberately the pessimistic one — the larger projection wins.
    Weighting by recent predictive accuracy was considered and dropped: it adds
    a feedback loop (the weight depends on estimates that depend on the weight)
    for a number that is a best-effort hint, not a scheduling promise.
    """
    eta = max(eta_items, eta_bytes)
    if eta <= 0:
        return 0
    return int(eta + 0.5)


def remaining_projection(done: int, total: int, rate: float) -> float:
    """Seconds remaining in one unit, or 0 when no projection is possible."""
    if total <= done or rate <= 0.0:
        return 0.0
    return (total - done) / rate


def next_interval_seconds(recent_durations_ms: list[int]) -> float:
    """Throttle: at least ``THROTTLE_FACTOR x`` the mean of the recent pass costs."""
    if not recent_durations_ms:
        return float(MIN_INTERVAL_SECONDS)
    mean_ms = sum(recent_durations_ms) / len(recent_durations_ms)
    return max(float(MIN_INTERVAL_SECONDS), THROTTLE_FACTOR * mean_ms / 1000.0)


def _query(client, sql: str, ds: str) -> list:
    return client.query(sql, parameters={"ds": ds}).result_rows


def _epoch(ts: datetime) -> float:
    """Unix seconds of a ClickHouse ``DateTime`` (naive UTC by convention)."""
    return ts.replace(tzinfo=timezone.utc).timestamp()


def _sample_plan(client, ds: str) -> StageSample:
    """P1 — plan computation. Unit: blobs planned. Bytes from blob sizes."""
    done = _query(client, "SELECT uniqExact(item_hash) FROM processing_plan_hits WHERE collection_dataset = {ds:String}", ds)[0][0]
    total = _query(client, "SELECT uniqExact(blob_hash) FROM blobs WHERE collection_dataset = {ds:String}", ds)[0][0]
    done_bytes = _query(client, "SELECT sum(sz) FROM (SELECT plan_hash, any(plan_size_bytes) AS sz FROM processing_plans WHERE collection_dataset = {ds:String} GROUP BY plan_hash)", ds)[0][0] or 0
    total_bytes = _query(client, "SELECT sum(sz) FROM (SELECT blob_hash, any(blob_size_bytes) AS sz FROM blobs WHERE collection_dataset = {ds:String} GROUP BY blob_hash)", ds)[0][0] or 0
    events = [
        (_epoch(ts), int(items), int(size))
        for items, size, ts in _query(
            client,
            "SELECT argMax(length(item_hashes), created_at), argMax(plan_size_bytes, created_at), max(created_at) AS ts "
            "FROM processing_plans WHERE collection_dataset = {ds:String} "
            f"GROUP BY plan_hash ORDER BY ts DESC LIMIT {RATE_WINDOW_EVENTS}",
            ds,
        )
    ]
    rate_items, rate_bytes = rate_from_events(events)
    eta = combine_eta(
        remaining_projection(done, total, rate_items),
        remaining_projection(done_bytes, total_bytes, rate_bytes),
    )
    return StageSample(STAGE_PLAN, done, total, rate_items, rate_bytes, eta)


def _sample_execute(client, ds: str) -> StageSample:
    """P2/P3 — plan execution. Unit: plans. Bytes/items from the plan definitions."""
    done = _query(client, "SELECT uniqExact(plan_hash) FROM processing_plan_finished WHERE collection_dataset = {ds:String}", ds)[0][0]
    total = _query(client, "SELECT uniqExact(plan_hash) FROM processing_plans WHERE collection_dataset = {ds:String}", ds)[0][0]
    totals = _query(client, "SELECT sum(length(ih)), sum(sz) FROM (SELECT plan_hash, any(item_hashes) AS ih, any(plan_size_bytes) AS sz FROM processing_plans WHERE collection_dataset = {ds:String} GROUP BY plan_hash)", ds)[0]
    total_items, total_bytes = int(totals[0] or 0), int(totals[1] or 0)
    dones = _query(client, "SELECT sum(length(ih)), sum(sz) FROM (SELECT f.plan_hash, any(p.item_hashes) AS ih, any(p.plan_size_bytes) AS sz FROM processing_plan_finished f INNER JOIN processing_plans p ON p.collection_dataset = f.collection_dataset AND p.plan_hash = f.plan_hash WHERE f.collection_dataset = {ds:String} GROUP BY f.plan_hash)", ds)[0]
    done_items, done_bytes = int(dones[0] or 0), int(dones[1] or 0)
    events = [
        (_epoch(ts), int(items), int(size))
        for ts, size, items in _query(
            client,
            "SELECT max(f.finished_at) AS ts, argMax(p.plan_size_bytes, f.finished_at), "
            "argMax(length(p.item_hashes), f.finished_at) "
            "FROM processing_plan_finished f "
            "INNER JOIN processing_plans p ON p.collection_dataset = f.collection_dataset AND p.plan_hash = f.plan_hash "
            "WHERE f.collection_dataset = {ds:String} "
            f"GROUP BY f.plan_hash ORDER BY ts DESC LIMIT {RATE_WINDOW_EVENTS}",
            ds,
        )
    ]
    rate_items, rate_bytes = rate_from_events(events)
    eta = combine_eta(
        remaining_projection(done_items, total_items, rate_items),
        remaining_projection(done_bytes, total_bytes, rate_bytes),
    )
    return StageSample(STAGE_EXECUTE, done, total, rate_items, rate_bytes, eta)


def _sample_nlp(client, ds: str) -> StageSample:
    """P4 — NLP/NER. Unit: text segments. Bytes from stored ``text_bytes`` columns."""
    seg = "(file_hash, extracted_by, page_id)"
    done = _query(client, f"SELECT uniqExact({seg}) FROM nlp_processed WHERE collection_dataset = {{ds:String}}", ds)[0][0]
    total = _query(client, f"SELECT uniqExact({seg}) FROM text_content WHERE collection_dataset = {{ds:String}}", ds)[0][0]
    done_bytes = _query(client, "SELECT sum(tb) FROM (SELECT file_hash, extracted_by, page_id, max(text_bytes) AS tb FROM nlp_processed WHERE collection_dataset = {ds:String} GROUP BY file_hash, extracted_by, page_id)", ds)[0][0] or 0
    total_bytes = _query(client, "SELECT sum(tb) FROM (SELECT file_hash, extracted_by, page_id, max(text_bytes) AS tb FROM text_content WHERE collection_dataset = {ds:String} GROUP BY file_hash, extracted_by, page_id)", ds)[0][0] or 0
    events = [
        (_epoch(ts), 1, int(tb))
        for ts, tb in _query(
            client,
            "SELECT max(processed_at) AS ts, argMax(text_bytes, processed_at) "
            "FROM nlp_processed WHERE collection_dataset = {ds:String} "
            f"GROUP BY file_hash, extracted_by, page_id ORDER BY ts DESC LIMIT {RATE_WINDOW_EVENTS}",
            ds,
        )
    ]
    rate_items, rate_bytes = rate_from_events(events)
    eta = combine_eta(
        remaining_projection(done, total, rate_items),
        remaining_projection(done_bytes, total_bytes, rate_bytes),
    )
    return StageSample(STAGE_NLP, done, total, rate_items, rate_bytes, eta)


def _sample_index(client, ds: str) -> StageSample:
    """P6 — indexing. Unit: documents. No byte watermark exists at this stage
    (``index_state`` carries no size), so the items projection is the only one."""
    done = _query(client, "SELECT uniqExact(file_hash) FROM index_state WHERE collection_dataset = {ds:String}", ds)[0][0]
    total = _query(client, "SELECT uniqExact(file_hash) FROM text_content WHERE collection_dataset = {ds:String}", ds)[0][0]
    events = [
        (_epoch(ts), 1, 0)
        for ts, in _query(
            client,
            "SELECT max(indexed_at) AS ts FROM index_state WHERE collection_dataset = {ds:String} "
            f"GROUP BY file_hash ORDER BY ts DESC LIMIT {RATE_WINDOW_EVENTS}",
            ds,
        )
    ]
    rate_items, rate_bytes = rate_from_events(events)
    eta = combine_eta(remaining_projection(done, total, rate_items), 0.0)
    return StageSample(STAGE_INDEX, done, total, rate_items, rate_bytes, eta)


_SAMPLERS = (_sample_plan, _sample_execute, _sample_nlp, _sample_index)


def collect_collection_samples(collectionname: str) -> tuple[list[dict], bool]:
    """Compute one sample per (dataset, stage) of a collection.

    Returns ``(rows, complete)``: ``rows`` ready for ``processing_eta_samples``
    (without ``sampled_at``/``collection_duration_ms``, filled in by the caller),
    and ``complete`` marking that every stage of every dataset is done, in
    which case ``rows`` is empty — a finished collection is never sampled
    (rule 8).
    """
    from database.clickhouse import get_collection_client, get_global_client

    with get_global_client() as client:
        datasets = [
            r[0]
            for r in client.query(
                "SELECT collection_dataset FROM dataset FINAL "
                "WHERE collectionname = {c:String} AND is_deleted = 0",
                parameters={"c": collectionname},
            ).result_rows
        ]
    if not datasets:
        return ([], True)

    rows: list[dict] = []
    complete = True
    with get_collection_client(collectionname) as client:
        for ds in datasets:
            for sampler in _SAMPLERS:
                sample = sampler(client, ds)
                if sample.done < sample.total:
                    complete = False
                rows.append(
                    {
                        "collectionname": collectionname,
                        "collection_dataset": ds,
                        "stage": sample.stage,
                        "done": sample.done,
                        "total": sample.total,
                        "rate_items_per_sec": sample.rate_items_per_sec,
                        "rate_bytes_per_sec": sample.rate_bytes_per_sec,
                        "eta_seconds": sample.eta_seconds,
                    }
                )
    return ([], True) if complete else (rows, False)


def insert_samples(rows: list[dict]) -> None:
    """Write one pass's samples into the global table."""
    from database.clickhouse import get_global_client

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    from datetime import timedelta

    data = [
        [
            r["collectionname"],
            r["collection_dataset"],
            r["stage"],
            now,
            r["done"],
            r["total"],
            r["rate_items_per_sec"],
            r["rate_bytes_per_sec"],
            r["eta_seconds"],
            now + timedelta(seconds=r["eta_seconds"]),
            r["collection_duration_ms"],
        ]
        for r in rows
    ]
    if not data:
        return
    with get_global_client() as client:
        client.insert(
            "processing_eta_samples",
            data,
            column_names=[
                "collectionname",
                "collection_dataset",
                "stage",
                "sampled_at",
                "done",
                "total",
                "rate_items_per_sec",
                "rate_bytes_per_sec",
                "eta_seconds",
                "deadline",
                "collection_duration_ms",
            ],
        )


def run_collection_pass(params: CollectEtaSamplesParams) -> CollectEtaSamplesResult:
    """One sampling pass over all collections. Sync; runs inside the activity."""
    from database.clickhouse import list_collections

    started = time.monotonic()
    completed: list[str] = []
    active: list[str] = []
    all_rows: list[dict] = []
    skip = set(params.skip_collections)

    for collectionname in list_collections():
        if collectionname in skip:
            continue
        collection_started = time.monotonic()
        try:
            rows, complete = collect_collection_samples(collectionname)
        except Exception as e:  # noqa: BLE001 - one broken collection must not stop the pass
            log.warning("[P_admin] ETA sampling failed for %s: %s", collectionname, e)
            continue
        collection_ms = int((time.monotonic() - collection_started) * 1000)
        if complete:
            completed.append(collectionname)
            continue
        active.append(collectionname)
        for row in rows:
            row["collection_duration_ms"] = collection_ms
        all_rows.extend(rows)

    duration_ms = int((time.monotonic() - started) * 1000)
    if all_rows:
        insert_samples(all_rows)
    log.info(
        "[P_admin] ETA pass: %d active, %d complete, %d skipped, %d samples in %d ms",
        len(active), len(completed), len(skip), len(all_rows), duration_ms,
    )
    return CollectEtaSamplesResult(
        duration_ms=duration_ms,
        completed_collections=completed,
        active_collections=active,
    )
