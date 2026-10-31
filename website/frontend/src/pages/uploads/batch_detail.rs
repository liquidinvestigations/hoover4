//! `/uploads/:collection/:batch_id?page`, the batch detail. It reads the outcome again
//! every 3 seconds until the batch state is terminal. The owner of an `uploading` batch
//! can continue the upload after a closed tab: the page matches a new selection of the
//! same files, and the driver checks the acknowledged bytes before it resumes. The run
//! commits after its last file only when it sends every file that waits for bytes. The
//! page lists the files that the selection did not name or whose bytes differ, and
//! Finish upload commits the batch without them.

use std::time::Duration;

use common::search_result::DocumentIdentifier;
use common::upload_pages::{
    batch_state_is_terminal, batch_state_label, match_resume_selection, pending_paths, ResumeFile,
    SelectedFile, UploadBatchDetail, UploadFileRow, UploadFileState,
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
use crate::tr;
use crate::i18n::SharedText;

const POLL: Duration = Duration::from_secs(3);
fn differs() -> String {
    tr!("uploads-batch-detail-the-selected-file-differs-from")
}
/// Paths of the list of files that have not been sent. The rest is a count.
const NOT_SENT_ROWS: usize = 20;

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
    rsx! { UploadBatchContent { key: "{collection}/{batch_id}", collection, batch_id, page } }
}

#[component]
fn UploadBatchContent(collection: String, batch_id: String, page: u32) -> Element {
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
                Some(Err(_)) => true,
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
    // The files of the batch that still wait for bytes and that the last selection did
    // not name, or that the last run did not send.
    let mut not_sent_yet = use_signal(Vec::<String>::new);
    // True when the resume run commits after its last file.
    let mut run_commits = use_signal(|| false);
    // A failed Finish upload, shown under the controls.
    let mut finish_error = use_signal(|| None::<String>);
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
            finish_error.set(None);
            if !found.names_the_batch() {
                return;
            }
            not_sent_yet.set(found.not_selected.clone());
            let commits = found.sends_every_pending_file();
            run_commits.set(commits);
            // Nothing to send, and other files still wait: the batch stays open.
            if found.matched.is_empty() && !commits {
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
                Some(Ok(d)) => tr!(
                    "uploads-batch-detail-uploading-files-to",
                    count: format_count(found.matched.len() as u64),
                    destination: destination_label(&d.batch)
                ),
                _ => String::new(),
            };
            transfer.set(Some(Transfer {
                heading,
                state: Progress { total, count: found.matched.len() as u64, phase: "checking".into(), ..Default::default() },
                error: None,
                batch_id: Some(batch_id.clone()),
            }));
            pending_resume.set(Some(serde_json::json!({
                "cmd": "resume",
                "batch_id": batch_id,
                "items": items,
                "chunk_bytes": chunk_bytes,
                "commit_when_done": commits,
            })));
        }
        DriverEvent::Checked { mismatched: found, sending } => {
            // Without a file to send, the driver starts a run only to commit a batch whose
            // files all have their bytes.
            if sending == 0 && !(*run_commits.peek() && found.is_empty()) {
                transfer.set(None);
            }
            mismatched.set(found);
        }
        DriverEvent::Sent { .. } => {
            transfer.set(None);
            *tick.write() += 1;
            // The run ended without a commit. Read the files that still wait for bytes.
            let (collection, batch_id, _) = key.peek().clone();
            spawn(async move {
                let files = upload_batch_resume_files(collection, batch_id).await.map_err(|e| user_facing_message(&e));
                if let Ok(batch_files) = &files {
                    let differs: Vec<String> = mismatched.peek().iter().map(|m| m.path.clone()).collect();
                    not_sent_yet.set(pending_paths(batch_files).into_iter().filter(|p| !differs.contains(p)).collect());
                }
                manifest.set(Some(files));
            });
        }
        DriverEvent::Committed { .. } => {
            transfer.set(None);
            resuming.set(false);
            not_sent_yet.set(Vec::new());
            mismatched.set(Vec::new());
            *tick.write() += 1;
        }
        DriverEvent::ResumeFailed { message } => {
            transfer.set(None);
            finish_error.set(Some(message));
        }
        DriverEvent::Phase { phase } => {
            if let Some(t) = transfer.write().as_mut() {
                t.state.phase = phase;
                t.error = None;
            }
        }
        DriverEvent::CommitFailed { message } => {
            if transfer.peek().is_some() {
                if let Some(t) = transfer.write().as_mut() {
                    t.state.phase = "commit_failed".into();
                    t.error = Some(message);
                }
            } else {
                finish_error.set(Some(message));
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
        None => rsx! { p { {tr!("uploads-batch-detail-loading")} } },
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
                    dt { {tr!("uploads-batch-detail-state")} } dd { class: "x-upload-state", "{batch_state_label(&b.state).shared()}" }
                    dt { {tr!("uploads-batch-detail-uploaded-by")} } dd { {tr!("uploads-batch-detail-utc", b_username: b.username.to_string(), started_label_b_created_ms: (started_label(b.created_ms)).to_string())} }
                    dt { {tr!("uploads-batch-detail-folder")} } dd { Link { to: browse, style: LINK, "{b.folder}" } }
                    dt { {tr!("uploads-batch-detail-files")} } dd { "{format_count(b.file_count as u64)}, {format_upload_size(b.byte_count)}" }
                    if let Some(op_id) = d.op_id.clone() {
                        dt { {tr!("uploads-batch-detail-operation")} }
                        dd { Link { to: Route::AdminOperationDetailPage { op_id: op_id.clone(), plans_page: 0, events_page: 0 }, style: LINK, "{op_id}" } }
                    }
                }
                if !d.error.is_empty() {
                    p { class: "x-upload-batch-error", style: "color: var(--x-danger); margin: 0;", "{d.error}" }
                }
                if can_continue {
                    div {
                        if resuming() && !matches!(&*manifest.read(), Some(Err(_))) {
                            if matches!(&*manifest.read(), Some(Ok(_))) {
                                DropZone { driver }
                            } else if manifest.read().is_none() {
                                p { role: "status", {tr!("uploads-batch-detail-loading-upload-files")} }
                            }
                        } else {
                            button {
                                class: "x-upload-continue-upload",
                                style: BTN,
                                onclick: move |_| {
                                    if *resuming.peek() && !matches!(&*manifest.peek(), Some(Err(_))) { return; }
                                    resuming.set(true);
                                    manifest.set(None);
                                    let (collection, batch_id, _) = key.peek().clone();
                                    spawn(async move {
                                        let files = upload_batch_resume_files(collection, batch_id).await
                                            .map_err(|e| user_facing_message(&e));
                                        manifest.set(Some(files));
                                    });
                                },
                                if matches!(&*manifest.read(), Some(Err(_))) { {tr!("uploads-batch-detail-retry-loading-files")} } else { {tr!("uploads-batch-detail-continue-upload")} }
                            }
                        }
                        div { style: "display: flex; align-items: center; gap: 10px; margin-top: 8px;",
                            button {
                                class: "x-upload-finish",
                                style: BTN,
                                disabled: transfer().is_some(),
                                onclick: move |_| {
                                    if transfer.peek().is_some() { return; }
                                    finish_error.set(None);
                                    transfer.set(Some(Transfer {
                                        heading: tr!("uploads-batch-detail-finishing-upload").into(),
                                        state: Progress { phase: "committing".into(), ..Default::default() },
                                        error: None,
                                        batch_id: Some(key.peek().1.clone()),
                                    }));
                                    driver.send(serde_json::json!({"cmd": "finish", "batch_id": key.peek().1.clone()}));
                                },
                                {tr!("uploads-batch-detail-finish-upload")}
                            }
                            span { style: "color: var(--x-ink-muted);",
                                {tr!("uploads-batch-detail-finish-upload-ingests-the-files")}
                            }
                        }
                        if let Some(e) = finish_error() {
                            ErrorBar { message: e }
                        }
                        if let Some(Err(e)) = manifest() {
                            ErrorBar { message: e }
                        }
                        if unmatched() > 0 {
                            p { class: "x-upload-unmatched", style: "color: var(--x-danger);",
                                {tr!("uploads-batch-detail-selected-files-do-not-match", format_count_unmatched_as_u64: (format_count(unmatched() as u64)).to_string())}
                            }
                        }
                        for (index, file) in mismatched().iter().enumerate() {
                            p { key: "{index}", class: "x-upload-mismatch", style: "color: var(--x-danger); margin: 2px 0; overflow-wrap: anywhere;",
                                if file.error.is_empty() { "{show_path(&file.path)} {differs()}" } else { "{show_path(&file.path)} {file.error}" }
                            }
                        }
                        if !not_sent_yet().is_empty() {
                            NotSentList { paths: not_sent_yet() }
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
                    span { {tr!("uploads-batch-detail-of-indexed", format_count_d_counts_indexed: (format_count(d.counts.indexed)).to_string(), format_count_d_counts_files: format_count(d.counts.files))} }
                }
                div { class: "x-upload-counts", style: "display: flex; gap: 18px; flex-wrap: wrap;",
                    span { {tr!("uploads-batch-detail-ingested", format_count_d_counts_ingested: (format_count(d.counts.ingested)).to_string())} }
                    span { {tr!("uploads-batch-detail-indexed", format_count_d_counts_indexed: (format_count(d.counts.indexed)).to_string())} }
                    span { {tr!("uploads-batch-detail-with-errors", format_count_d_counts_with_errors: (format_count(d.counts.with_errors)).to_string())} }
                    span { {tr!("uploads-batch-detail-rejected", format_count_d_counts_rejected: (format_count(d.counts.rejected)).to_string())} }
                    span { {tr!("uploads-batch-detail-not-sent", format_count_d_counts_not_sent: (format_count(d.counts.not_sent)).to_string())} }
                }
                table { class: "x-upload-files", style: TABLE,
                    thead {
                        tr {
                            th { style: TH, {tr!("uploads-batch-detail-path")} }
                            th { style: TH, {tr!("uploads-batch-detail-size")} }
                            th { style: TH, {tr!("uploads-batch-detail-state")} }
                            th { style: TH, {tr!("uploads-batch-detail-error")} }
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
                        span { {tr!("uploads-batch-detail-of", current_1: (current + 1).to_string(), pages: pages)} }
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
        Some(Ok(d)) => tr!("uploads-batch-detail-upload-to", destination: destination_label(&d.batch)),
        _ => tr!("uploads-batch-detail-upload"),
    };
    let list = Route::UploadsPage { collection: key().0 };
    rsx! {
        Title { {tr!("uploads-batch-detail-hoover-search-upload")} }
        UploadScripts {}
        div { style: PAGE_STYLE, "inert": transfer().is_some().then_some(""),
            div { style: "max-width: 1100px; margin: 0 auto;",
                div { style: "display: flex; align-items: center; gap: 15px; margin-bottom: 15px;",
                    Link { to: list, style: "{LINK} display: inline-flex; align-items: center; gap: 4px;",
                        Icon { icon: MdArrowBack, width: 16, height: 16 }
                        {tr!("uploads-batch-detail-uploads")}
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

/// The files of the batch that still wait for bytes, after a selection or a run.
#[component]
fn NotSentList(paths: Vec<String>) -> Element {
    let more = paths.len().saturating_sub(NOT_SENT_ROWS);
    rsx! {
        div { class: "x-upload-not-selected", style: "margin: 4px 0;",
            p { style: "margin: 2px 0;",
                {tr!("uploads-batch-detail-files-of-this-upload-have", format_count_paths_len_as_u64: (format_count(paths.len() as u64)).to_string())}
            }
            for (index, path) in paths.iter().take(NOT_SENT_ROWS).enumerate() {
                div { key: "{index}", style: "padding-left: 16px; overflow-wrap: anywhere;", "{show_path(path)}" }
            }
            if more > 0 {
                div { style: "padding-left: 16px; color: var(--x-ink-muted);", {tr!("uploads-batch-detail-and-more-files", format_count_more_as_u64: (format_count(more as u64)).to_string())} }
            }
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
            td { style: "{TD} {state_style}", "{row.state.label().shared()}" }
            td { style: "{TD} overflow-wrap: anywhere;", title: "{row.error}", "{first_line}" }
        }
    }
}
