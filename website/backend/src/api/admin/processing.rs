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
//! has unmerged duplicates — every count below uses `FINAL` or `uniqExact` to avoid
//! that, at the cost of some query time. These are admin pages hit by a handful of
//! people, so correctness wins over latency here.

use std::collections::BTreeMap;

use common::current_user::CurrentUser;
use common::processing_types::*;
use time::format_description::well_known::Rfc3339;

use crate::api::admin::temporal_trigger;
use crate::auth::guard;
use crate::db_auth::collections;
use crate::db_utils::clickhouse_utils::{get_collection_client, get_global_client};

/// Base URL of the Temporal *UI*, used only to build deep links shown to admins.
/// Distinct from `TEMPORAL_HTTP_URL`, which is the API the backend calls: the UI runs
/// on a different port and, unlike the API, is reached from the admin's browser rather
/// than from this container, so it must be a host-reachable address.
fn temporal_ui_base() -> String {
    std::env::var("TEMPORAL_UI_URL").unwrap_or_else(|_| "http://localhost:8081".to_string())
}

fn temporal_api_base() -> String {
    std::env::var("TEMPORAL_HTTP_URL").unwrap_or_else(|_| "http://localhost:7243".to_string())
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

    // P0 — scan. Blobs discovered so far. No denominator: the scan learns the size of
    // the job as it walks the tree, and `blobs` has no timestamp column, so no ETA.
    let scanned = grouped_counts(
        &client,
        "SELECT collection_dataset, uniqExact(blob_hash) AS value \
         FROM blobs GROUP BY collection_dataset",
    )
    .await?;

    // P1 — plan computation. Every discovered blob should end up in exactly one plan.
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

    // P2/P3 — plan execution (parsing happens inside the plan execution workflow, so
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

    // P4 — NLP/NER. Denominator is the text segments extracted by P3.
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

    // P5 — indexing. Denominator is documents with text, not segments: indexing writes
    // one Manticore document per file.
    let docs_total = grouped_counts(
        &client,
        "SELECT collection_dataset, uniqExact(file_hash) AS value \
         FROM text_content GROUP BY collection_dataset",
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
                },
            ),
            stage_progress(
                STAGE_NLP,
                "P4 · Extract entities (NLP)",
                "text segments",
                &StageCounts {
                    done: pick(&segments_nlp, &ds),
                    total: Some(pick(&segments_total, &ds)),
                    recent_done: Some(pick(&segments_nlp_recent, &ds)),
                },
            ),
            stage_progress(
                STAGE_INDEX,
                "P5 · Index for search",
                "documents",
                &StageCounts {
                    done: pick(&docs_indexed, &ds),
                    total: Some(pick(&docs_total, &ds)),
                    recent_done: Some(pick(&docs_indexed_recent, &ds)),
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
/// Pipeline workflow ids are `<kind>-<collection_dataset>` (see `temporal_trigger`), so
/// each dataset contributes the exact top-level ids the trigger module can produce,
/// OR-ed together. Child workflows (`HandleFolders-<hash>`, per-plan runs) carry no
/// dataset in their id — they are matched through the `CollectionDataset` search
/// attribute that the workers register at startup and set on every workflow start
/// (see `tasks/visibility.py`). The id clause stays as a fallback `OR` so workflows
/// started before the attribute existed still show up.
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
                    uniqExact(hash) AS document_count, toUnixTimestamp(max(timestamp)) AS last_seen, \
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
                count() AS error_count, toUnixTimestamp(max(timestamp)) AS last_seen, \
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
/// plan — P4 entity extraction is the common case — still lets the plan finish. So
/// restarting the workflow on its own is a no-op for exactly the failures an admin is
/// most likely to be looking at. Deleting the finished-marker first is what puts the
/// work back in front of the pipeline.
///
/// Reprocessing a whole plan to fix one document is coarse (a plan is a batch of
/// blobs), but the pipeline's unit of work *is* the plan, and every stage is
/// idempotent — re-running one costs time, not correctness.
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

/// Re-run the pipeline for the documents a task failed on.
///
/// Reopens every plan containing a document that `task_name` failed on, clears those
/// error rows, and restarts `ExecutePlans`. The workflow id is dataset-keyed, so a
/// second click while one is running is a no-op rather than a duplicate run.
pub async fn admin_retry_failed_task(
    user: &CurrentUser,
    collectionname: String,
    collection_dataset: String,
    task_name: String,
) -> anyhow::Result<String> {
    guard::require_admin(user)?;
    let client = get_collection_client(&collectionname);

    let hashes: Vec<String> = client
        .query(
            "SELECT DISTINCT hash FROM processing_errors \
             WHERE collection_dataset = ? AND task_name = ? AND hash != ''",
        )
        .bind(&collection_dataset)
        .bind(&task_name)
        .fetch_all::<String>()
        .await?;

    let reopened = reopen_plans_for_hashes(&client, &collection_dataset, &hashes).await?;

    // Clear the errors we are about to retry. Bounded to one task of one dataset; a
    // mutation is the only way to delete from a plain MergeTree.
    client
        .query(
            "ALTER TABLE processing_errors DELETE \
             WHERE collection_dataset = ? AND task_name = ?",
        )
        .bind(&collection_dataset)
        .bind(&task_name)
        .execute()
        .await?;

    let run_id = temporal_trigger::trigger_workflow(&collection_dataset, "execute_plans").await?;
    Ok(format!("{run_id} ({reopened} plan(s) reopened)"))
}

/// Retry the processing of a single document.
///
/// Reopens the plan that document belongs to, clears its error rows, and restarts
/// `ExecutePlans`. The plan is the pipeline's unit of work, so its other documents are
/// reprocessed too — see open question Q4.
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

    let run_id = temporal_trigger::trigger_workflow(&collection_dataset, "execute_plans").await?;
    Ok(format!("{run_id} ({reopened} plan(s) reopened)"))
}

#[cfg(test)]
mod tests {
    use super::*;

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
        let wf = parse_workflow(&raw, "http://localhost:8081").unwrap();
        assert_eq!(wf.status, "FAILED");
        assert!(wf.is_failed());
        assert!(!wf.is_running());
        assert_eq!(wf.close_time, None);
        assert_eq!(wf.parent_workflow_id.as_deref(), Some("parent-1"));
        assert_eq!(
            wf.temporal_url,
            "http://localhost:8081/namespaces/default/workflows/execute-plans-c_ds/abc/history"
        );
    }

    #[test]
    fn parse_workflow_rejects_a_row_without_an_execution() {
        assert!(parse_workflow(&serde_json::json!({ "type": { "name": "X" } }), "u").is_none());
    }
}
