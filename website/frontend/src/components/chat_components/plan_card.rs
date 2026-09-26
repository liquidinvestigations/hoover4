//! The plan card of a deep-research request.
//!
//! The planner's answer row carries a [`ChatPlanReference`]. The card reads the plan run
//! and the tree at the referenced version through `chat_plan_view`, and shows one of these
//! states:
//!
//! - `planning` and `revising`: the tree so far, and a stop button.
//! - `awaiting_review`: the tree, with approve, reject and stop on the current version.
//! - `executing`: the sections from `sections_json`, and the live runs of the current batch
//!   from the poll's `subagent_runs`.
//! - `completed`, `failed`, `cancelled`: the sections, with each failed section marked.
//!   A `completed` run whose tree has no section says that the planner finished with no
//!   section.
//!
//! A card whose version is older than the run's `reviewed_version`, or whose answer row a
//! later planner answer of the same plan run follows, shows its tree labelled as an earlier
//! version and offers no action. A missing or foreign run shows `Plan state
//! is unavailable`. While the run is not terminal, the card reads the view again every
//! [`REFRESH_SECONDS`] seconds, and it stops at a terminal state. The card can render before
//! the worker writes the run row, so it stops at `unavailable` only after
//! [`UNAVAILABLE_READS`] reads in a row.
//!
//! Every hook is created before any branch. Every text is a text node, because the tree
//! and the section titles come from a model.

use common::chat_types::SubagentRunEntry;
use common::plan_types::{
    has_section, ChatPlanReference, PlanAction, PlanDecisionOutcome, PlanDecisionRequest,
    PlanNodeView, PlanView, MAX_PLAN_COMMENT_CHARS,
};
use dioxus::prelude::*;

use crate::api::chat_api::{chat_decide_plan, chat_plan_view};

/// Seconds between two reads of a plan that is not terminal.
pub const REFRESH_SECONDS: u64 = 3;

/// The reads in a row that must find no run before the card stops reading.
pub const UNAVAILABLE_READS: u32 = 10;

/// The plan run of each deep-research request that this browser tab started, as
/// `(session_id, plan_run_id)`. The session page shows a card for it until the planner's
/// answer row names the same plan run. The home page starts a request and then opens the
/// session page, so the value lives outside both pages. A reload clears it.
pub static STARTED_PLANS: GlobalSignal<Vec<(String, String)>> = Signal::global(Vec::new);

/// Record the plan run that a deep-research request started.
pub fn remember_started_plan(session_id: String, plan_run_id: String) {
    let mut plans = STARTED_PLANS.write();
    plans.retain(|(s, _)| s != &session_id);
    plans.push((session_id, plan_run_id));
}

/// The plan run that this tab started in a session, if any.
pub fn started_plan(session_id: &str) -> Option<String> {
    STARTED_PLANS
        .read()
        .iter()
        .find(|(s, _)| s == session_id)
        .map(|(_, r)| r.clone())
}

/// What the session page gives every plan card.
#[derive(Clone, Copy)]
pub struct PlanCardContext {
    pub session_id: ReadSignal<String>,
    /// Called after an accepted approve or reject, which opens a new turn. The page then
    /// follows that turn with its poll.
    pub on_turn_started: Callback<()>,
}

/// The card's copy of the last read.
#[derive(Clone, PartialEq)]
enum Loaded {
    Pending,
    Unavailable,
    View(PlanView),
}

#[component]
pub fn PlanCard(
    reference: ChatPlanReference,
    /// The poll's sub-agent entries of the open turn. Read in `executing` only.
    #[props(default)]
    subagent_runs: Vec<SubagentRunEntry>,
    /// True when a later planner answer of the same plan run follows this one. The card
    /// then shows an earlier version, also when the tree version did not change.
    #[props(default)]
    superseded: bool,
) -> Element {
    let context = try_consume_context::<PlanCardContext>();
    let mut loaded = use_signal(|| Loaded::Pending);
    let mut busy = use_signal(|| false);
    let mut notice = use_signal(|| None::<String>);
    let mut reject_open = use_signal(|| false);
    let mut comment = use_signal(String::new);
    // One id for each decision the person starts. It stays for a retry after a transport
    // error, so the backend returns the recorded outcome and starts nothing twice.
    let mut pending_decision = use_signal(|| None::<(PlanAction, String)>);

    let run_id = reference.run_id.clone();
    let version = reference.reviewed_version;
    let session_id = context.map(|c| c.session_id);

    // The first read and the refresh loop. It ends when the run is terminal or unavailable.
    let loop_run_id = run_id.clone();
    use_future(move || {
        let run_id = loop_run_id.clone();
        async move {
            let Some(session_id) = session_id else {
                loaded.set(Loaded::Unavailable);
                return;
            };
            let mut unavailable_reads = 0;
            loop {
                let sid = session_id.peek().clone();
                let next = match chat_plan_view(sid, run_id.clone(), version).await {
                    Ok(Some(view)) => Loaded::View(view),
                    Ok(None) => Loaded::Unavailable,
                    Err(_) => loaded.peek().clone(),
                };
                let stop = match &next {
                    Loaded::View(view) => view.is_terminal(),
                    Loaded::Unavailable => {
                        unavailable_reads += 1;
                        unavailable_reads >= UNAVAILABLE_READS
                    }
                    Loaded::Pending => false,
                };
                if *loaded.peek() != next {
                    loaded.set(next);
                }
                if stop {
                    return;
                }
                n0_future::time::sleep(std::time::Duration::from_secs(REFRESH_SECONDS)).await;
            }
        }
    });

    let decide_run_id = run_id.clone();
    let decide = move |action: PlanAction| {
        let Some(context) = context else {
            return;
        };
        if *busy.peek() {
            return;
        }
        let decision_id = match pending_decision.peek().clone() {
            Some((pending, id)) if pending == action => id,
            _ => new_decision_id(),
        };
        pending_decision.set(Some((action, decision_id.clone())));
        let request = PlanDecisionRequest {
            session_id: context.session_id.peek().clone(),
            run_id: decide_run_id.clone(),
            reviewed_version: version,
            decision_id,
            action,
            comment: if action == PlanAction::Reject {
                comment.peek().trim().to_string()
            } else {
                String::new()
            },
        };
        busy.set(true);
        notice.set(None);
        let run_id = decide_run_id.clone();
        spawn(async move {
            match chat_decide_plan(request).await {
                Ok(outcome) => {
                    pending_decision.set(None);
                    let accepted = matches!(
                        outcome,
                        PlanDecisionOutcome::Accepted | PlanDecisionOutcome::Duplicate { .. }
                    );
                    notice.set(outcome_text(&outcome));
                    if accepted {
                        reject_open.set(false);
                        comment.set(String::new());
                        if action != PlanAction::Cancel {
                            context.on_turn_started.call(());
                        }
                    }
                }
                Err(e) => notice.set(Some(format!("The decision was not sent: {e}"))),
            }
            let sid = context.session_id.peek().clone();
            if let Ok(view) = chat_plan_view(sid, run_id, version).await {
                loaded.set(view.map(Loaded::View).unwrap_or(Loaded::Unavailable));
            }
            busy.set(false);
        });
    };

    let current = loaded.read().clone();
    let view = match current {
        Loaded::Pending => {
            return rsx! {
                div { "data-plan-card": "{run_id}", style: CARD_STYLE,
                    CardHeader { state_label: "Reading the plan\u{2026}".to_string() }
                }
            };
        }
        Loaded::Unavailable => {
            return rsx! {
                div { "data-plan-card": "{run_id}", "data-plan-state": "unavailable",
                    style: CARD_STYLE,
                    CardHeader { state_label: "Plan state is unavailable".to_string() }
                }
            };
        }
        Loaded::View(view) => view,
    };

    // A reference with version 0 follows the newest tree of a plan that has no answer
    // row yet. It is never stale.
    let stale = superseded || (version != 0 && version < view.reviewed_version);
    let terminal = view.is_terminal();
    let can_review = !stale && version != 0 && view.state == "awaiting_review";
    let can_stop = !stale && !terminal;
    let sections = parse_sections(&view.sections_json);
    let show_sections = !sections.is_empty() && !stale;
    let state_label = if view.state == "completed" && !has_section(&view.nodes) {
        NO_SECTION_TEXT
    } else {
        state_text(&view.state)
    };
    let rows = tree_rows(&view.nodes);
    let is_busy = *busy.read();
    let comment_len = comment.read().trim().chars().count();
    let live: Vec<SubagentRunEntry> = if view.state == "executing" {
        subagent_runs
    } else {
        Vec::new()
    };
    let stale_text = if version < view.reviewed_version {
        format!(
            "This is version {version} of the plan. The plan has a newer version ({}) \
             further down.",
            view.reviewed_version
        )
    } else {
        "This is an earlier review round of the plan. The current round is further down."
            .to_string()
    };
    let mut decide_approve = decide.clone();
    let mut decide_reject = decide.clone();
    let mut decide_cancel = decide;

    rsx! {
        div {
            "data-plan-card": "{view.run_id}",
            "data-plan-state": "{view.state}",
            style: CARD_STYLE,
            CardHeader { state_label: state_label.to_string() }
            if stale {
                div { "data-plan-stale": "true",
                    style: "font-size: 12px; color: #92400E; background: #FFFBEB; \
                            border: 1px solid #FDE68A; border-radius: 6px; padding: 4px 8px;",
                    "{stale_text}"
                }
            }
            if show_sections {
                SectionList { sections: sections.clone(), terminal }
            }
            if !live.is_empty() {
                LiveRuns { entries: live }
            }
            if show_sections {
                details { style: "font-size: 12px; color: #475569;",
                    summary { style: "cursor: pointer;", "Plan version {view.version}" }
                    TreeView { rows: rows.clone() }
                }
            } else {
                div { style: "font-size: 12px; color: #64748B;",
                    "Plan version {view.version}, review round {view.review_round}"
                }
                TreeView { rows: rows.clone() }
            }
            if let Some(text) = notice.read().clone() {
                div { "data-plan-notice": "true",
                    style: "font-size: 12px; color: #92400E;",
                    "{text}"
                }
            }
            if can_review && *reject_open.read() {
                div { style: "display: flex; flex-direction: column; gap: 6px;",
                    textarea {
                        "data-plan-comment": "true",
                        rows: "3",
                        maxlength: "{MAX_PLAN_COMMENT_CHARS}",
                        placeholder: "Tell the planner what to change",
                        style: "font-size: 13px; padding: 6px 8px; border: 1px solid #CBD5E1; \
                                border-radius: 6px; resize: vertical;",
                        value: "{comment}",
                        oninput: move |e| comment.set(e.value()),
                    }
                }
            }
            if can_review || can_stop {
                div { style: "display: flex; gap: 8px; flex-wrap: wrap;",
                    if can_review && !*reject_open.read() {
                        button {
                            "data-plan-action": "approve",
                            style: BUTTON_PRIMARY,
                            disabled: is_busy,
                            onclick: move |_| decide_approve(PlanAction::Approve),
                            "Approve plan"
                        }
                        button {
                            "data-plan-action": "reject-open",
                            style: BUTTON_PLAIN,
                            disabled: is_busy,
                            onclick: move |_| reject_open.set(true),
                            "Ask for changes"
                        }
                    }
                    if can_review && *reject_open.read() {
                        button {
                            "data-plan-action": "reject",
                            style: BUTTON_PRIMARY,
                            disabled: is_busy || comment_len == 0,
                            onclick: move |_| decide_reject(PlanAction::Reject),
                            "Send the comment"
                        }
                        button {
                            style: BUTTON_PLAIN,
                            disabled: is_busy,
                            onclick: move |_| reject_open.set(false),
                            "Back"
                        }
                    }
                    if can_stop {
                        button {
                            "data-plan-action": "cancel",
                            style: BUTTON_STOP,
                            disabled: is_busy,
                            onclick: move |_| decide_cancel(PlanAction::Cancel),
                            "Stop the plan"
                        }
                    }
                }
            }
        }
    }
}

const CARD_STYLE: &str = "align-self: stretch; margin-top: 8px; background: #F8FAFC; \
     border: 1px solid #CBD5E1; border-radius: 10px; padding: 10px 12px; font-size: 13px; \
     color: #0F172A; display: flex; flex-direction: column; gap: 8px;";
const BUTTON_PRIMARY: &str = "background: #4F46E5; color: white; border: none; \
     border-radius: 6px; padding: 5px 12px; font-size: 13px; cursor: pointer;";
const BUTTON_PLAIN: &str = "background: white; color: #334155; border: 1px solid #CBD5E1; \
     border-radius: 6px; padding: 5px 12px; font-size: 13px; cursor: pointer;";
const BUTTON_STOP: &str = "background: white; color: #B91C1C; border: 1px solid #FCA5A5; \
     border-radius: 6px; padding: 5px 12px; font-size: 13px; cursor: pointer;";

#[component]
fn CardHeader(state_label: String) -> Element {
    rsx! {
        div { style: "display: flex; align-items: center; gap: 10px;",
            span {
                style: "background: #E0E7FF; color: #3730A3; border-radius: 999px; \
                        padding: 1px 8px; font-size: 11px; font-weight: 600;",
                "Research plan"
            }
            span { style: "font-weight: 600;", "{state_label}" }
        }
    }
}

/// The state text of a completed plan run whose tree has no section.
const NO_SECTION_TEXT: &str = "The planner finished with no section";

/// The text the card shows for a plan run state.
fn state_text(state: &str) -> &'static str {
    match state {
        "planning" => "The planner writes the plan",
        "awaiting_review" => "The plan waits for your review",
        "revising" => "The planner changes the plan after your comment",
        "executing" => "The organizer runs the approved plan",
        "completed" => "The plan is complete",
        "failed" => "The plan run failed",
        "cancelled" => "The plan was stopped",
        _ => "The plan state is not known",
    }
}

/// The text the card shows for a decision outcome, or `None` when the refreshed view
/// shows the result.
fn outcome_text(outcome: &PlanDecisionOutcome) -> Option<String> {
    match outcome {
        PlanDecisionOutcome::Accepted => None,
        PlanDecisionOutcome::Duplicate { .. } => {
            Some("This decision is already recorded.".to_string())
        }
        PlanDecisionOutcome::StaleVersion { current_version } => Some(format!(
            "The plan changed to version {current_version}. Read that version before you decide."
        )),
        PlanDecisionOutcome::WrongState { state } => Some(format!(
            "The plan state is {state}, so it cannot take this decision now."
        )),
        PlanDecisionOutcome::Terminal { state } => Some(format!(
            "The plan run is {state}. It takes no more decisions."
        )),
        PlanDecisionOutcome::StartFailed { error } => {
            Some(format!("The next run did not start: {error}"))
        }
        PlanDecisionOutcome::EmptyPlan { .. } => Some(
            "This plan has no section, so it cannot run. Reject it with a comment, and the \
             planner writes it again."
                .to_string(),
        ),
    }
}

/// One entry of `sections_json`.
#[derive(Clone, PartialEq, Debug)]
struct Section {
    node_id: String,
    title: String,
    tasks: u64,
    state: String,
    corrections: u64,
    defect_classes: Vec<String>,
    failed: bool,
}

fn parse_sections(json: &str) -> Vec<Section> {
    let Ok(serde_json::Value::Array(items)) = serde_json::from_str::<serde_json::Value>(json)
    else {
        return Vec::new();
    };
    items
        .iter()
        .map(|item| {
            let text = |key: &str| item.get(key).and_then(|v| v.as_str()).unwrap_or_default();
            Section {
                node_id: text("node_id").to_string(),
                title: text("title").to_string(),
                tasks: item.get("tasks").and_then(|v| v.as_u64()).unwrap_or(0),
                state: text("state").to_string(),
                corrections: item.get("corrections").and_then(|v| v.as_u64()).unwrap_or(0),
                defect_classes: item
                    .get("defect_classes")
                    .and_then(|v| v.as_array())
                    .map(|a| {
                        a.iter()
                            .filter_map(|c| c.as_str().map(str::to_string))
                            .collect()
                    })
                    .unwrap_or_default(),
                failed: item.get("failed").and_then(|v| v.as_bool()).unwrap_or(false),
            }
        })
        .collect()
}

/// The sections of an approved plan. A section is marked failed only when the run is
/// terminal, because during execution `failed` means that no review accepted it yet.
#[component]
fn SectionList(sections: Vec<Section>, terminal: bool) -> Element {
    rsx! {
        div { style: "display: flex; flex-direction: column; gap: 4px;",
            div { style: "font-size: 12px; font-weight: 600; color: #475569;", "Sections" }
            for (i, section) in sections.into_iter().enumerate() {
                {
                    let failed = terminal && section.failed;
                    let state = if failed {
                        "failed".to_string()
                    } else if section.state.is_empty() {
                        "not started".to_string()
                    } else if terminal {
                        "accepted".to_string()
                    } else {
                        section.state.replace('_', " ")
                    };
                    let color = if failed { "#B91C1C" } else { "#334155" };
                    let heading = format!("{}. {}", i + 1, section.title);
                    let defects = section.defect_classes.join(", ");
                    let tasks = if section.tasks == 1 {
                        "1 task".to_string()
                    } else {
                        format!("{} tasks", section.tasks)
                    };
                    rsx! {
                        div {
                            key: "{section.node_id}",
                            "data-plan-section": "{i}",
                            "data-plan-section-failed": "{failed}",
                            style: "display: flex; flex-direction: column; gap: 2px; \
                                    padding: 4px 8px; background: white; \
                                    border: 1px solid #E2E8F0; border-radius: 6px;",
                            div { style: "display: flex; gap: 8px; align-items: baseline;",
                                span { style: "flex: 1; min-width: 0;", "{heading}" }
                                span { style: "font-size: 11px; color: #64748B;", "{tasks}" }
                                span { style: "font-size: 11px; font-weight: 600; color: {color};",
                                    "{state}"
                                }
                            }
                            if section.corrections > 0 {
                                div { style: "font-size: 11px; color: #64748B;",
                                    "Corrections: {section.corrections}"
                                }
                            }
                            if failed && !section.defect_classes.is_empty() {
                                div { style: "font-size: 11px; color: #B91C1C;",
                                    "Open defects: {defects}"
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

/// The sub-agent runs of the current batch, a depth 2 run under its parent.
#[component]
fn LiveRuns(entries: Vec<SubagentRunEntry>) -> Element {
    let top: Vec<SubagentRunEntry> = entries.iter().filter(|e| e.depth == 1).cloned().collect();
    let count = top.len();
    rsx! {
        div { "data-plan-live-runs": "{count}",
            style: "display: flex; flex-direction: column; gap: 4px;",
            div { style: "font-size: 12px; font-weight: 600; color: #475569;", "Running now" }
            for entry in top {
                div { key: "{entry.run_id}",
                    style: "display: flex; flex-direction: column; gap: 2px;",
                    LiveRun { entry: entry.clone() }
                    for nested in entries.iter().filter(|e| e.parent_run_id == entry.run_id).cloned() {
                        div { key: "{nested.run_id}",
                            style: "margin-left: 18px; border-left: 2px solid #C7D2FE; \
                                    padding-left: 8px;",
                            LiveRun { entry: nested.clone() }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn LiveRun(entry: SubagentRunEntry) -> Element {
    let state = entry.state.replace('_', " ");
    rsx! {
        div { style: "display: flex; gap: 8px; font-size: 12px; color: #1E293B;",
            span { style: "flex: 1; min-width: 0;", "{entry.objective}" }
            span { style: "color: #64748B;", "{entry.tool_calls} tool calls" }
            span { style: "font-weight: 600;", "{state}" }
        }
    }
}

/// One line of the rendered tree: depth, number and text.
#[derive(Clone, PartialEq, Debug)]
struct TreeRow {
    node_id: String,
    depth: usize,
    number: String,
    text: String,
}

/// The tree in reading order. The root is depth 0 with no number, its children are the
/// sections `1`, `2`, and their children are `1.1`, `1.2`.
fn tree_rows(nodes: &[PlanNodeView]) -> Vec<TreeRow> {
    let mut rows = Vec::new();
    let mut roots: Vec<&PlanNodeView> = nodes.iter().filter(|n| n.parent_id.is_none()).collect();
    roots.sort_by_key(|n| n.ordinal);
    for root in roots {
        rows.push(TreeRow {
            node_id: root.node_id.clone(),
            depth: 0,
            number: String::new(),
            text: root.text.clone(),
        });
        push_children(nodes, &root.node_id, "", 1, &mut rows);
    }
    rows
}

fn push_children(
    nodes: &[PlanNodeView],
    parent: &str,
    prefix: &str,
    depth: usize,
    rows: &mut Vec<TreeRow>,
) {
    // The tree holds at most 150 nodes and three levels. The bound stops a cycle in a
    // malformed snapshot.
    if depth > 8 {
        return;
    }
    let mut children: Vec<&PlanNodeView> = nodes
        .iter()
        .filter(|n| n.parent_id.as_deref() == Some(parent))
        .collect();
    children.sort_by_key(|n| n.ordinal);
    for (i, child) in children.into_iter().enumerate() {
        let number = if prefix.is_empty() {
            format!("{}", i + 1)
        } else {
            format!("{prefix}.{}", i + 1)
        };
        rows.push(TreeRow {
            node_id: child.node_id.clone(),
            depth,
            number: number.clone(),
            text: child.text.clone(),
        });
        push_children(nodes, &child.node_id, &number, depth + 1, rows);
    }
}

#[component]
fn TreeView(rows: Vec<TreeRow>) -> Element {
    let count = rows.len();
    rsx! {
        div { "data-plan-tree": "{count}",
            style: "display: flex; flex-direction: column; gap: 2px; font-size: 13px;",
            for row in rows {
                {
                    let indent = row.depth.saturating_sub(1) * 18;
                    let weight = if row.depth <= 1 { "600" } else { "400" };
                    rsx! {
                        div { key: "{row.node_id}",
                            style: "padding-left: {indent}px; font-weight: {weight}; \
                                    color: #1E293B; word-break: break-word;",
                            if row.number.is_empty() {
                                "{row.text}"
                            } else {
                                "{row.number} {row.text}"
                            }
                        }
                    }
                }
            }
        }
    }
}

/// A random UUID in the version 4 layout, for the decision id.
///
/// The browser's crypto source gives the bytes. The server-side render build has no
/// browser, and no decision starts there, so it falls back to the clock and a counter.
fn new_decision_id() -> String {
    let mut bytes = [0u8; 16];
    let filled = web_sys::window()
        .and_then(|w| w.crypto().ok())
        .map(|c| c.get_random_values_with_u8_array(&mut bytes).is_ok())
        .unwrap_or(false);
    if !filled {
        use std::sync::atomic::{AtomicU64, Ordering};
        static COUNTER: AtomicU64 = AtomicU64::new(1);
        let n = COUNTER.fetch_add(1, Ordering::Relaxed);
        let t = web_sys::window()
            .and_then(|w| w.performance())
            .map(|p| p.now().to_bits())
            .unwrap_or(0);
        bytes[..8].copy_from_slice(&t.to_le_bytes());
        bytes[8..].copy_from_slice(&n.to_le_bytes());
    }
    bytes[6] = (bytes[6] & 0x0F) | 0x40;
    bytes[8] = (bytes[8] & 0x3F) | 0x80;
    let hex: String = bytes.iter().map(|b| format!("{b:02x}")).collect();
    format!(
        "{}-{}-{}-{}-{}",
        &hex[0..8],
        &hex[8..12],
        &hex[12..16],
        &hex[16..20],
        &hex[20..32]
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn node(id: &str, parent: Option<&str>, ordinal: u32, text: &str) -> PlanNodeView {
        PlanNodeView {
            node_id: id.to_string(),
            parent_id: parent.map(str::to_string),
            ordinal,
            text: text.to_string(),
        }
    }

    #[test]
    fn the_tree_numbers_sections_and_tasks_in_ordinal_order() {
        let nodes = vec![
            node("t2", Some("s1"), 2, "second task"),
            node("root", None, 1, "question"),
            node("s2", Some("root"), 2, "section two"),
            node("s1", Some("root"), 1, "section one"),
            node("t1", Some("s1"), 1, "first task"),
        ];
        let rows: Vec<(String, usize)> = tree_rows(&nodes)
            .into_iter()
            .map(|r| (format!("{} {}", r.number, r.text).trim().to_string(), r.depth))
            .collect();
        assert_eq!(
            rows,
            vec![
                ("question".to_string(), 0),
                ("1 section one".to_string(), 1),
                ("1.1 first task".to_string(), 2),
                ("1.2 second task".to_string(), 2),
                ("2 section two".to_string(), 1),
            ]
        );
    }

    #[test]
    fn an_empty_plan_refusal_tells_the_person_to_reject_it() {
        let text = outcome_text(&PlanDecisionOutcome::EmptyPlan {
            root_node_id: "root".into(),
        })
        .unwrap();
        assert_eq!(
            text,
            "This plan has no section, so it cannot run. Reject it with a comment, and the \
             planner writes it again."
        );
    }

    #[test]
    fn the_sections_parse_from_the_worker_json() {
        let json = r#"[{"corrections": 1, "defect_classes": ["no-verdict"], "failed": true,
            "node_id": "s1", "state": "completed", "tasks": 2, "title": "one"}]"#;
        let sections = parse_sections(json);
        assert_eq!(sections.len(), 1);
        assert!(sections[0].failed);
        assert_eq!(sections[0].defect_classes, vec!["no-verdict".to_string()]);
        assert!(parse_sections("").is_empty());
    }
}
