//! Admin dataset detail page.

use dioxus::prelude::*;

use crate::api::error_util::user_facing_message;
use crate::api::admin_api::{
    admin_delete_dataset, admin_get_dataset, admin_get_dataset_uploads, admin_set_dataset_uploads,
    admin_trigger_workflow, admin_update_dataset,
};
use crate::components::admin_components::{
    AdminGuard, AdminShell, DatasetOcrSettingsPanel, ErrorBar, SuccessBar, BTN, BTN_DANGER,
    HELP_TEXT, INPUT, LABEL, LINK, MODULE, MODULE_BODY, MODULE_CAPTION,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::routes::Route;
use common::storage_tree::{format_size, state_label};

#[component]
pub fn AdminDatasetPage(collection_id: String, dataset_id: String) -> Element {
    let collection_id_for_content = collection_id.clone();
    let dataset_id_for_content = dataset_id.clone();
    rsx! {
        Title { "Admin: dataset {dataset_id}" }
        AdminGuard {
            AdminShell {
                title: format!("Dataset {dataset_id}"),
                breadcrumb: format!("Collections \u{203a} {collection_id}"),
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
    let mut display_name = use_signal(String::new);
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
            display_name.set(d.dataset.dataset_display_name.clone());
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

    let is_disk = detail.dataset.dataset_type == "disk";

    rsx! {
        if let Some(m) = msg.read().clone() {
            SuccessBar { message: m }
        }
        if let Some(err) = error_msg.read().clone() {
            ErrorBar { message: err }
        }
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, "Metadata" }
            div { style: "{MODULE_BODY} display: flex; flex-direction: column; gap: 10px; max-width: 640px;",
                label { style: LABEL,
                    span { style: "width: 90px; color: var(--x-ink-muted);", "Display name" }
                    input { style: "{INPUT} flex: 1;", value: "{display_name}", oninput: move |e| display_name.set(e.value()) }
                }
                div { style: "display: flex; font-size: var(--x-text-sm);",
                    span { style: "width: 96px; color: var(--x-ink-muted);", "Name" }
                    span { "{detail.dataset.dataset_name}" }
                }
                div { style: "display: flex; font-size: var(--x-text-sm);",
                    span { style: "width: 96px; color: var(--x-ink-muted);", "Type" }
                    span { "{detail.dataset.dataset_type}" }
                }
                div { style: "display: flex; font-size: var(--x-text-sm);",
                    span { style: "width: 96px; color: var(--x-ink-muted);", "Path" }
                    span { style: "word-break: break-all;", "{detail.dataset.dataset_path}" }
                }
                div { style: "display: flex; font-size: var(--x-text-sm);",
                    span { style: "width: 96px; color: var(--x-ink-muted);", "Created" }
                    span { "{detail.dataset.date_created}" }
                }
                div { style: "display: flex; font-size: var(--x-text-sm); align-items: baseline;",
                    span { style: "width: 96px; color: var(--x-ink-muted);", "Collection" }
                    Link {
                        to: Route::AdminCollectionPage { collection_id: detail.collectionname.clone() },
                        style: LINK,
                        "{detail.collectionname}"
                    }
                }
                if is_disk {
                    DatasetUploadsControl { collection_dataset: dataset_id.clone() }
                }
                div {
                    button {
                        style: BTN,
                        onclick: {
                            let cd = dataset_id.clone();
                            move |_| {
                                let cd = cd.clone();
                                let dn = display_name.read().clone();
                                spawn(async move {
                                    msg.set(None);
                                    error_msg.set(None);
                                    match admin_update_dataset(cd, dn).await {
                                        Ok(()) => {
                                            msg.set(Some("The dataset was changed successfully.".to_string()));
                                            detail_res.restart();
                                        }
                                        Err(e) => error_msg.set(Some(user_facing_message(&e))),
                                    }
                                });
                            }
                        },
                        "Save"
                    }
                }
            }
        }
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, "Statistics" }
            div { style: "{MODULE_BODY} display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 12px;",
                match detail.aggregates.clone() {
                    Some(a) => rsx! {
                        StatCard { label: "State", value: state_label(a.processing).to_string() }
                        StatCard { label: "Documents", value: a.document_count.to_string() }
                        StatCard { label: "Size", value: format_size(a.total_size_bytes) }
                        StatCard { label: "Indexed", value: a.indexed_count.to_string() }
                        StatCard { label: "Errors", value: a.error_count.to_string() }
                    },
                    None => rsx! {
                        StatCard { label: "Documents", value: "Not counted yet".to_string() }
                    },
                }
                StatCard { label: "Plans finished", value: format!("{} of {}", detail.stats.plans_finished, detail.stats.plans_total) }
            }
        }
        DatasetOcrSettingsPanel { collection_dataset: dataset_id.clone() }
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, "Processing" }
            div { style: MODULE_BODY,
                div { style: "display: flex; gap: 8px; flex-wrap: wrap;",
                    if is_disk {
                        WorkflowButton { label: "Rescan disk", kind: "rescan", dataset_id: dataset_id.clone(), pending, msg, error_msg }
                    }
                    WorkflowButton { label: "Compute plans", kind: "compute_plans", dataset_id: dataset_id.clone(), pending, msg, error_msg }
                    WorkflowButton { label: "Execute plans", kind: "execute_plans", dataset_id: dataset_id.clone(), pending, msg, error_msg }
                    WorkflowButton { label: "Run OCR", kind: "rerun_ocr", dataset_id: dataset_id.clone(), pending, msg, error_msg }
                }
            }
        }
        div { class: "x-admin-module", style: MODULE,
            h2 { style: "{MODULE_CAPTION} color: var(--x-danger);", "Danger zone" }
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 8px;", "This deletes the dataset and all data extracted from it. You cannot undo it." }
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
                                    Err(e) => error_msg.set(Some(user_facing_message(&e))),
                                }
                            });
                        }
                    },
                    "Delete dataset and its data"
                }
            }
        }
    }
}

/// The "Accept uploads" checkbox. It shows for a dataset whose folder is in a writable
/// mount, and for a dataset that accepts uploads. It is disabled while another dataset of the collection accepts uploads, unless
/// this dataset accepts uploads too, so a conflict can be cleared from either page.
#[component]
fn DatasetUploadsControl(collection_dataset: String) -> Element {
    let for_res = collection_dataset.clone();
    let mut setting_res = use_resource(move || admin_get_dataset_uploads(for_res.clone()));
    let mut error_msg = use_signal(|| None::<String>);
    let mut saving = use_signal(|| false);

    let setting = setting_res.read().as_ref().and_then(|r| r.as_ref().ok()).cloned();
    let load_error = setting_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().err().map(user_facing_message));

    if let Some(err) = load_error {
        return rsx! { ErrorBar { message: format!("The upload setting could not be read: {err}") } };
    }
    let Some(setting) = setting else {
        return rsx! {};
    };
    // A dataset that accepts uploads keeps the checkbox after its mount stops being
    // writable, so an administrator can turn the setting off.
    if !setting.writable_mount && !setting.enabled {
        return rsx! {};
    }
    let mount_gone = !setting.writable_mount;
    let others = setting.other_upload_datasets.join(", ");
    let blocked_note = if setting.other_upload_datasets.len() == 1 {
        format!("{others} already accepts uploads.")
    } else {
        format!("{others} already accept uploads.")
    };
    let blocked = !setting.enabled && !setting.other_upload_datasets.is_empty();
    let conflict = setting.enabled && !setting.other_upload_datasets.is_empty();
    let enabled = setting.enabled;

    rsx! {
        if let Some(err) = error_msg.read().clone() {
            ErrorBar { message: err }
        }
        label { style: LABEL,
            input {
                r#type: "checkbox",
                checked: enabled,
                disabled: blocked || *saving.read(),
                onchange: {
                    let cd = collection_dataset.clone();
                    move |e: Event<FormData>| {
                        let cd = cd.clone();
                        let on = e.checked();
                        saving.set(true);
                        spawn(async move {
                            error_msg.set(None);
                            if let Err(err) = admin_set_dataset_uploads(cd, on).await {
                                error_msg.set(Some(user_facing_message(&err)));
                            }
                            saving.set(false);
                            setting_res.restart();
                        });
                    }
                },
            }
            "Accept uploads"
        }
        if mount_gone {
            p { style: "{HELP_TEXT} margin: 0;", "The folder of this dataset is not in a writable dataset mount, so it receives no uploads." }
        }
        if blocked {
            p { style: "{HELP_TEXT} margin: 0;", "{blocked_note}" }
        }
        if conflict {
            p { style: "{HELP_TEXT} margin: 0; color: var(--x-danger);",
                "This dataset and {others} accept uploads. A collection can have one upload dataset. Turn off Accept uploads on all of them but one."
            }
        }
    }
}

#[component]
fn StatCard(label: String, value: String) -> Element {
    rsx! {
        div { style: "padding: 12px 14px; border: 1px solid; border-color: var(--x-border); border-radius: var(--x-radius);",
            div { style: "color: var(--x-ink-muted); font-size: var(--x-text-sm);", "{label}" }
            div { style: "font-size: var(--x-text-xl); font-weight: 500; color: var(--x-ink-strong); margin-top: 2px;", "{value}" }
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
                            Ok(run_id) => msg.set(Some(format!("Operation started: {run_id}"))),
                            Err(e) => error_msg.set(Some(user_facing_message(&e))),
                        }
                        pending.set(false);
                    });
                }
            },
            if *pending.read() { "Starting\u{2026}" } else { "{label}" }
        }
    }
}
