//! The `run_subagent` card: the sub-agents of one delegation call.
//!
//! The card reads two sources and nothing else:
//!
//! - While the batch is open, the poll's `subagent_runs` entries whose `batch_id` and
//!   `tool_call_id` match the tool row's `tool_input`. Each entry gives the state of the
//!   sub-agent, its tool calls and its partial text while it runs, and its report when it
//!   ends. A depth 2 entry shows under the depth 1 entry that delegated it.
//! - After the batch ends, the reports in the tool row's `tool_output`, which the
//!   continuation writes as `{"reports": [...], "refused": [...]}`.
//!
//! Every text is a text node. A report and a partial text come from a model that read
//! documents and web pages, so neither is rendered as HTML.

use common::chat_types::{SubagentMessage, SubagentRunEntry};
use dioxus::prelude::*;

use super::{json_str, tool_content};

/// Characters of a stored report the card shows before the rest is cut.
const REPORT_CHARS: usize = 2_000;

#[component]
pub fn SubagentCard(
    tool_input: String,
    tool_output: String,
    running: bool,
    /// The poll's entries for the whole turn. The card picks its own.
    subagent_runs: Vec<SubagentRunEntry>,
) -> Element {
    let input: serde_json::Value = serde_json::from_str(&tool_input).unwrap_or_default();
    let batch_id = json_str(&input, "batch_id");
    let call_id = json_str(&input, "tool_call_id");
    let objectives: Vec<String> = input
        .get("briefings")
        .and_then(|b| b.as_array())
        .map(|a| a.iter().map(|b| json_str(b, "objective")).collect())
        .unwrap_or_default();

    let own: Vec<SubagentRunEntry> = if batch_id.is_empty() {
        Vec::new()
    } else {
        subagent_runs
            .iter()
            .filter(|e| e.depth == 1 && e.batch_id == batch_id && e.tool_call_id == call_id)
            .cloned()
            .collect()
    };
    let reports = stored_reports(&tool_output);

    let headline = if !own.is_empty() {
        let open = own.iter().filter(|e| !e.is_terminal()).count();
        format!("Sub-agents: {open} of {} working", own.len())
    } else if let Some((reports, refused)) = &reports {
        let mut text = format!("Sub-agents: {} reports", reports.len());
        if !refused.is_empty() {
            text.push_str(&format!(", {} briefings refused", refused.len()));
        }
        text
    } else if running || batch_id.is_empty() {
        "Delegating to sub-agents\u{2026}".to_string()
    } else {
        format!("Sub-agents: {} briefings, starting", objectives.len())
    };

    rsx! {
        div {
            "data-subagent-card": "{call_id}",
            style: "align-self: flex-start; width: 92%; background: #F0F9FF; \
                    border: 1px solid #BAE6FD; border-radius: 10px; padding: 8px 12px; \
                    font-size: 13px; color: #0C4A6E; display: flex; flex-direction: column; \
                    gap: 6px;",
            div { style: "display: flex; align-items: center; gap: 10px;",
                span {
                    style: "background: #BAE6FD; border-radius: 999px; padding: 1px 8px; \
                            font-size: 11px; font-weight: 600; font-family: ui-monospace, monospace;",
                    "run_subagent"
                }
                span { style: "font-weight: 600;", "{headline}" }
            }
            if !own.is_empty() {
                for entry in own.iter().cloned() {
                    div { key: "{entry.run_id}",
                        style: "display: flex; flex-direction: column; gap: 4px;",
                        EntryView { entry: entry.clone() }
                        for nested in subagent_runs.iter().filter(|e| e.parent_run_id == entry.run_id).cloned() {
                            div { key: "{nested.run_id}",
                                style: "margin-left: 18px; border-left: 2px solid #BAE6FD; \
                                        padding-left: 8px;",
                                EntryView { entry: nested.clone() }
                            }
                        }
                    }
                }
            } else if let Some((reports, refused)) = reports {
                for (i, report) in reports.into_iter().enumerate() {
                    div { key: "report-{i}", StoredReport { report } }
                }
                for (i, reason) in refused.into_iter().enumerate() {
                    div { key: "refused-{i}",
                        style: "color: #92400E; font-size: 12px;",
                        "Refused: {reason}"
                    }
                }
            } else {
                for (i, objective) in objectives.into_iter().enumerate() {
                    div { key: "briefing-{i}", style: "color: #075985;", "\u{2022} {objective}" }
                }
            }
        }
    }
}

/// One stored report from the tool row's output.
#[derive(Clone, PartialEq)]
struct Report {
    task: String,
    state: String,
    text: String,
}

/// `(reports, refused reasons)` from the tool row's output, `None` before the
/// continuation writes it.
fn stored_reports(tool_output: &str) -> Option<(Vec<Report>, Vec<String>)> {
    let content = tool_content(tool_output)?;
    let reports = content.get("reports")?.as_array()?;
    let reports = reports
        .iter()
        .map(|r| {
            let error = json_str(r, "error");
            Report {
                task: json_str(r, "task"),
                state: json_str(r, "state"),
                text: if error.is_empty() { json_str(r, "report") } else { error },
            }
        })
        .collect();
    let refused = content
        .get("refused")
        .and_then(|r| r.as_array())
        .map(|a| {
            a.iter()
                .map(|r| {
                    let reason = json_str(r, "reason");
                    let objective = json_str(r, "objective");
                    if objective.is_empty() { reason } else { format!("{objective} ({reason})") }
                })
                .collect()
        })
        .unwrap_or_default();
    Some((reports, refused))
}

#[component]
fn StoredReport(report: Report) -> Element {
    let text = cut(&report.text, REPORT_CHARS);
    rsx! {
        details {
            summary { style: "cursor: pointer;",
                StateBadge { state: report.state.clone() }
                span { style: "margin-left: 6px;", "{report.task}" }
            }
            div {
                style: "margin-top: 4px; padding: 6px 8px; background: white; border-radius: 6px; \
                        white-space: pre-wrap; word-break: break-word; color: #1E293B;",
                "{text}"
            }
        }
    }
}

#[component]
fn EntryView(entry: SubagentRunEntry) -> Element {
    let calls = if entry.tool_calls == 1 {
        "1 tool call".to_string()
    } else {
        format!("{} tool calls", entry.tool_calls)
    };
    let partial = entry
        .messages
        .iter()
        .rev()
        .find(|m| m.role == "ai" && !m.content.trim().is_empty())
        .map(|m| (m.content.clone(), !m.is_final));
    let steps: Vec<String> = entry.messages.iter().filter_map(step_label).collect();
    rsx! {
        div {
            "data-subagent-run": "{entry.run_id}",
            "data-subagent-state": "{entry.state}",
            style: "display: flex; flex-direction: column; gap: 3px;",
            div { style: "display: flex; align-items: center; gap: 8px;",
                StateBadge { state: entry.state.clone() }
                span { style: "flex: 1; min-width: 0; font-weight: 500;", "{entry.objective}" }
                span { style: "color: #64748B; font-size: 12px;", "{calls}" }
            }
            if entry.state == "running" && !steps.is_empty() {
                div {
                    style: "font-family: ui-monospace, monospace; font-size: 11px; color: #475569; \
                            max-height: 90px; overflow-y: auto;",
                    for (i, step) in steps.into_iter().enumerate() {
                        div { key: "{i}", "{step}" }
                    }
                }
            }
            if entry.state == "running" {
                if let Some((text, streaming)) = partial {
                    div {
                        style: "padding: 4px 8px; background: white; border-radius: 6px; \
                                white-space: pre-wrap; word-break: break-word; color: #1E293B; \
                                max-height: 140px; overflow-y: auto;",
                        "{text}"
                        if streaming {
                            span { style: "color: #0284C7;", "\u{258D}" }
                        }
                    }
                }
            }
            if entry.is_terminal() && !entry.report.is_empty() {
                details {
                    summary { style: "cursor: pointer; font-size: 12px;", "Report" }
                    div {
                        style: "margin-top: 4px; padding: 6px 8px; background: white; \
                                border-radius: 6px; white-space: pre-wrap; word-break: break-word; \
                                color: #1E293B;",
                        "{entry.report}"
                    }
                }
            }
        }
    }
}

/// One line for a tool call or a tool result of a running thread, `None` for text.
fn step_label(m: &SubagentMessage) -> Option<String> {
    match m.role.as_str() {
        "ai" if !m.calls.is_empty() => Some(format!("\u{2192} {}", m.calls.join(", "))),
        "tool" => Some(format!("\u{2190} {} ({} characters)", m.tool_name, m.content.chars().count())),
        _ => None,
    }
}

#[component]
fn StateBadge(state: String) -> Element {
    let (label, background, ink) = match state.as_str() {
        "running" => ("running", "#DBEAFE", "#1E40AF"),
        "waiting_for_children" => ("waiting for its sub-agents", "#E0E7FF", "#3730A3"),
        "completed" => ("done", "#DCFCE7", "#166534"),
        "failed" => ("failed", "#FEE2E2", "#991B1B"),
        "cancelled" => ("stopped", "#F1F5F9", "#475569"),
        _ => ("starting", "#F1F5F9", "#475569"),
    };
    rsx! {
        span {
            style: "flex-shrink: 0; background: {background}; color: {ink}; border-radius: 999px; \
                    padding: 1px 7px; font-size: 11px; font-weight: 600;",
            "{label}"
        }
    }
}

fn cut(text: &str, chars: usize) -> String {
    if text.chars().count() <= chars {
        return text.to_string();
    }
    format!("{}\u{2026}", text.chars().take(chars).collect::<String>())
}
