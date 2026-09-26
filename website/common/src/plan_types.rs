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
    /// The reviewed version has no section, so an approve is refused.
    /// `sections` is empty, and `root_node_id` names the root.
    EmptyPlan { root_node_id: String },
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
    /// The `end_reason` of the newest agent run of a terminal plan run that has one:
    /// `step_budget` or `repeated_call`. Empty for a live plan run.
    #[serde(default)]
    pub end_reason: String,
}

impl PlanView {
    pub fn is_terminal(&self) -> bool {
        PLAN_TERMINAL_STATES.contains(&self.state.as_str())
    }

    /// Why a terminal research run stopped short, as the transcript says it, or `None`.
    ///
    /// A cancelled plan run has none, because a person stopped it. "no section ran" means
    /// an approved plan whose sections recorded no run, which is what a run whose
    /// briefings were all refused leaves.
    pub fn stop_reason(&self) -> Option<&'static str> {
        if !self.is_terminal() || self.state == "cancelled" {
            return None;
        }
        match self.end_reason.as_str() {
            "step_budget" => return Some("the step budget ran out"),
            "repeated_call" => return Some("a repeated call"),
            _ => {}
        }
        let ran = serde_json::from_str::<Vec<serde_json::Value>>(&self.sections_json)
            .unwrap_or_default()
            .iter()
            .any(|s| s.get("state").and_then(|v| v.as_str()).is_some_and(|v| !v.is_empty()));
        (self.approved_version > 0 && !ran).then_some("no section ran")
    }
}

/// Whether a tree has a section: a node with at least one leaf child. The root counts.
/// The Python copy is `sections` in `main_services/processing/database/agent_plans.py`.
/// The two copies are one rule and change in one patch.
///
/// A root whose children are all leaves is one section, with those leaves as its tasks.
pub fn has_section(nodes: &[PlanNodeView]) -> bool {
    let parents: std::collections::HashSet<&str> =
        nodes.iter().filter_map(|n| n.parent_id.as_deref()).collect();
    // A node with a parent is a child. A child that is not a parent is a leaf, and its
    // parent is a section. The Python copy also requires the parent to be in the tree.
    let ids: std::collections::HashSet<&str> = nodes.iter().map(|n| n.node_id.as_str()).collect();
    nodes.iter().any(|n| {
        !parents.contains(n.node_id.as_str())
            && n.parent_id.as_deref().is_some_and(|parent| ids.contains(parent))
    })
}

/// The node id of the root of a tree: the node with no parent. Empty when there is none.
pub fn root_node_id(nodes: &[PlanNodeView]) -> String {
    nodes
        .iter()
        .find(|n| n.parent_id.is_none())
        .map(|n| n.node_id.clone())
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn node(id: &str, parent: Option<&str>) -> PlanNodeView {
        PlanNodeView {
            node_id: id.into(),
            parent_id: parent.map(Into::into),
            ordinal: 0,
            text: id.into(),
        }
    }

    #[test]
    fn a_root_only_tree_has_no_section() {
        let nodes = [node("root", None)];
        assert!(!has_section(&nodes));
        assert_eq!(root_node_id(&nodes), "root");
    }

    #[test]
    fn a_section_of_two_tasks_is_a_section() {
        let nodes = [
            node("root", None),
            node("s1", Some("root")),
            node("t1", Some("s1")),
            node("t2", Some("s1")),
        ];
        assert!(has_section(&nodes));
    }

    #[test]
    fn a_root_with_only_leaf_children_is_a_section() {
        let nodes = [
            node("root", None),
            node("s1", Some("root")),
            node("s2", Some("root")),
        ];
        assert!(has_section(&nodes));
    }

    #[test]
    fn an_empty_tree_has_no_section_and_no_root() {
        assert!(!has_section(&[]));
        assert_eq!(root_node_id(&[]), "");
    }

    fn view(state: &str, approved_version: u64, sections_json: &str, end_reason: &str) -> PlanView {
        PlanView {
            run_id: "r".into(),
            plan_id: "p".into(),
            state: state.into(),
            reviewed_version: 1,
            approved_version,
            review_round: 1,
            version: 1,
            nodes: Vec::new(),
            sections_json: sections_json.into(),
            end_reason: end_reason.into(),
        }
    }

    #[test]
    fn a_stopped_research_run_names_its_reason() {
        let none_ran = r#"[{"node_id":"a","state":""}]"#;
        let one_ran = r#"[{"node_id":"a","state":"completed"}]"#;
        assert_eq!(view("completed", 1, none_ran, "").stop_reason(), Some("no section ran"));
        assert_eq!(view("completed", 1, "[]", "").stop_reason(), Some("no section ran"));
        assert_eq!(view("completed", 1, one_ran, "step_budget").stop_reason(), Some("the step budget ran out"));
        assert_eq!(view("failed", 1, one_ran, "repeated_call").stop_reason(), Some("a repeated call"));
        assert_eq!(view("completed", 1, one_ran, "").stop_reason(), None);
        assert_eq!(view("cancelled", 1, none_ran, "").stop_reason(), None, "a person stopped it");
        assert_eq!(view("executing", 1, none_ran, "").stop_reason(), None, "the run is live");
        assert_eq!(view("completed", 0, "[]", "").stop_reason(), None, "no plan was approved");
    }
}
