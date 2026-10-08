//! The bug control in the left rail and the full-screen feedback overlay.
//!
//! Selecting the control makes the icon red at once. `assets/feedback.js` then copies
//! the DOM, draws an image of the tab from the DOM and returns both with the collected
//! log entries and the debug context. The overlay shows what was captured and lets the
//! person select Bug or Feedback, write a title and a description, and send the report.
//! The capture stays in the browser script until it sends the report, so the page holds
//! only the preview.
//!
//! The home page feedback card starts the same flow through [`use_feedback`].

use dioxus::prelude::*;
use dioxus_free_icons::icons::md_action_icons::MdBugReport;
use dioxus_free_icons::Icon;

use common::feedback_types::{DESCRIPTION_MAX_CHARS, TITLE_MAX_CHARS};

/// One collected browser log entry.
#[derive(Debug, Clone, PartialEq, serde::Deserialize)]
pub struct LogEntry {
    pub time: String,
    pub level: String,
    pub source: String,
    pub message: String,
}

/// What `hooverFeedback.capture()` returns.
#[derive(Debug, Clone, PartialEq, serde::Deserialize)]
pub struct Capture {
    pub report_id: String,
    pub png_data_url: String,
    pub png_bytes: u64,
    pub dom_bytes: u64,
    pub context: serde_json::Map<String, serde_json::Value>,
    pub notes: Vec<String>,
    pub logs: Vec<LogEntry>,
}

#[derive(Debug, Clone, PartialEq, serde::Deserialize)]
struct SendResult {
    ok: bool,
    status: u16,
    message: String,
}

#[derive(Debug, Clone, PartialEq, Default)]
pub enum FeedbackPhase {
    #[default]
    Idle,
    Capturing,
    Open(Capture),
    Failed(String),
}

/// The feedback state that the rail control and the home page card share.
#[derive(Clone, Copy)]
pub struct FeedbackState {
    pub phase: Signal<FeedbackPhase>,
}

impl FeedbackState {
    /// Start a capture unless one is open already.
    pub fn start(mut self) {
        if *self.phase.peek() != FeedbackPhase::Idle {
            return;
        }
        self.phase.set(FeedbackPhase::Capturing);
        spawn(async move {
            // The script waits for two frames first, so the red icon is painted before
            // the drawing blocks the page.
            let result = document::eval(
                "await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); \
                 if (!window.hooverFeedback) throw new Error('The feedback script did not load.'); \
                 return await window.hooverFeedback.capture();",
            )
            .join::<Capture>()
            .await;
            self.phase.set(match result {
                Ok(capture) => FeedbackPhase::Open(capture),
                Err(e) => FeedbackPhase::Failed(format!("The capture failed: {e}")),
            });
        });
    }

    pub fn close(mut self) {
        document::eval("window.hooverFeedback && window.hooverFeedback.discard();");
        self.phase.set(FeedbackPhase::Idle);
    }
}

/// Provide the shared feedback state. The navigation frame calls this once.
pub fn use_feedback_provider() -> FeedbackState {
    use_context_provider(|| FeedbackState { phase: Signal::new(FeedbackPhase::Idle) })
}

/// The shared feedback state, for a control that starts a report.
pub fn use_feedback() -> FeedbackState {
    use_context::<FeedbackState>()
}

/// The bug control in the left rail, with the overlay that it opens.
#[component]
pub fn FeedbackRailButton() -> Element {
    let state = use_feedback();
    let phase = (state.phase)();
    let colour = if phase == FeedbackPhase::Idle { "white" } else { "#ff1f1f" };
    rsx! {
        crate::components::navbar::RailHint {
            label: "Bug Report & Feedback Form",
            button {
                id: "x-feedback-button",
                "aria-label": "Bug Report & Feedback Form",
                style: "background: none; border: none; padding: 0; cursor: pointer; color: {colour}; display: flex;",
                onclick: move |_| state.start(),
                Icon { icon: MdBugReport, style: "width: 26px; height: 26px;" }
            }
        }
        match phase {
            FeedbackPhase::Open(capture) => rsx! { FeedbackOverlay { capture } },
            FeedbackPhase::Failed(message) => rsx! { CaptureFailed { message } },
            _ => rsx! {},
        }
    }
}

const OVERLAY: &str = "position: fixed; inset: 0; z-index: 2000; background: white; display: flex; flex-direction: column; font-family: var(--x-font); color: var(--x-ink); font-size: var(--x-text-md);";
const COLUMN: &str = "flex: 1; min-width: 0; overflow-y: auto; padding: 20px 28px;";
const H2: &str = "margin: 0 0 10px; font-size: var(--x-text-lg); font-weight: 600; color: var(--x-ink-strong);";
const FIELD_LABEL: &str = "display: block; margin: 14px 0 6px; font-weight: 600; color: var(--x-ink-strong);";
const INPUT: &str = "width: 100%; box-sizing: border-box; border: 1px solid; border-color: var(--x-border-strong); border-radius: 6px; padding: 8px 10px; font: inherit; color: var(--x-ink-strong);";
const BTN: &str = "background: white; color: var(--x-ink-strong); border: 1px solid; border-color: var(--x-border-strong); padding: 7px 16px; border-radius: 16px; cursor: pointer; font: inherit; font-weight: 500;";
const BTN_PRIMARY: &str = "background-color: var(--x-link); color: white; border: 1px solid; border-color: var(--x-link); padding: 7px 16px; border-radius: 16px; cursor: pointer; font: inherit; font-weight: 500;";
const MUTED: &str = "color: var(--x-ink-muted); font-size: var(--x-text-sm);";

/// Size in KB with one decimal.
pub fn kb(bytes: u64) -> String {
    format!("{:.1} KB", bytes as f64 / 1024.0)
}

#[component]
fn CaptureFailed(message: String) -> Element {
    let state = use_feedback();
    rsx! {
        div { id: "x-feedback-overlay", style: OVERLAY,
            div { style: COLUMN,
                h2 { style: H2, "Report a bug or send feedback" }
                p { style: "color: var(--x-danger);", "{message}" }
                button { style: BTN, onclick: move |_| state.close(), "Close" }
            }
        }
    }
}

#[derive(Clone, Copy, PartialEq)]
enum SendState {
    Editing,
    Sending,
    Sent,
}

#[component]
fn FeedbackOverlay(capture: Capture) -> Element {
    let state = use_feedback();
    let mut kind = use_signal(|| "bug".to_string());
    let mut title = use_signal(String::new);
    let mut description = use_signal(String::new);
    let mut send_state = use_signal(|| SendState::Editing);
    let mut error = use_signal(|| None::<String>);

    let send = move |_| {
        if title.read().trim().is_empty() {
            error.set(Some("Write a title.".to_string()));
            return;
        }
        error.set(None);
        send_state.set(SendState::Sending);
        let fields = serde_json::json!({
            "kind": kind(),
            "title": title(),
            "description": description(),
        });
        spawn(async move {
            let result = document::eval(&format!(
                "return await window.hooverFeedback.send({fields});"
            ))
            .join::<SendResult>()
            .await;
            match result {
                Ok(r) if r.ok => send_state.set(SendState::Sent),
                Ok(r) => {
                    let detail = if r.status == 0 { r.message } else { format!("{} ({})", r.message, r.status) };
                    error.set(Some(format!("The report was not sent: {detail}. Select Send to try again.")));
                    send_state.set(SendState::Editing);
                }
                Err(e) => {
                    error.set(Some(format!("The report was not sent: {e}. Select Send to try again.")));
                    send_state.set(SendState::Editing);
                }
            }
        });
    };

    let sending = send_state() == SendState::Sending;
    let kind_button = |value: &'static str, label: &'static str| {
        let selected = kind() == value;
        let style = if selected { BTN_PRIMARY } else { BTN };
        rsx! {
            button {
                class: "x-feedback-kind",
                style: style,
                role: "radio",
                "aria-checked": "{selected}",
                onclick: move |_| kind.set(value.to_string()),
                "{label}"
            }
        }
    };

    rsx! {
        div {
            id: "x-feedback-overlay",
            role: "dialog",
            "aria-modal": "true",
            "aria-label": "Report a bug or send feedback",
            style: OVERLAY,
            onkeydown: move |e: KeyboardEvent| {
                if e.key() == Key::Escape && send_state() != SendState::Sending {
                    state.close();
                }
            },
            div { style: "display: flex; align-items: center; gap: 12px; padding: 14px 28px; border-bottom: 1px solid; border-bottom-color: var(--x-border);",
                h1 { style: "margin: 0; flex: 1; font-size: var(--x-text-2xl); font-weight: 600; color: var(--x-ink-strong);",
                    "Report a bug or send feedback"
                }
                button { style: BTN, disabled: sending, onclick: move |_| state.close(),
                    if send_state() == SendState::Sent { "Close" } else { "Cancel" }
                }
            }
            div { style: "flex: 1; min-height: 0; display: flex;",
                div { style: "{COLUMN} border-right: 1px solid; border-right-color: var(--x-border);",
                    if send_state() == SendState::Sent {
                        p { id: "x-feedback-sent", style: "color: var(--x-ok); font-weight: 600;", "The report was sent. Thank you." }
                    } else {
                        h2 { style: H2, "Report" }
                        div { role: "radiogroup", "aria-label": "Report type", style: "display: flex; gap: 8px;",
                            {kind_button("bug", "Bug")}
                            {kind_button("feedback", "Feedback")}
                        }
                        label { style: FIELD_LABEL, r#for: "x-feedback-title", "Title" }
                        input {
                            id: "x-feedback-title",
                            style: INPUT,
                            maxlength: "{TITLE_MAX_CHARS}",
                            autofocus: true,
                            placeholder: "What happened, in one line",
                            value: "{title}",
                            oninput: move |e| title.set(e.value()),
                        }
                        label { style: FIELD_LABEL, r#for: "x-feedback-description", "Description" }
                        textarea {
                            id: "x-feedback-description",
                            style: "{INPUT} min-height: 180px; resize: vertical;",
                            maxlength: "{DESCRIPTION_MAX_CHARS}",
                            placeholder: "What you did, what you expected, and what you saw. You can paste links to other pages of the application.",
                            value: "{description}",
                            oninput: move |e| description.set(e.value()),
                        }
                        if let Some(message) = error() {
                            p { id: "x-feedback-error", style: "color: var(--x-danger); margin: 12px 0 0;", "{message}" }
                        }
                        div { style: "margin-top: 14px;",
                            button { id: "x-feedback-send", style: BTN_PRIMARY, disabled: sending, onclick: send,
                                if sending { "Sending\u{2026}" } else { "Send" }
                            }
                        }
                    }
                    h2 { style: "{H2} margin-top: 24px;", "Captured page" }
                    p { id: "x-feedback-sizes", style: MUTED,
                        "Page image: {kb(capture.png_bytes)}. DOM copy: {kb(capture.dom_bytes)}."
                    }
                    for note in capture.notes.iter() {
                        p { class: "x-feedback-note", style: "color: var(--x-warning); margin: 4px 0;", "{note}" }
                    }
                    if capture.png_data_url.is_empty() {
                        p { style: MUTED, "The report has no page image." }
                    } else {
                        img {
                            id: "x-feedback-image",
                            src: "{capture.png_data_url}",
                            alt: "Image of the page when the report started",
                            style: "display: block; max-width: 100%; margin-top: 8px; border: 1px solid; border-color: var(--x-border);",
                        }
                    }
                }
                div { style: COLUMN,
                    h2 { style: H2, "Debug context" }
                    table { style: "border-collapse: collapse; width: 100%;",
                        tbody {
                            for (key, value) in capture.context.iter() {
                                tr { key: "{key}",
                                    td { style: "padding: 3px 12px 3px 0; vertical-align: top; white-space: nowrap; {MUTED}", "{key}" }
                                    td { style: "padding: 3px 0; word-break: break-all;", "{context_value(value)}" }
                                }
                            }
                        }
                    }
                    h2 { style: "{H2} margin-top: 24px;", "Browser log ({capture.logs.len()} entries)" }
                    if capture.logs.is_empty() {
                        p { style: MUTED, "The page wrote no log entries since it loaded." }
                    } else {
                        div { id: "x-feedback-log", style: "font-family: ui-monospace, monospace; font-size: var(--x-text-xs); border: 1px solid; border-color: var(--x-border); border-radius: 6px;",
                            for (i, entry) in capture.logs.iter().enumerate() {
                                div { key: "{i}", style: "padding: 4px 8px; border-bottom: 1px solid; border-bottom-color: var(--x-border); white-space: pre-wrap; word-break: break-word; color: {level_colour(&entry.level)};",
                                    "{entry.time} {entry.level} {entry.source}: {entry.message}"
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

fn level_colour(level: &str) -> &'static str {
    match level {
        "error" => "var(--x-danger)",
        "warning" => "var(--x-warning)",
        _ => "var(--x-ink)",
    }
}

fn context_value(value: &serde_json::Value) -> String {
    match value {
        serde_json::Value::String(s) => s.clone(),
        serde_json::Value::Array(items) => items
            .iter()
            .map(context_value)
            .collect::<Vec<_>>()
            .join(", "),
        serde_json::Value::Null => String::new(),
        other => other.to_string(),
    }
}
