//! The dataset OCR language form and the job status strip that keeps it unlockable.
//!
//! These two are one file because they are one mechanism. The form disables itself while
//! an apply job runs; the strip is what makes that job visible. A form that hides its own
//! lock is a form that locks forever — so the strip polls, reports staleness, and shows
//! the error when a job fails.
//!
//! Neither of them is the actual guard. `admin_apply_ocr_languages` refuses a second
//! dispatch server-side by reading the same `dataset_jobs` row, because two admins in two
//! browsers are not stopped by a disabled button.

use dioxus::prelude::*;

use common::admin_types::{DatasetJobStatus, DatasetOcrPanel};

use crate::api::admin_api::{admin_apply_ocr_languages, admin_get_dataset_job, admin_get_dataset_ocr};
use crate::components::admin_components::{
    ErrorBar, SuccessBar, BTN, C_HEADER, HELP_TEXT, INPUT, MODULE, MODULE_BODY, MODULE_CAPTION,
};

/// How often the strip re-reads the job row while one is running. Fast enough that Apply
/// feels answered, slow enough that an admin leaving the page open is not a load source.
const POLL_SECONDS: u64 = 3;

/// Past this, a `running` job that has not advanced is called out as possibly stuck.
/// Matches `JOB_STALE_SECONDS` in the backend, which is what actually refuses a second
/// dispatch — the number is repeated rather than shared because one is a warning and the
/// other is a decision, and they are allowed to diverge later.
const STALE_SECONDS: u64 = 900;

/// `{"stage": "...", "added": [...], "removed": [...]}` as one readable line.
///
/// Falls back to the raw string: a detail blob this cannot parse is still the only thing
/// the admin has to go on, and hiding it would leave the strip saying "running" and
/// nothing else.
fn describe(detail: &str) -> String {
    let Ok(value) = serde_json::from_str::<serde_json::Value>(detail) else {
        return detail.to_string();
    };
    let stage = value
        .get("stage")
        .and_then(|v| v.as_str())
        .unwrap_or("working");
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
    let mut parts = vec![stage.to_string()];
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

/// Polled `dataset_jobs` strip. Renders nothing when the dataset has never had a job.
///
/// `on_change` fires when the state transitions, so the page holding the form can refetch
/// once the job finishes rather than leaving stale variant counts on screen.
#[component]
pub fn DatasetJobStrip(
    /// A `ReadSignal`, not a `String`, for the reason spelled out at length in
    /// `ai_chat/session_page.rs`: the router **reuses** these components when it navigates
    /// between two datasets. A handler that closes over a `String` cloned on first render
    /// keeps polling the dataset the admin has left, and writes its answers into the
    /// signals now rendering the new one.
    collection_dataset: ReadSignal<String>,
    #[props(default = None)] on_change: Option<EventHandler<DatasetJobStatus>>,
) -> Element {
    let mut job = use_signal(|| None::<DatasetJobStatus>);
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
                if let Ok(current) = admin_get_dataset_job(dataset.clone()).await {
                    if *poll_gen.peek() != generation {
                        return;
                    }
                    let state = current
                        .as_ref()
                        .map(|j| format!("{}:{}", j.job_id, j.state))
                        .unwrap_or_default();
                    if state != *last_state.peek() {
                        last_state.set(state);
                        if let (Some(handler), Some(value)) = (&on_change, &current) {
                            handler.call(value.clone());
                        }
                    }
                    job.set(current);
                }
                // Keep polling after a job ends: the next Apply on this page has to be
                // picked up too, and the alternative is a strip that goes silent exactly
                // when the admin presses the button.
                n0_future::time::sleep(std::time::Duration::from_secs(POLL_SECONDS)).await;
            }
        });
    });

    let Some(current) = job.read().clone() else {
        return rsx! {};
    };

    let stale = current.is_running() && current.stale_seconds > STALE_SECONDS;
    let (background, border, ink) = match current.state.as_str() {
        "failed" => ("#fdecea", "#f5c6cb", "#a94442"),
        "running" if stale => ("#fff4e5", "#ffd8a8", "#8a5a00"),
        "running" => ("#e8f4fa", "#bcdff1", "#31708f"),
        _ => ("#eaf6ea", "#c3e6cb", "#3c763d"),
    };

    rsx! {
        div {
            style: "background: {background}; border: 1px solid {border}; color: {ink}; \
                    border-radius: 4px; padding: 10px 12px; margin-bottom: 16px; font-size: 13px;",
            div { style: "font-weight: 600;",
                "{current.kind} \u{2014} {current.state}"
                if current.is_running() {
                    span { style: "font-weight: 400;", " \u{b7} started {current.started_at}" }
                }
            }
            if !current.detail.is_empty() {
                div { style: "margin-top: 3px;", "{describe(&current.detail)}" }
            }
            if stale {
                div { style: "margin-top: 3px; font-weight: 600;",
                    "No progress for {current.stale_seconds / 60} minutes. The job may be stuck \u{2014} check the Temporal workflow before assuming it will finish."
                }
            }
            if !current.error.is_empty() {
                div {
                    style: "margin-top: 6px; font-family: ui-monospace, monospace; font-size: 12px; \
                            white-space: pre-wrap; word-break: break-word;",
                    "{current.error}"
                }
            }
            if !current.is_running() && !current.finished_at.is_empty() {
                div { style: "margin-top: 3px; opacity: 0.8;", "finished {current.finished_at}" }
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
    let ink = if disabled { "#999" } else { "#333" };
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
                            style: "display: flex; align-items: center; gap: 5px; font-size: 13px; \
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
    if let Some(ref loaded) = panel {
        let id = loaded.collection_dataset.clone();
        let tess = loaded.tesseract_languages.clone();
        let easy = loaded.easyocr_languages.clone();
        use_effect(move || {
            if *seeded_for.peek() != id {
                tesseract.set(split_languages(&tess));
                easyocr_raw.set(easy.clone());
                seeded_for.set(id.clone());
            }
        });
    }

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

    let job_running = panel.job.as_ref().is_some_and(|j| j.is_running());
    let current_tesseract = split_languages(&panel.tesseract_languages);
    let selected_tesseract = tesseract.read().clone();
    let dirty = selected_tesseract != current_tesseract
        || *easyocr_raw.read() != panel.easyocr_languages;
    let can_apply = dirty && !job_running && !*submitting.read() && !selected_tesseract.is_empty();

    let apply_style = if can_apply { "" } else { "opacity: 0.5; cursor: not-allowed;" };
    let dataset_for_apply = panel.collection_dataset.clone();
    let dataset_for_strip = panel.collection_dataset.clone();

    rsx! {
        DatasetJobStrip {
            collection_dataset: dataset_for_strip,
            on_change: move |_| panel_res.restart(),
        }
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "OCR languages" }
            div { style: "{MODULE_BODY} display: flex; flex-direction: column; gap: 16px;",
                if let Some(m) = msg.read().clone() { SuccessBar { message: m } }
                if let Some(e) = error_msg.read().clone() { ErrorBar { message: e } }

                p { style: "{HELP_TEXT} margin: 0;",
                    "Each language set is a separate stored variant of every document's text. "
                    "A "
                    strong { "Tesseract" }
                    " language is nearly free: it takes eng+ron in a single pass and picks per region, so the whole set is one pass and one variant. "
                    "An "
                    strong { "EasyOCR" }
                    " language in a new script is not: EasyOCR cannot mix scripts, so each script group is a full extra pass over the dataset plus a complete set of entity, chunk, embedding and index rows for it."
                }

                div {
                    div { style: "font-size: 12px; font-weight: 600; color: {C_HEADER}; margin-bottom: 6px;",
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
                            disabled: job_running,
                        }
                        p { style: "{HELP_TEXT} margin: 6px 0 0;",
                            "Order matters: the first language is the primary one, so eng+ron and ron+eng are different variants. "
                            "Selected: "
                            strong { "{selected_tesseract.join(\"+\")}" }
                        }
                    }
                }

                div {
                    div { style: "font-size: 12px; font-weight: 600; color: {C_HEADER}; margin-bottom: 6px;",
                        "EasyOCR"
                    }
                    if panel.easyocr_configured {
                        input {
                            style: "{INPUT} width: 260px;",
                            value: "{easyocr_raw}",
                            disabled: job_running,
                            oninput: move |e| easyocr_raw.set(e.value()),
                        }
                    } else {
                        input { style: "{INPUT} width: 260px;", value: "{panel.easyocr_languages}", disabled: true }
                        p { style: "{HELP_TEXT} margin: 6px 0 0;",
                            "The EasyOCR service is not deployed on this stack (easyocr_enabled = false in hoover4.ini), so no EasyOCR variants are produced and this setting has no effect until it is. "
                            "It is shown rather than hidden because the stored value is still what a future deployment would run with."
                        }
                    }
                }

                if !panel.text_variants.is_empty() {
                    div {
                        div { style: "font-size: 12px; font-weight: 600; color: {C_HEADER}; margin-bottom: 6px;",
                            "Stored text variants"
                        }
                        div { style: "display: flex; flex-wrap: wrap; gap: 6px;",
                            for variant in panel.text_variants.iter() {
                                span {
                                    key: "{variant.extracted_by}",
                                    style: "background: #f6f6f6; border: 1px solid #eee; border-radius: 999px; \
                                            padding: 2px 10px; font-size: 12px;",
                                    "{common::document_sources::text_source_label(&variant.extracted_by)} \u{b7} {variant.page_count} pages"
                                }
                            }
                        }
                        p { style: "{HELP_TEXT} margin: 6px 0 0;",
                            "Removing a language deletes its variant here and in the search index, and the derived PDF that goes with it."
                        }
                    }
                }

                if panel.ocr_pdf_configured && !panel.pdf_variants.is_empty() {
                    div {
                        div { style: "font-size: 12px; font-weight: 600; color: {C_HEADER}; margin-bottom: 6px;",
                            "Searchable PDFs"
                        }
                        div { style: "display: flex; flex-wrap: wrap; gap: 6px;",
                            for variant in panel.pdf_variants.iter() {
                                span {
                                    key: "{variant.engine}-{variant.languages}",
                                    style: "background: #f6f6f6; border: 1px solid #eee; border-radius: 999px; \
                                            padding: 2px 10px; font-size: 12px;",
                                    "{variant.engine} \u{b7} {variant.languages} \u{b7} {variant.pdf_count} files \u{b7} {variant.total_bytes / 1024 / 1024} MB"
                                }
                            }
                        }
                    }
                } else if !panel.ocr_pdf_configured {
                    p { style: "{HELP_TEXT} margin: 0;",
                        "Searchable PDFs are turned off for this deployment (ocr_pdf_enabled = false), so no OCR'd PDF source is produced for scanned documents."
                    }
                }

                div {
                    if job_running {
                        p { style: "{HELP_TEXT} margin: 0 0 6px;",
                            "We're working on it. The form unlocks when the job above finishes, and you can change the languages again then."
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
                    if !dirty && !job_running {
                        span { style: "{HELP_TEXT} margin-left: 10px;", "No changes to apply." }
                    }
                }
            }
        }
    }
}
