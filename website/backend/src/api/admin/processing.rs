//! Admin processing-management API: stage progress, ETAs, Temporal workflow browsing,
//! failure lists and retries.
//!
//! Everything here is read-only except [`admin_retry_failed_task`] and
//! [`admin_retry_document`], and every entry point is admin-gated.
//!
//! **Where the numbers come from.** There is no progress table in the pipeline; each
//! stage instead leaves a watermark row behind (a finished plan, an `nlp_processed`
//! row, an `index_state` row). Progress is therefore *derived* by counting watermarks
//! against the population that should eventually produce them. That means the numbers
//! are eventually-consistent and can briefly exceed 100% while a `ReplacingMergeTree`
//! has unmerged duplicates, every count below uses `FINAL` or `uniqExact` to avoid
//! that, at the cost of some query time. These are admin pages hit by a handful of
//! people, so correctness wins over latency here.

use std::collections::BTreeMap;

use common::current_user::CurrentUser;
use common::processing_types::*;
use time::format_description::well_known::Rfc3339;

use crate::api::admin::operations;
use crate::auth::guard;
use crate::db_auth::collections;
use crate::db_utils::clickhouse_utils::{get_collection_client, get_global_client};

/// Base URL of the Temporal *UI*, used only to build deep links shown to admins.
/// Distinct from `TEMPORAL_HTTP_URL`, which is the API the backend calls: the UI runs
/// on a different port and, unlike the API, is reached from the admin's browser rather
/// than from this container, so it must be a host-reachable address.
fn temporal_ui_base() -> String {
    std::env::var("TEMPORAL_UI_URL").unwrap_or_else(|_| "http://localhost:21909".to_string())
}

fn temporal_api_base() -> String {
    std::env::var("TEMPORAL_HTTP_URL").unwrap_or_else(|_| "http://localhost:21908".to_string())
}

// ---------------------------------------------------------------------------
// Stage progress
// ---------------------------------------------------------------------------

/// `(collection_dataset, done, total, recent_done)` for one stage across all datasets
/// of a collection.
#[derive(Debug, Clone, Default)]
struct StageCounts {
    done: u64,
    total: Option<u64>,
    /// Rows completed inside the trailing rate window; `None` when the stage has no
    /// completion timestamp.
    recent_done: Option<u64>,
    /// Documents `processing_errors` records a failure of this stage for.
    failed_documents: u64,
}

/// Which stage bar a `processing_errors.task_name` belongs under.
///
/// The error rows name the *task* that failed, and a task is finer-grained than a bar:
/// four different index writers and a dozen parse tasks report separately. Mapping them
/// onto the five bars is what lets a failure be shown next to the work it belongs to
/// instead of only as a dataset-wide total. The default is the execute bar because the
/// parse tasks are per-file children of plan execution and they are the long tail;
/// mirrored on the processing side by `tasks/P_admin/failed_file_retry.py`, which
/// decides what a retry of each task has to re-run.
fn stage_for_task(task_name: &str) -> &'static str {
    match task_name {
        "archive_scan" => STAGE_SCAN,
        "P4_ExtractEntities" => STAGE_NLP,
        // P5 has no bar of its own: chunk+embed feeds the index, and its failures show
        // up as documents that are indexed without vectors.
        "P5_ChunkEmbed" => STAGE_INDEX,
        other if other.starts_with("P6_") => STAGE_INDEX,
        _ => STAGE_EXECUTE,
    }
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct DatasetCountRow {
    collection_dataset: String,
    value: u64,
}

/// Run a `SELECT collection_dataset, <agg> ... GROUP BY collection_dataset` and return
/// it as a map. Every stage query has this shape, so they all go through here.
async fn grouped_counts(
    client: &clickhouse::Client,
    sql: &str,
) -> anyhow::Result<BTreeMap<String, u64>> {
    let rows = client.query(sql).fetch_all::<DatasetCountRow>().await?;
    Ok(rows
        .into_iter()
        .map(|r| (r.collection_dataset, r.value))
        .collect())
}

/// Build a [`StageProgress`] from the three raw counts.
///
/// The ETA is deliberately conservative: it is `None` unless the stage is genuinely
/// incomplete *and* observed to be moving. Showing "ETA 4 days" for a pipeline that has
/// been idle for a week is worse than showing nothing.
fn stage_progress(
    stage: &str,
    label: &str,
    unit: &str,
    counts: &StageCounts,
) -> StageProgress {
    let rate_per_minute = counts
        .recent_done
        .map(|recent| recent as f64 / RATE_WINDOW_MINUTES as f64);

    let eta_seconds = match (counts.total, rate_per_minute) {
        (Some(total), Some(rate)) if total > counts.done && rate > 0.0 => {
            let remaining = (total - counts.done) as f64;
            Some((remaining / rate * 60.0).ceil() as u64)
        }
        _ => None,
    };

    StageProgress {
        stage: stage.to_string(),
        label: label.to_string(),
        unit: unit.to_string(),
        done: counts.done,
        total: counts.total,
        rate_per_minute,
        eta_seconds,
        failed_documents: counts.failed_documents,
    }
}

fn pick(map: &BTreeMap<String, u64>, dataset: &str) -> u64 {
    map.get(dataset).copied().unwrap_or(0)
}

/// Per-collection processing status: one row per dataset, one bar per stage.
pub async fn admin_collection_processing(
    user: &CurrentUser,
    collectionname: String,
) -> anyhow::Result<CollectionProcessingStatus> {
    guard::require_admin(user)?;

    let db_ready = collections::collection_db_ready(&collectionname).await?;
    let dataset_links = collections::list_collection_datasets(&collectionname).await?;

    if !db_ready || dataset_links.is_empty() {
        // Querying a half-provisioned database throws "unknown table" rather than
        // returning zeroes, so short-circuit instead of letting the page 500.
        return Ok(CollectionProcessingStatus {
            collectionname,
            db_ready,
            datasets: Vec::new(),
        });
    }

    let display_names = dataset_display_names(&collectionname).await?;
    let client = get_collection_client(&collectionname);
    let window = RATE_WINDOW_MINUTES;

    // P0, scan. Blobs discovered so far. No denominator: the scan learns the size of
    // the job as it walks the tree, and `blobs` has no timestamp column, so no ETA.
    let scanned = grouped_counts(
        &client,
        "SELECT collection_dataset, uniqExact(blob_hash) AS value \
         FROM blobs GROUP BY collection_dataset",
    )
    .await?;

    // P1, plan computation. Every discovered blob should end up in exactly one plan.
    let planned = grouped_counts(
        &client,
        "SELECT collection_dataset, uniqExact(item_hash) AS value \
         FROM processing_plan_hits GROUP BY collection_dataset",
    )
    .await?;
    let planned_recent = grouped_counts(
        &client,
        &format!(
            "SELECT collection_dataset, uniqExact(plan_hash) AS value FROM processing_plans \
             WHERE created_at >= now() - INTERVAL {window} MINUTE GROUP BY collection_dataset"
        ),
    )
    .await?;

    // P2/P3, plan execution (parsing happens inside the plan execution workflow, so
    // the two share one bar; a separate P3 bar would be the same number twice).
    let plans_total = grouped_counts(
        &client,
        "SELECT collection_dataset, uniqExact(plan_hash) AS value \
         FROM processing_plans GROUP BY collection_dataset",
    )
    .await?;
    let plans_done = grouped_counts(
        &client,
        "SELECT collection_dataset, uniqExact(plan_hash) AS value \
         FROM processing_plan_finished GROUP BY collection_dataset",
    )
    .await?;
    let plans_recent = grouped_counts(
        &client,
        &format!(
            "SELECT collection_dataset, uniqExact(plan_hash) AS value FROM processing_plan_finished \
             WHERE finished_at >= now() - INTERVAL {window} MINUTE GROUP BY collection_dataset"
        ),
    )
    .await?;

    // P4, NLP/NER. Denominator is the text pages extracted by P3.
    //
    // These count `(file_hash, extracted_by, page_id)` triples, and `page_id` is a real
    // page number rather than a multi-megabyte segment ordinal, so the unit count is
    // orders of magnitude larger than a segment count would be. The label below says
    // "pages" for that reason. `processing_eta_samples` rows are only comparable across
    // runs that share this unit.
    //
    // `nlp_processed` now carries `nlp_model` too, so a segment has one row per NER
    // provider. Counting the triple rather than the quad deliberately reads as "at
    // least one provider has finished this page", which is what the progress bar means.
    let segments_total = grouped_counts(
        &client,
        "SELECT collection_dataset, uniqExact((file_hash, extracted_by, page_id)) AS value \
         FROM text_content GROUP BY collection_dataset",
    )
    .await?;
    let segments_nlp = grouped_counts(
        &client,
        "SELECT collection_dataset, uniqExact((file_hash, extracted_by, page_id)) AS value \
         FROM nlp_processed GROUP BY collection_dataset",
    )
    .await?;
    let segments_nlp_recent = grouped_counts(
        &client,
        &format!(
            "SELECT collection_dataset, uniqExact((file_hash, extracted_by, page_id)) AS value \
             FROM nlp_processed WHERE processed_at >= now() - INTERVAL {window} MINUTE \
             GROUP BY collection_dataset"
        ),
    )
    .await?;

    // P6, indexing. Denominator is every document that reaches indexing, which is every
    // blob in the dataset, NOT the documents that have text.
    //
    // It used to count `uniqExact(file_hash) FROM text_content`, and that population is
    // strictly smaller: indexing writes a Manticore document for every file, including
    // the ones with no extractable text (an image with no OCR hit, a binary, a
    // zero-byte file), because a document with only metadata is still findable by
    // filename and type. The bar therefore read `266 / 94 documents` (283%) on the
    // first dataset that had many text-free files.
    //
    // `blobs` is the same population P0 and P1 report against, so the four stage bars
    // now share a denominator and can be read down the page as one pipeline.
    let docs_total = grouped_counts(
        &client,
        "SELECT collection_dataset, uniqExact(blob_hash) AS value \
         FROM blobs GROUP BY collection_dataset",
    )
    .await?;
    let docs_indexed = grouped_counts(
        &client,
        "SELECT collection_dataset, uniqExact(file_hash) AS value \
         FROM index_state GROUP BY collection_dataset",
    )
    .await?;
    let docs_indexed_recent = grouped_counts(
        &client,
        &format!(
            "SELECT collection_dataset, uniqExact(file_hash) AS value FROM index_state \
             WHERE indexed_at >= now() - INTERVAL {window} MINUTE GROUP BY collection_dataset"
        ),
    )
    .await?;

    let errors = grouped_counts(
        &client,
        "SELECT collection_dataset, count() AS value \
         FROM processing_errors GROUP BY collection_dataset",
    )
    .await?;

    // Failures per (dataset, stage), counting DOCUMENTS rather than error rows: a
    // document that failed three times is one document missing from the corpus, and the
    // bar it sits next to counts documents too. Dataset-level rows carry no hash and
    // are excluded here. They are in `errors` above, which is the dataset's own total.
    let failure_rows = client
        .query(
            "SELECT collection_dataset, task_name, uniqExact(hash) AS value \
             FROM processing_errors WHERE hash != '' GROUP BY collection_dataset, task_name",
        )
        .fetch_all::<(String, String, u64)>()
        .await?;
    let mut failed_by_stage: BTreeMap<(String, &'static str), u64> = BTreeMap::new();
    for (ds, task_name, count) in failure_rows {
        *failed_by_stage
            .entry((ds, stage_for_task(&task_name)))
            .or_default() += count;
    }
    let failed = |ds: &str, stage: &'static str| -> u64 {
        failed_by_stage
            .get(&(ds.to_string(), stage))
            .copied()
            .unwrap_or(0)
    };

    let mut datasets = Vec::with_capacity(dataset_links.len());
    for link in dataset_links {
        let ds = link.collection_dataset;
        let stages = vec![
            stage_progress(
                STAGE_SCAN,
                "P0 · Scan & deduplicate",
                "blobs",
                &StageCounts {
                    done: pick(&scanned, &ds),
                    total: None,
                    recent_done: None,
                    failed_documents: failed(&ds, STAGE_SCAN),
                },
            ),
            stage_progress(
                STAGE_PLAN,
                "P1 · Compute plans",
                "blobs planned",
                &StageCounts {
                    done: pick(&planned, &ds),
                    total: Some(pick(&scanned, &ds)),
                    recent_done: Some(pick(&planned_recent, &ds)),
                    failed_documents: failed(&ds, STAGE_PLAN),
                },
            ),
            stage_progress(
                STAGE_EXECUTE,
                "P2/P3 · Execute plans & parse",
                "plans",
                &StageCounts {
                    done: pick(&plans_done, &ds),
                    total: Some(pick(&plans_total, &ds)),
                    recent_done: Some(pick(&plans_recent, &ds)),
                    failed_documents: failed(&ds, STAGE_EXECUTE),
                },
            ),
            stage_progress(
                STAGE_NLP,
                "P4 · Extract entities (NLP)",
                "text pages",
                &StageCounts {
                    done: pick(&segments_nlp, &ds),
                    total: Some(pick(&segments_total, &ds)),
                    recent_done: Some(pick(&segments_nlp_recent, &ds)),
                    failed_documents: failed(&ds, STAGE_NLP),
                },
            ),
            stage_progress(
                STAGE_INDEX,
                "P6 · Index for search",
                "documents",
                &StageCounts {
                    done: pick(&docs_indexed, &ds),
                    total: Some(pick(&docs_total, &ds)),
                    recent_done: Some(pick(&docs_indexed_recent, &ds)),
                    failed_documents: failed(&ds, STAGE_INDEX),
                },
            ),
        ];
        datasets.push(DatasetProcessingStatus {
            dataset_display_name: display_names
                .get(&ds)
                .cloned()
                .unwrap_or_else(|| ds.clone()),
            error_count: pick(&errors, &ds),
            collection_dataset: ds,
            stages,
        });
    }

    Ok(CollectionProcessingStatus {
        collectionname,
        db_ready,
        datasets,
    })
}

async fn dataset_display_names(
    collectionname: &str,
) -> anyhow::Result<BTreeMap<String, String>> {
    let client = get_global_client();
    let rows = client
        .query(
            "SELECT collection_dataset, dataset_display_name FROM dataset FINAL \
             WHERE collectionname = ? AND is_deleted = 0",
        )
        .bind(collectionname)
        .fetch_all::<(String, String)>()
        .await?;
    Ok(rows.into_iter().collect())
}

// ---------------------------------------------------------------------------
// Stored ETA samples
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct EtaSampleRow {
    collection_dataset: String,
    stage: String,
    sampled_at: i64,
    done: u64,
    total: u64,
    rate_items_per_sec: f64,
    rate_bytes_per_sec: f64,
    eta_seconds: u64,
    deadline: i64,
}

/// The stored ETA sample history for one collection: newest 100 samples per
/// (dataset, stage), newest first. Written by the `CollectEtaSamples` workflow;
/// this endpoint is a cheap indexed read, never a recompute.
pub async fn admin_list_eta_samples(
    user: &CurrentUser,
    collectionname: String,
) -> anyhow::Result<Vec<EtaSamplePoint>> {
    guard::require_admin(user)?;
    let client = get_global_client();
    let rows = client
        .query(
            "SELECT collection_dataset, stage, toInt64(toUnixTimestamp(sampled_at)) AS sampled_at, \
                    done, total, rate_items_per_sec, rate_bytes_per_sec, eta_seconds, \
                    toInt64(toUnixTimestamp(deadline)) AS deadline \
             FROM processing_eta_samples \
             WHERE collectionname = ? \
             ORDER BY sampled_at DESC LIMIT 100 BY collection_dataset, stage",
        )
        .bind(&collectionname)
        .fetch_all::<EtaSampleRow>()
        .await?;

    Ok(rows
        .into_iter()
        .map(|r| EtaSamplePoint {
            collection_dataset: r.collection_dataset,
            stage: r.stage,
            sampled_at: format_ts(r.sampled_at),
            sampled_at_unix: r.sampled_at,
            done: r.done,
            total: r.total,
            rate_items_per_sec: r.rate_items_per_sec,
            rate_bytes_per_sec: r.rate_bytes_per_sec,
            eta_seconds: r.eta_seconds,
            deadline: format_ts(r.deadline),
            deadline_unix: r.deadline,
        })
        .collect())
}

// ---------------------------------------------------------------------------
// Where processing time goes
// ---------------------------------------------------------------------------
//
// Both endpoints read `processing_task_runs` / `processing_task_inflight`, written by
// the worker-side activity interceptor (`main_services/processing/tasks/task_timing.py`).
// Unlike the stage progress above, these are not derived from watermarks: they are a
// direct record of every activity execution, so they need no `FINAL` and no `uniqExact`.
//
// Everything is reported per COLLECTION, not per dataset: the question these answer is
// "what should I optimise" and "should I add workers", and both are properties of the
// pipeline, not of one dataset.

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct TaskTimeRawRow {
    task_name: String,
    total_seconds: f64,
    executions: u64,
    error_count: u64,
    mean_ms: f64,
    p95_ms: f64,
    max_ms: u64,
}

/// Per-task-type time breakdown for one collection, plus wall clock and the achieved
/// parallelism (summed task time / wall clock).
///
/// The parallelism ratio is the number worth reading first: at 1.0 the pipeline is
/// serial and making the top task faster is the whole win; at 8.0 on an 8-slot worker
/// the slots are saturated and more workers is the only thing that helps.
pub async fn admin_task_time_breakdown(
    user: &CurrentUser,
    collectionname: String,
) -> anyhow::Result<TaskTimeBreakdown> {
    guard::require_admin(user)?;
    let empty = TaskTimeBreakdown {
        rows: Vec::new(),
        total_seconds: 0.0,
        total_executions: 0,
        wall_clock_seconds: 0.0,
        achieved_parallelism: 0.0,
        first_started: None,
        last_finished: None,
    };
    if !collections::collection_db_ready(&collectionname).await? {
        return Ok(empty);
    }
    let client = get_collection_client(&collectionname);

    // Every aggregate is cast explicitly. See the `last_seen` note above: RowBinary is
    // positional and untyped, so a `UInt32` decoded into an `i64` field desynchronises
    // the whole row.
    let raw = client
        .query(
            "SELECT task_name, \
                    toFloat64(sum(run_time_ms)) / 1000 AS total_seconds, \
                    toUInt64(count()) AS executions, \
                    toUInt64(countIf(outcome = 'error')) AS error_count, \
                    toFloat64(avg(run_time_ms)) AS mean_ms, \
                    toFloat64(quantileExact(0.95)(run_time_ms)) AS p95_ms, \
                    toUInt64(max(run_time_ms)) AS max_ms \
             FROM processing_task_runs \
             GROUP BY task_name \
             ORDER BY total_seconds DESC",
        )
        .fetch_all::<TaskTimeRawRow>()
        .await?;

    if raw.is_empty() {
        return Ok(empty);
    }

    // The wall clock is the span from the first execution's start to the last one's
    // end. An aggregate over an empty table still returns a row (of zeroes), which is
    // why `raw.is_empty()` is the emptiness test rather than this.
    let (first_ms, last_ms) = client
        .query(
            "SELECT toInt64(min(toUnixTimestamp64Milli(started_at))) AS first_ms, \
                    toInt64(max(toUnixTimestamp64Milli(started_at) + toInt64(run_time_ms))) AS last_ms \
             FROM processing_task_runs",
        )
        .fetch_one::<(i64, i64)>()
        .await?;

    let total_seconds: f64 = raw.iter().map(|r| r.total_seconds).sum();
    let total_executions: u64 = raw.iter().map(|r| r.executions).sum();
    let wall_clock_seconds = ((last_ms - first_ms).max(0) as f64) / 1000.0;

    Ok(TaskTimeBreakdown {
        rows: raw
            .into_iter()
            .map(|r| TaskTimeRow {
                task_name: r.task_name,
                share_percent: share(r.total_seconds, total_seconds),
                total_seconds: r.total_seconds,
                executions: r.executions,
                error_count: r.error_count,
                mean_ms: r.mean_ms,
                p95_ms: r.p95_ms,
                max_ms: r.max_ms,
            })
            .collect(),
        total_seconds,
        total_executions,
        wall_clock_seconds,
        achieved_parallelism: if wall_clock_seconds > 0.0 {
            total_seconds / wall_clock_seconds
        } else {
            0.0
        },
        first_started: Some(format_ts(first_ms / 1000)),
        last_finished: Some(format_ts(last_ms / 1000)),
    })
}

/// `part` as a percentage of `whole`, and 0 rather than NaN when there is no whole.
fn share(part: f64, whole: f64) -> f64 {
    if whole > 0.0 {
        (part / whole * 100.0).clamp(0.0, 100.0)
    } else {
        0.0
    }
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct LiveWindowRow {
    task_name: String,
    seconds_in_window: f64,
    completed: u64,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct InFlightRow {
    task_name: String,
    in_flight: u64,
    oldest_age_ms: u64,
}

/// What the pipeline is spending time on *right now*: a trailing window of completed
/// executions, plus the sampled set of executions still running.
///
/// The two halves answer different questions and neither is enough alone. Completed
/// executions give the share of time per task type but cannot see a task that has been
/// running for twenty minutes. It has not finished, so it has no row. The in-flight
/// samples see exactly that one, but only as a count.
///
/// Window arithmetic is an overlap, not a "finished inside the window" filter: an
/// execution that straddles an edge contributes only the part inside, so the shares sum
/// to the window and `average_concurrency` is a real average rather than an artefact of
/// where the boundary fell.
pub async fn admin_task_time_live(
    user: &CurrentUser,
    collectionname: String,
    window_seconds: u32,
) -> anyhow::Result<LiveTaskActivity> {
    guard::require_admin(user)?;
    let window = window_seconds.clamp(10, 3600);
    let empty = LiveTaskActivity {
        rows: Vec::new(),
        window_seconds: window,
        total_seconds_in_window: 0.0,
        average_concurrency: 0.0,
        in_flight_total: 0,
        sampled_at: None,
    };
    if !collections::collection_db_ready(&collectionname).await? {
        return Ok(empty);
    }
    let client = get_collection_client(&collectionname);

    // Lookback is the window plus an hour: an execution that started before the window
    // opened still overlaps it, and the longest activities in this pipeline (OCR over a
    // large scan, ffmpeg over a long video) run for minutes, not hours.
    let lookback = window as u64 + 3600;
    let window_ms = window as i64 * 1000;
    let window_rows = client
        .query(&format!(
            "WITH toUnixTimestamp64Milli(now64(3)) AS t1, t1 - {window_ms} AS t0 \
             SELECT task_name, \
                    toFloat64(sum(greatest(toInt64(0), \
                        least(toUnixTimestamp64Milli(started_at) + toInt64(run_time_ms), t1) \
                      - greatest(toUnixTimestamp64Milli(started_at), t0)))) / 1000 AS seconds_in_window, \
                    toUInt64(countIf(toUnixTimestamp64Milli(started_at) + toInt64(run_time_ms) >= t0)) AS completed \
             FROM processing_task_runs \
             WHERE started_at >= now() - INTERVAL {lookback} SECOND \
             GROUP BY task_name \
             HAVING seconds_in_window > 0 \
             ORDER BY seconds_in_window DESC"
        ))
        .fetch_all::<LiveWindowRow>()
        .await?;

    // A sample is a LEVEL, not a counter: take the newest one per worker and sum those.
    // Summing the raw rows would multiply concurrency by the number of samples taken.
    let fresh = INFLIGHT_FRESHNESS_SECONDS;
    let inflight_rows = client
        .query(&format!(
            "SELECT task_name, \
                    toUInt64(sum(worker_in_flight)) AS in_flight, \
                    toUInt64(max(worker_oldest_ms)) AS oldest_age_ms \
             FROM ( \
                SELECT task_name, worker_id, \
                       argMax(in_flight, sampled_at) AS worker_in_flight, \
                       argMax(oldest_age_ms, sampled_at) AS worker_oldest_ms \
                FROM processing_task_inflight \
                WHERE sampled_at >= now() - INTERVAL {fresh} SECOND \
                GROUP BY task_name, worker_id \
             ) \
             GROUP BY task_name"
        ))
        .fetch_all::<InFlightRow>()
        .await?;

    let newest_sample = client
        .query(&format!(
            "SELECT toInt64(toUnixTimestamp(max(sampled_at))) \
             FROM processing_task_inflight WHERE sampled_at >= now() - INTERVAL {fresh} SECOND"
        ))
        .fetch_one::<i64>()
        .await?;

    Ok(merge_live(window, window_rows_to_pairs(window_rows), inflight_rows, newest_sample))
}

fn window_rows_to_pairs(rows: Vec<LiveWindowRow>) -> Vec<(String, f64, u64)> {
    rows.into_iter()
        .map(|r| (r.task_name, r.seconds_in_window, r.completed))
        .collect()
}

/// Join the completed-window rows with the in-flight samples.
///
/// Split out of the query path so it can be tested: the case that matters is a task
/// that appears in ONE of the two halves only, either a long activity still running (in
/// flight, no completed time) or one that just finished (time, nothing in flight).
/// Dropping either would make the live view lie about what is happening.
fn merge_live(
    window: u32,
    window_rows: Vec<(String, f64, u64)>,
    inflight_rows: Vec<InFlightRow>,
    newest_sample_unix: i64,
) -> LiveTaskActivity {
    let mut inflight: BTreeMap<String, (u64, u64)> = inflight_rows
        .into_iter()
        .map(|r| (r.task_name, (r.in_flight, r.oldest_age_ms)))
        .collect();

    let total_seconds_in_window: f64 = window_rows.iter().map(|(_, s, _)| *s).sum();
    let mut rows: Vec<LiveTaskRow> = window_rows
        .into_iter()
        .map(|(task_name, seconds, completed)| {
            let (in_flight, oldest_ms) = inflight.remove(&task_name).unwrap_or((0, 0));
            LiveTaskRow {
                share_percent: share(seconds, total_seconds_in_window),
                task_name,
                seconds_in_window: seconds,
                completed,
                in_flight,
                oldest_age_seconds: oldest_ms / 1000,
            }
        })
        .collect();

    // Whatever is left is running but has not completed anything inside the window,
    // the stuck-task case, and the single most useful row on the panel.
    for (task_name, (in_flight, oldest_ms)) in inflight {
        rows.push(LiveTaskRow {
            task_name,
            seconds_in_window: 0.0,
            share_percent: 0.0,
            completed: 0,
            in_flight,
            oldest_age_seconds: oldest_ms / 1000,
        });
    }

    let in_flight_total = rows.iter().map(|r| r.in_flight).sum();
    LiveTaskActivity {
        window_seconds: window,
        total_seconds_in_window,
        average_concurrency: total_seconds_in_window / window as f64,
        in_flight_total,
        sampled_at: (newest_sample_unix > 0).then(|| format_ts(newest_sample_unix)),
        rows,
    }
}

// ---------------------------------------------------------------------------
// Temporal workflow browser
// ---------------------------------------------------------------------------
/// Strip Temporal's `WORKFLOW_EXECUTION_STATUS_` prefix, e.g.
/// `WORKFLOW_EXECUTION_STATUS_RUNNING` -> `RUNNING`.
fn short_status(raw: &str) -> String {
    raw.strip_prefix("WORKFLOW_EXECUTION_STATUS_")
        .unwrap_or(raw)
        .to_string()
}

/// Build the visibility query for a collection's workflows.
///
/// A workflow belongs to a dataset through the `CollectionDataset` search attribute,
/// which the workers register at startup and set on every start (see
/// `tasks/visibility.py`). That is the clause that matters: it is the only one that
/// finds a child workflow, whose id (`HandleFolders-<hash>`, the per-plan runs) names
/// no dataset, and the only one that finds a run dispatched under an operation id.
///
/// The `<kind>-<collection_dataset>` ids are OR-ed in beside it as a fallback, for a
/// run started under a fixed id and carrying no attribute.
pub fn collection_visibility_query(
    collection_datasets: &[String],
    filter: WorkflowFilter,
) -> Option<String> {
    let mut clauses: Vec<String> = Vec::new();

    if !collection_datasets.is_empty() {
        let per_dataset: Vec<String> = collection_datasets
            .iter()
            // A dataset name is ClickHouse-validated upstream, so it cannot contain a
            // quote; still, refuse anything odd rather than building a query with it.
            .filter(|ds| !ds.contains('\'') && !ds.contains('"'))
            .map(|ds| {
                let ids = [
                    format!("ingest-disk-{ds}"),
                    format!("compute-plans-{ds}"),
                    format!("execute-plans-{ds}"),
                    format!("purge-dataset-{ds}"),
                ]
                .into_iter()
                .map(|id| format!("WorkflowId = '{id}'"))
                .collect::<Vec<_>>()
                .join(" OR ");
                format!("(CollectionDataset = '{ds}' OR {ids})")
            })
            .collect();
        if per_dataset.is_empty() {
            return None;
        }
        clauses.push(format!("({})", per_dataset.join(" OR ")));
    }

    if let Some(status) = filter.status_clause() {
        clauses.push(status.to_string());
    }

    if clauses.is_empty() {
        None
    } else {
        Some(clauses.join(" AND "))
    }
}

fn parse_workflow(value: &serde_json::Value, ui_base: &str) -> Option<WorkflowSummary> {
    let execution = value.get("execution")?;
    let workflow_id = execution.get("workflowId")?.as_str()?.to_string();
    let run_id = execution.get("runId")?.as_str()?.to_string();
    Some(WorkflowSummary {
        temporal_url: format!(
            "{ui_base}/namespaces/default/workflows/{workflow_id}/{run_id}/history"
        ),
        workflow_type: value
            .get("type")
            .and_then(|t| t.get("name"))
            .and_then(|n| n.as_str())
            .unwrap_or("unknown")
            .to_string(),
        status: short_status(value.get("status").and_then(|s| s.as_str()).unwrap_or("")),
        task_queue: value
            .get("taskQueue")
            .and_then(|q| q.as_str())
            .unwrap_or("")
            .to_string(),
        start_time: value
            .get("startTime")
            .and_then(|t| t.as_str())
            .unwrap_or("")
            .to_string(),
        close_time: value
            .get("closeTime")
            .and_then(|t| t.as_str())
            .map(str::to_string),
        parent_workflow_id: value
            .get("parentExecution")
            .and_then(|p| p.get("workflowId"))
            .and_then(|w| w.as_str())
            .map(str::to_string),
        workflow_id,
        run_id,
    })
}

/// List Temporal workflows, optionally scoped to one collection.
///
/// `collectionname` empty means "every workflow on the cluster", which is what the
/// global workflow browser shows.
pub async fn admin_list_workflows(
    user: &CurrentUser,
    collectionname: String,
    filter: WorkflowFilter,
    page_size: u32,
) -> anyhow::Result<Vec<WorkflowSummary>> {
    guard::require_admin(user)?;

    let query = if collectionname.is_empty() {
        filter.status_clause().map(str::to_string)
    } else {
        let datasets: Vec<String> = collections::list_collection_datasets(&collectionname)
            .await?
            .into_iter()
            .map(|d| d.collection_dataset)
            .collect();
        if datasets.is_empty() {
            return Ok(Vec::new());
        }
        collection_visibility_query(&datasets, filter)
    };

    let mut request = reqwest::Client::new()
        .get(format!(
            "{}/api/v1/namespaces/default/workflows",
            temporal_api_base()
        ))
        .query(&[("pageSize", page_size.clamp(1, 200).to_string())]);
    if let Some(q) = query {
        request = request.query(&[("query", q)]);
    }

    let response = request.send().await?;
    if !response.status().is_success() {
        let status = response.status();
        let text = response.text().await.unwrap_or_default();
        anyhow::bail!("temporal workflow list failed ({status}): {text}");
    }

    let json: serde_json::Value = response.json().await?;
    let ui_base = temporal_ui_base();
    Ok(json
        .get("executions")
        .and_then(|e| e.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| parse_workflow(v, &ui_base))
                .collect()
        })
        .unwrap_or_default())
}

// ---------------------------------------------------------------------------
// Failures
// ---------------------------------------------------------------------------

/// NOTE on `last_seen`: `toUnixTimestamp()` returns ClickHouse `UInt32`, and RowBinary is
/// positional and untyped. A `UInt32` column read into an `i64` field consumes four bytes
/// too many and desynchronises the whole row, so the server fn 500s. It only ever fails
/// when there is at least one row to decode, which is why an empty collection looked fine
/// and this shipped. Every query feeding this struct must therefore say
/// `toInt64(toUnixTimestamp(...))` explicitly.
#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct TaskFailureRow {
    collection_dataset: String,
    task_name: String,
    error_count: u64,
    document_count: u64,
    last_seen: i64,
    sample_error: String,
}

fn format_ts(unix_seconds: i64) -> String {
    time::OffsetDateTime::from_unix_timestamp(unix_seconds)
        .ok()
        .and_then(|dt| dt.format(&Rfc3339).ok())
        .unwrap_or_else(|| unix_seconds.to_string())
}

/// Truncate an error blob to a single readable line for list views. Stack traces run to
/// kilobytes and would otherwise be shipped to the browser in full for every row.
fn first_line(error: &str, max: usize) -> String {
    let line = error.lines().find(|l| !l.trim().is_empty()).unwrap_or("");
    if line.chars().count() > max {
        format!("{}\u{2026}", line.chars().take(max).collect::<String>())
    } else {
        line.to_string()
    }
}

/// Failures grouped by task, most recent first. This is the "what is broken" list.
pub async fn admin_list_task_failures(
    user: &CurrentUser,
    collectionname: String,
    limit: u32,
) -> anyhow::Result<Vec<TaskFailureGroup>> {
    guard::require_admin(user)?;
    if !collections::collection_db_ready(&collectionname).await? {
        return Ok(Vec::new());
    }
    let client = get_collection_client(&collectionname);
    let rows = client
        .query(
            "SELECT collection_dataset, task_name, count() AS error_count, \
                    uniqExact(hash) AS document_count, \
                    toInt64(toUnixTimestamp(max(timestamp))) AS last_seen, \
                    argMax(error_logs, timestamp) AS sample_error \
             FROM processing_errors \
             GROUP BY collection_dataset, task_name \
             ORDER BY last_seen DESC LIMIT ?",
        )
        .bind(limit.clamp(1, 500))
        .fetch_all::<TaskFailureRow>()
        .await?;

    Ok(rows
        .into_iter()
        .map(|r| TaskFailureGroup {
            collection_dataset: r.collection_dataset,
            task_name: r.task_name,
            error_count: r.error_count,
            document_count: r.document_count,
            last_seen: format_ts(r.last_seen),
            sample_error: first_line(&r.sample_error, 200),
        })
        .collect())
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct DocumentFailureRow {
    collection_dataset: String,
    hash: String,
    task_names: Vec<String>,
    error_count: u64,
    last_seen: i64,
    last_error: String,
}

/// Failures grouped by document. This is the "which files are affected" list.
///
/// `task_name` may be empty in `processing_errors` for dataset-level failures; those
/// rows carry an empty `hash` too and are grouped under a single blank document, which
/// the UI labels "dataset-level".
pub async fn admin_list_document_failures(
    user: &CurrentUser,
    collectionname: String,
    collection_dataset: String,
    limit: u32,
) -> anyhow::Result<Vec<DocumentFailure>> {
    guard::require_admin(user)?;
    if !collections::collection_db_ready(&collectionname).await? {
        return Ok(Vec::new());
    }
    let client = get_collection_client(&collectionname);

    let dataset_filter = if collection_dataset.is_empty() {
        String::new()
    } else {
        "WHERE collection_dataset = ?".to_string()
    };
    let sql = format!(
        "SELECT collection_dataset, hash, groupUniqArray(task_name) AS task_names, \
                count() AS error_count, \
                toInt64(toUnixTimestamp(max(timestamp))) AS last_seen, \
                argMax(error_logs, timestamp) AS last_error \
         FROM processing_errors {dataset_filter} \
         GROUP BY collection_dataset, hash \
         ORDER BY last_seen DESC LIMIT ?"
    );
    let mut query = client.query(&sql);
    if !collection_dataset.is_empty() {
        query = query.bind(&collection_dataset);
    }
    let rows = query
        .bind(limit.clamp(1, 500))
        .fetch_all::<DocumentFailureRow>()
        .await?;

    // Resolve VFS paths in one extra query rather than a join: `processing_errors` has
    // no path, and joining `vfs_files` per row would be one query per failure.
    let hashes: Vec<String> = rows
        .iter()
        .map(|r| r.hash.clone())
        .filter(|h| !h.is_empty())
        .collect();
    let mut paths: BTreeMap<String, String> = BTreeMap::new();
    if !hashes.is_empty() {
        let path_rows = client
            .query("SELECT hash, any(path) FROM vfs_files WHERE hash IN ? GROUP BY hash")
            .bind(&hashes)
            .fetch_all::<(String, String)>()
            .await?;
        paths = path_rows.into_iter().collect();
    }

    Ok(rows
        .into_iter()
        .map(|r| DocumentFailure {
            path: paths.get(&r.hash).cloned(),
            collection_dataset: r.collection_dataset,
            task_names: r.task_names,
            error_count: r.error_count,
            last_seen: format_ts(r.last_seen),
            last_error: first_line(&r.last_error, 2000),
            hash: r.hash,
        })
        .collect())
}

// ---------------------------------------------------------------------------
// Retries
// ---------------------------------------------------------------------------

/// Mark the plans containing `hashes` as unfinished, and return how many were reopened.
///
/// This is what makes a retry actually retry. `ExecutePlans` skips any plan already in
/// `processing_plan_finished`, and a stage that records an error *without* failing the
/// plan (P4 entity extraction is the common case), still lets the plan finish. So
/// restarting the workflow on its own is a no-op for exactly the failures an admin is
/// most likely to be looking at. Deleting the finished-marker first is what puts the
/// work back in front of the pipeline.
///
/// Reprocessing a whole plan to fix one document is coarse (a plan is a batch of
/// blobs), but the pipeline's unit of work *is* the plan, and every stage is
/// idempotent. Re-running one costs time, not correctness.
async fn reopen_plans_for_hashes(
    client: &clickhouse::Client,
    collection_dataset: &str,
    hashes: &[String],
) -> anyhow::Result<u64> {
    if hashes.is_empty() {
        return Ok(0);
    }
    let plan_hashes: Vec<String> = client
        .query(
            "SELECT DISTINCT plan_hash FROM processing_plan_hits FINAL \
             WHERE collection_dataset = ? AND item_hash IN ?",
        )
        .bind(collection_dataset)
        .bind(hashes)
        .fetch_all::<String>()
        .await?;

    if plan_hashes.is_empty() {
        return Ok(0);
    }

    client
        .query(
            "ALTER TABLE processing_plan_finished DELETE \
             WHERE collection_dataset = ? AND plan_hash IN ?",
        )
        .bind(collection_dataset)
        .bind(&plan_hashes)
        .execute()
        .await?;

    Ok(plan_hashes.len() as u64)
}

/// Re-run the stage that failed, for the documents it failed on.
///
/// Dispatched as a `retry_failed_files` operation, so the retry takes the dataset's lock,
/// leaves a row saying what was retried and how it ended, and re-runs only the stage that
/// recorded the failures rather than the whole pipeline. The error rows survive until the
/// documents they describe are demonstrably fixed: clearing them up front would lose the
/// record of every retry that fails the same way.
pub async fn admin_retry_failed_task(
    user: &CurrentUser,
    collectionname: String,
    collection_dataset: String,
    task_name: String,
) -> anyhow::Result<String> {
    guard::require_admin(user)?;
    if task_name.is_empty() {
        anyhow::bail!("no task name given");
    }
    let detail = serde_json::json!({ "task_name": task_name }).to_string();
    operations::dispatch_operation(
        "retry_failed_files",
        &collectionname,
        &collection_dataset,
        &user.username,
        "",
        &detail,
    )
    .await
}

/// Retry the processing of a single document.
///
/// Reopens the plan that document belongs to, clears its error rows, and dispatches an
/// `execute_plans` operation. The plan is the pipeline's unit of work, so its other
/// documents are reprocessed too, which is not yet decided.
///
/// The error rows are cleared before the re-run here, unlike the per-task retry, which
/// keeps them until the documents are demonstrably fixed. One document is a small
/// enough claim that the file browser showing it clean and then failing again is
/// tolerable; a whole task's worth is not.
pub async fn admin_retry_document(
    user: &CurrentUser,
    collectionname: String,
    collection_dataset: String,
    hash: String,
) -> anyhow::Result<String> {
    guard::require_admin(user)?;
    if hash.is_empty() {
        anyhow::bail!("no document hash given");
    }
    let client = get_collection_client(&collectionname);

    let reopened =
        reopen_plans_for_hashes(&client, &collection_dataset, std::slice::from_ref(&hash)).await?;

    client
        .query("ALTER TABLE processing_errors DELETE WHERE collection_dataset = ? AND hash = ?")
        .bind(&collection_dataset)
        .bind(&hash)
        .execute()
        .await?;

    let op_id = operations::dispatch_operation(
        "execute_plans",
        &collectionname,
        &collection_dataset,
        &user.username,
        "",
        "",
    )
    .await?;
    Ok(format!("{op_id} ({reopened} plan(s) reopened)"))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A stage whose documents failed must not read as finished, and the failure
    /// must land on the bar it happened at.
    #[test]
    fn every_error_task_lands_on_a_stage() {
        assert_eq!(stage_for_task("P4_ExtractEntities"), STAGE_NLP);
        assert_eq!(stage_for_task("archive_scan"), STAGE_SCAN);
        assert_eq!(stage_for_task("P6_IndexTextPages"), STAGE_INDEX);
        assert_eq!(stage_for_task("P6_IndexMetadata"), STAGE_INDEX);
        assert_eq!(stage_for_task("P5_ChunkEmbed"), STAGE_INDEX);
        // The parse tasks and anything new default to the execute bar.
        for task in ["detector_error_tika", "run_ocr_and_store", "pdf_process", ""] {
            assert_eq!(stage_for_task(task), STAGE_EXECUTE, "{task}");
        }
    }

    #[test]
    fn a_stage_with_failed_documents_is_not_complete() {
        let mut stage = stage_progress(
            STAGE_NLP,
            "P4",
            "text pages",
            &StageCounts {
                done: 5970,
                total: Some(5970),
                recent_done: None,
                failed_documents: 200,
            },
        );
        assert!(!stage.is_complete());
        stage.failed_documents = 0;
        assert!(stage.is_complete());
    }

    #[test]
    fn short_status_strips_the_prefix() {
        assert_eq!(short_status("WORKFLOW_EXECUTION_STATUS_RUNNING"), "RUNNING");
        assert_eq!(short_status("RUNNING"), "RUNNING");
        assert_eq!(short_status(""), "");
    }

    #[test]
    fn first_line_takes_one_line_and_truncates() {
        assert_eq!(first_line("\n\nboom\ntrace\ntrace", 100), "boom");
        assert_eq!(first_line("abcdef", 3), "abc\u{2026}");
        assert_eq!(first_line("", 10), "");
    }

    #[test]
    fn visibility_query_covers_every_trigger_id() {
        let q = collection_visibility_query(&["c_ds".to_string()], WorkflowFilter::All).unwrap();
        for prefix in ["ingest-disk", "compute-plans", "execute-plans", "purge-dataset"] {
            assert!(q.contains(&format!("WorkflowId = '{prefix}-c_ds'")), "missing {prefix}");
        }
        assert!(!q.contains("ExecutionStatus"));
    }

    #[test]
    fn visibility_query_has_search_attribute_and_id_fallback() {
        let q = collection_visibility_query(&["c_ds".to_string()], WorkflowFilter::All).unwrap();
        // The search-attribute clause finds child workflows; the id clause keeps
        // pre-attribute runs visible.
        assert!(q.contains("CollectionDataset = 'c_ds'"));
        assert!(q.contains("WorkflowId = 'ingest-disk-c_ds'"));
        assert!(q.contains(" OR "));
    }

    #[test]
    fn visibility_query_quotes_each_dataset_safely() {
        let q = collection_visibility_query(
            &["ds_one".to_string(), "ds_two".to_string()],
            WorkflowFilter::All,
        )
        .unwrap();
        assert!(q.contains("CollectionDataset = 'ds_one'"));
        assert!(q.contains("CollectionDataset = 'ds_two'"));
    }

    #[test]
    fn visibility_query_adds_status_filter() {
        let q =
            collection_visibility_query(&["c_ds".to_string()], WorkflowFilter::Running).unwrap();
        assert!(q.contains("ExecutionStatus = 'Running'"));
        assert!(q.contains(" AND "));
    }

    #[test]
    fn visibility_query_without_datasets_is_status_only() {
        assert_eq!(
            collection_visibility_query(&[], WorkflowFilter::Failed),
            Some(WorkflowFilter::Failed.status_clause().unwrap().to_string())
        );
        assert_eq!(collection_visibility_query(&[], WorkflowFilter::All), None);
    }

    /// A dataset name is validated upstream, but the query builder must not be the
    /// thing that trusts it.
    #[test]
    fn visibility_query_drops_quoted_ids() {
        assert_eq!(
            collection_visibility_query(&["bad'name".to_string()], WorkflowFilter::All),
            None
        );
    }

    fn counts(done: u64, total: Option<u64>, recent: Option<u64>) -> StageCounts {
        StageCounts {
            done,
            total,
            recent_done: recent,
            failed_documents: 0,
        }
    }

    #[test]
    fn eta_scales_with_the_measured_rate() {
        // 100 remaining at 10/min over the window -> 600s.
        let p = stage_progress("s", "S", "u", &counts(0, Some(100), Some(10 * RATE_WINDOW_MINUTES)));
        assert_eq!(p.eta_seconds, Some(600));
        assert_eq!(p.rate_per_minute, Some(10.0));
    }

    #[test]
    fn no_eta_when_idle_complete_or_unbounded() {
        assert_eq!(stage_progress("s", "S", "u", &counts(0, Some(100), Some(0))).eta_seconds, None);
        assert_eq!(stage_progress("s", "S", "u", &counts(100, Some(100), Some(50))).eta_seconds, None);
        assert_eq!(stage_progress("s", "S", "u", &counts(5, None, None)).eta_seconds, None);
    }

    #[test]
    fn percent_and_completion() {
        let p = stage_progress("s", "S", "u", &counts(25, Some(50), None));
        assert_eq!(p.percent(), Some(50.0));
        assert!(!p.is_complete());
        // Nothing to do reads as done, not as 0%.
        let empty = stage_progress("s", "S", "u", &counts(0, Some(0), None));
        assert_eq!(empty.percent(), Some(100.0));
        assert!(empty.is_complete());
        assert_eq!(stage_progress("s", "S", "u", &counts(9, None, None)).percent(), None);
    }

    #[test]
    fn parse_workflow_builds_a_deep_link() {
        let raw = serde_json::json!({
            "execution": { "workflowId": "execute-plans-c_ds", "runId": "abc" },
            "type": { "name": "ExecutePlans" },
            "status": "WORKFLOW_EXECUTION_STATUS_FAILED",
            "taskQueue": "processing-common-queue",
            "startTime": "2026-01-01T00:00:00Z",
            "parentExecution": { "workflowId": "parent-1" }
        });
        let wf = parse_workflow(&raw, "http://localhost:21909").unwrap();
        assert_eq!(wf.status, "FAILED");
        assert!(wf.is_failed());
        assert!(!wf.is_running());
        assert_eq!(wf.close_time, None);
        assert_eq!(wf.parent_workflow_id.as_deref(), Some("parent-1"));
        assert_eq!(
            wf.temporal_url,
            "http://localhost:21909/namespaces/default/workflows/execute-plans-c_ds/abc/history"
        );
    }

    fn inflight(task: &str, count: u64, oldest_ms: u64) -> InFlightRow {
        InFlightRow {
            task_name: task.to_string(),
            in_flight: count,
            oldest_age_ms: oldest_ms,
        }
    }

    #[test]
    fn live_shares_add_up_and_concurrency_is_per_second() {
        let live = merge_live(
            60,
            vec![("a".into(), 90.0, 3), ("b".into(), 30.0, 1)],
            vec![inflight("a", 2, 5_000)],
            1_700_000_000,
        );
        assert_eq!(live.rows[0].task_name, "a");
        assert_eq!(live.rows[0].share_percent, 75.0);
        assert_eq!(live.rows[1].share_percent, 25.0);
        // 120 task-seconds inside a 60 s window is two activities running on average.
        assert_eq!(live.average_concurrency, 2.0);
        assert_eq!(live.in_flight_total, 2);
        assert_eq!(live.rows[0].oldest_age_seconds, 5);
        assert!(live.sampled_at.is_some());
    }

    /// The stuck-task case: running for minutes, so it has completed nothing and would
    /// vanish from a completed-rows-only view exactly when it matters most.
    #[test]
    fn a_task_that_is_only_running_still_gets_a_row() {
        let live = merge_live(60, vec![], vec![inflight("slow_ocr", 1, 900_000)], 17);
        assert_eq!(live.rows.len(), 1);
        assert_eq!(live.rows[0].task_name, "slow_ocr");
        assert_eq!(live.rows[0].seconds_in_window, 0.0);
        assert_eq!(live.rows[0].oldest_age_seconds, 900);
        assert_eq!(live.in_flight_total, 1);
    }

    #[test]
    fn nothing_running_is_empty_not_an_error() {
        let live = merge_live(60, vec![], vec![], 0);
        assert!(live.rows.is_empty());
        assert_eq!(live.in_flight_total, 0);
        assert_eq!(live.average_concurrency, 0.0);
        assert_eq!(live.sampled_at, None);
    }

    #[test]
    fn share_of_nothing_is_zero_not_nan() {
        assert_eq!(share(0.0, 0.0), 0.0);
        assert_eq!(share(1.0, 4.0), 25.0);
    }

    #[test]
    fn parse_workflow_rejects_a_row_without_an_execution() {
        assert!(parse_workflow(&serde_json::json!({ "type": { "name": "X" } }), "u").is_none());
    }
}
