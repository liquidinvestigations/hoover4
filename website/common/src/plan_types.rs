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

/// The most sections of a plan: direct children of the root. The Python copy is
/// `MAX_SECTIONS` in `main_services/processing/database/agent_plans.py`.
pub const MAX_PLAN_SECTIONS: usize = 4;

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
    /// `root_node_id` names the root.
    EmptyPlan { root_node_id: String },
    /// The reviewed version has more sections than [`MAX_PLAN_SECTIONS`], so an approve is
    /// refused. A plan from before the section rule of direct root children can hold more.
    TooManySections { sections: u64, limit: u64 },
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
    /// `end_reason`, `failed` and `cause`, and `corrections` and `defect_classes`, which a
    /// plan from before the controller's section start can hold. Empty before execution.
    pub sections_json: String,
    /// The `end_reason` of the newest agent run of a terminal plan run that has one:
    /// `step_budget` or `empty_response`, or `repeated_call` in an older run. Empty for a
    /// live plan run.
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
    /// an approved plan whose sections recorded no run.
    pub fn stop_reason(&self) -> Option<&'static str> {
        if !self.is_terminal() || self.state == "cancelled" {
            return None;
        }
        match self.end_reason.as_str() {
            "step_budget" => return Some("the step budget ran out"),
            "empty_response" => return Some("the model returned two empty replies"),
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

/// The sections of a tree: the direct children of the root. One researcher runs each
/// section with its whole subtree, and a child of the root with no children is a section of
/// one task. The Python copy is `sections` in
/// `main_services/processing/database/agent_plans.py`. The two copies are one rule and
/// change in one patch.
pub fn section_count(nodes: &[PlanNodeView]) -> usize {
    let root = root_node_id(nodes);
    if root.is_empty() {
        return 0;
    }
    nodes
        .iter()
        .filter(|n| n.parent_id.as_deref() == Some(root.as_str()))
        .count()
}

/// Whether a tree has a section: a direct child of the root.
pub fn has_section(nodes: &[PlanNodeView]) -> bool {
    section_count(nodes) > 0
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
    fn each_child_of_the_root_is_a_section_with_its_subtree() {
        let nodes = [
            node("root", None),
            node("s1", Some("root")),
            node("s2", Some("root")),
            node("t1", Some("s2")),
            node("t2", Some("t1")),
        ];
        assert!(has_section(&nodes));
        assert_eq!(section_count(&nodes), 2);
        assert_eq!(section_count(&[node("root", None)]), 0);
        assert_eq!(section_count(&[]), 0);
    }

    #[test]
    fn a_plan_view_of_an_older_backend_and_new_section_keys_deserialize() {
        // No `end_reason` field, and entries with the older and the newer keys.
        let text = r#"{"run_id":"r","plan_id":"p","state":"completed","reviewed_version":2,
            "approved_version":2,"review_round":0,"version":2,"nodes":[],
            "sections_json":"[{\"node_id\":\"a\",\"corrections\":1,\"failed\":false},{\"node_id\":\"b\",\"state\":\"failed\",\"end_reason\":\"\",\"cause\":\"the run ended failed\",\"failed\":true}]"}"#;
        let view: PlanView = serde_json::from_str(text).unwrap();
        assert_eq!(view.end_reason, "");
        let sections: Vec<serde_json::Value> = serde_json::from_str(&view.sections_json).unwrap();
        assert_eq!(sections.len(), 2);
        assert_eq!(sections[1]["cause"], "the run ended failed");
    }

    #[test]
    fn a_too_many_sections_outcome_round_trips() {
        let outcome = PlanDecisionOutcome::TooManySections { sections: 5, limit: 4 };
        let text = serde_json::to_string(&outcome).unwrap();
        assert_eq!(text, r#"{"outcome":"too_many_sections","sections":5,"limit":4}"#);
        assert_eq!(serde_json::from_str::<PlanDecisionOutcome>(&text).unwrap(), outcome);
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
        assert_eq!(
            view("completed", 1, one_ran, "empty_response").stop_reason(),
            Some("the model returned two empty replies")
        );
        assert_eq!(view("completed", 1, one_ran, "").stop_reason(), None);
        assert_eq!(view("cancelled", 1, none_ran, "").stop_reason(), None, "a person stopped it");
        assert_eq!(view("executing", 1, none_ran, "").stop_reason(), None, "the run is live");
        assert_eq!(view("completed", 0, "[]", "").stop_reason(), None, "no plan was approved");
    }
}
