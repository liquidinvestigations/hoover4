//! `/upload?collection&dataset&folder`, the upload page. It selects the destination
//! dataset and the folder, collects files and folders, lists the files that fail a check, and sends
//! `begin`. The progress dialog then shows the transfer, and the batch detail page opens
//! after `commit`.

use common::search_result::DocumentIdentifier;
use common::upload_pages::{begin_request_id, begin_result_unknown, SelectedFile, UnconfirmedBegin};
use common::uploads::{
    check_manifest, format_count, format_upload_size, manifest_body_bytes, BeginFile, BeginRefusal,
    BeginRequest, FileProblem, LimitsResponse, UploadTargetInfo, MANIFEST_TOO_LARGE_MESSAGE,
};
use common::vfs::PathDescriptor;
use dioxus::prelude::*;
use dioxus_free_icons::icons::md_navigation_icons::{MdArrowBack, MdClose};
use dioxus_free_icons::Icon;

use super::driver::{use_upload_driver, DriverEvent, DropZone, Progress, ProgressDialog, UploadDriver, UploadScripts};
use super::folder_tree::FolderTree;
use crate::api::board_api::new_request_id;
use crate::api::error_util::user_facing_message;
use crate::api::uploads_api::upload_page_info;
use crate::components::admin_components::{ErrorBar, BTN, BTN_PRIMARY, LINK, SELECT};
use crate::routes::Route;
use crate::tr;

/// Rows of the file list. The rest is a count.
const LIST_ROWS: usize = 500;

pub(super) const PAGE_STYLE: &str = "width: 100%; height: 100%; background: #F5F6F8; box-sizing: border-box; padding: 23px; overflow: auto; font-family: var(--x-font); color: var(--x-ink);";
pub(super) const SURFACE_STYLE: &str = "display: flex; flex-direction: column; gap: 10px; background: white; border: 1px solid; border-color: var(--x-border); border-radius: 12px; padding: 16px;";
pub(super) const H1_STYLE: &str = "margin: 0; font-size: var(--x-text-page); line-height: var(--x-line-page); font-weight: 600; color: var(--x-ink-strong);";
const FIELD_LABEL: &str = "font-size: var(--x-text-body); font-weight: 600; color: var(--x-ink-strong); margin: 4px 0 0;";
const PROBLEM_STYLE: &str = "color: var(--x-danger); font-size: var(--x-text-body);";

/// The address of the file browser at a folder of the upload dataset.
pub(super) fn browser_route(dataset: &str, folder: &str) -> Route {
    let path = if folder.is_empty() { "/".to_string() } else { folder.to_string() };
    Route::file_browser_page(dataset.to_string(), PathDescriptor { container_hash: String::new(), path }, None::<DocumentIdentifier>)
}

/// The problems of a refused `begin`, with the status text when the body is not a refusal.
fn refusal_from(status: u16, body: &str) -> BeginRefusal {
    match serde_json::from_str::<BeginRefusal>(body) {
        Ok(refusal) => refusal,
        Err(_) => BeginRefusal {
            message: if body.trim().is_empty() { tr!("uploads-upload-http", status: status.to_string()) } else { body.to_string() },
            ..Default::default()
        },
    }
}

/// The checks of the page: [`check_manifest`] and the size of the `begin` body.
/// The target of the address: the named dataset of the collection, the first upload
/// dataset of the collection without a dataset, or the first target without a collection.
pub fn chosen_target<'a>(targets: &'a [UploadTargetInfo], collection: &str, dataset: &str) -> Option<&'a UploadTargetInfo> {
    match (collection.is_empty(), dataset.is_empty()) {
        (true, _) => targets.first(),
        (false, true) => targets.iter().find(|t| t.collection == collection),
        (false, false) => targets.iter().find(|t| t.collection == collection && t.dataset == dataset),
    }
}

pub fn page_problems(info: &LimitsResponse, folder: &str, request: &BeginRequest) -> (Vec<String>, Vec<FileProblem>) {
    let check = check_manifest(&info.limits, folder, &request.files);
    let mut batch = check.batch_problems;
    if !request.files.is_empty() && manifest_body_bytes(request) as u64 > info.limits.manifest_max_bytes {
        batch.push(MANIFEST_TOO_LARGE_MESSAGE.to_string());
    }
    (batch, check.problems)
}

/// A path for the page. A control character shows as its escape, so a name with a tab is
/// visible.
pub(super) fn show_path(path: &str) -> String {
    path.chars()
        .map(|c| if c.is_control() { c.escape_default().to_string() } else { c.to_string() })
        .collect()
}

/// The dialog of a running transfer.
#[derive(Clone, PartialEq)]
pub(super) struct Transfer {
    pub heading: String,
    pub state: Progress,
    pub error: Option<String>,
    pub batch_id: Option<String>,
}

#[component]
pub fn UploadPage(collection: String, dataset: String, folder: String) -> Element {
    let info = use_resource(upload_page_info);
    let mut selection = use_signal(Vec::<SelectedFile>::new);
    let mut refusal = use_signal(|| None::<BeginRefusal>);
    let mut transfer = use_signal(|| None::<Transfer>);
    // The destination of the running transfer, for the detail address after `commit`.
    let sending_to = use_signal(String::new);
    // The last `begin` without a decision of the server. A click with the same selection
    // and destination sends its request id again.
    let mut unconfirmed = use_signal(|| None::<UnconfirmedBegin>);

    let driver = use_upload_driver(Callback::new(move |event: DriverEvent| match event {
        DriverEvent::Added { files } => {
            refusal.set(None);
            selection.write().extend(files);
        }
        DriverEvent::Refused { status, body } => {
            transfer.set(None);
            if !begin_result_unknown(status) {
                unconfirmed.set(None);
            }
            refusal.set(Some(refusal_from(status, &body)));
        }
        DriverEvent::Begun { batch_id } => {
            unconfirmed.set(None);
            if let Some(t) = transfer.write().as_mut() {
                t.batch_id = Some(batch_id);
            }
        }
        DriverEvent::Committed { .. } => {
            let batch_id = transfer.peek().as_ref().and_then(|t| t.batch_id.clone());
            if let Some(batch_id) = batch_id {
                let collection = sending_to.peek().clone();
                navigator().push(Route::UploadBatchPage { collection, batch_id, page: 0 });
            }
        }
        DriverEvent::Phase { phase } => {
            if let Some(t) = transfer.write().as_mut() {
                t.state.phase = phase;
                t.error = None;
            }
        }
        DriverEvent::CommitFailed { message } => {
            if let Some(t) = transfer.write().as_mut() {
                t.state.phase = "commit_failed".into();
                t.error = Some(message);
            }
        }
        // The server deleted the batch. The page returns to an empty form.
        DriverEvent::Aborted { .. } => {
            transfer.set(None);
            refusal.set(None);
            unconfirmed.set(None);
            selection.set(Vec::new());
        }
        DriverEvent::AbortFailed { message } => {
            if let Some(t) = transfer.write().as_mut() {
                t.state.phase = "abort_failed".into();
                t.error = Some(message);
            }
        }
        other => {
            if let (Some(state), Some(t)) = (other.progress(), transfer.write().as_mut()) {
                t.state = state;
            }
        }
    }));

    let info_value = info.read().clone();
    let body = match info_value {
        None => rsx! { p { {tr!("uploads-upload-loading")} } },
        Some(Err(e)) => rsx! { ErrorBar { message: user_facing_message(&e) } },
        Some(Ok(info)) => {
            let target = chosen_target(&info.targets, &collection, &dataset).cloned();
            match target {
                None if !collection.is_empty() => rsx! {
                    p { class: "x-upload-none", {tr!("uploads-upload-you-cannot-upload-into-this")} }
                },
                None => rsx! {
                    p { class: "x-upload-none", {tr!("uploads-upload-you-cannot-upload-into-any")} }
                },
                Some(target) => rsx! {
                    UploadForm {
                        info: info.clone(),
                        target,
                        folder: folder.clone(),
                        selection,
                        refusal,
                        transfer,
                        sending_to,
                        unconfirmed,
                        driver,
                    }
                },
            }
        }
    };

    let back = if collection.is_empty() {
        Route::storage_root()
    } else {
        match info.read().as_ref() {
            Some(Ok(info)) => match chosen_target(&info.targets, &collection, &dataset) {
                Some(t) => browser_route(&t.dataset, &folder),
                None => Route::storage_root(),
            },
            _ => Route::storage_root(),
        }
    };
    let uploads_link = Route::UploadsPage { collection: collection.clone() };

    rsx! {
        Title { {tr!("uploads-upload-hoover-search-upload")} }
        UploadScripts {}
        div { style: PAGE_STYLE, "inert": transfer().is_some().then_some(""),
            div { style: "max-width: 860px; margin: 0 auto;",
                div { style: "display: flex; align-items: center; gap: 15px; margin-bottom: 15px;",
                    Link { to: back, style: "{LINK} display: inline-flex; align-items: center; gap: 4px;",
                        Icon { icon: MdArrowBack, width: 16, height: 16 }
                        {tr!("uploads-upload-file-browser")}
                    }
                    h1 { style: H1_STYLE, {tr!("uploads-upload-upload")} }
                    span { style: "flex: 1 1 auto;" }
                    Link { to: uploads_link, class: "x-upload-history-link", style: LINK, {tr!("uploads-upload-uploads")} }
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
fn UploadForm(
    info: LimitsResponse,
    target: UploadTargetInfo,
    folder: String,
    selection: Signal<Vec<SelectedFile>>,
    refusal: Signal<Option<BeginRefusal>>,
    transfer: Signal<Option<Transfer>>,
    sending_to: Signal<String>,
    unconfirmed: Signal<Option<UnconfirmedBegin>>,
    driver: UploadDriver,
) -> Element {
    let folder = common::uploads::normalize_folder(&folder).unwrap_or_else(|_| folder.clone());
    let files: Vec<BeginFile> = selection
        .read()
        .iter()
        .map(|f| BeginFile { path: f.path.clone(), size: f.size, last_modified_ms: f.last_modified_ms })
        .collect();
    let request = BeginRequest {
        // The click replaces this id with one from the browser's random source, or with
        // the id of an unconfirmed `begin` of the same request. It has the same length, so
        // the size check measures the body that the click sends.
        request_id: "0".repeat(32),
        collection: target.collection.clone(),
        dataset: target.dataset.clone(),
        folder: folder.clone(),
        files,
    };
    // An empty selection is not a problem. Upload is disabled without files.
    let (batch_problems, problems) = if request.files.is_empty() {
        (Vec::new(), Vec::new())
    } else {
        page_problems(&info, &folder, &request)
    };
    let total: u64 = request.files.iter().map(|f| f.size).sum();
    let count = request.files.len();
    let refused = refusal();
    let chunk_bytes = info.limits.chunk_bytes;
    let blocked = transfer().is_some() || count == 0 || !batch_problems.is_empty() || !problems.is_empty();

    let dataset = target.dataset.clone();
    let tree_collection = target.collection.clone();
    let tree_dataset = target.dataset.clone();
    let targets_for_select = info.targets.clone();
    let heading = tr!(
        "uploads-upload-uploading-files-to-folder",
        count: format_count(count as u64),
        collection: target.collection.clone(),
        dataset: target.dataset.clone(),
        folder: folder.to_string()
    );
    let selected = selection.read().clone();
    let shown: Vec<SelectedFile> = selected.iter().take(LIST_ROWS).cloned().collect();
    let more = selected.len().saturating_sub(LIST_ROWS);

    rsx! {
        label { style: FIELD_LABEL, r#for: "x-upload-destination", {tr!("uploads-upload-destination")} }
        if info.targets.len() > 1 {
            select {
                id: "x-upload-destination",
                style: "{SELECT} max-width: 420px;",
                onchange: move |e| {
                    // A dataset id names one dataset in the installation, so it selects the target.
                    if let Some(t) = targets_for_select.iter().find(|t| t.dataset == e.value()) {
                        navigator().replace(Route::UploadPage {
                            collection: t.collection.clone(),
                            dataset: t.dataset.clone(),
                            folder: "/".to_string(),
                        });
                    }
                },
                // `selected` on the option, because a `value` on the select is set before
                // its options exist and the browser then shows the first option.
                for t in info.targets.iter() {
                    option { key: "{t.dataset}", value: "{t.dataset}", selected: t.dataset == dataset, "{t.collection} / {t.dataset}" }
                }
            }
        } else {
            div { id: "x-upload-destination", "{target.collection} / {target.dataset}" }
        }
        p { style: FIELD_LABEL, {tr!("uploads-upload-folder")} }
        FolderTree {
            dataset: dataset.clone(),
            selected: folder.clone(),
            on_select: move |path: String| {
                navigator().replace(Route::UploadPage {
                    collection: tree_collection.clone(),
                    dataset: tree_dataset.clone(),
                    folder: path,
                });
            },
        }
        div { style: "margin-top: 8px;", DropZone { driver } }

        for (index, message) in batch_problems.iter().enumerate() {
            p { key: "batch-{index}", class: "x-upload-problem", style: PROBLEM_STYLE, "{message}" }
        }
        if !problems.is_empty() {
            ProblemList { heading: tr!("uploads-upload-files-cannot-be-uploaded", format_count_problems_len_as_u64: (format_count(problems.len() as u64)).to_string()), problems: problems.clone() }
        }
        if let Some(r) = refused {
            for (index, message) in r.batch_problems.iter().enumerate() {
                p { key: "refused-{index}", class: "x-upload-problem", style: PROBLEM_STYLE, "{message}" }
            }
            if !r.problems.is_empty() {
                ProblemList { heading: tr!("uploads-upload-files-cannot-be-uploaded-2", format_count_r_problems_len_as_u64: (format_count(r.problems.len() as u64)).to_string()), problems: r.problems.clone() }
            }
            if !r.collisions.is_empty() {
                div { class: "x-upload-collisions", style: PROBLEM_STYLE,
                    p { style: "margin: 4px 0;", {tr!("uploads-upload-these-paths-exist-in-the")} }
                    for path in r.collisions.iter() {
                        div { key: "{path}", style: "padding-left: 16px; overflow-wrap: anywhere;", "{path}" }
                    }
                }
            }
            if r.problems.is_empty() && r.collisions.is_empty() && r.batch_problems.is_empty() {
                p { class: "x-upload-problem", style: PROBLEM_STYLE, "{r.message}" }
            }
        }

        if count > 0 {
            div { style: "display: flex; align-items: center; gap: 12px; margin-top: 6px;",
                p { style: "{FIELD_LABEL} margin: 0;", {tr!("uploads-upload-files")} }
                span { class: "x-upload-summary", style: "flex: 1 1 auto; color: var(--x-ink-muted);",
                    {tr!("uploads-upload-files-2", format_count_count_as_u64: (format_count(count as u64)).to_string(), format_upload_size_total: format_upload_size(total))}
                }
                button {
                    class: "x-upload-clear",
                    style: BTN,
                    onclick: move |_| {
                        let ids: Vec<u64> = selection.peek().iter().map(|f| f.id).collect();
                        driver.send(serde_json::json!({"cmd": "forget", "ids": ids}));
                        selection.set(Vec::new());
                        refusal.set(None);
                    },
                    {tr!("uploads-upload-clear")}
                }
            }
            div { class: "x-upload-list", style: "border: 1px solid; border-color: var(--x-border); border-radius: 6px; max-height: 320px; overflow: auto;",
                for file in shown.iter() {
                    FileLine { key: "{file.id}", file: file.clone(), selection, refusal, driver }
                }
                if more > 0 {
                    div { style: "padding: 4px 10px; color: var(--x-ink-muted);", {tr!("uploads-upload-and-more-files", format_count_more_as_u64: (format_count(more as u64)).to_string())} }
                }
            }
        }
        div { style: "margin-top: 6px;",
            button {
                class: "x-upload-submit",
                style: BTN_PRIMARY,
                disabled: blocked,
                onclick: move |_| {
                    if transfer.peek().is_some() { return; }
                    let ids: Vec<u64> = selection.peek().iter().map(|f| f.id).collect();
                    let paths: Vec<String> = request.files.iter().map(|f| f.path.clone()).collect();
                    let mut request = request.clone();
                    request.request_id = String::new();
                    let request_key = serde_json::to_string(&request).unwrap_or_default();
                    request.request_id = begin_request_id(unconfirmed.peek().as_ref(), &request_key, new_request_id);
                    unconfirmed.set(Some(UnconfirmedBegin { request_id: request.request_id.clone(), request_key }));
                    let body = serde_json::to_string(&request).unwrap_or_default();
                    refusal.set(None);
                    sending_to.set(request.collection.clone());
                    transfer.set(Some(Transfer {
                        heading: heading.clone(),
                        state: Progress { total, count: count as u64, phase: "starting".into(), ..Default::default() },
                        error: None,
                        batch_id: None,
                    }));
                    driver.send(serde_json::json!({
                        "cmd": "begin",
                        "body": body,
                        "ids": ids,
                        "paths": paths,
                        "chunk_bytes": chunk_bytes,
                    }));
                },
                {tr!("uploads-upload-upload-files", format_count_count_as_u64: (format_count(count as u64)).to_string())}
            }
        }
    }
}

#[component]
fn ProblemList(heading: String, problems: Vec<FileProblem>) -> Element {
    rsx! {
        div { class: "x-upload-problems", style: PROBLEM_STYLE,
            p { style: "margin: 4px 0;", "{heading}" }
            for (index, problem) in problems.iter().enumerate() {
                div { key: "{index}", style: "display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; padding-left: 16px;",
                    span { style: "overflow-wrap: anywhere;", "{show_path(&problem.path)}" }
                    span { "{problem.message}" }
                }
            }
        }
    }
}

#[component]
fn FileLine(
    file: SelectedFile,
    selection: Signal<Vec<SelectedFile>>,
    refusal: Signal<Option<BeginRefusal>>,
    driver: UploadDriver,
) -> Element {
    let id = file.id;
    rsx! {
        div { class: "x-upload-file", style: "display: flex; align-items: center; gap: 10px; padding: 3px 10px; border-bottom: 1px solid; border-color: var(--x-border);",
            span { style: "flex: 1 1 auto; overflow-wrap: anywhere;", "{show_path(&file.path)}" }
            span { style: "color: var(--x-ink-muted); white-space: nowrap;", "{format_upload_size(file.size)}" }
            button {
                class: "x-upload-remove",
                "aria-label": "Remove",
                style: "border: none; background: none; cursor: pointer; display: inline-flex; color: var(--x-ink-muted); padding: 0;",
                onclick: move |_| {
                    selection.write().retain(|f| f.id != id);
                    refusal.set(None);
                    driver.send(serde_json::json!({"cmd": "forget", "ids": [id]}));
                },
                Icon { icon: MdClose, width: 16, height: 16 }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_address_selects_one_dataset_of_a_collection_with_several() {
        let target = |c: &str, d: &str| UploadTargetInfo { collection: c.into(), dataset: d.into() };
        let targets = vec![target("legal", "legal_in"), target("press", "press_en"), target("press", "press_ru")];
        assert_eq!(chosen_target(&targets, "press", "press_ru"), Some(&targets[2]));
        assert_eq!(chosen_target(&targets, "press", ""), Some(&targets[1]));
        assert_eq!(chosen_target(&targets, "", ""), Some(&targets[0]));
        assert_eq!(chosen_target(&targets, "press", "legal_in"), None);
        assert_eq!(chosen_target(&targets, "other", ""), None);
    }
}
