//! Types shared between the operations admin page and the backend that feeds it.
//!
//! The operations log is the permanent record of every long operation somebody asked
//! for. Its whole point is that a run which *finished* over failed documents reads as
//! exactly that rather than as green, so every type here carries the failure side of a
//! result beside the success side and never one without the other.

/// One row of the global `operations` table, formatted for display.
///
/// Times are RFC 3339 strings rather than timestamps: the row is rendered, never
/// arithmetic'd, in the browser, and shipping a formatted string keeps the one
/// timezone decision on the server.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct OperationRow {
    /// Also the Temporal workflow id.
    pub op_id: String,
    pub kind: String,
    /// `collection` | `dataset` | `global`.
    pub target_kind: String,
    pub collectionname: String,
    pub collection_dataset: String,
    /// The single string this operation acts on, already resolved from `target_kind`.
    pub target: String,
    /// `pending` | `running` | `finished` | `errored` | `cancelled`.
    pub state: String,
    pub started_at: String,
    /// `None` while the operation has not reached a terminal state.
    pub finished_at: Option<String>,
    /// Wall time, in seconds, to `finished_at` or to now.
    pub duration_seconds: u64,
    pub progress_done: u64,
    /// **Zero means "not yet known", not "no work"**, a scan that has not produced
    /// plans yet reports `0`, and a bar drawn from `done/total` must say so rather
    /// than render an empty bar over a run that is working.
    pub progress_total: u64,
    /// Seconds remaining, `0` when no estimate can be made yet.
    pub eta_seconds: u32,
    pub error: String,
    pub user_id: String,
    /// The `op_id` this run was created from, empty for a first attempt.
    pub rerun_of: String,
    /// Whether re-running this kind needs a typed confirmation naming the target.
    pub destructive: bool,
    /// Documents in this operation's dataset that recorded at least one error, as
    /// counted by the operation itself. `None` means the operation never recorded a
    /// count (an older row, or a kind that does not process documents), and must be
    /// rendered as unknown, never as zero.
    pub failed_documents: Option<u64>,
    /// Individual task failures behind `failed_documents`; one document can fail
    /// several times.
    pub failed_tasks: Option<u64>,
    /// Error rows in the dataset before this operation selected any for a re-run.
    /// `None` means this operation did not use the re-run selector.
    pub errors_before_run: Option<u64>,
    /// Selected Error rows that no longer have an Error row from this operation.
    pub recovered_errors: Option<u64>,
    /// Selected Error rows that have a new Error row from this operation.
    pub still_failing_errors: Option<u64>,
    /// Error rows the selector removed because their stage is disabled.
    pub removed_stage_off_errors: Option<u64>,
    /// Error rows the selector could not attach to an operation plan.
    pub without_plan_errors: Option<u64>,
    /// Selected Error pairs with no supported recovery activity.
    pub unknown_task_errors: Option<u64>,
    /// The `detail` JSON as stored, for the parameters the operation was dispatched
    /// with.
    pub detail: String,
    /// True when `operation_failures` has at least one row for this `op_id`. An
    /// operation can be `finished` and still have a captured tree.
    pub has_failure_tree: bool,
    /// Deep link to this operation in the Temporal UI, built from `op_id` and
    /// `TEMPORAL_UI_URL`. Rendered whether or not that UI is reachable from the
    /// reader's browser.
    pub temporal_url: String,
}

/// One plan that an operation ran.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct OperationPlanRow {
    pub collection_dataset: String,
    pub plan_hash: String,
    pub source: String,
    pub finished: bool,
}

/// One Error event that an operation recorded.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct OperationErrorEventRow {
    pub collection_dataset: String,
    pub hash: String,
    pub task_name: String,
    pub event: String,
    pub created_at: String,
    pub error_excerpt: String,
}

/// Everything one operation-detail page renders.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct OperationDetail {
    pub row: OperationRow,
    pub plans: Vec<OperationPlanRow>,
    pub plans_total: u64,
    pub events: Vec<OperationErrorEventRow>,
    pub events_total: u64,
    pub page_size: u32,
}

/// The re-run outcome sentence, or `None` when this operation has no re-run counts.
pub fn rerun_outcome_summary(row: &OperationRow) -> Option<String> {
    let before = row.errors_before_run?;
    let recovered = row.recovered_errors.unwrap_or(0);
    let still_failing = row.still_failing_errors.unwrap_or(0);
    let removed = row.removed_stage_off_errors.unwrap_or(0);
    let without_plan = row.without_plan_errors.unwrap_or(0);
    let unknown = row.unknown_task_errors.unwrap_or(0);
    let partial = if row.state == "cancelled" { "partial " } else { "" };
    Some(format!(
        "{partial}{recovered} recovered, {still_failing} still failing, {removed} removed (stage off), {without_plan} without a plan, {unknown} unknown task, {before} before this run"
    ))
}

/// The error rate of one task type, and whether it is above the configured line.
///
/// Both counts come from `processing_task_runs`, which records one row per activity
/// execution whatever its outcome, so the numerator and the denominator are the same
/// population, which is the only way this number means anything.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct TaskErrorRate {
    pub task_name: String,
    /// Activity executions, successful and failed. A Temporal retry is a second
    /// execution and a second row, so a task that only ever succeeds on its third
    /// attempt shows a real error rate here.
    pub runs_total: u64,
    pub runs_failed: u64,
    /// Distinct documents this task ran on, and how many of them saw at least one
    /// failed execution.
    pub documents_total: u64,
    pub documents_failed: u64,
    /// `runs_failed / runs_total`, as a percentage.
    pub error_rate_percent: f64,
    /// Whether `error_rate_percent` is above the deployment's configured line. Decided
    /// on the server so the CLI and the page cannot disagree about what "above" means.
    pub above_threshold: bool,
}

/// Everything `/admin/operations` renders in one round trip.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct OperationsPage {
    pub rows: Vec<OperationRow>,
    /// Whether a further page exists behind this one.
    pub has_more: bool,
    /// Collections that have at least one operation, for the collection filter.
    pub collections: Vec<String>,
    /// Per-task error rates over the same scope as the list.
    pub task_error_rates: Vec<TaskErrorRate>,
    /// The error rate above which a task type is called out, as configured for this
    /// deployment. Shipped to the browser so the page can name the number it is
    /// judging against instead of implying a universal one.
    pub error_rate_threshold_percent: f64,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn row(state: &str, errors_before_run: Option<u64>) -> OperationRow {
        OperationRow {
            op_id: String::new(),
            kind: String::new(),
            target_kind: String::new(),
            collectionname: String::new(),
            collection_dataset: String::new(),
            target: String::new(),
            state: state.into(),
            started_at: String::new(),
            finished_at: None,
            duration_seconds: 0,
            progress_done: 0,
            progress_total: 0,
            eta_seconds: 0,
            error: String::new(),
            user_id: String::new(),
            rerun_of: String::new(),
            destructive: false,
            failed_documents: None,
            failed_tasks: None,
            errors_before_run,
            recovered_errors: Some(3),
            still_failing_errors: Some(1),
            removed_stage_off_errors: Some(2),
            without_plan_errors: Some(0),
            unknown_task_errors: Some(0),
            detail: String::new(),
            has_failure_tree: false,
            temporal_url: String::new(),
        }
    }

    #[test]
    fn rerun_outcome_summary_formats_finished_cancelled_and_unknown_rows() {
        assert_eq!(
            rerun_outcome_summary(&row("finished", Some(12))),
            Some("3 recovered, 1 still failing, 2 removed (stage off), 0 without a plan, 0 unknown task, 12 before this run".into())
        );
        let mut cancelled = row("cancelled", Some(4));
        cancelled.recovered_errors = Some(0);
        cancelled.still_failing_errors = Some(0);
        cancelled.removed_stage_off_errors = Some(0);
        assert_eq!(
            rerun_outcome_summary(&cancelled),
            Some("partial 0 recovered, 0 still failing, 0 removed (stage off), 0 without a plan, 0 unknown task, 4 before this run".into())
        );
        assert_eq!(rerun_outcome_summary(&row("finished", None)), None);
    }
}
