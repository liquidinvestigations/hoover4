//! `/uploads/:collection/:batch_id?page`, the batch detail. It reads the outcome again
//! every 3 seconds until the batch state is terminal. The owner of an `uploading` batch
//! can continue the upload after a closed tab: the page matches a new selection of the
//! same files, and the driver checks the acknowledged bytes before it resumes.

use std::time::Duration;

use common::search_result::DocumentIdentifier;
use common::upload_pages::{
    batch_state_is_terminal, batch_state_label, match_resume_selection, ResumeFile, SelectedFile,
    UploadBatchDetail, UploadFileRow, UploadFileState,
};
use common::uploads::{format_count, format_upload_size};
use dioxus::prelude::*;
use dioxus_free_icons::icons::md_navigation_icons::{MdArrowBack, MdChevronLeft, MdChevronRight};
use dioxus_free_icons::Icon;

use super::batch_list::{destination_label, started_label};
use super::driver::{use_upload_driver, DriverEvent, DropZone, FailedFile, Progress, ProgressDialog, UploadScripts};
use super::upload_page::{browser_route, show_path, Transfer, H1_STYLE, PAGE_STYLE, SURFACE_STYLE};
use crate::api::error_util::user_facing_message;
use crate::api::uploads_api::{upload_batch_detail, upload_batch_resume_files, upload_page_info};
use crate::components::admin_components::{ErrorBar, BTN, LINK, TABLE, TD, TH};
use crate::routes::Route;

const POLL: Duration = Duration::from_secs(3);
const DIFFERS: &str = "The selected file differs from the uploaded bytes.";

/// The address of the document view of an indexed file.
fn document_route(dataset: &str, hash: &str) -> Route {
    Route::ViewDocumentPage {
        document_identifier: DocumentIdentifier { collection_dataset: dataset.to_string(), file_hash: hash.to_string() }.into(),
        doc_viewer_state: None.into(),
        viewer_right_tab_state: crate::data_definitions::doc_viewer_state::ViewerRightTabState::default().into(),
    }
}

#[component]
pub fn UploadBatchPage(collection: String, batch_id: String, page: u32) -> Element {
    let key = use_memo(use_reactive!(|collection, batch_id, page| (collection, batch_id, page)));
    let mut tick = use_signal(|| 0u64);
    let detail = use_resource(move || {
        let (collection, batch_id, page) = key();
        tick();
        async move { upload_batch_detail(collection, batch_id, page).await }
    });
    // The last answer, so a poll does not blank the page.
    let mut shown = use_signal(|| None::<Result<UploadBatchDetail, ServerFnError>>);
    use_effect(move || {
        if let Some(value) = detail.read().clone() {
            shown.set(Some(value));
        }
    });
    use_future(move || async move {
        loop {
            n0_future::time::sleep(POLL).await;
            let running = match &*shown.peek() {
                Some(Ok(d)) => !batch_state_is_terminal(&d.batch.state),
                Some(Err(_)) => false,
                None => true,
            };
            if running {
                *tick.write() += 1;
            }
        }
    });

    // "Continue upload": the manifest of the batch, the reselection, and the transfer.
    let mut resuming = use_signal(|| false);
    let mut manifest = use_signal(|| None::<Result<Vec<ResumeFile>, String>>);
    let mut unmatched = use_signal(|| 0usize);
    let mut mismatched = use_signal(Vec::<FailedFile>::new);
    let mut transfer = use_signal(|| None::<Transfer>);
    let limits = use_resource(upload_page_info);
    // The driver callback cannot name the driver, so it leaves the resume command here,
    // and the effect below sends it.
    let mut pending_resume = use_signal(|| None::<serde_json::Value>);

    let driver = use_upload_driver(Callback::new(move |event: DriverEvent| match event {
        DriverEvent::Added { files } => {
            if transfer.peek().is_some() {
                return;
            }
            let Some(Ok(batch_files)) = manifest.peek().clone() else { return };
            let found = match_resume_selection(&batch_files, &files);
            unmatched.set(found.unmatched);
            mismatched.set(Vec::new());
            if !found.names_the_batch() {
                return;
            }
            let chunk_bytes = match &*limits.peek() {
                Some(Ok(info)) => info.limits.chunk_bytes,
                _ => common::uploads::UploadLimits::default().chunk_bytes,
            };
            let by_id: std::collections::HashMap<u64, &SelectedFile> = files.iter().map(|f| (f.id, f)).collect();
            let items: Vec<serde_json::Value> = found
                .matched
                .iter()
                .map(|(id, file_no)| serde_json::json!({"id": id, "file_no": file_no, "path": by_id[id].path}))
                .collect();
            let total: u64 = found.matched.iter().map(|(id, _)| by_id[id].size).sum();
            let batch_id = key.peek().1.clone();
            let heading = match &*shown.peek() {
                Some(Ok(d)) => format!(
                    "Uploading {} files to {}",
                    format_count(found.matched.len() as u64),
                    destination_label(&d.batch)
                ),
                _ => String::new(),
            };
            transfer.set(Some(Transfer {
                heading,
                state: Progress { total, count: found.matched.len() as u64, ..Default::default() },
                error: None,
                batch_id: Some(batch_id.clone()),
            }));
            pending_resume.set(Some(serde_json::json!({
                "cmd": "resume",
                "batch_id": batch_id,
                "items": items,
                "chunk_bytes": chunk_bytes,
            })));
        }
        DriverEvent::Checked { mismatched: found, sending } => {
            if sending == 0 && !found.is_empty() {
                transfer.set(None);
            }
            mismatched.set(found);
        }
        DriverEvent::Committed { .. } => {
            transfer.set(None);
            resuming.set(false);
            *tick.write() += 1;
        }
        DriverEvent::CommitFailed { message } => {
            if let Some(t) = transfer.write().as_mut() {
                t.error = Some(message);
            }
        }
        DriverEvent::Refused { .. } | DriverEvent::Begun { .. } => {}
        other => {
            if let (Some(state), Some(t)) = (other.progress(), transfer.write().as_mut()) {
                t.state = state;
            }
        }
    }));
    use_effect(move || {
        if let Some(command) = pending_resume() {
            driver.send(command);
            pending_resume.set(None);
        }
    });

    let value = shown();
    let body = match value {
        None => rsx! { p { "Loading..." } },
        Some(Err(e)) => rsx! { ErrorBar { message: user_facing_message(&e) } },
        Some(Ok(d)) => {
            let b = d.batch.clone();
            let can_continue = d.is_owner && b.state == "uploading";
            let browse = browser_route(&b.upload_dataset, &b.folder);
            let pages = d.page_count;
            let current = d.page;
            let (collection, batch_id, _) = key();
            let (prev_collection, prev_batch) = (collection.clone(), batch_id.clone());
            rsx! {
                dl { class: "x-board-stats x-upload-fields",
                    dt { "State" } dd { class: "x-upload-state", "{batch_state_label(&b.state)}" }
                    dt { "Uploaded by" } dd { "{b.username}, {started_label(b.created_ms)} UTC" }
                    dt { "Folder" } dd { Link { to: browse, style: LINK, "{b.folder}" } }
                    dt { "Files" } dd { "{format_count(b.file_count as u64)}, {format_upload_size(b.byte_count)}" }
                    if let Some(op_id) = d.op_id.clone() {
                        dt { "Operation" }
                        dd { Link { to: Route::AdminOperationDetailPage { op_id: op_id.clone(), plans_page: 0, events_page: 0 }, style: LINK, "{op_id}" } }
                    }
                }
                if !d.error.is_empty() {
                    p { class: "x-upload-batch-error", style: "color: var(--x-danger); margin: 0;", "{d.error}" }
                }
                if can_continue {
                    div {
                        if resuming() {
                            DropZone { driver }
                        } else {
                            button {
                                class: "x-upload-continue-upload",
                                style: BTN,
                                onclick: move |_| {
                                    resuming.set(true);
                                    let (collection, batch_id, _) = key.peek().clone();
                                    spawn(async move {
                                        let files = upload_batch_resume_files(collection, batch_id).await
                                            .map_err(|e| user_facing_message(&e));
                                        manifest.set(Some(files));
                                    });
                                },
                                "Continue upload"
                            }
                        }
                        if let Some(Err(e)) = manifest() {
                            ErrorBar { message: e }
                        }
                        if unmatched() > 0 {
                            p { class: "x-upload-unmatched", style: "color: var(--x-danger);",
                                "{format_count(unmatched() as u64)} selected files do not match this upload."
                            }
                        }
                        for (index, file) in mismatched().iter().enumerate() {
                            p { key: "{index}", class: "x-upload-mismatch", style: "color: var(--x-danger); margin: 2px 0; overflow-wrap: anywhere;",
                                if file.error.is_empty() { "{show_path(&file.path)} {DIFFERS}" } else { "{show_path(&file.path)} {file.error}" }
                            }
                        }
                    }
                }
                div { style: "display: flex; align-items: center; gap: 10px;",
                    progress {
                        class: "x-upload-indexed-bar",
                        style: "flex: 1 1 auto; height: 14px; accent-color: var(--x-link);",
                        max: "{d.counts.files.max(1)}",
                        value: "{d.counts.indexed}",
                    }
                    span { "{format_count(d.counts.indexed)} of {format_count(d.counts.files)} indexed" }
                }
                div { class: "x-upload-counts", style: "display: flex; gap: 18px; flex-wrap: wrap;",
                    span { "Ingested {format_count(d.counts.ingested)}" }
                    span { "Indexed {format_count(d.counts.indexed)}" }
                    span { "With errors {format_count(d.counts.with_errors)}" }
                    span { "Rejected {format_count(d.counts.rejected)}" }
                    span { "Not sent {format_count(d.counts.not_sent)}" }
                }
                table { class: "x-upload-files", style: TABLE,
                    thead {
                        tr {
                            th { style: TH, "Path" }
                            th { style: TH, "Size" }
                            th { style: TH, "State" }
                            th { style: TH, "Error" }
                        }
                    }
                    tbody {
                        for row in d.files.iter() {
                            FileTableLine { key: "{row.file_no}", dataset: b.upload_dataset.clone(), row: row.clone() }
                        }
                    }
                }
                if pages > 1 {
                    div { style: "display: flex; align-items: center; gap: 8px;",
                        button {
                            style: BTN,
                            "aria-label": "Previous page",
                            disabled: current == 0,
                            onclick: move |_| { navigator().replace(Route::UploadBatchPage { collection: prev_collection.clone(), batch_id: prev_batch.clone(), page: current.saturating_sub(1) }); },
                            Icon { icon: MdChevronLeft, width: 16, height: 16 }
                        }
                        span { "{current + 1} of {pages}" }
                        button {
                            style: BTN,
                            "aria-label": "Next page",
                            disabled: current + 1 >= pages,
                            onclick: move |_| { navigator().replace(Route::UploadBatchPage { collection: collection.clone(), batch_id: batch_id.clone(), page: current + 1 }); },
                            Icon { icon: MdChevronRight, width: 16, height: 16 }
                        }
                    }
                }
            }
        }
    };

    let heading = match &*shown.read() {
        Some(Ok(d)) => format!("Upload to {}", destination_label(&d.batch)),
        _ => "Upload".to_string(),
    };
    let list = Route::UploadsPage { collection: key().0 };
    rsx! {
        Title { "Hoover Search - Upload" }
        UploadScripts {}
        div { style: PAGE_STYLE,
            div { style: "max-width: 1100px; margin: 0 auto;",
                div { style: "display: flex; align-items: center; gap: 15px; margin-bottom: 15px;",
                    Link { to: list, style: "{LINK} display: inline-flex; align-items: center; gap: 4px;",
                        Icon { icon: MdArrowBack, width: 16, height: 16 }
                        "Uploads"
                    }
                    h1 { style: "{H1_STYLE} overflow-wrap: anywhere;", "{heading}" }
                }
                div { style: SURFACE_STYLE, {body} }
            }
        }
        if let Some(t) = transfer() {
            ProgressDialog { heading: t.heading, state: t.state, error: t.error, driver }
        }
    }
}

#[component]
fn FileTableLine(dataset: String, row: UploadFileRow) -> Element {
    let first_line = row.error.lines().next().unwrap_or("").to_string();
    let state_style = if row.state == UploadFileState::Errors || row.state == UploadFileState::Rejected {
        "color: var(--x-danger);"
    } else {
        ""
    };
    let path = show_path(&row.path);
    rsx! {
        tr { class: "x-upload-file-row", "data-state": "{row.state.label()}",
            td { style: "{TD} overflow-wrap: anywhere;",
                if row.state == UploadFileState::Indexed && !row.file_hash.is_empty() {
                    Link { to: document_route(&dataset, &row.file_hash), style: LINK, "{path}" }
                } else {
                    "{path}"
                }
            }
            td { style: "{TD} white-space: nowrap;", "{format_upload_size(row.size_bytes)}" }
            td { style: "{TD} {state_style}", "{row.state.label()}" }
            td { style: "{TD} overflow-wrap: anywhere;", title: "{row.error}", "{first_line}" }
        }
    }
}
