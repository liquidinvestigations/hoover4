//! The dataset OCR language form and the operation strip that keeps it unlockable.
//!
//! These two are one file because they are one mechanism. The form disables itself while
//! an apply operation runs; the strip is what makes that operation visible. A form that
//! hides its own lock is a form that locks forever, so the strip polls, reports
//! staleness, and shows the error when an operation fails.
//!
//! Neither of them is the actual guard. `admin_apply_ocr_languages` refuses a second
//! dispatch server-side through the operations lock, reading the same row the strip
//! polls, because two admins in two browsers are not stopped by a disabled button.

use dioxus::prelude::*;

use common::admin_types::{DatasetOcrPanel, DatasetOperationStatus};

use crate::api::admin_api::{
    admin_apply_ocr_languages, admin_get_dataset_ocr, admin_get_dataset_operation,
};
use crate::components::admin_components::{
    ErrorBar, SuccessBar, BTN, HELP_TEXT, SUBHEADING, INPUT, MODULE, MODULE_BODY, MODULE_CAPTION,
};

/// How often the strip re-reads the operation row while one is running. Fast enough that
/// Apply reads as answered, slow enough that an admin leaving the page open is not a load
/// source.
const POLL_SECONDS: u64 = 3;

/// Past this, a running operation that has not advanced is called out as possibly stuck.
///
/// A warning and nothing else: the lock deliberately has no staleness timeout, because a
/// run that stopped reporting may still have activities in flight. Releasing it is a
/// cancellation, which is a decision a person makes with this number in front of them.
const STALE_SECONDS: u64 = 900;

/// Describe the recorded stage or the operation state and ingest plan counts.
fn describe(operation: &DatasetOperationStatus) -> String {
    let value = serde_json::from_str::<serde_json::Value>(&operation.detail)
        .unwrap_or(serde_json::Value::Null);
    let stage = value.get("stage").and_then(|v| v.as_str());
    let mut parts = vec![stage.unwrap_or(&operation.state).to_string()];
    if stage.is_none() && matches!(operation.kind.as_str(), "add_dataset" | "rescan_dataset") {
        parts.push(format!("{} of {} plans", operation.progress_done, operation.progress_total));
    }
    let list = |key: &str| -> String {
        value
            .get(key)
            .and_then(|v| v.as_array())
            .map(|a| {
                a.iter()
                    .filter_map(|v| v.as_str())
                    .collect::<Vec<_>>()
                    .join(", ")
            })
            .unwrap_or_default()
    };
    let added = list("added");
    let removed = list("removed");
    if !added.is_empty() {
        parts.push(format!("adding {added}"));
    }
    if !removed.is_empty() {
        parts.push(format!("removing {removed}"));
    }
    if let Some(plans) = value.get("plans").and_then(|v| v.as_u64()) {
        if plans > 0 {
            parts.push(format!("{plans} plan(s) reopened"));
        }
    }
    parts.join(" \u{b7} ")
}

/// Polled `operations` strip. Renders nothing until the dataset has had an operation.
///
/// `on_change` fires when the state transitions, so the page holding the form can refetch
/// once the operation finishes rather than leaving stale variant counts on screen.
#[component]
pub fn DatasetOperationStrip(
    /// A `ReadSignal`, not a `String`, for the reason spelled out at length in
    /// `ai_chat/session_page.rs`: the router **reuses** these components when it navigates
    /// between two datasets. A handler that closes over a `String` cloned on first render
    /// keeps polling the dataset the admin has left, and writes its answers into the
    /// signals now rendering the new one.
    collection_dataset: ReadSignal<String>,
    #[props(default = None)] on_change: Option<EventHandler<DatasetOperationStatus>>,
) -> Element {
    let mut job = use_signal(|| None::<DatasetOperationStatus>);
    let mut last_state = use_signal(String::new);
    // Bumped when the dataset changes, to retire the loop that was polling the old one.
    let mut poll_gen = use_signal(|| 0_u64);
    let mut polling_for = use_signal(String::new);

    use_effect(move || {
        // Read, not peeked: this subscription is what makes the effect re-run when the
        // router hands the component a different dataset.
        let dataset = collection_dataset.read().clone();
        if *polling_for.peek() == dataset {
            return;
        }
        polling_for.set(dataset.clone());
        job.set(None);
        last_state.set(String::new());
        let generation = *poll_gen.peek() + 1;
        poll_gen.set(generation);

        spawn(async move {
            loop {
                if *poll_gen.peek() != generation {
                    return;
                }
                if let Ok(current) = admin_get_dataset_operation(dataset.clone()).await {
                    if *poll_gen.peek() != generation {
                        return;
                    }
                    let state = current
                        .as_ref()
                        .map(|j| format!("{}:{}", j.op_id, j.state))
                        .unwrap_or_default();
                    if state != *last_state.peek() {
                        last_state.set(state);
                        if let (Some(handler), Some(value)) = (&on_change, &current) {
                            handler.call(value.clone());
                        }
                    }
                    job.set(current);
                }
                // Keep polling after an operation ends: the next Apply on this page has to
                // be picked up too, and the alternative is a strip that goes silent
                // exactly when the admin presses the button.
                n0_future::time::sleep(std::time::Duration::from_secs(POLL_SECONDS)).await;
            }
        });
    });

    let Some(current) = job.read().clone() else {
        return rsx! {};
    };

    let stale = current.is_running() && current.stale_seconds > STALE_SECONDS;
    let (background, border, ink) = match current.state.as_str() {
        "errored" => ("#fdecea", "#f5c6cb", "#a94442"),
        "cancelled" => ("#f3f3f3", "#dcdcdc", "#666666"),
        _ if stale => ("#fff4e5", "#ffd8a8", "#8a5a00"),
        "pending" | "queued" | "running" => ("#e8f4fa", "#bcdff1", "#31708f"),
        _ => ("#eaf6ea", "#c3e6cb", "#3c763d"),
    };

    rsx! {
        div {
            style: "background: {background}; border: 1px solid {border}; color: {ink}; \
                    border-radius: 6px; padding: 10px 12px; margin-bottom: 16px; font-size: var(--x-text-md);",
            div { style: "font-weight: 500;",
                "Last operation: {current.kind}, {current.state}"
                if current.is_running() {
                    span { style: "font-weight: 400;", ", started {current.started_at}" }
                } else if !current.finished_at.is_empty() {
                    span { style: "font-weight: 400;", ", {current.finished_at}" }
                }
            }
            if current.is_running() && (!current.detail.is_empty() || matches!(current.kind.as_str(), "add_dataset" | "rescan_dataset")) {
                div { style: "margin-top: 3px;", "{describe(&current)}" }
            }
            if stale {
                div { style: "margin-top: 3px; font-weight: 500;",
                    "No progress for {current.stale_seconds / 60} minutes. Check the Temporal workflow, and cancel the operation if it is stuck."
                }
            }
            if !current.error.is_empty() {
                div {
                    style: "margin-top: 6px; font-family: ui-monospace, monospace; font-size: var(--x-text-xs); \
                            white-space: pre-wrap; word-break: break-word;",
                    "{current.error}"
                }
            }
        }
    }
}

/// One engine's language list, as a set of checkboxes over what the tier can serve.
///
/// A text box would let an admin type a language the image does not have, which fails per
/// file hours later. The backend refuses that too, but the form should not be able to
/// compose the request in the first place.
#[component]
fn LanguageChecklist(
    available: Vec<String>,
    selected: Signal<Vec<String>>,
    disabled: bool,
) -> Element {
    let ink = if disabled { "var(--x-ink-faint)" } else { "var(--x-ink)" };
    rsx! {
        div {
            style: "display: flex; flex-wrap: wrap; gap: 10px 16px;",
            for code in available.iter().cloned() {
                {
                    let code_for_check = code.clone();
                    let code_for_toggle = code.clone();
                    let is_on = selected.read().iter().any(|c| *c == code_for_check);
                    rsx! {
                        label {
                            key: "{code}",
                            style: "display: flex; align-items: center; gap: 5px; font-size: var(--x-text-sm); \
                                    color: {ink};",
                            input {
                                r#type: "checkbox",
                                checked: is_on,
                                disabled,
                                onchange: move |_| {
                                    let mut current = selected.write();
                                    // Append rather than insert in sorted position:
                                    // Tesseract treats the first language as primary, so
                                    // the order the admin builds is the request.
                                    if let Some(at) = current.iter().position(|c| *c == code_for_toggle) {
                                        current.remove(at);
                                    } else {
                                        current.push(code_for_toggle.clone());
                                    }
                                },
                            }
                            "{code}"
                        }
                    }
                }
            }
        }
    }
}

fn split_languages(raw: &str) -> Vec<String> {
    raw.split('+')
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
        .collect()
}

#[component]
pub fn DatasetOcrSettingsPanel(collection_dataset: ReadSignal<String>) -> Element {
    // `use_resource` subscribes to the signal it reads, which is what makes this refetch
    // when the router reuses the component for a different dataset.
    let mut panel_res = use_resource(move || admin_get_dataset_ocr(collection_dataset.read().clone()));

    let mut tesseract = use_signal(Vec::<String>::new);
    let mut easyocr_raw = use_signal(String::new);
    let mut seeded_for = use_signal(String::new);
    let mut msg = use_signal(|| None::<String>);
    let mut error_msg = use_signal(|| None::<String>);
    let mut submitting = use_signal(|| false);

    let panel: Option<DatasetOcrPanel> = panel_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned();
    let load_failed = panel_res.read().as_ref().is_some_and(|r| r.is_err());

    // Seed the form from the server's values once per dataset, and re-seed when the
    // router reuses this component for another one. Writing signals during render is what
    // `use_effect` is for; the guard is the dataset id rather than a bool so a navigation
    // between two datasets does not leave the first one's languages in the boxes.
    //
    // The hook runs on every render and the resource is read *inside* it, both so the
    // effect re-runs when the fetch resolves and because a `use_effect` that only exists
    // once a resource has resolved shifts every hook index after it on the render that
    // adds it, which traps the WebAssembly runtime and leaves the page painted but dead.
    use_effect(move || {
        let loaded = panel_res
            .read()
            .as_ref()
            .and_then(|r| r.as_ref().ok())
            .cloned();
        if let Some(loaded) = loaded {
            if *seeded_for.peek() != loaded.collection_dataset {
                tesseract.set(split_languages(&loaded.tesseract_languages));
                easyocr_raw.set(loaded.easyocr_languages);
                seeded_for.set(loaded.collection_dataset);
            }
        }
    });

    let Some(panel) = panel else {
        return rsx! {
            div { style: MODULE,
                h2 { style: MODULE_CAPTION, "OCR languages" }
                div { style: MODULE_BODY,
                    if load_failed {
                        ErrorBar { message: "Failed to load the OCR settings for this dataset" }
                    } else {
                        "Loading\u{2026}"
                    }
                }
            }
        };
    };

    let operation_running = panel.operation.as_ref().is_some_and(|o| o.is_running());
    let current_tesseract = split_languages(&panel.tesseract_languages);
    let selected_tesseract = tesseract.read().clone();
    let dirty = selected_tesseract != current_tesseract
        || *easyocr_raw.read() != panel.easyocr_languages;
    let can_apply = dirty && !operation_running && !*submitting.read() && !selected_tesseract.is_empty();

    let apply_style = if can_apply { "" } else { "opacity: 0.5; cursor: not-allowed;" };
    let dataset_for_apply = panel.collection_dataset.clone();
    let dataset_for_strip = panel.collection_dataset.clone();

    rsx! {
        DatasetOperationStrip {
            collection_dataset: dataset_for_strip,
            on_change: move |_| panel_res.restart(),
        }
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "OCR languages" }
            div { style: "{MODULE_BODY} display: flex; flex-direction: column; gap: 16px;",
                if let Some(m) = msg.read().clone() { SuccessBar { message: m } }
                if let Some(e) = error_msg.read().clone() { ErrorBar { message: e } }

                p { style: "{HELP_TEXT} margin: 0;",
                    "Each EasyOCR script group adds one OCR pass over the dataset. Tesseract reads all its languages in one pass."
                }

                div {
                    h3 { style: SUBHEADING,
                        "Tesseract"
                    }
                    if panel.tesseract_available.is_empty() {
                        p { style: "{HELP_TEXT} margin: 0;",
                            "The Tesseract service did not answer, so the installed languages are unknown. "
                            "The list comes from the running image, not from configuration \u{2014} without it this form would be offering languages that fail per file."
                        }
                    } else {
                        LanguageChecklist {
                            available: panel.tesseract_available.clone(),
                            selected: tesseract,
                            disabled: operation_running,
                        }
                        p { style: "{HELP_TEXT} margin: 6px 0 0;",
                            "The first language is the primary one. Selected: "
                            strong { "{selected_tesseract.join(\"+\")}" }
                        }
                    }
                }

                div {
                    h3 { style: SUBHEADING,
                        "EasyOCR"
                    }
                    if panel.easyocr_configured {
                        input {
                            style: "{INPUT} width: 260px;",
                            value: "{easyocr_raw}",
                            disabled: operation_running,
                            oninput: move |e| easyocr_raw.set(e.value()),
                        }
                    } else {
                        input { style: "{INPUT} width: 260px;", value: "{panel.easyocr_languages}", disabled: true }
                        p { style: "{HELP_TEXT} margin: 6px 0 0;",
                            "EasyOCR is off on this deployment, so this setting has no effect."
                        }
                    }
                }

                if !panel.text_variants.is_empty() {
                    div {
                        h3 { style: SUBHEADING,
                            "Stored text variants"
                        }
                        div { style: "display: flex; flex-wrap: wrap; gap: 6px;",
                            for variant in panel.text_variants.iter() {
                                span {
                                    key: "{variant.extracted_by}",
                                    style: "background: var(--x-surface-muted); border: 1px solid var(--x-border); border-radius: 999px; \
                                            padding: 2px 10px; font-size: var(--x-text-xs);",
                                    "{common::document_sources::text_source_label(&variant.extracted_by)} \u{b7} {variant.page_count} pages"
                                }
                            }
                        }
                        p { style: "{HELP_TEXT} margin: 6px 0 0;",
                            "Removing a language deletes its text, its search rows and its searchable PDF."
                        }
                    }
                }

                if panel.ocr_pdf_configured && !panel.pdf_variants.is_empty() {
                    div {
                        h3 { style: SUBHEADING,
                            "Searchable PDFs"
                        }
                        div { style: "display: flex; flex-wrap: wrap; gap: 6px;",
                            for variant in panel.pdf_variants.iter() {
                                span {
                                    key: "{variant.engine}-{variant.languages}",
                                    style: "background: var(--x-surface-muted); border: 1px solid var(--x-border); border-radius: 999px; \
                                            padding: 2px 10px; font-size: var(--x-text-xs);",
                                    "{variant.engine} \u{b7} {variant.languages} \u{b7} {variant.pdf_count} files \u{b7} {variant.total_bytes / 1024 / 1024} MB"
                                }
                            }
                        }
                    }
                } else if !panel.ocr_pdf_configured {
                    p { style: "{HELP_TEXT} margin: 0;",
                        "Searchable PDFs are off on this deployment."
                    }
                }

                div {
                    if operation_running {
                        p { style: "{HELP_TEXT} margin: 0 0 6px;",
                            "The form unlocks when the operation above finishes."
                        }
                    }
                    button {
                        style: "{BTN} {apply_style}",
                        disabled: !can_apply,
                        onclick: {
                            let dataset = dataset_for_apply.clone();
                            move |_| {
                                let dataset = dataset.clone();
                                let tess = tesseract.read().join("+");
                                let easy = easyocr_raw.read().clone();
                                submitting.set(true);
                                spawn(async move {
                                    msg.set(None);
                                    error_msg.set(None);
                                    match admin_apply_ocr_languages(dataset, tess, easy).await {
                                        Ok(job_id) => {
                                            msg.set(Some(format!("Apply job started: {job_id}")));
                                            panel_res.restart();
                                        }
                                        Err(e) => error_msg.set(Some(e.to_string())),
                                    }
                                    submitting.set(false);
                                });
                            }
                        },
                        if *submitting.read() { "Starting\u{2026}" } else { "Apply" }
                    }
                    if !dirty && !operation_running {
                        span { style: "{HELP_TEXT} margin-left: 10px;", "No changes to apply." }
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ingest_without_stage_uses_operation_state_and_plan_counts() {
        let mut operation = DatasetOperationStatus {
            op_id: "op".into(), kind: "add_dataset".into(), state: "running".into(),
            detail: "{}".into(), error: String::new(), started_at: String::new(),
            finished_at: String::new(), stale_seconds: 0, progress_done: 3, progress_total: 10,
        };
        assert_eq!(describe(&operation), "running · 3 of 10 plans");
        operation.detail = r#"{"stage":"parsing"}"#.into();
        assert_eq!(describe(&operation), "parsing");
    }
}
