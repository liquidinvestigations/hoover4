//! Admin dataset detail page.

use dioxus::prelude::*;

use crate::api::admin_api::{
    admin_delete_dataset, admin_get_dataset, admin_list_collections, admin_trigger_workflow,
    admin_update_dataset,
};
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, SuccessBar, BTN, BTN_DANGER, C_HEADER, HELP_TEXT, INPUT,
    LABEL, MODULE, MODULE_BODY, MODULE_CAPTION, SELECT,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::routes::Route;

#[component]
pub fn AdminDatasetPage(collection_id: String, dataset_id: String) -> Element {
    let collection_id_for_content = collection_id.clone();
    let dataset_id_for_content = dataset_id.clone();
    rsx! {
        Title { "Admin — Dataset {dataset_id}" }
        AdminGuard {
            AdminShell {
                title: "Change dataset".to_string(),
                breadcrumb: format!("Collections \u{203a} {collection_id} \u{203a} {dataset_id}"),
                active: "collections".to_string(),
                SuspendWrapper {
                    DatasetDetailContent {
                        collection_id: collection_id_for_content,
                        dataset_id: dataset_id_for_content,
                    }
                }
            }
        }
    }
}

#[component]
fn DatasetDetailContent(collection_id: String, dataset_id: String) -> Element {
    let dataset_id_for_res = dataset_id.clone();
    let mut detail_res = use_resource(move || admin_get_dataset(dataset_id_for_res.clone()));
    let cols_res = use_resource(admin_list_collections);
    let mut dataset_name = use_signal(String::new);
    let mut collection_sel = use_signal(String::new);
    let mut msg = use_signal(|| None::<String>);
    let mut error_msg = use_signal(|| None::<String>);
    let pending = use_signal(|| false);
    let mut form_seeded = use_signal(|| false);

    let detail = detail_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned();

    if let Some(ref d) = detail {
        if !*form_seeded.read() {
            dataset_name.set(d.dataset.dataset_name.clone());
            collection_sel.set(d.collectionname.clone().unwrap_or_default());
            form_seeded.set(true);
        }
    }

    let load_failed = detail_res
        .read()
        .as_ref()
        .is_some_and(|r| r.is_err());

    let Some(detail) = detail else {
        return rsx! {
            if load_failed {
                ErrorBar { message: "Failed to load dataset" }
            } else {
                "Loading..."
            }
        };
    };

    let all_collections = cols_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned();
    let is_disk = detail.dataset.dataset_type == "disk";

    rsx! {
        if let Some(m) = msg.read().clone() {
            SuccessBar { message: m }
        }
        if let Some(err) = error_msg.read().clone() {
            ErrorBar { message: err }
        }
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Metadata" }
            div { style: "{MODULE_BODY} display: flex; flex-direction: column; gap: 10px; max-width: 640px;",
                label { style: LABEL,
                    span { style: "width: 90px; color: #666;", "Name" }
                    input { style: "{INPUT} flex: 1;", value: "{dataset_name}", oninput: move |e| dataset_name.set(e.value()) }
                }
                div { style: "display: flex; font-size: 13px;",
                    span { style: "width: 96px; color: #666;", "Type" }
                    span { "{detail.dataset.dataset_type}" }
                }
                div { style: "display: flex; font-size: 13px;",
                    span { style: "width: 96px; color: #666;", "Path" }
                    span { style: "word-break: break-all;", "{detail.dataset.dataset_path}" }
                }
                div { style: "display: flex; font-size: 13px;",
                    span { style: "width: 96px; color: #666;", "Created" }
                    span { "{detail.dataset.date_created}" }
                }
                if let Some(cols) = all_collections {
                    label { style: LABEL,
                        span { style: "width: 90px; color: #666;", "Collection" }
                        select {
                            style: SELECT,
                            value: "{collection_sel}",
                            onchange: move |e| collection_sel.set(e.value()),
                            option { value: "", "(unassigned)" }
                            for c in cols {
                                option { key: "{c.collectionname}", value: "{c.collectionname}", "{c.collectionname}" }
                            }
                        }
                    }
                }
                div {
                    button {
                        style: BTN,
                        onclick: {
                            let cd = dataset_id.clone();
                            move |_| {
                                let cd = cd.clone();
                                let name = dataset_name.read().clone();
                                let col = collection_sel.read().clone();
                                let cn = if col.is_empty() { None } else { Some(col) };
                                spawn(async move {
                                    msg.set(None);
                                    error_msg.set(None);
                                    match admin_update_dataset(cd, name, cn).await {
                                        Ok(()) => {
                                            msg.set(Some("The dataset was changed successfully.".to_string()));
                                            detail_res.restart();
                                        }
                                        Err(e) => error_msg.set(Some(e.to_string())),
                                    }
                                });
                            }
                        },
                        "Save"
                    }
                }
            }
        }
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Processing stats" }
            div { style: "{MODULE_BODY} display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 12px;",
                StatCard { label: "Blobs", value: detail.stats.blob_count }
                StatCard { label: "VFS files", value: detail.stats.vfs_file_count }
                StatCard { label: "Plans total", value: detail.stats.plans_total }
                StatCard { label: "Plans finished", value: detail.stats.plans_finished }
                StatCard { label: "Errors", value: detail.stats.error_count }
            }
        }
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Processing workflows" }
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 10px;", "Triggers a Temporal workflow for this dataset." }
                div { style: "display: flex; gap: 8px; flex-wrap: wrap;",
                    if is_disk {
                        WorkflowButton { label: "Rescan disk", kind: "rescan", dataset_id: dataset_id.clone(), pending, msg, error_msg }
                    }
                    WorkflowButton { label: "Compute plans", kind: "compute_plans", dataset_id: dataset_id.clone(), pending, msg, error_msg }
                    WorkflowButton { label: "Execute plans", kind: "execute_plans", dataset_id: dataset_id.clone(), pending, msg, error_msg }
                }
            }
        }
        div { style: MODULE,
            h2 { style: "{MODULE_CAPTION} background: #ba2121;", "Danger zone" }
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 8px;", "Soft-deletes the dataset: it disappears from search and browsing, but blobs and derived data are kept." }
                button {
                    style: BTN_DANGER,
                    onclick: {
                        let cd = dataset_id.clone();
                        let cid = collection_id.clone();
                        move |_| {
                            let cd = cd.clone();
                            let cid = cid.clone();
                            spawn(async move {
                                match admin_delete_dataset(cd).await {
                                    Ok(()) => {
                                        let _ = navigator().push(Route::AdminCollectionPage { collection_id: cid });
                                    }
                                    Err(e) => error_msg.set(Some(e.to_string())),
                                }
                            });
                        }
                    },
                    "Soft-delete dataset"
                }
            }
        }
    }
}

#[component]
fn StatCard(label: String, value: u64) -> Element {
    rsx! {
        div { style: "background: #f6f6f6; padding: 12px; border: 1px solid #eee;",
            div { style: "font-size: 24px; font-weight: 600; color: {C_HEADER};", "{value}" }
            div { style: "color: #666; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 2px;", "{label}" }
        }
    }
}

#[component]
fn WorkflowButton(
    label: String,
    kind: String,
    dataset_id: String,
    pending: Signal<bool>,
    msg: Signal<Option<String>>,
    error_msg: Signal<Option<String>>,
) -> Element {
    let mut pending = pending;
    let mut msg = msg;
    let mut error_msg = error_msg;
    rsx! {
        button {
            style: BTN,
            disabled: *pending.read(),
            onclick: {
                let kind = kind.clone();
                let ds = dataset_id.clone();
                move |_| {
                    let kind = kind.clone();
                    let ds = ds.clone();
                    pending.set(true);
                    spawn(async move {
                        msg.set(None);
                        error_msg.set(None);
                        match admin_trigger_workflow(ds, kind).await {
                            Ok(run_id) => msg.set(Some(format!("Workflow started: {run_id}"))),
                            Err(e) => error_msg.set(Some(e.to_string())),
                        }
                        pending.set(false);
                    });
                }
            },
            if *pending.read() { "Starting\u{2026}" } else { "{label}" }
        }
    }
}
