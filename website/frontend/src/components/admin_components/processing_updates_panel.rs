//! The Processing updates module of the dataset page and the collection page.
//!
//! It shows the stored calculation of each update step, lets the administrator select
//! steps, and starts an update with the selection and the fingerprints that the page
//! showed. The pipeline refuses a request whose fingerprints changed and runs nothing,
//! and the module then shows the error and the new counts. An empty selection disables
//! the button, and the server refuses it too.
//!
//! The module reads stored rows every few seconds. Check again asks the pipeline to
//! calculate the scope now.

use dioxus::prelude::*;

use common::processing_updates::{selection_summary, ProcessingUpdatesView, UpdateStepState, UpdateStepView};
use common::uploads::format_count;
use common::storage_tree::format_size;

use crate::api::admin_api::{
    admin_get_collection_updates, admin_get_processing_updates, admin_request_update_check,
    admin_start_collection_update, admin_start_processing_update,
};
use crate::api::error_util::user_facing_message;
use crate::components::admin_components::{
    action_state, ErrorBar, SuccessBar, BTN, BTN_PRIMARY, HELP_TEXT, MODULE, MODULE_BODY, MODULE_CAPTION, TABLE, TD, TH,
};
use crate::routes::Route;
use crate::tr;
use crate::i18n::SharedText;

/// How often the module reads the stored state.
const POLL_SECONDS: u64 = 5;

async fn load(scope_kind: String, scope_id: String) -> Result<(ProcessingUpdatesView, Vec<(String, String)>), ServerFnError> {
    if scope_kind == "collection" {
        admin_get_collection_updates(scope_id).await
    } else {
        admin_get_processing_updates(scope_id).await.map(|view| (view, Vec::new()))
    }
}

#[component]
pub fn ProcessingUpdatesPanel(
    /// `dataset` or `collection`.
    scope_kind: String,
    /// A `ReadSignal`, so the module follows the router when it reuses the page.
    scope_id: ReadSignal<String>,
) -> Element {
    let mut tick = use_signal(|| 0_u64);
    use_future(move || async move {
        loop {
            n0_future::time::sleep(std::time::Duration::from_secs(POLL_SECONDS)).await;
            let next = *tick.peek() + 1;
            tick.set(next);
        }
    });
    let scope_key = (scope_kind.clone(), scope_id());
    let mut scope_generation = use_signal(|| 0u64);
    let mut action_generation = use_signal(|| 0u64);
    let mut submission_token = use_signal(|| 0u64);
    let request_scope = (scope_key.0.clone(), scope_key.1.clone(), scope_generation());
    let tick_value = tick();
    let view_res = use_resource(use_reactive!(|request_scope, tick_value| async move {
        let result = load(request_scope.0.clone(), request_scope.1.clone()).await;
        (request_scope, result)
    }));
    let mut selected = use_signal(Vec::<String>::new);
    let mut seeded_key = use_signal(String::new);
    let mut msg = use_signal(|| None::<String>);
    let mut error_msg = use_signal(|| None::<String>);
    let mut submitting = use_signal(|| false);
    let mut active_scope = use_signal(|| scope_key.clone());
    let seed_scope = scope_key.clone();

    // Select the waiting steps once for each set of fingerprints, so a poll does not undo
    // what the administrator chose. The hook runs on every render, see the OCR panel.
    use_effect(use_reactive!(|seed_scope| {
        if *active_scope.peek() != seed_scope {
            active_scope.set(seed_scope.clone());
            scope_generation += 1;
            action_generation += 1;
            submission_token.set(0);
            selected.set(Vec::new());
            seeded_key.set(String::new());
            msg.set(None);
            error_msg.set(None);
            submitting.set(false);
        }
        let generation = scope_generation();
        let loaded = view_res.read().as_ref().filter(|(key, _)| key == &(seed_scope.0.clone(), seed_scope.1.clone(), generation))
            .and_then(|(_, result)| result.as_ref().ok()).cloned();
        if let Some((view, _)) = loaded {
            let key = format!(
                "{}|{}",
                view.scope_id,
                view.steps.iter().map(|s| s.fingerprint.as_str()).collect::<Vec<_>>().join(",")
            );
            if *seeded_key.peek() != key {
                selected.set(
                    view.steps
                        .iter()
                        .filter(|s| s.state.selected_by_default())
                        .map(|s| s.step_id.clone())
                        .collect(),
                );
                seeded_key.set(key);
            }
        }
    }));

    let title = if scope_kind == "collection" { tr!("processing-updates-panel-collection-updates") } else { tr!("processing-updates-panel-processing-updates") };
    let loaded = view_res.read().as_ref().filter(|(key, _)| key == &request_scope)
        .map(|(_, result)| result.as_ref().cloned().map_err(user_facing_message));
    let (view, datasets) = match loaded {
        None => {
            return rsx! {
                div { class: "x-admin-module x-processing-updates", "data-update-scope": "{scope_key.1}", "data-update-generation": "{request_scope.2}", style: MODULE,
                    h2 { style: MODULE_CAPTION, "{title}" }
                    div { style: MODULE_BODY, {tr!("processing-updates-panel-loading-u")} }
                }
            };
        }
        Some(Err(e)) => {
            return rsx! {
                div { class: "x-admin-module x-processing-updates", "data-update-scope": "{scope_key.1}", "data-update-generation": "{request_scope.2}", style: MODULE,
                    h2 { style: MODULE_CAPTION, "{title}" }
                    div { style: MODULE_BODY, ErrorBar { message: tr!("processing-updates-panel-the-processing-updates-could-not", e: e.to_string()) } }
                }
            };
        }
        Some(Ok(pair)) => pair,
    };

    let chosen = selected.read().clone();
    let summary = selection_summary(&view.steps, &chosen).shared();
    let running = !view.running_op_id.is_empty();
    let can_start = !chosen.is_empty() && !running && !*submitting.read();
    let start_style = action_state(can_start);
    let status = view.status_line().shared();
    let unique_unit = count_unit(view.unique_files, "files");
    let runs_word = tr!("processing-updates-step-runs", count: view.executions);
    let scope_for_check = view.scope_id.clone();
    let scope_for_start = view.scope_id.clone();
    let kind_for_start = scope_kind.clone();
    let steps_for_start = view.steps.clone();

    rsx! {
        div { class: "x-admin-module x-processing-updates", "data-update-scope": "{scope_key.1}", "data-update-generation": "{request_scope.2}", style: MODULE,
            h2 { style: MODULE_CAPTION, "{title}" }
            div { style: "{MODULE_BODY} display: flex; flex-direction: column; gap: 10px;",
                if let Some(m) = msg.read().clone() { SuccessBar { message: m } }
                if let Some(e) = error_msg.read().clone() { ErrorBar { message: e } }
                div { style: "display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap;",
                    strong { class: "x-updates-status", "{status}" }
                    if running {
                        Link { to: Route::AdminOperationDetailPage { op_id: view.running_op_id.clone(), plans_page: 0, events_page: 0 }, {tr!("processing-updates-panel-open-the-operation")} }
                    }
                }
                p { class: "x-updates-checked", style: "{HELP_TEXT} margin: 0;",
                    if view.checked_at.is_empty() {
                        {tr!("processing-updates-panel-the-pipeline-has-not-calculated")}
                    } else {
                        {tr!("processing-updates-panel-calculated-at-in-ms", view_checked_at: view.checked_at.to_string(), view_check_ms: view.check_ms.to_string())}
                        {tr!("processing-updates-panel-the-waiting-steps-change-each", view_unique_files: view.unique_files, unique_unit: unique_unit, format_size_view_unique_bytes: format_size(view.unique_bytes), view_executions: view.executions.to_string(), runs_word: runs_word)}
                    }
                }
                if !view.automatic {
                    p { style: "{HELP_TEXT} margin: 0;", {tr!("processing-updates-panel-automatic-updates-are-off-on")} }
                }
                if !view.prerequisites_waiting.is_empty() {
                    p { style: "margin: 0; color: var(--x-warning);",
                        {tr!("admin-processing-updates-panel-prerequisites-waiting", steps: view.prerequisites_waiting.join(", "))}
                    }
                }
                table { style: TABLE,
                    thead {
                        tr {
                            th { style: TH, "" }
                            th { style: TH, {tr!("processing-updates-panel-step")} }
                            th { style: "{TH} text-align: right;", {tr!("processing-updates-panel-count")} }
                            th { style: TH, {tr!("processing-updates-panel-state")} }
                            th { style: TH, {tr!("processing-updates-panel-last-run")} }
                        }
                    }
                    tbody {
                        for step in view.steps.iter().cloned() {
                            {
                                let id_for_check = step.step_id.clone();
                                let is_on = chosen.contains(&step.step_id);
                                let unit = count_unit(step.pending, &step.unit);
                                let texts = step_texts(&step);
                                let state_label = if step.state == UpdateStepState::UpToDate { {tr!("processing-updates-panel-up-to-date-select-it")} } else { step.state.label().shared() };
                                let state_colour = match step.state {
                                    UpdateStepState::Failed => "var(--x-danger)",
                                    UpdateStepState::Waiting | UpdateStepState::Running => "var(--x-link)",
                                    _ => "var(--x-ink)",
                                };
                                rsx! {
                                    tr { key: "{step.step_id}", class: "x-update-step",
                                        td { style: TD,
                                            input {
                                                r#type: "checkbox",
                                                checked: is_on,
                                                disabled: running,
                                                onchange: move |e: Event<FormData>| {
                                                    let mut current = selected.write();
                                                    current.retain(|s| *s != id_for_check);
                                                    if e.checked() {
                                                        current.push(id_for_check.clone());
                                                    }
                                                },
                                            }
                                        }
                                        td { style: TD,
                                            div { style: "font-weight: 500;", "{texts.title}" }
                                            div { style: HELP_TEXT, "{texts.explanation}" }
                                            div { style: HELP_TEXT, {tr!("processing-updates-panel-runs", step_runs: texts.runs)} }
                                        }
                                        td { style: "{TD} text-align: right; white-space: nowrap;",
                                            if step.state == UpdateStepState::UpToDate {
                                                // An applied step has no automatic work. Its
                                                // count is the estimate of a manual run.
                                                span { title: tr!("processing-updates-panel-a-run-again-would-select", step_unit: step.unit.to_string()), {tr!("processing-updates-panel-on-a-run-again", step_pending: step.pending.to_string(), unit: unit.to_string())} }
                                            } else {
                                                "{step.pending} {unit}"
                                            }
                                            if step.pending_bytes > 0 {
                                                div { style: HELP_TEXT, "{format_size(step.pending_bytes)}" }
                                            }
                                        }
                                        td { style: "{TD} color: {state_colour};",
                                            "{state_label}"
                                            if !step.last_error.is_empty() && matches!(step.state, UpdateStepState::Failed) {
                                                div { style: "{HELP_TEXT} white-space: pre-wrap;", "{step.last_error}" }
                                            }
                                        }
                                        td { style: "{TD} white-space: nowrap;",
                                            if step.last_op_id.is_empty() {
                                                {tr!("processing-updates-panel-never")}
                                            } else {
                                                Link { to: Route::AdminOperationDetailPage { op_id: step.last_op_id.clone(), plans_page: 0, events_page: 0 }, "{step.last_run_at}" }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                p { class: "x-updates-summary", style: "margin: 0;", "{summary}" }
                div { style: "display: flex; gap: 8px; flex-wrap: wrap;",
                    button {
                        class: "x-update-processing",
                        style: "{BTN_PRIMARY} {start_style}",
                        disabled: !can_start,
                        onclick: move |_| {
                            let scope = scope_for_start.clone();
                            let action_scope = active_scope.peek().clone();
                            let scope_epoch = *scope_generation.peek();
                            let action_token = *action_generation.peek() + 1;
                            action_generation.set(action_token);
                            let kind = kind_for_start.clone();
                            let chosen = selected.read().clone();
                            let fingerprints: Vec<String> = chosen
                                .iter()
                                .map(|id| steps_for_start.iter().find(|s| &s.step_id == id).map(|s| s.fingerprint.clone()).unwrap_or_default())
                                .collect();
                            submission_token.set(action_token);
                            submitting.set(true);
                            msg.set(None);
                            error_msg.set(None);
                            spawn(async move {
                                let started = if kind == "collection" {
                                    admin_start_collection_update(scope, chosen, fingerprints).await
                                } else {
                                    admin_start_processing_update(scope, chosen, fingerprints).await
                                };
                                if *active_scope.peek() != action_scope || *scope_generation.peek() != scope_epoch { return; }
                                // A newer Check again owns messages. This submission still owns its busy flag.
                                if *submission_token.peek() == action_token { submitting.set(false); }
                                if *action_generation.peek() != action_token { return; }
                                match started {
                                    Ok(op_id) => msg.set(Some(tr!("processing-updates-panel-update-started", op_id: op_id.to_string()))),
                                    Err(e) => error_msg.set(Some(user_facing_message(&e))),
                                }
                            });
                        },
                        if scope_kind == "collection" { {tr!("processing-updates-panel-update-collection")} } else { {tr!("processing-updates-panel-update-processing")} }
                    }
                    button {
                        class: "x-update-check",
                        style: BTN,
                        onclick: move |_| {
                            let scope = scope_for_check.clone();
                            let action_scope = active_scope.peek().clone();
                            let scope_epoch = *scope_generation.peek();
                            let action_token = *action_generation.peek() + 1;
                            action_generation.set(action_token);
                            msg.set(None);
                            error_msg.set(None);
                            spawn(async move {
                                let result = admin_request_update_check(scope).await;
                                if *active_scope.peek() != action_scope || *scope_generation.peek() != scope_epoch || *action_generation.peek() != action_token { return; }
                                match result {
                                    Ok(()) => msg.set(Some(tr!("processing-updates-check-requested"))),
                                    Err(e) => error_msg.set(Some(user_facing_message(&e))),
                                }
                            });
                        },
                        {tr!("processing-updates-panel-check-again")}
                    }
                }
                if !datasets.is_empty() {
                    table { style: TABLE,
                        thead { tr { th { style: TH, {tr!("processing-updates-panel-dataset")} } th { style: TH, {tr!("processing-updates-panel-processing-updates")} } } }
                        tbody {
                            for (dataset, line) in datasets.iter().cloned() {
                                tr { key: "{dataset}",
                                    td { style: TD,
                                        Link {
                                            to: Route::AdminDatasetPage { collection_id: view.collectionname.clone(), dataset_id: dataset.clone() },
                                            "{dataset}"
                                        }
                                    }
                                    td { style: TD, "{line}" }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

/// The unit word of a count in the interface language: `files`, `folders` or `tables`.
fn count_unit(count: u64, unit: &str) -> String {
    tr!("processing-updates-unit", unit: unit.to_string(), count: count)
}

/// The steps of the pipeline registry (`P_admin/updates/registry.py`) that the catalog
/// translates. Another step shows the English texts that the pipeline stored.
const TRANSLATED_STEPS: [&str; 16] = [
    "search_schema", "unfinished", "failed_files", "virus_scan", "tables", "ocr", "ocr_detection", "pdf_text",
    "vectors", "folder_counts", "archive_members", "image_previews", "search_terms", "entities", "page_text",
    "text_rows",
];

/// The title, the explanation and the runs of one step, in the interface language.
struct StepTexts {
    title: String,
    explanation: String,
    runs: String,
}

fn step_texts(step: &UpdateStepView) -> StepTexts {
    if !TRANSLATED_STEPS.contains(&step.step_id.as_str()) {
        return StepTexts { title: step.title.clone(), explanation: step.explanation.clone(), runs: step.runs.clone() };
    }
    // i18n: data, the catalog id of a registry step
    let id = |part: &str| format!("processing-update-{}-{part}", step.step_id);
    StepTexts {
        title: tr!(&id("title")),
        explanation: tr!(&id("explanation"), files: step.pending, count: format_count(step.pending)),
        runs: tr!(&id("runs")),
    }
}
