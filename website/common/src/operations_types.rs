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
    /// **Zero means "not yet known", not "no work"** — a scan that has not produced
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
    /// count — an older row, or a kind that does not process documents — and must be
    /// rendered as unknown, never as zero.
    pub failed_documents: Option<u64>,
    /// Individual task failures behind `failed_documents`; one document can fail
    /// several times.
    pub failed_tasks: Option<u64>,
    /// The `detail` JSON as stored, for the parameters the operation was dispatched
    /// with.
    pub detail: String,
}

/// The error rate of one task type, and whether it is above the configured line.
///
/// Both counts come from `processing_task_runs`, which records one row per activity
/// execution whatever its outcome — so the numerator and the denominator are the same
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
