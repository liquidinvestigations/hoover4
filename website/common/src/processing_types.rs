//! DTOs for the admin "collection processing" views, shared between frontend and backend.

/// Stable identifiers for the pipeline stages, matching the `P<n>_*` task packages in
/// `main_services/processing/tasks/`.
///
/// Kept as `&'static str` constants rather than an enum because the frontend only ever
/// displays them and the backend only ever fills them in; an enum would buy nothing and
/// cost a conversion at both ends.
pub const STAGE_SCAN: &str = "P0_scan";
pub const STAGE_PLAN: &str = "P1_plan";
pub const STAGE_EXECUTE: &str = "P2_execute";
pub const STAGE_NLP: &str = "P4_nlp";
pub const STAGE_INDEX: &str = "P5_index";

/// Progress of one pipeline stage for one dataset.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct StageProgress {
    /// One of the `STAGE_*` constants above.
    pub stage: String,
    /// Human label for the UI, e.g. "P3 · Parse & execute plans".
    pub label: String,
    /// What the numbers count, e.g. "plans" or "text segments". Shown next to the
    /// counts so `312 / 900` is not ambiguous.
    pub unit: String,
    pub done: u64,
    /// `None` for stages with no knowable denominator — P0 discovers work as it runs,
    /// so "42 of ?" is the honest display, not "42 of 42, complete".
    pub total: Option<u64>,
    /// Items completed per minute, measured over [`RATE_WINDOW_MINUTES`]. `None` when
    /// the stage has no completion timestamp to measure against.
    pub rate_per_minute: Option<f64>,
    /// Seconds until `done == total` at the current rate. `None` when the stage is
    /// finished, has no denominator, or is not currently making progress.
    pub eta_seconds: Option<u64>,
}

impl StageProgress {
    /// Completion percentage, or `None` when there is no denominator.
    ///
    /// A stage with `total == 0` counts as complete (100%): there was nothing to do.
    pub fn percent(&self) -> Option<f64> {
        let total = self.total?;
        if total == 0 {
            return Some(100.0);
        }
        Some((self.done as f64 / total as f64 * 100.0).clamp(0.0, 100.0))
    }

    pub fn is_complete(&self) -> bool {
        self.total.is_some_and(|t| self.done >= t)
    }
}

/// One stored ETA sample (`processing_eta_samples`, global database), written by
/// the `CollectEtaSamples` workflow and only read here — the website never
/// computes these in the request path.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct EtaSamplePoint {
    pub collection_dataset: String,
    /// One of the `STAGE_*` constants above.
    pub stage: String,
    /// RFC 3339 sample time.
    pub sampled_at: String,
    pub sampled_at_unix: i64,
    pub done: u64,
    pub total: u64,
    pub rate_items_per_sec: f64,
    pub rate_bytes_per_sec: f64,
    /// 0 when no estimate could be made.
    pub eta_seconds: u64,
    /// RFC 3339 estimated completion time — `sampled_at + eta_seconds`. This is
    /// what the chart plots: a converging estimate reads as a flattening line.
    /// Best-effort, not a scheduling promise.
    pub deadline: String,
    pub deadline_unix: i64,
}

/// Trailing window, in minutes, over which completion rate (and therefore ETA) is
/// measured. Long enough to smooth out per-plan bursts, short enough that an ETA
/// reacts within a coffee break.
pub const RATE_WINDOW_MINUTES: u64 = 10;

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct DatasetProcessingStatus {
    pub collection_dataset: String,
    pub dataset_display_name: String,
    pub stages: Vec<StageProgress>,
    /// Errors recorded in `processing_errors` for this dataset, all time.
    pub error_count: u64,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct CollectionProcessingStatus {
    pub collectionname: String,
    /// False when the collection database has not been provisioned yet; every count
    /// below is then zero and should be displayed as "provisioning", not "idle".
    pub db_ready: bool,
    pub datasets: Vec<DatasetProcessingStatus>,
}

/// One Temporal workflow execution, flattened to what the admin list shows.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct WorkflowSummary {
    pub workflow_id: String,
    pub run_id: String,
    pub workflow_type: String,
    /// `RUNNING`, `COMPLETED`, `FAILED`, … — the `WORKFLOW_EXECUTION_STATUS_` prefix
    /// stripped off, because it is noise in a table.
    pub status: String,
    pub task_queue: String,
    pub start_time: String,
    pub close_time: Option<String>,
    /// Deep link into the Temporal UI for this run.
    pub temporal_url: String,
    /// Workflow id of the parent, when this is a child workflow.
    pub parent_workflow_id: Option<String>,
}

impl WorkflowSummary {
    pub fn is_failed(&self) -> bool {
        matches!(self.status.as_str(), "FAILED" | "TIMED_OUT" | "TERMINATED")
    }

    pub fn is_running(&self) -> bool {
        self.status == "RUNNING"
    }
}

/// Filter for the workflow browser. Maps onto a Temporal visibility query.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub enum WorkflowFilter {
    All,
    Running,
    Failed,
}

impl WorkflowFilter {
    /// The `ExecutionStatus` clause this filter contributes, if any.
    pub fn status_clause(&self) -> Option<&'static str> {
        match self {
            Self::All => None,
            Self::Running => Some("ExecutionStatus = 'Running'"),
            // Temporal has no "any failure" status, so the three terminal failure
            // states are spelled out.
            Self::Failed => Some(
                "(ExecutionStatus = 'Failed' OR ExecutionStatus = 'TimedOut' \
                 OR ExecutionStatus = 'Terminated')",
            ),
        }
    }
}

/// A failure bucket: one task that failed, with how often and how recently.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct TaskFailureGroup {
    pub collection_dataset: String,
    pub task_name: String,
    pub error_count: u64,
    /// Number of distinct documents affected.
    pub document_count: u64,
    pub last_seen: String,
    /// First line of the most recent error, for the list view.
    pub sample_error: String,
}

/// A failure seen from the document's side: everything that went wrong for one blob.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct DocumentFailure {
    pub collection_dataset: String,
    pub hash: String,
    /// VFS path of the file, when one is known. Blobs reached through an archive or an
    /// email attachment may have several; the first is shown.
    pub path: Option<String>,
    pub task_names: Vec<String>,
    pub error_count: u64,
    pub last_seen: String,
    /// Full error text of the most recent failure.
    pub last_error: String,
}
