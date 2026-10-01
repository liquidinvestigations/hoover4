//! The plan card of a deep-research request.
//!
//! The planner's answer row carries a [`ChatPlanReference`]. The card reads the plan run
//! and the tree at the referenced version through `chat_plan_view`, and shows one of these
//! states:
//!
//! - `planning` and `revising`: the tree so far, and a stop button.
//! - `awaiting_review`: the tree, with approve, reject and stop on the current version.
//! - `awaiting_review` with a tree that has no section, or more than
//!   [`MAX_PLAN_SECTIONS`] sections: the approve button is disabled, and the card says why.
//!   The backend refuses such an approve too.
//! - `executing`: the sections from `sections_json`, and the live runs of the current batch
//!   from the poll's `subagent_runs`. When every section run ended and the organizer runs,
//!   the view's `phase` is `combining`, and the card says that the organizer combines the
//!   reports.
//! - `completed`, `failed`, `cancelled`: the sections, each with its outcome, and the cause
//!   of each failed section. A completed plan with failed sections says how many failed.
//!   A `completed` run whose tree has no section says that the planner finished with no
//!   section.
//!
//! Each section with a report has a disclosure with the report (`chat_plan_section_reports`).
//! A typed report shows the model's final answer and its latest texts apart from what code
//! recorded: the reads with their spans and failures, the citations with their quote
//! checks, the notes, the artifacts and the execution diagnostics. A report from before
//! the typed report shows its text, labelled as such. Missing metadata is never read as
//! success.
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
    has_section, section_count, ChatPlanReference, PlanAction, PlanDecisionOutcome,
    PlanDecisionRequest, PlanNodeView, PlanView, MAX_PLAN_COMMENT_CHARS, MAX_PLAN_SECTIONS,
    PHASE_COMBINING,
};
use common::report_types::{EvidenceEntry, ReportData, SectionReport, SectionReportView};
use dioxus::prelude::*;

use crate::api::chat_api::{chat_decide_plan, chat_plan_section_reports, chat_plan_view};

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
    /// A planner question replaces the ordinary review actions with an answer box.
    #[props(default)]
    question: String,
    #[props(default)]
    question_options: Vec<String>,
) -> Element {
    let context = try_consume_context::<PlanCardContext>();
    let mut loaded = use_signal(|| Loaded::Pending);
    let mut reports = use_signal(Vec::<SectionReportView>::new);
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
                // The reports of the sections, while the plan runs and once when it ends.
                if let Loaded::View(view) = &next {
                    if (view.state == "executing" || view.is_terminal())
                        && !view.sections_json.is_empty()
                    {
                        if let Ok(Some(read)) =
                            chat_plan_section_reports(session_id.peek().clone(), run_id.clone()).await
                        {
                            if *reports.peek() != read {
                                reports.set(read);
                            }
                        }
                    }
                }
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
    let question_review = can_review && !question.is_empty();
    let can_stop = !stale && !terminal;
    let sections = parse_sections(&view.sections_json);
    let show_sections = !sections.is_empty() && !stale;
    let failed_sections = sections.iter().filter(|s| s.failed).count();
    let state_label = if view.state == "completed" && !has_section(&view.nodes) {
        NO_SECTION_TEXT.to_string()
    } else if view.state == "completed" && failed_sections > 0 {
        format!(
            "The plan is complete. {failed_sections} of {} sections failed",
            sections.len()
        )
    } else if view.state == "executing" && view.phase == PHASE_COMBINING {
        COMBINING_TEXT.to_string()
    } else {
        state_text(&view.state).to_string()
    };
    // The backend refuses the same approve. The card says why before the click.
    let approve_refusal = approve_refusal(&view.nodes);
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
    let mut decide_question = decide.clone();
    let mut decide_cancel = decide;

    rsx! {
        div {
            "data-plan-card": "{view.run_id}",
            "data-plan-state": "{view.state}",
            style: CARD_STYLE,
            CardHeader { state_label: state_label.clone() }
            if stale {
                div { "data-plan-stale": "true",
                    style: "font-size: 12px; color: #92400E; background: #FFFBEB; \
                            border: 1px solid #FDE68A; border-radius: 6px; padding: 4px 8px;",
                    "{stale_text}"
                }
            }
            if show_sections {
                SectionList {
                    sections: sections.clone(),
                    terminal,
                    reports: reports.read().clone(),
                    live: live.clone(),
                }
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
            if question_review {
                div { style: "display: flex; flex-direction: column; gap: 6px;",
                    div { "data-plan-question": "true", style: "font-size: 13px; white-space: pre-wrap;", "{question}" }
                    div { style: "display: flex; gap: 6px; flex-wrap: wrap;",
                        for (index, option) in question_options.into_iter().enumerate() {
                            button {
                                key: "{index}",
                                style: BUTTON_PLAIN,
                                onclick: move |_| comment.set(option.clone()),
                                "{option}"
                            }
                        }
                    }
                    textarea {
                        "data-plan-question-reply": "true",
                        rows: "3",
                        maxlength: "{MAX_PLAN_COMMENT_CHARS}",
                        placeholder: "Reply to the planner",
                        style: "font-size: 13px; padding: 6px 8px; border: 1px solid #CBD5E1; border-radius: 6px; resize: vertical;",
                        value: "{comment}",
                        oninput: move |e| comment.set(e.value()),
                    }
                }
            } else if can_review && *reject_open.read() {
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
                    if question_review {
                        button {
                            "data-plan-action": "question-reply",
                            style: BUTTON_PRIMARY,
                            disabled: is_busy || comment_len == 0,
                            onclick: move |_| decide_question(PlanAction::Reject),
                            "Send answer"
                        }
                    } else if can_review && !*reject_open.read() {
                        if let Some(reason) = approve_refusal.clone() {
                            div { "data-plan-approve-refused": "true",
                                style: "font-size: 12px; color: #92400E; flex-basis: 100%;",
                                "{reason}"
                            }
                        }
                        button {
                            "data-plan-action": "approve",
                            style: BUTTON_PRIMARY,
                            disabled: is_busy || approve_refusal.is_some(),
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

/// The state text of an executing plan whose organizer combines the section reports.
const COMBINING_TEXT: &str = "Every section ended. The organizer combines the reports";

/// Why the tree cannot be approved, or `None`. A section is a direct child of the root.
fn approve_refusal(nodes: &[PlanNodeView]) -> Option<String> {
    let sections = section_count(nodes);
    if sections == 0 {
        return Some(
            "This plan has no section, so it cannot run. Ask for changes, and the planner \
             writes it again."
                .to_string(),
        );
    }
    (sections > MAX_PLAN_SECTIONS).then(|| {
        format!(
            "This plan has {sections} top-level sections, and a plan can run at most \
             {MAX_PLAN_SECTIONS}. Ask for changes, and the planner merges the sections."
        )
    })
}

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
        PlanDecisionOutcome::TooManySections { sections, limit } => Some(format!(
            "This plan has {sections} top-level sections, and a plan can run at most {limit}. \
             Reject it with a comment, and the planner merges the sections."
        )),
    }
}

/// One entry of `sections_json`.
#[derive(Clone, PartialEq, Debug)]
struct Section {
    node_id: String,
    title: String,
    tasks: u64,
    state: String,
    end_reason: String,
    cause: String,
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
                end_reason: text("end_reason").to_string(),
                cause: text("cause").to_string(),
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

/// The sections of an approved plan, each with its outcome and its report. A section is
/// marked failed only when the run is terminal, because during execution the worker's
/// entries do not yet hold the outcome.
#[component]
fn SectionList(
    sections: Vec<Section>,
    terminal: bool,
    reports: Vec<SectionReportView>,
    live: Vec<SubagentRunEntry>,
) -> Element {
    rsx! {
        div { style: "display: flex; flex-direction: column; gap: 4px;",
            div { style: "font-size: 12px; font-weight: 600; color: #475569;", "Sections" }
            for (i, section) in sections.into_iter().enumerate() {
                {
                    let failed = terminal && section.failed;
                    let state = section_state_text(&section, terminal, &live);
                    let color = if failed { "#B91C1C" } else { "#334155" };
                    let heading = format!("{}. {}", i + 1, section.title);
                    let defects = section.defect_classes.join(", ");
                    let tasks = if section.tasks == 1 {
                        "1 task".to_string()
                    } else {
                        format!("{} tasks", section.tasks)
                    };
                    let report = reports
                        .iter()
                        .find(|r| r.node_id == section.node_id)
                        .map(|r| r.report.clone());
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
                            if failed && !section.cause.is_empty() {
                                div { "data-plan-section-cause": "true",
                                    style: "font-size: 11px; color: #B91C1C;",
                                    "Cause: {section.cause}"
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
                            if let Some(report) = report {
                                details { "data-plan-section-report": "{i}",
                                    style: "font-size: 12px; color: #334155;",
                                    summary { style: "cursor: pointer;", "Report" }
                                    SectionReportBody { report }
                                }
                            } else if terminal {
                                div { "data-plan-section-report": "missing",
                                    style: "font-size: 11px; color: #92400E;",
                                    "No report was written for this section."
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

/// The state text of one section. A terminal plan shows the outcome that the worker
/// recorded. While the plan runs, the stored entries hold no state yet, so a section with
/// a live run shows the state of that run. A section with no run shows "not started".
fn section_state_text(section: &Section, terminal: bool, live: &[SubagentRunEntry]) -> String {
    if terminal && section.failed {
        return "failed".to_string();
    }
    let state = if section.state.is_empty() {
        live.iter()
            .find(|e| e.depth == 1 && !e.plan_node_id.is_empty() && e.plan_node_id == section.node_id)
            .map(|e| e.state.as_str())
            .unwrap_or_default()
    } else {
        section.state.as_str()
    };
    if state.is_empty() {
        return "not started".to_string();
    }
    state.replace('_', " ")
}

/// One report of a section.
#[component]
fn SectionReportBody(report: SectionReport) -> Element {
    match report {
        SectionReport::Typed { data } => rsx! { TypedReport { data } },
        SectionReport::Legacy { text } => rsx! {
            div { "data-report-shape": "legacy",
                style: "display: flex; flex-direction: column; gap: 4px; padding-top: 4px;",
                div { style: "color: #92400E;",
                    "This report is from before the typed report. It has no recorded reads, \
                     citations or diagnostics. Its text follows."
                }
                div { style: "white-space: pre-wrap; word-break: break-word;", "{text}" }
            }
        },
        SectionReport::Missing => rsx! {
            div { "data-report-shape": "missing", style: "color: #92400E;",
                "No report was written for this section."
            }
        },
    }
}

/// A typed report: the model text, then what code recorded, in separate parts.
#[component]
fn TypedReport(data: ReportData) -> Element {
    let execution = execution_text(&data);
    let final_answer = data.final_answer.clone();
    let final_text = final_answer.as_ref().map(|a| a.text.clone()).unwrap_or_default();
    let recent: Vec<String> = data
        .recent_text
        .iter()
        .map(|t| t.text.clone())
        .filter(|t| !t.is_empty() && t != &final_text)
        .collect();
    let reads: Vec<String> = data.documents_read.iter().map(read_text).collect();
    let citations: Vec<String> = data.citations.iter().map(citation_text).collect();
    let notes: Vec<String> = data.notes.iter().map(note_text).collect();
    let artifacts: Vec<String> = data
        .artifacts
        .iter()
        .map(|e| label_of(e, &["title", "url", "artifact_id"]))
        .collect();
    let diagnostics = diagnostics_lines(&data);
    rsx! {
        div { "data-report-shape": "typed",
            style: "display: flex; flex-direction: column; gap: 6px; padding-top: 4px;",
            div { "data-report-execution": "true", style: "color: #475569;", "{execution}" }
            if let Some(answer) = final_answer {
                div { style: "display: flex; flex-direction: column; gap: 2px;",
                    div { style: "font-weight: 600;",
                        if answer.asked { "Question to you" } else { "Final answer" }
                    }
                    div { "data-report-final": "true",
                        style: "white-space: pre-wrap; word-break: break-word;",
                        "{answer.text}"
                    }
                }
            } else {
                div { "data-report-final": "none", style: "color: #92400E;",
                    "The run wrote no final answer."
                }
            }
            if !recent.is_empty() {
                ReportList { title: "Latest texts of the model".to_string(), items: recent, key_name: "recent".to_string() }
            }
            div { style: "font-weight: 600; color: #475569; border-top: 1px solid #E2E8F0; \
                          padding-top: 4px;",
                "Recorded from the tool results"
            }
            ReportList { title: format!("Documents read ({})", reads.len()), items: reads, key_name: "reads".to_string() }
            ReportList { title: format!("Citations ({})", citations.len()), items: citations, key_name: "citations".to_string() }
            if !notes.is_empty() {
                ReportList { title: format!("Notes ({})", notes.len()), items: notes, key_name: "notes".to_string() }
            }
            if !artifacts.is_empty() {
                ReportList { title: format!("Artifacts ({})", artifacts.len()), items: artifacts, key_name: "artifacts".to_string() }
            }
            if !diagnostics.is_empty() {
                ReportList { title: "Diagnostics".to_string(), items: diagnostics, key_name: "diagnostics".to_string() }
            }
        }
    }
}

#[component]
fn ReportList(title: String, items: Vec<String>, key_name: String) -> Element {
    rsx! {
        div { "data-report-list": "{key_name}",
            style: "display: flex; flex-direction: column; gap: 1px;",
            div { style: "font-weight: 600;", "{title}" }
            for (i, item) in items.into_iter().enumerate() {
                div { key: "{i}", style: "padding-left: 10px; white-space: pre-wrap; \
                                         word-break: break-word;",
                    "{item}"
                }
            }
        }
    }
}

/// How the section's run ended, in words. Absent fields say nothing: an absent ending
/// is not a success.
fn execution_text(data: &ReportData) -> String {
    let e = &data.execution;
    let mut parts = Vec::new();
    if e.state.is_empty() {
        parts.push("The report does not record how the run ended.".to_string());
    } else {
        parts.push(format!("The run ended {}.", e.state.replace('_', " ")));
    }
    match e.end_reason.as_str() {
        "" => {}
        "step_budget" => parts.push("It stopped at the step limit.".to_string()),
        "empty_response" => parts.push("It stopped after two empty replies.".to_string()),
        other => parts.push(format!("It stopped: {}.", other.replace('_', " "))),
    }
    if e.incomplete {
        parts.push("Its work is incomplete.".to_string());
    }
    if !e.error.is_empty() {
        parts.push(format!("Error: {}", e.error));
    }
    parts.join(" ")
}

/// A string value of a reference, else the first of `keys` that has one, else "an item".
fn label_of(entry: &EvidenceEntry, keys: &[&str]) -> String {
    keys.iter()
        .map(|k| entry.reference_str(k))
        .find(|v| !v.is_empty())
        .unwrap_or("an item")
        .to_string()
}

/// The span of a read, as the report records it, or "".
fn span_text(entry: &EvidenceEntry) -> String {
    let Some(range) = &entry.range else { return String::new() };
    let num = |k: &str| range.get(k).and_then(|v| v.as_u64());
    let mut parts = Vec::new();
    if let Some(page) = num("page") {
        parts.push(format!("page {page}"));
    }
    if let (Some(a), Some(b)) = (num("start_bytes"), num("end_bytes")) {
        let total = num("total_bytes").map(|t| format!(" of {t}")).unwrap_or_default();
        parts.push(format!("bytes {a} to {b}{total}"));
    }
    if let Some(a) = num("start_chars") {
        let end = num("end_chars").map(|b| format!(" to {b}")).unwrap_or_default();
        let total = num("total_chars").map(|t| format!(" of {t}")).unwrap_or_default();
        parts.push(format!("characters {a}{end}{total}"));
    }
    if let Some(find) = range.get("find").and_then(|v| v.as_str()) {
        let shown = range.get("spans").and_then(|v| v.as_array()).map_or(0, |a| a.len());
        parts.push(format!("find \"{find}\", {shown} passages shown"));
    }
    parts.join(", ")
}

fn read_text(entry: &EvidenceEntry) -> String {
    let what = label_of(entry, &["path", "url", "title", "file_hash"]);
    let span = span_text(entry);
    match entry.status.as_str() {
        "error" => format!("{what}: failed: {}", entry.error.clone().unwrap_or_default()),
        "partial" if span.is_empty() => format!("{what}: part of the text"),
        "partial" => format!("{what}: part of the text, {span}"),
        "ok" if span.is_empty() => format!("{what}: read"),
        "ok" => format!("{what}: read, {span}"),
        other => format!("{what}: {other}"),
    }
}

fn citation_text(entry: &EvidenceEntry) -> String {
    let handle = entry.reference_str("handle");
    let what = label_of(entry, &["path", "file_hash"]);
    if entry.status == "error" {
        return format!("{what}: failed: {}", entry.error.clone().unwrap_or_default());
    }
    let verified = entry.reference.get("quote_verified").and_then(|v| v.as_bool()) == Some(true);
    let reason = entry.reference_str("quote_reason");
    let quote = if verified {
        "quote verified".to_string()
    } else if reason.is_empty() {
        "quote not verified".to_string()
    } else {
        format!("quote not verified ({reason})")
    };
    let handle = if handle.is_empty() { String::new() } else { format!("{handle} ") };
    format!("{handle}{what}: {quote}")
}

fn note_text(entry: &EvidenceEntry) -> String {
    label_of(entry, &["text", "title", "note_id"])
}

/// The diagnostics of a report that are not empty, one line each.
fn diagnostics_lines(data: &ReportData) -> Vec<String> {
    let d = &data.diagnostics;
    let check = &d.citation_check;
    let mut out = Vec::new();
    if d.failed_items > 0 {
        out.push(format!("{} reads or citations failed.", d.failed_items));
    }
    if !d.unanswered_calls.is_empty() {
        out.push(format!("{} calls have no result.", d.unanswered_calls.len()));
    }
    if !check.unresolved.is_empty() {
        out.push(format!("Labels that no citation gave: {}.", check.unresolved.join(", ")));
    }
    if !check.conflicting.is_empty() {
        out.push(format!(
            "Labels that citations gave to more than one document: {}.",
            check.conflicting.join(", ")
        ));
    }
    if !check.unverified_quotes.is_empty() {
        out.push(format!("{} quotes are not verified.", check.unverified_quotes.len()));
    }
    if d.repair_round {
        out.push("The run had one citation repair round.".to_string());
    }
    if d.legacy_tool_messages > 0 {
        out.push(format!(
            "{} tool results are from before the recorded evidence, so their reads are not listed.",
            d.legacy_tool_messages
        ));
    }
    for (list, count) in &d.left_out {
        if *count > 0 {
            out.push(format!("The report leaves out {count} entries of {list}."));
        }
    }
    out
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
        div { "data-plan-live-run": "{entry.state}",
            style: "display: flex; gap: 8px; font-size: 12px; color: #1E293B;",
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
    fn approval_is_refused_for_a_root_only_tree_and_too_many_sections() {
        let root = node("root", None, 1, "question");
        assert!(approve_refusal(&[root.clone()]).unwrap().contains("no section"));
        let mut nodes = vec![root.clone()];
        for i in 0..5 {
            nodes.push(node(&format!("s{i}"), Some("root"), i, "section"));
        }
        assert!(approve_refusal(&nodes).unwrap().contains("5 top-level sections"));
        assert_eq!(approve_refusal(&nodes[..3]), None);
    }

    #[test]
    fn a_failed_section_shows_failed_and_a_live_one_shows_its_state() {
        let json = r#"[{"node_id":"a","title":"A","tasks":1,"state":"completed","end_reason":"",
            "cause":"","failed":false},{"node_id":"b","title":"B","tasks":2,"state":"completed",
            "end_reason":"step_budget","cause":"the run stopped at the step limit","failed":true}]"#;
        let sections = parse_sections(json);
        assert_eq!(section_state_text(&sections[0], true, &[]), "completed");
        assert_eq!(section_state_text(&sections[1], true, &[]), "failed");
        assert_eq!(sections[1].cause, "the run stopped at the step limit");
        assert_eq!(section_state_text(&sections[1], false, &[]), "completed");
    }

    #[test]
    fn a_section_without_a_stored_state_shows_its_live_run() {
        let json = r#"[{"node_id":"a","title":"A","tasks":1,"state":"","failed":false},
            {"node_id":"b","title":"B","tasks":1,"state":"","failed":false}]"#;
        let sections = parse_sections(json);
        let live: Vec<SubagentRunEntry> = serde_json::from_str(
            r#"[{"run_id":"r1","parent_run_id":"o","depth":1,"batch_id":"x","tool_call_id":"",
                "plan_node_id":"a","state":"running","objective":"A","tool_calls":3}]"#,
        )
        .unwrap();
        assert_eq!(section_state_text(&sections[0], false, &live), "running");
        assert_eq!(section_state_text(&sections[1], false, &live), "not started");
    }

    #[test]
    fn a_typed_report_lists_partial_and_failed_reads_and_an_incomplete_run() {
        let data: ReportData = serde_json::from_str(r#"{
            "version": 1,
            "execution": {"state": "completed", "end_reason": "step_budget", "incomplete": true, "error": ""},
            "documents_read": [
              {"kind": "document_read", "status": "partial", "reference": {"path": "/a.txt"},
               "range": {"page": 2, "start_bytes": 0, "end_bytes": 10, "total_bytes": 90}},
              {"kind": "document_read", "status": "error", "reference": {"file_hash": "bbbb"}, "error": "not found"},
              {"kind": "document_read", "status": "partial", "reference": {"url": "https://x.example/p"},
               "range": {"find": "Staff", "spans": [[1, 5], [9, 12]], "matches": 4, "total_chars": 99}}
            ],
            "citations": [{"kind": "citation", "status": "ok",
               "reference": {"handle": "[D1]", "path": "/a.txt", "quote_verified": false, "quote_reason": "absent"}}],
            "diagnostics": {"citation_check": {"unresolved": ["[D4]"], "conflicting": ["[D2]"]}}
        }"#).unwrap();
        assert_eq!(execution_text(&data),
                   "The run ended completed. It stopped at the step limit. Its work is incomplete.");
        let reads: Vec<String> = data.documents_read.iter().map(read_text).collect();
        assert_eq!(reads[0], "/a.txt: part of the text, page 2, bytes 0 to 10 of 90");
        assert_eq!(reads[1], "bbbb: failed: not found");
        assert_eq!(reads[2], "https://x.example/p: part of the text, find \"Staff\", 2 passages shown");
        assert_eq!(citation_text(&data.citations[0]), "[D1] /a.txt: quote not verified (absent)");
        let lines = diagnostics_lines(&data);
        assert!(lines.contains(&"Labels that no citation gave: [D4].".to_string()));
        assert!(lines.contains(&"Labels that citations gave to more than one document: [D2].".to_string()));
    }

    #[test]
    fn a_report_with_no_ending_does_not_read_as_success() {
        let data: ReportData = serde_json::from_str(r#"{"version": 1}"#).unwrap();
        assert_eq!(execution_text(&data), "The report does not record how the run ended.");
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
