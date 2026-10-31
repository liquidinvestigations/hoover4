//! Processing updates on the admin pages: read the stored state, request a calculation,
//! and start an update with the steps that a person selected.
//!
//! The pipeline owns the calculation (`main_services/processing/tasks/P_admin/updates/`).
//! This module reads its three state tables, so a page load runs no count query. A
//! calculation request and a settings save signal the coordinator workflow
//! `processing-updates` over Temporal's HTTP API. The signal also starts the coordinator
//! when it is closed.
//!
//! A request names its steps and the fingerprints that the page showed. An empty
//! selection is refused here and in the pipeline, because no selection means no work.
//! The pipeline refuses a request whose fingerprints changed, with the new counts, and
//! runs nothing.

use std::collections::HashMap;

use common::current_user::CurrentUser;
use common::processing_updates::{ProcessingUpdatesView, UpdateStepState, UpdateStepView};
use time::format_description::well_known::Rfc3339;

use crate::api::admin::operations;
use crate::auth::guard;
use crate::db_utils::clickhouse_utils::get_global_client;

/// The coordinator workflow, its signal and its queue. Mirrors `COORDINATOR_ID` and the
/// `request_check` signal in `tasks/P_admin/updates/workflows.py`.
pub const COORDINATOR_ID: &str = "processing-updates";
const COORDINATOR_TYPE: &str = "ProcessingUpdates";
const COORDINATOR_QUEUE: &str = "processing-common-queue";

#[derive(clickhouse::Row, serde::Deserialize)]
struct CheckRow {
    step_id: String,
    desired_fingerprint: String,
    pending_files: u64,
    pending_bytes: u64,
    automatic_files: u64,
    executions: u64,
    detail: String,
    check_ms: u32,
    checked_on: i64,
}

#[derive(clickhouse::Row, serde::Deserialize)]
struct AttemptRow {
    step_id: String,
    op_id: String,
    desired_fingerprint: String,
    state: String,
    error: String,
    started_on: i64,
    operation_state: String,
}

fn format_ts(unix_seconds: i64) -> String {
    if unix_seconds <= 0 {
        return String::new();
    }
    time::OffsetDateTime::from_unix_timestamp(unix_seconds)
        .ok()
        .and_then(|dt| dt.format(&Rfc3339).ok())
        .unwrap_or_default()
}

/// The state of a running attempt row whose operation row ended, as the pipeline reads
/// it (`database/processing_updates.py:effective_attempt_state`).
fn effective_attempt_state(state: &str, operation_state: &str) -> String {
    if state != "running" || !matches!(operation_state, "finished" | "errored" | "cancelled") {
        return state.to_string();
    }
    if operation_state == "cancelled" { "cancelled".into() } else { "failed".into() }
}

/// The display state of one step from its check, applied fingerprint and newest attempt.
fn step_state(
    step_id: &str,
    check: &CheckRow,
    applied: Option<&String>,
    attempt: Option<&AttemptRow>,
) -> UpdateStepState {
    if let Some(attempt) = attempt {
        let state = effective_attempt_state(&attempt.state, &attempt.operation_state);
        if state == "running" {
            return UpdateStepState::Running;
        }
        if attempt.desired_fingerprint == check.desired_fingerprint && applied != Some(&check.desired_fingerprint) {
            match state.as_str() {
                "failed" => return UpdateStepState::Failed,
                "cancelled" => return UpdateStepState::Cancelled,
                _ => {}
            }
        }
    }
    if applied == Some(&check.desired_fingerprint) {
        if step_id == "failed_files" && check.pending_files > 0 {
            return UpdateStepState::RetryAvailable;
        }
        return UpdateStepState::UpToDate;
    }
    if check.pending_files > 0 { UpdateStepState::Waiting } else { UpdateStepState::UpToDate }
}

/// The stored state of one scope.
pub async fn read_view(scope_kind: &str, scope_id: &str, collectionname: &str) -> anyhow::Result<ProcessingUpdatesView> {
    let client = get_global_client();
    let checks: Vec<CheckRow> = client
        .query(
            "SELECT step_id, desired_fingerprint, pending_files, pending_bytes, automatic_files, \
             executions, detail, check_ms, toInt64(toUnixTimestamp(checked_at)) AS checked_on \
             FROM processing_update_checks FINAL WHERE scope_id = ?",
        )
        .bind(scope_id)
        .fetch_all()
        .await?;
    let applied: HashMap<String, String> = client
        .query("SELECT step_id, applied_fingerprint FROM processing_update_applied FINAL WHERE scope_id = ?")
        .bind(scope_id)
        .fetch_all::<(String, String)>()
        .await?
        .into_iter()
        .collect();
    let attempts: Vec<AttemptRow> = client
        .query(
            "SELECT a.step_id AS step_id, a.op_id AS op_id, a.desired_fingerprint AS desired_fingerprint, \
             a.state AS state, a.error AS error, toInt64(toUnixTimestamp(a.started_at)) AS started_on, \
             o.state AS operation_state \
             FROM processing_update_attempts AS a FINAL \
             LEFT JOIN (SELECT op_id, state FROM operations FINAL \
                        WHERE kind IN ('update_dataset', 'update_collection')) AS o ON o.op_id = a.op_id \
             WHERE a.scope_id = ? ORDER BY a.started_at DESC",
        )
        .bind(scope_id)
        .fetch_all()
        .await?;
    let mut newest: HashMap<String, &AttemptRow> = HashMap::new();
    for attempt in &attempts {
        newest.entry(attempt.step_id.clone()).or_insert(attempt);
    }
    let running: Vec<(String, String, u64, u64)> = client
        .query(
            "SELECT op_id, state, progress_done, progress_total FROM operations FINAL \
             WHERE kind IN ('update_dataset', 'update_collection') AND state IN ('pending', 'queued', 'running') \
             AND (collection_dataset = ? OR (target_kind = 'collection' AND collectionname = ? AND ? = 'collection')) \
             ORDER BY started_at DESC LIMIT 1",
        )
        .bind(scope_id)
        .bind(collectionname)
        .bind(scope_kind)
        .fetch_all()
        .await?;

    let mut view = ProcessingUpdatesView {
        scope_kind: scope_kind.to_string(),
        scope_id: scope_id.to_string(),
        collectionname: collectionname.to_string(),
        automatic: std::env::var("HOOVER4_PROCESSING_UPDATES_AUTOMATIC").map_or(true, |v| v.trim() != "false"),
        ..Default::default()
    };
    if let Some((op_id, state, done, total)) = running.into_iter().next() {
        view.running_op_id = op_id;
        view.running_state = state;
        view.running_done = done;
        view.running_total = total;
    }
    let mut ordered: Vec<(i64, UpdateStepView)> = Vec::new();
    for check in &checks {
        if check.step_id.is_empty() {
            view.unique_files = check.pending_files;
            view.unique_bytes = check.pending_bytes;
            view.executions = check.executions;
            view.checked_at = format_ts(check.checked_on);
            view.check_ms = u64::from(check.check_ms);
            continue;
        }
        let detail: serde_json::Value = serde_json::from_str(&check.detail).unwrap_or_default();
        let text = |key: &str| detail.get(key).and_then(|v| v.as_str()).unwrap_or_default().to_string();
        let attempt = newest.get(&check.step_id).copied();
        let state = step_state(&check.step_id, check, applied.get(&check.step_id), attempt);
        ordered.push((
            detail.get("order").and_then(|v| v.as_i64()).unwrap_or(99),
            UpdateStepView {
                step_id: check.step_id.clone(),
                title: text("title"),
                explanation: text("explanation"),
                runs: text("runs"),
                unit: text("unit"),
                pending: check.pending_files,
                pending_bytes: check.pending_bytes,
                automatic: check.automatic_files,
                state,
                fingerprint: check.desired_fingerprint.clone(),
                last_run_at: attempt.map(|a| format_ts(a.started_on)).unwrap_or_default(),
                last_op_id: attempt.map(|a| a.op_id.clone()).unwrap_or_default(),
                last_error: attempt.map(|a| a.error.clone()).unwrap_or_default(),
            },
        ));
    }
    ordered.sort_by_key(|(order, _)| *order);
    view.steps = ordered.into_iter().map(|(_, step)| step).collect();

    if scope_kind == "dataset" {
        let collection = Box::pin(read_view("collection", collectionname, collectionname)).await?;
        view.prerequisites_waiting = collection
            .steps
            .iter()
            .filter(|s| !matches!(s.state, UpdateStepState::UpToDate))
            .map(|s| s.title.clone())
            .collect();
    }
    Ok(view)
}

/// Ask the coordinator to calculate a scope now. `*` asks for every scope.
///
/// The signal starts the coordinator when it is closed, so a closed coordinator returns
/// with the first settings save or page request.
pub async fn signal_check(scope_id: &str) -> anyhow::Result<()> {
    let base = crate::temporal_ready::temporal_base_url();
    let url = format!(
        "{base}/api/v1/namespaces/default/workflows/{COORDINATOR_ID}/signal-with-start/request_check"
    );
    let body = serde_json::json!({
        "workflowType": { "name": COORDINATOR_TYPE },
        "taskQueue": { "name": COORDINATOR_QUEUE },
        "signalInput": [ { "scope_id": scope_id, "force": true } ],
    });
    crate::temporal_ready::wait_for_temporal().await?;
    let response = crate::temporal_ready::start_client().post(&url).json(&body).send().await?;
    if !response.status().is_success() {
        let text = response.text().await.unwrap_or_default();
        anyhow::bail!("could not ask the processing update coordinator to calculate {scope_id}: {text}");
    }
    Ok(())
}

/// The processing updates of one dataset.
pub async fn admin_get_processing_updates(
    user: &CurrentUser,
    collection_dataset: String,
) -> anyhow::Result<ProcessingUpdatesView> {
    guard::require_admin(user)?;
    let collectionname = crate::db_utils::collectionname_of_dataset(&collection_dataset).await?;
    read_view("dataset", &collection_dataset, &collectionname).await
}

/// The collection steps, and the status line of each dataset of the collection.
pub async fn admin_get_collection_updates(
    user: &CurrentUser,
    collectionname: String,
) -> anyhow::Result<(ProcessingUpdatesView, Vec<(String, String)>)> {
    guard::require_admin(user)?;
    crate::db_utils::clickhouse_utils::collection_db_name(&collectionname)?;
    let collection = read_view("collection", &collectionname, &collectionname).await?;
    let datasets: Vec<String> = get_global_client()
        .query("SELECT collection_dataset FROM dataset FINAL WHERE collectionname = ? AND is_deleted = 0 ORDER BY collection_dataset")
        .bind(&collectionname)
        .fetch_all()
        .await?;
    let mut lines = Vec::new();
    for dataset in datasets {
        let view = read_view("dataset", &dataset, &collectionname).await?;
        lines.push((dataset, view.status_line()));
    }
    Ok((collection, lines))
}

/// Ask the pipeline to calculate the updates of a dataset or a collection now.
pub async fn admin_request_update_check(user: &CurrentUser, scope_id: String) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    signal_check(&scope_id).await
}

/// Refuse an empty selection and steps that the page did not show.
fn validate_selection(
    view: &ProcessingUpdatesView,
    steps: &[String],
    fingerprints: &[String],
) -> anyhow::Result<serde_json::Value> {
    if steps.is_empty() {
        return Err(guard::InvalidInput("Select at least one update step.".to_string()).into());
    }
    if steps.len() != fingerprints.len() {
        anyhow::bail!("each selected step needs the fingerprint that the page showed");
    }
    let mut chosen = serde_json::Map::new();
    for (step, fingerprint) in steps.iter().zip(fingerprints) {
        if !view.steps.iter().any(|s| &s.step_id == step) {
            return Err(guard::InvalidInput(format!("{step} is not an update step of {}.", view.scope_id)).into());
        }
        chosen.insert(step.clone(), serde_json::Value::String(fingerprint.clone()));
    }
    Ok(serde_json::json!({ "steps": steps, "fingerprints": chosen, "automatic": false }))
}

/// Start an `update_dataset` operation with the selected steps.
pub async fn admin_start_processing_update(
    user: &CurrentUser,
    collection_dataset: String,
    steps: Vec<String>,
    fingerprints: Vec<String>,
) -> anyhow::Result<String> {
    guard::require_admin(user)?;
    let collectionname = crate::db_utils::collectionname_of_dataset(&collection_dataset).await?;
    let view = read_view("dataset", &collection_dataset, &collectionname).await?;
    let detail = validate_selection(&view, &steps, &fingerprints)?;
    operations::dispatch_operation(
        "update_dataset", &collectionname, &collection_dataset, &user.username, "", &detail.to_string(),
    )
    .await
}

/// Start an `update_collection` operation with the selected collection steps.
pub async fn admin_start_collection_update(
    user: &CurrentUser,
    collectionname: String,
    steps: Vec<String>,
    fingerprints: Vec<String>,
) -> anyhow::Result<String> {
    guard::require_admin(user)?;
    crate::db_utils::clickhouse_utils::collection_db_name(&collectionname)?;
    let view = read_view("collection", &collectionname, &collectionname).await?;
    let detail = validate_selection(&view, &steps, &fingerprints)?;
    operations::dispatch_operation(
        "update_collection", &collectionname, "", &user.username, "", &detail.to_string(),
    )
    .await
}

#[cfg(test)]
mod tests {
    use super::*;

    fn check(fp: &str, pending: u64) -> CheckRow {
        CheckRow {
            step_id: "ocr".into(), desired_fingerprint: fp.into(), pending_files: pending,
            pending_bytes: 0, automatic_files: pending, executions: 0, detail: "{}".into(),
            check_ms: 0, checked_on: 0,
        }
    }

    fn attempt(fp: &str, state: &str, operation: &str) -> AttemptRow {
        AttemptRow {
            step_id: "ocr".into(), op_id: "op".into(), desired_fingerprint: fp.into(),
            state: state.into(), error: String::new(), started_on: 0, operation_state: operation.into(),
        }
    }

    #[test]
    fn a_step_reads_its_state_from_check_applied_and_attempt() {
        let applied = "F".to_string();
        assert_eq!(step_state("ocr", &check("F", 4), None, None), UpdateStepState::Waiting);
        assert_eq!(step_state("ocr", &check("F", 4), Some(&applied), None), UpdateStepState::UpToDate);
        assert_eq!(step_state("ocr", &check("F", 0), None, None), UpdateStepState::UpToDate);
        assert_eq!(step_state("failed_files", &check("F", 4), Some(&applied), None), UpdateStepState::RetryAvailable);
        let running = attempt("F", "running", "running");
        assert_eq!(step_state("ocr", &check("F", 4), None, Some(&running)), UpdateStepState::Running);
        let cancelled = attempt("F", "running", "cancelled");
        assert_eq!(step_state("ocr", &check("F", 4), None, Some(&cancelled)), UpdateStepState::Cancelled);
        let failed_old = attempt("OLD", "failed", "errored");
        assert_eq!(step_state("ocr", &check("F", 4), None, Some(&failed_old)), UpdateStepState::Waiting);
    }

    #[test]
    fn an_empty_or_unknown_selection_is_refused() {
        let view = ProcessingUpdatesView {
            scope_id: "c_ds".into(),
            steps: vec![UpdateStepView { step_id: "ocr".into(), ..Default::default() }],
            ..Default::default()
        };
        assert!(validate_selection(&view, &[], &[]).is_err());
        assert!(validate_selection(&view, &["vectors".into()], &["F".into()]).is_err());
        let detail = validate_selection(&view, &["ocr".into()], &["F".into()]).unwrap();
        assert_eq!(detail["fingerprints"]["ocr"], "F");
        assert_eq!(detail["automatic"], false);
    }
}
