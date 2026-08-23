//! The operations log, read and dispatched from the admin UI.
//!
//! `Hoover4_Processing.operations` is the permanent record of every long operation
//! somebody asked for: what it was, who asked, how far it got and how it ended. The
//! processing side writes it; this module reads it and dispatches new ones the same way
//! the command line does, so a person and a terminal see one history rather than two.
//!
//! Three properties of the table decide the shape of everything below.
//!
//! * It is a `ReplacingMergeTree(updated_at)`, so every read says `FINAL` or it will
//!   see one operation several times, once per state transition.
//! * `started_at` leads the sort key and is immutable for a given `op_id`, so
//!   newest-first paging reads the tail of the primary key instead of sorting.
//! * `op_id` **is** the Temporal workflow id and carries a timestamp, so a dispatch can
//!   never collapse into a running execution and a re-run is always a new row.

use common::current_user::CurrentUser;
use common::operations_types::{OperationRow, OperationsPage, TaskErrorRate};
use time::format_description::well_known::Rfc3339;

use crate::auth::guard;
use crate::db_auth::collections;
use crate::db_utils::clickhouse_utils::{get_collection_client, get_global_client};

/// Every operation kind, what it locks on, and whether it destroys data.
///
/// A deliberate mirror of `KINDS` in the processing side's `database/operations.py`.
/// Destructiveness is a property of the kind and not of the caller, which is the whole
/// reason it is a table in two places rather than a judgement made at each button: the
/// CLI and this page cannot disagree about which operations are dangerous. **A kind
/// added on one side must be added on the other.**
const KINDS: &[(&str, &str, bool)] = &[
    // (kind, target_kind, destructive)
    ("add_dataset", "dataset", false),
    ("rescan_dataset", "dataset", false),
    ("compute_plans", "dataset", false),
    ("execute_plans", "dataset", false),
    ("purge_dataset", "dataset", true),
    ("delete_dataset", "dataset", true),
    ("change_ocr_languages", "dataset", false),
    ("reindex_collection", "collection", false),
    ("retry_failed_files", "dataset", false),
    ("ensure_collection", "collection", false),
    ("drop_collection_database", "collection", true),
    ("export_collection", "collection", false),
    ("import_collection", "collection", true),
];

/// Kinds the operations workflow can actually drive today. The rest are registered —
/// the table, the lock and the destructive flag know them — but dispatching one raises
/// a named error, so the UI must not offer to start or re-run them.
const DRIVEN_KINDS: &[&str] = &[
    "add_dataset",
    "rescan_dataset",
    "reindex_collection",
    "purge_dataset",
    "change_ocr_languages",
    "retry_failed_files",
];

fn kind_entry(kind: &str) -> Option<&'static (&'static str, &'static str, bool)> {
    KINDS.iter().find(|(k, _, _)| *k == kind)
}

fn is_destructive(kind: &str) -> bool {
    kind_entry(kind).map(|(_, _, d)| *d).unwrap_or(false)
}

/// The error rate above which a task type is called out as a possible tooling
/// limitation rather than as ordinary mess.
///
/// Deployment configuration, never a literal in a component: it is a judgement about
/// what counts as an acceptable failure rate on a messy corpus, it will be revised, and
/// a judgement buried in rendering code is one nobody can find. Unset falls back to the
/// value the project currently judges by.
pub fn error_rate_threshold_percent() -> f64 {
    std::env::var("HOOVER4_ERROR_RATE_ALERT_PERCENT")
        .ok()
        .and_then(|v| v.trim().parse::<f64>().ok())
        .filter(|v| *v > 0.0)
        .unwrap_or(5.0)
}

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
struct OperationDbRow {
    op_id: String,
    kind: String,
    target_kind: String,
    collectionname: String,
    collection_dataset: String,
    state: String,
    #[serde(with = "clickhouse::serde::time::datetime")]
    started_at: time::OffsetDateTime,
    #[serde(with = "clickhouse::serde::time::datetime")]
    finished_at: time::OffsetDateTime,
    #[serde(with = "clickhouse::serde::time::datetime")]
    updated_at: time::OffsetDateTime,
    progress_done: u64,
    progress_total: u64,
    eta_seconds: u32,
    detail: String,
    error: String,
    user_id: String,
    rerun_of: String,
}

/// The column list, in table order. A `ReplacingMergeTree` update rewrites the whole
/// row, so a column missing from an insert is silently reset to its default — and
/// RowBinary is positional, so a select in a different order pairs values with the
/// wrong fields without complaining.
const COLUMNS: &str = "op_id, kind, target_kind, collectionname, collection_dataset, \
                       state, started_at, finished_at, updated_at, \
                       progress_done, progress_total, eta_seconds, \
                       detail, error, user_id, rerun_of";

fn format_datetime(dt: time::OffsetDateTime) -> String {
    dt.format(&Rfc3339).unwrap_or_else(|_| dt.to_string())
}

/// Epoch 0 is the table's own "not finished" sentinel, not a real timestamp.
fn finished_at_of(dt: time::OffsetDateTime) -> Option<String> {
    if dt.unix_timestamp() <= 0 {
        None
    } else {
        Some(format_datetime(dt))
    }
}

/// Read a counter the operation recorded into its own `detail` JSON.
///
/// Absent means the operation never counted, which is a different answer from zero and
/// is carried as `None` all the way to the page: an older row, or a kind that does not
/// process documents, must render as unknown rather than as a clean run.
fn detail_u64(detail: &str, key: &str) -> Option<u64> {
    serde_json::from_str::<serde_json::Value>(detail)
        .ok()?
        .get(key)?
        .as_u64()
}

fn to_display_row(r: OperationDbRow) -> OperationRow {
    let now = time::OffsetDateTime::now_utc().unix_timestamp();
    let end = if r.finished_at.unix_timestamp() > 0 {
        r.finished_at.unix_timestamp()
    } else {
        now
    };
    let target = match r.target_kind.as_str() {
        "dataset" => r.collection_dataset.clone(),
        "collection" => r.collectionname.clone(),
        _ => String::new(),
    };
    OperationRow {
        destructive: is_destructive(&r.kind),
        failed_documents: detail_u64(&r.detail, "failed_documents"),
        failed_tasks: detail_u64(&r.detail, "failed_tasks"),
        duration_seconds: (end - r.started_at.unix_timestamp()).max(0) as u64,
        started_at: format_datetime(r.started_at),
        finished_at: finished_at_of(r.finished_at),
        target,
        op_id: r.op_id,
        kind: r.kind,
        target_kind: r.target_kind,
        collectionname: r.collectionname,
        collection_dataset: r.collection_dataset,
        state: r.state,
        progress_done: r.progress_done,
        progress_total: r.progress_total,
        eta_seconds: r.eta_seconds,
        error: r.error,
        user_id: r.user_id,
        rerun_of: r.rerun_of,
        detail: r.detail,
    }
}

async fn fetch_rows(
    state: &str,
    collectionname: &str,
    limit: u32,
    offset: u32,
) -> anyhow::Result<Vec<OperationDbRow>> {
    let client = get_global_client();
    // Both filters are bound parameters guarded by a flag, rather than an SQL string
    // assembled from whether they are empty: one query shape means one plan and one
    // place to be wrong.
    let sql = format!(
        "SELECT {COLUMNS} FROM operations FINAL \
         WHERE (? = '' OR state = ?) AND (? = '' OR collectionname = ?) \
         ORDER BY started_at DESC, op_id DESC LIMIT ? OFFSET ?"
    );
    Ok(client
        .query(&sql)
        .bind(state)
        .bind(state)
        .bind(collectionname)
        .bind(collectionname)
        .bind(limit)
        .bind(offset)
        .fetch_all::<OperationDbRow>()
        .await?)
}

/// Task types this collection has run, with how often they failed.
///
/// Numerator and denominator both come from `processing_task_runs`, which holds one row
/// per activity execution whatever its outcome. Taking the failures from
/// `processing_errors` instead would divide one table's count by another's, and the two
/// do not name detector failures the same way — a rate off a mismatched denominator is
/// worse than no rate, because it is believable.
async fn task_error_rates(collectionname: &str) -> anyhow::Result<Vec<TaskErrorRate>> {
    #[derive(Debug, clickhouse::Row, serde::Deserialize)]
    struct RateRow {
        task_name: String,
        runs_total: u64,
        runs_failed: u64,
        documents_total: u64,
        documents_failed: u64,
    }

    if !collections::collection_db_ready(collectionname).await? {
        return Ok(Vec::new());
    }
    let threshold = error_rate_threshold_percent();
    let client = get_collection_client(collectionname);
    let rows = client
        .query(
            "SELECT task_name, \
                    count() AS runs_total, \
                    countIf(outcome = 'error') AS runs_failed, \
                    uniqExact(hash) AS documents_total, \
                    uniqExactIf(hash, outcome = 'error') AS documents_failed \
             FROM processing_task_runs \
             GROUP BY task_name \
             ORDER BY runs_failed DESC, runs_total DESC",
        )
        .fetch_all::<RateRow>()
        .await?;

    Ok(rows
        .into_iter()
        .map(|r| {
            let rate = if r.runs_total == 0 {
                0.0
            } else {
                r.runs_failed as f64 * 100.0 / r.runs_total as f64
            };
            TaskErrorRate {
                task_name: r.task_name,
                runs_total: r.runs_total,
                runs_failed: r.runs_failed,
                documents_total: r.documents_total,
                documents_failed: r.documents_failed,
                error_rate_percent: rate,
                above_threshold: rate > threshold,
            }
        })
        .collect())
}

/// The operations log, newest first, with the per-task error rates beside it.
///
/// `collectionname` empty means every collection. The error-rate panel is only
/// computed when one collection is chosen: the counts live in each collection's own
/// database, and summing rates across databases would need every collection queried on
/// every page load to produce a number no one asked for.
pub async fn admin_list_operations(
    user: &CurrentUser,
    state: String,
    collectionname: String,
    limit: u32,
    offset: u32,
) -> anyhow::Result<OperationsPage> {
    guard::require_admin(user)?;
    let limit = limit.clamp(1, 200);
    // One row further than the page, so "is there another page" is answered by the
    // same read rather than by a second count over a table that is being written to.
    let raw = fetch_rows(&state, &collectionname, limit + 1, offset).await?;
    let has_more = raw.len() as u32 > limit;
    let rows: Vec<OperationRow> = raw
        .into_iter()
        .take(limit as usize)
        .map(to_display_row)
        .collect();

    let client = get_global_client();
    let collections = client
        .query("SELECT DISTINCT collectionname FROM operations WHERE collectionname != '' ORDER BY collectionname")
        .fetch_all::<String>()
        .await?;

    let task_error_rates = if collectionname.is_empty() {
        Vec::new()
    } else {
        task_error_rates(&collectionname).await?
    };

    Ok(OperationsPage {
        rows,
        has_more,
        collections,
        task_error_rates,
        error_rate_threshold_percent: error_rate_threshold_percent(),
    })
}

/// Dispatch a fresh operation from an existing one: a new id, a new row, `rerun_of`
/// naming what it came from.
///
/// A re-run is never a resumption. The old row keeps its outcome so the log shows every
/// attempt, which is the reason the id carries a timestamp in the first place.
///
/// `confirm_target` is what the person typed. A destructive kind is refused unless it
/// matches the target exactly — checked here and not only in the browser, because a
/// confirmation enforced in the page is a confirmation that is not enforced.
pub async fn admin_rerun_operation(
    user: &CurrentUser,
    op_id: String,
    confirm_target: String,
) -> anyhow::Result<String> {
    guard::require_admin(user)?;
    let client = get_global_client();
    let sql = format!("SELECT {COLUMNS} FROM operations FINAL WHERE op_id = ? LIMIT 1");
    let mut rows = client
        .query(&sql)
        .bind(&op_id)
        .fetch_all::<OperationDbRow>()
        .await?;
    let Some(row) = rows.pop() else {
        anyhow::bail!("operation not found: {op_id}");
    };
    let display = to_display_row(row);
    if !DRIVEN_KINDS.contains(&display.kind.as_str()) {
        anyhow::bail!(
            "{} has no driver in the operations workflow yet, so it cannot be re-run from here",
            display.kind
        );
    }
    if display.destructive && confirm_target != display.target {
        anyhow::bail!(
            "type the target ({}) to confirm a {} re-run",
            display.target,
            display.kind
        );
    }
    // The original row's `detail` is what the re-run is dispatched with. A kind whose
    // behaviour is decided by parameters — which languages, which failed task — would
    // otherwise be re-run against whatever the dataset is set to now, which is not what
    // the row in front of the person says.
    let detail = display.detail.clone();
    dispatch_operation(
        &display.kind,
        &display.collectionname,
        &display.collection_dataset,
        &user.username,
        &display.op_id,
        &detail,
    )
    .await
}

/// Write the `pending` row, then start the workflow on that row's id.
///
/// The row is written first on purpose: an operation that has a workflow and no row is
/// invisible to everything except Temporal, and Temporal here forgets after a day. If
/// the start then fails, the row is landed in `errored` rather than left holding the
/// lock for ever.
///
/// `detail` is the JSON object the operation is dispatched with — the languages of an
/// OCR change, the failed task of a retry. It goes onto the row *and* into the workflow
/// input, which is what makes a re-run of that row ask for the same thing. Empty falls
/// back to whatever the kind can work out for itself.
pub async fn dispatch_operation(
    kind: &str,
    collectionname: &str,
    collection_dataset: &str,
    user_id: &str,
    rerun_of: &str,
    detail: &str,
) -> anyhow::Result<String> {
    let Some((_, target_kind, _)) = kind_entry(kind) else {
        anyhow::bail!("unknown operation kind: {kind}");
    };
    let target = match *target_kind {
        "dataset" => collection_dataset,
        "collection" => collectionname,
        _ => "global",
    };
    let now = time::OffsetDateTime::now_utc();
    let op_id = format!("{kind}-{target}-{}", now.unix_timestamp());

    // The lock is one rule with one owner: a second dispatch is refused while a
    // non-terminal row holds the same kind and target. A stale row is NOT free — a run
    // that stopped reporting may still have activities in flight.
    let client = get_global_client();
    let target_column = match *target_kind {
        "dataset" => "collection_dataset",
        "collection" => "collectionname",
        _ => "",
    };
    if !target_column.is_empty() {
        let blockers = client
            .query(&format!(
                "SELECT op_id, state FROM operations FINAL \
                 WHERE kind = ? AND {target_column} = ? AND state IN ('pending', 'running') \
                 ORDER BY started_at DESC LIMIT 5"
            ))
            .bind(kind)
            .bind(target)
            .fetch_all::<(String, String)>()
            .await?;
        if !blockers.is_empty() {
            let names = blockers
                .iter()
                .map(|(id, st)| format!("{id} ({st})"))
                .collect::<Vec<_>>()
                .join(", ");
            anyhow::bail!("{kind} is already running for {target}: {names}. Wait for it, or cancel it, then dispatch again.");
        }
    }

    let detail = match detail.trim() {
        "" | "{}" => dispatch_detail(kind, collection_dataset).await,
        given => given.to_string(),
    };
    let epoch = time::OffsetDateTime::from_unix_timestamp(0)?;
    let row = OperationDbRow {
        op_id: op_id.clone(),
        kind: kind.to_string(),
        target_kind: target_kind.to_string(),
        collectionname: collectionname.to_string(),
        collection_dataset: collection_dataset.to_string(),
        state: "pending".to_string(),
        started_at: now,
        finished_at: epoch,
        updated_at: now,
        progress_done: 0,
        progress_total: 0,
        eta_seconds: 0,
        detail: detail.clone(),
        error: String::new(),
        user_id: user_id.to_string(),
        rerun_of: rerun_of.to_string(),
    };
    let mut insert = client.insert::<OperationDbRow>("operations").await?;
    insert.write(&row).await?;
    insert.end().await?;

    match start_operation_workflow(&op_id, kind, collectionname, collection_dataset, &detail).await
    {
        Ok(()) => Ok(op_id),
        Err(e) => {
            let mut failed = row;
            failed.state = "errored".to_string();
            failed.error = format!("{e}");
            failed.finished_at = time::OffsetDateTime::now_utc();
            failed.updated_at = failed.finished_at;
            // `started_at` is carried through untouched: it is in the sort key, and a
            // different one inserts a second row instead of replacing the first, which
            // shows one operation twice in the log.
            let mut insert = client.insert::<OperationDbRow>("operations").await?;
            insert.write(&failed).await?;
            insert.end().await?;
            Err(e)
        }
    }
}

/// The parameters an operation was dispatched with, as its `detail` JSON. A disk
/// dataset's path is read off the registry so the operation carries what it ran on.
async fn dispatch_detail(kind: &str, collection_dataset: &str) -> String {
    if kind != "add_dataset" && kind != "rescan_dataset" {
        return "{}".to_string();
    }
    let path = dataset_path(collection_dataset).await.unwrap_or_default();
    serde_json::json!({ "dataset_path": path }).to_string()
}

async fn dataset_path(collection_dataset: &str) -> anyhow::Result<String> {
    let client = get_global_client();
    let rows = client
        .query("SELECT dataset_path FROM dataset FINAL WHERE collection_dataset = ? AND is_deleted = 0 LIMIT 1")
        .bind(collection_dataset)
        .fetch_all::<String>()
        .await?;
    rows.into_iter()
        .next()
        .ok_or_else(|| anyhow::anyhow!("dataset not found: {collection_dataset}"))
}

/// Start the `Operation` workflow over Temporal's HTTP API, on the operation's own id.
///
/// The workflow id **is** the operation id. It already carries a timestamp, so a reuse
/// policy would decide nothing and a conflict is a genuine one — two dispatches can
/// never collapse into a single execution, which is the property the whole operations
/// layer exists to guarantee.
async fn start_operation_workflow(
    op_id: &str,
    kind: &str,
    collectionname: &str,
    collection_dataset: &str,
    detail: &str,
) -> anyhow::Result<()> {
    let base_url = std::env::var("TEMPORAL_HTTP_URL")
        .unwrap_or_else(|_| "http://localhost:21908".to_string());
    let dataset_path = if kind == "add_dataset" || kind == "rescan_dataset" {
        dataset_path(collection_dataset).await.unwrap_or_default()
    } else {
        String::new()
    };
    // No conflict or reuse policy is sent. This server's HTTP API rejects the request
    // outright with `unknown field "workflowIdConflictPolicy"` rather than ignoring it,
    // and the policy would decide nothing anyway: the id carries a timestamp, so two
    // dispatches never share one, and the server's own default already refuses a start
    // against a running execution of the same id.
    let body = serde_json::json!({
        "workflowType": { "name": "Operation" },
        "taskQueue": { "name": "operations-queue" },
        "input": [ {
            "op_id": op_id,
            "kind": kind,
            "collectionname": collectionname,
            "collection_dataset": collection_dataset,
            "dataset_path": dataset_path,
            // The same object the row carries: the workflow reads its parameters from
            // here, so a row and the execution it names can never describe two
            // different requests.
            "detail": serde_json::from_str::<serde_json::Value>(detail)
                .unwrap_or_else(|_| serde_json::json!({})),
        } ],
    });
    let url = format!("{base_url}/api/v1/namespaces/default/workflows/{op_id}");
    let response = reqwest::Client::new()
        .post(&url)
        .header("Content-Type", "application/json")
        .json(&body)
        .send()
        .await?;
    if !response.status().is_success() {
        let text = response.text().await.unwrap_or_default();
        anyhow::bail!("could not start the operation workflow: {text}");
    }
    Ok(())
}

/// Ask Temporal to cancel an operation and land its row in `cancelled`.
///
/// The terminal row is written **here, by the canceller**, and not by the workflow. A
/// cancelled workflow cannot schedule further activities, so a cleanup write attempted
/// inside it is cancelled with it and the row stays non-terminal for ever — holding the
/// lock that cancelling was meant to release.
pub async fn admin_cancel_operation(user: &CurrentUser, op_id: String) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    let base_url = std::env::var("TEMPORAL_HTTP_URL")
        .unwrap_or_else(|_| "http://localhost:21908".to_string());
    let url =
        format!("{base_url}/api/v1/namespaces/default/workflows/{op_id}/cancel");
    // A workflow that has already finished cannot be cancelled, and that is not a
    // failure of this call: the row still has to be landed either way.
    let _ = reqwest::Client::new()
        .post(&url)
        .header("Content-Type", "application/json")
        .json(&serde_json::json!({}))
        .send()
        .await;

    let client = get_global_client();
    let sql = format!("SELECT {COLUMNS} FROM operations FINAL WHERE op_id = ? LIMIT 1");
    let mut rows = client
        .query(&sql)
        .bind(&op_id)
        .fetch_all::<OperationDbRow>()
        .await?;
    let Some(mut row) = rows.pop() else {
        anyhow::bail!("operation not found: {op_id}");
    };
    if ["finished", "errored", "cancelled"].contains(&row.state.as_str()) {
        return Ok(());
    }
    row.state = "cancelled".to_string();
    row.finished_at = time::OffsetDateTime::now_utc();
    row.updated_at = row.finished_at;
    let mut insert = client.insert::<OperationDbRow>("operations").await?;
    insert.write(&row).await?;
    insert.end().await?;
    Ok(())
}
