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
pub const STAGE_INDEX: &str = "P6_index";

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
    /// `None` for stages with no knowable denominator. P0 discovers work as it runs,
    /// so "42 of ?" is the honest display, not "42 of 42, complete".
    pub total: Option<u64>,
    /// Items completed per minute, measured over [`RATE_WINDOW_MINUTES`]. `None` when
    /// the stage has no completion timestamp to measure against.
    pub rate_per_minute: Option<f64>,
    /// Seconds until `done == total` at the current rate. `None` when the stage is
    /// finished, has no denominator, or is not currently making progress.
    pub eta_seconds: Option<u64>,
    /// Documents this stage recorded an error for, from `processing_errors`.
    ///
    /// A plan is marked finished when its stages have *run*, not when every document
    /// succeeded: the stages record per-document failures and carry on, deliberately,
    /// so that one unparseable file does not stop a dataset. The consequence is that a
    /// bar can read `done` over documents that were never processed, which is how 4 792
    /// documents lost their entities to an NER outage and still looked complete. The
    /// count is carried per stage so the failure is shown where it happened rather than
    /// only as a dataset-wide total.
    #[serde(default)]
    pub failed_documents: u64,
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

    /// True when the stage has reached its denominator AND lost nothing on the way.
    ///
    /// A stage with failed documents is never "complete": the work it did not do is
    /// invisible in `done / total` (a document whose NER failed writes no watermark, so
    /// it leaves the numerator *and* stays in the denominator only until the corpus is
    /// re-counted), and reporting it as finished is what left the failures unnoticed.
    pub fn is_complete(&self) -> bool {
        self.failed_documents == 0 && self.total.is_some_and(|t| self.done >= t)
    }
}

/// One stored ETA sample (`processing_eta_samples`, global database), written by
/// the `CollectEtaSamples` workflow and only read here, the website never
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
    /// RFC 3339 estimated completion time: `sampled_at + eta_seconds`. This is
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
    /// `RUNNING`, `COMPLETED`, `FAILED`, …, the `WORKFLOW_EXECUTION_STATUS_` prefix
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

// ---------------------------------------------------------------------------
// Where processing time goes
// ---------------------------------------------------------------------------

/// Default trailing window, in seconds, for the live activity view. Long enough that a
/// short task shows up at all, short enough that the shares track what the pipeline is
/// doing *now* rather than what it did five minutes ago.
pub const LIVE_WINDOW_SECONDS: u32 = 60;

/// How stale an in-flight sample may be and still count as "running". Workers sample
/// every 5 s, so this tolerates two missed samples before a task disappears from the
/// live view.
pub const INFLIGHT_FRESHNESS_SECONDS: u32 = 20;

/// One task type's share of the total processing time, all time.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct TaskTimeRow {
    /// Temporal activity type, which is the unit being optimised.
    pub task_name: String,
    /// Summed wall time of every execution, in seconds. This is the number to sort by:
    /// the top row is where an optimisation pays the most.
    pub total_seconds: f64,
    /// `total_seconds` as a percentage of the collection's summed task time.
    pub share_percent: f64,
    pub executions: u64,
    /// Executions that raised. Their time is included in `total_seconds`. Failing is
    /// not free, and a task that burns an hour retrying should read as an hour.
    pub error_count: u64,
    pub mean_ms: f64,
    pub p95_ms: f64,
    pub max_ms: u64,
}

/// The whole time breakdown for one collection, plus the two numbers that say whether
/// the answer is "make the task faster" or "run more workers".
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct TaskTimeBreakdown {
    /// Sorted by `total_seconds` descending.
    pub rows: Vec<TaskTimeRow>,
    /// Summed task time across every task type, in seconds.
    pub total_seconds: f64,
    pub total_executions: u64,
    /// End of the last execution minus the start of the first, in seconds. Includes
    /// any idle gap between two ingests, which is why the ratio below is *achieved*
    /// parallelism and not a hardware limit.
    pub wall_clock_seconds: f64,
    /// `total_seconds / wall_clock_seconds`. 1.0 means the pipeline was effectively
    /// serial; 8.0 means eight task-seconds were spent per elapsed second.
    pub achieved_parallelism: f64,
    /// RFC 3339 bounds of the measured span, `None` when nothing has been recorded.
    pub first_started: Option<String>,
    pub last_finished: Option<String>,
}

/// One task type in the live view.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct LiveTaskRow {
    pub task_name: String,
    /// Task-seconds spent inside the window. An execution that straddles the window
    /// edge contributes only its overlap, so the shares add up to the window.
    pub seconds_in_window: f64,
    pub share_percent: f64,
    /// Executions that finished inside the window.
    pub completed: u64,
    /// Executions running right now, summed over the newest sample of each worker.
    pub in_flight: u64,
    /// Age of the longest-running one, in seconds. A number that keeps climbing while
    /// `completed` stays at zero is a stuck task.
    pub oldest_age_seconds: u64,
}

/// What the pipeline is doing right now.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct LiveTaskActivity {
    /// Sorted by `seconds_in_window` descending, in-flight-only rows last.
    pub rows: Vec<LiveTaskRow>,
    pub window_seconds: u32,
    pub total_seconds_in_window: f64,
    /// `total_seconds_in_window / window_seconds`: how many activities ran in parallel
    /// on average over the window.
    pub average_concurrency: f64,
    pub in_flight_total: u64,
    /// RFC 3339 time of the newest in-flight sample, `None` when no worker has
    /// reported recently, which is how "nothing is running" is expressed.
    pub sampled_at: Option<String>,
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
