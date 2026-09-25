//! The plan decision and the plan view of a deep-research plan run.
//!
//! A deep-research request is a plan run. A planner run writes the plan tree and answers,
//! and the plan then waits for review with no workflow open. The person approves, rejects or
//! cancels it with [`PlanDecisionRequest`]. An approve starts the organizer run, and a reject
//! starts the next planner round. Each outcome is typed, so the card can show the reason for
//! a refusal.

use serde::{Deserialize, Serialize};

/// The most characters in a rejection comment.
pub const MAX_PLAN_COMMENT_CHARS: usize = 10_000;

/// The plan run states, as `agent_plan_runs.state` holds them.
pub const PLAN_TERMINAL_STATES: [&str; 3] = ["completed", "failed", "cancelled"];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PlanAction {
    Approve,
    Reject,
    Cancel,
}

impl PlanAction {
    pub fn as_str(self) -> &'static str {
        match self {
            PlanAction::Approve => "approve",
            PlanAction::Reject => "reject",
            PlanAction::Cancel => "cancel",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PlanDecisionRequest {
    pub session_id: String,
    /// The plan run id, from the card's [`ChatPlanReference`].
    pub run_id: String,
    /// The version of the tree the person saw.
    pub reviewed_version: u64,
    /// Made by the card when the person clicks. A second click with the same id returns
    /// the first outcome and starts nothing.
    pub decision_id: String,
    pub action: PlanAction,
    /// Reject only, 1 to [`MAX_PLAN_COMMENT_CHARS`] characters.
    pub comment: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "outcome", rename_all = "snake_case")]
pub enum PlanDecisionOutcome {
    Accepted,
    Duplicate { first: Box<PlanDecisionOutcome> },
    StaleVersion { current_version: u64 },
    WrongState { state: String },
    Terminal { state: String },
    /// The run start failed after the readiness gate. The transcript holds an error row.
    StartFailed { error: String },
}

/// The `plan_reference_json` of a planner's answer row: the plan the card shows.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChatPlanReference {
    pub plan_id: String,
    /// The plan run id.
    pub run_id: String,
    pub reviewed_version: u64,
}

/// One node of a plan tree.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PlanNodeView {
    pub node_id: String,
    pub parent_id: Option<String>,
    pub ordinal: u32,
    pub text: String,
}

/// What the plan card reads: the plan run state and the tree at one version.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PlanView {
    pub run_id: String,
    pub plan_id: String,
    pub state: String,
    pub reviewed_version: u64,
    pub approved_version: u64,
    pub review_round: u64,
    /// The version of `nodes`.
    pub version: u64,
    pub nodes: Vec<PlanNodeView>,
    /// For each section of the approved tree: `node_id`, `title`, `tasks`, `state`,
    /// `corrections`, `defect_classes` and `failed`. Empty before execution.
    pub sections_json: String,
}

impl PlanView {
    pub fn is_terminal(&self) -> bool {
        PLAN_TERMINAL_STATES.contains(&self.state.as_str())
    }
}
