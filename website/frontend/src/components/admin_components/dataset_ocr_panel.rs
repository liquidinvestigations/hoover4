//! Read-only automatic OCR coverage and the dataset operation strip.
//!
//! The strip polls the newest operation of the dataset, reports staleness, and shows the
//! error when an operation fails.
//!
use dioxus::prelude::*;

use common::admin_types::{DatasetOcrPanel, DatasetOperationStatus};

use crate::api::admin_api::{
    admin_get_dataset_ocr, admin_get_dataset_operation,
};
use crate::components::admin_components::{
    ErrorBar, BTN, HELP_TEXT, SUBHEADING, MODULE, MODULE_BODY, MODULE_CAPTION,
};
use crate::tr;
use crate::i18n::SharedText;

/// How often the strip re-reads the operation row while one is running. Fast enough that
/// status changes remain visible without frequent requests from an idle page.
/// An open page is not a load
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
        parts.push(tr!("dataset-ocr-panel-of-plans", operation_progress_done: operation.progress_done.to_string(), operation_progress_total: operation.progress_total.to_string()));
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
        parts.push(tr!("dataset-ocr-panel-adding", added: added.to_string()));
    }
    if !removed.is_empty() {
        parts.push(tr!("dataset-ocr-panel-removing", removed: removed.to_string()));
    }
    if let Some(plans) = value.get("plans").and_then(|v| v.as_u64()) {
        if plans > 0 {
            parts.push(tr!("dataset-ocr-panel-plan-s-reopened", plans: plans.to_string()));
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
                {tr!("dataset-ocr-panel-last-operation", current_kind: current.kind.to_string(), current_state: current.state.to_string())}
                if current.is_running() {
                    span { style: "font-weight: 400;", {tr!("dataset-ocr-panel-started", current_started_at: current.started_at.to_string())} }
                } else if !current.finished_at.is_empty() {
                    span { style: "font-weight: 400;", ", {current.finished_at}" }
                }
            }
            if current.is_running() && (!current.detail.is_empty() || matches!(current.kind.as_str(), "add_dataset" | "rescan_dataset")) {
                div { style: "margin-top: 3px;", "{describe(&current)}" }
            }
            if stale {
                div { style: "margin-top: 3px; font-weight: 500;",
                    {tr!("dataset-ocr-panel-no-progress-for-minutes-check", current_stale_seconds_60: (current.stale_seconds / 60).to_string())}
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

/// Read current automatic OCR coverage without exposing legacy settings.
#[component]
pub fn DatasetOcrSettingsPanel(collection_dataset: ReadSignal<String>) -> Element {
    let dataset = collection_dataset();
    let mut attempt = use_signal(|| 0u64);
    let mut active_dataset = use_signal(|| dataset.clone());
    let mut scope_generation = use_signal(|| 0u64);
    use_effect(use_reactive!(|dataset| {
        if *active_dataset.peek() != dataset {
            active_dataset.set(dataset);
            scope_generation += 1;
        }
    }));
    let refresh = attempt();
    let generation = scope_generation();
    let mut panel_res = use_resource(use_reactive!(|dataset, generation, refresh| async move {
        let result = admin_get_dataset_ocr(dataset.clone()).await;
        (dataset, generation, refresh, result)
    }));
    let reply = panel_res.read().clone().filter(|(id, epoch, revision, _)|
        id == &dataset && *epoch == generation && *revision == refresh);
    rsx! {
        DatasetOperationStrip {
            collection_dataset,
            on_change: move |_| { attempt += 1; },
        }
        div { class: "x-admin-module x-automatic-ocr", "data-dataset": "{dataset}", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("automatic-ocr-title")} }
            div { style: MODULE_BODY,
                p { style: HELP_TEXT, {tr!("automatic-ocr-policy")} }
                match reply {
                    None => rsx! { p { {tr!("dataset-ocr-panel-loading-u")} } },
                    Some((_, _, _, Err(error))) => rsx! { ErrorBar { message: crate::api::error_util::user_facing_message(&error) } },
                    Some((_, _, _, Ok(panel))) => rsx! { AutomaticOcrCoverage { panel } },
                }
                button { style: BTN, onclick: move |_| { panel_res.clear(); attempt += 1; },
                    {tr!("automatic-ocr-refresh")}
                }
            }
        }
    }
}

/// Translate planner reasons while retaining arbitrary stored failure text.
fn coverage_reason(reason: &str) -> String {
    match reason {
        "detected_no_text" => tr!("automatic-ocr-state", state: "no_text"),
        "unknown_script" | "tesseract_capabilities_unavailable" | "detected_language" |
        "unknown_language_script_coverage" | "language_script_mismatch_script_coverage" |
        "language_model_unavailable_script_coverage" | "easyocr_capabilities_unavailable" |
        "tesseract_script_unavailable" | "script_coverage_unavailable" =>
            tr!("automatic-ocr-reason-label", reason: reason.to_string()),
        _ => reason.to_string(),
    }
}

fn detected_label(code: &str, script: bool) -> String {
    if code.is_empty() || matches!(code, "und" | "Unknown" | "Common" | "NULL") {
        tr!("admin-collections-list-unknown")
    } else if script { crate::i18n::script_facet_label(code) }
    else { crate::i18n::language_facet_label(code) }
}

/// State labels distinguish published output from planned and failed coverage.
fn coverage_state(state: &str) -> String {
    match state {
        "candidate" | "planned" | "failed" | "incomplete" | "unsupported" | "published" | "applied" |
        "ready" | "no_text" => tr!("automatic-ocr-state", state: state.to_string()),
        _ => state.to_string(),
    }
}

#[component]
fn AutomaticOcrCoverage(panel: DatasetOcrPanel) -> Element {
    let status = &panel.automatic_status;
    rsx! {
        div { class: "x-automatic-ocr-status", "data-policy-version": "{status.policy_version}",
            if status.states.is_empty() {
                p { class: "x-automatic-ocr-unknown", {tr!("automatic-ocr-unknown")} }
            } else {
                table { style: "width: 100%; text-align: left; margin: 12px 0;",
                    thead { tr {
                        th { {tr!("processing-updates-panel-state")} }
                        th { {tr!("file-browser-files")} }
                        th { {tr!("automatic-ocr-pages")} }
                        th { {tr!("automatic-ocr-reason")} }
                    } }
                    tbody { for (index, row) in status.states.iter().enumerate() {
                        tr { key: "{index}", "data-ocr-state": "{row.state}",
                            td { "{coverage_state(&row.state)}" }
                            td { "{row.files}" } td { "{row.pages}" }
                            td { title: "{row.reason}", "{coverage_reason(&row.reason)}" }
                        }
                    } }
                }
            }
            if status.states.iter().any(|row| matches!(row.state.as_str(), "failed" | "incomplete" | "unsupported")) {
                p { class: "x-automatic-ocr-retry", {tr!("automatic-ocr-retry")} }
            }
            if !status.page_decisions.is_empty() {
                h3 { style: SUBHEADING, {tr!("automatic-ocr-coverage")} }
                table { style: "width: 100%; text-align: left; margin: 12px 0;",
                    thead { tr {
                        th { {tr!("search-filter-modal-ocr-script")} }
                        th { {tr!("search-filter-modal-ocr-language")} }
                        th { {tr!("processing-updates-panel-state")} }
                        th { {tr!("automatic-ocr-models")} }
                        th { {tr!("automatic-ocr-pages")} }
                        th { {tr!("automatic-ocr-reason")} }
                    } }
                    tbody { for (index, row) in status.page_decisions.iter().enumerate() {
                        tr { key: "{index}", "data-ocr-page-state": "{row.status}",
                            td { title: "{row.script}", "{detected_label(&row.script, true)}" } td { title: "{row.language}", "{detected_label(&row.language, false)}" }
                            td { "{coverage_state(&row.status)}" }
                            td { "{row.engine} {row.languages}" }
                            td { "{row.pages}" } td { title: "{row.reason}", "{coverage_reason(&row.reason)}" }
                        }
                    } }
                }
            }
            if status.page_decisions_truncated || status.capability_digests_truncated {
                p { {tr!("automatic-ocr-truncated")} }
            }
            if !panel.text_variants.is_empty() {
                h3 { style: SUBHEADING, {tr!("dataset-ocr-panel-stored-text-variants")} }
                for (index, variant) in panel.text_variants.iter().enumerate() {
                    p { key: "{index}", {tr!("admin-dataset-ocr-panel-variant-pages", source: common::document_sources::text_source_label(&variant.extracted_by).shared(), pages: variant.page_count)} }
                }
            }
            if !panel.pdf_variants.is_empty() {
                h3 { style: SUBHEADING, {tr!("dataset-ocr-panel-searchable-pdfs")} }
                for (index, variant) in panel.pdf_variants.iter().enumerate() {
                    p { key: "{index}", {tr!("dataset-ocr-panel-u-u-files-u-mb", variant_engine: variant.engine.clone(), variant_languages: variant.languages.clone(), variant_pdf_count: variant.pdf_count, variant_total_bytes_1024_1024: (variant.total_bytes / 1024 / 1024).to_string())} }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn coverage_reasons_preserve_stored_failure_details() {
        assert_eq!(coverage_reason("unknown_script"), "Script not identified");
        assert_eq!(coverage_reason("RemoteError: private model diagnostic"), "RemoteError: private model diagnostic");
        assert_eq!(detected_label("FutureScript", true), "FutureScript");
        assert_eq!(detected_label("und", false), "Unknown");
    }

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
