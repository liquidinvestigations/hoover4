//! Processing updates as the admin pages show them.
//!
//! The pipeline calculates each update step and stores the result
//! (`main_services/processing/tasks/P_admin/updates/`). The website reads the stored rows
//! only, so a page load runs no count query. The step titles and explanations come from
//! the pipeline registry with the counts written in.

use serde::{Deserialize, Serialize};

/// The display state of one update step.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum UpdateStepState {
    /// The applied output matches what the step should produce now.
    #[default]
    UpToDate,
    /// The step has work, and the automatic run or a person starts it.
    Waiting,
    /// The automatic run has nothing to do, and files can be retried by hand.
    RetryAvailable,
    /// An operation runs the step now.
    Running,
    /// The last attempt at the current fingerprint failed.
    Failed,
    /// The last attempt at the current fingerprint was cancelled.
    Cancelled,
    /// The pipeline has not calculated the step yet.
    NotCalculated,
}

impl UpdateStepState {
    pub fn label(self) -> &'static str {
        match self {
            UpdateStepState::UpToDate => "Up to date",
            UpdateStepState::Waiting => "Waiting",
            UpdateStepState::RetryAvailable => "Retry available",
            UpdateStepState::Running => "Running",
            UpdateStepState::Failed => "Failed",
            UpdateStepState::Cancelled => "Cancelled",
            UpdateStepState::NotCalculated => "Not calculated yet",
        }
    }

    /// Whether the page selects the step by default.
    pub fn selected_by_default(self) -> bool {
        matches!(self, UpdateStepState::Waiting | UpdateStepState::Failed | UpdateStepState::Cancelled)
    }
}

/// One update step of a dataset or a collection.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct UpdateStepView {
    pub step_id: String,
    pub title: String,
    pub explanation: String,
    /// The runs that follow, in words.
    pub runs: String,
    /// `files` or `tables`.
    pub unit: String,
    pub pending: u64,
    pub pending_bytes: u64,
    pub automatic: u64,
    pub state: UpdateStepState,
    /// The desired fingerprint that the page shows. A request carries it back, and the
    /// pipeline refuses the request when the state changed.
    pub fingerprint: String,
    pub last_run_at: String,
    pub last_op_id: String,
    pub last_error: String,
}

/// The processing updates of one scope.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct ProcessingUpdatesView {
    /// `dataset` or `collection`.
    pub scope_kind: String,
    pub scope_id: String,
    pub collectionname: String,
    pub steps: Vec<UpdateStepView>,
    /// Files of the waiting steps, each file once.
    pub unique_files: u64,
    pub unique_bytes: u64,
    /// Step runs of the waiting steps.
    pub executions: u64,
    /// When the pipeline calculated the scope, RFC 3339, and how long it took.
    pub checked_at: String,
    pub check_ms: u64,
    /// The live update operation of the scope, `(op_id, state, done, total)`.
    pub running_op_id: String,
    pub running_state: String,
    pub running_done: u64,
    pub running_total: u64,
    /// Collection steps that a dataset writer waits for.
    pub prerequisites_waiting: Vec<String>,
    /// `[processing_updates] automatic` of the installation.
    pub automatic: bool,
}

impl ProcessingUpdatesView {
    /// The steps that wait for work.
    pub fn waiting(&self) -> usize {
        self.steps.iter().filter(|s| s.state == UpdateStepState::Waiting).count()
    }

    /// The status line of the scope.
    pub fn status_line(&self) -> String {
        if !self.running_op_id.is_empty() {
            let step = (self.running_done + 1).min(self.running_total.max(1));
            return format!("Update running, step {step} of {}", self.running_total.max(1));
        }
        match self.waiting() {
            0 if self.steps.iter().any(|s| s.state == UpdateStepState::Failed) => {
                "An update step failed".to_string()
            }
            0 if self.steps.iter().all(|s| s.state == UpdateStepState::NotCalculated) => {
                "Not calculated yet".to_string()
            }
            0 => "Up to date".to_string(),
            1 => "1 update waiting".to_string(),
            n => format!("{n} updates waiting"),
        }
    }
}

/// The sentence above the Update processing button, for the selected steps.
///
/// Counts of different steps can name one file twice, so the sentence counts step runs
/// and gives the summed files as an upper bound. The page shows the unique files of all
/// waiting steps beside it.
pub fn selection_summary(steps: &[UpdateStepView], selected: &[String]) -> String {
    let chosen: Vec<&UpdateStepView> = steps.iter().filter(|s| selected.contains(&s.step_id)).collect();
    if chosen.is_empty() {
        return "No step is selected, so nothing runs.".to_string();
    }
    let files: u64 = chosen.iter().filter(|s| s.unit == "files").map(|s| s.pending).sum();
    let bytes: u64 = chosen.iter().map(|s| s.pending_bytes).sum();
    let runs = if chosen.len() == 1 { "1 step".to_string() } else { format!("{} steps", chosen.len()) };
    format!(
        "This runs {runs} on at most {files} files ({}). Search results for these documents change while it runs.",
        crate::storage_tree::format_size(bytes)
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn step(id: &str, pending: u64, state: UpdateStepState) -> UpdateStepView {
        UpdateStepView { step_id: id.into(), pending, unit: "files".into(), state, ..Default::default() }
    }

    #[test]
    fn an_empty_selection_runs_nothing() {
        let steps = [step("ocr", 5, UpdateStepState::Waiting)];
        assert_eq!(selection_summary(&steps, &[]), "No step is selected, so nothing runs.");
    }

    #[test]
    fn the_summary_counts_step_runs_and_an_upper_bound_of_files() {
        let steps = [step("ocr", 5, UpdateStepState::Waiting), step("vectors", 3, UpdateStepState::Waiting)];
        let text = selection_summary(&steps, &["ocr".into(), "vectors".into()]);
        assert!(text.starts_with("This runs 2 steps on at most 8 files"), "{text}");
    }

    #[test]
    fn the_status_line_names_running_waiting_and_up_to_date() {
        let mut view = ProcessingUpdatesView {
            steps: vec![step("ocr", 5, UpdateStepState::Waiting), step("vectors", 0, UpdateStepState::UpToDate)],
            ..Default::default()
        };
        assert_eq!(view.status_line(), "1 update waiting");
        view.running_op_id = "op".into();
        view.running_total = 2;
        view.running_done = 1;
        assert_eq!(view.status_line(), "Update running, step 2 of 2");
        view.running_op_id.clear();
        view.steps[0].state = UpdateStepState::UpToDate;
        assert_eq!(view.status_line(), "Up to date");
    }
}
