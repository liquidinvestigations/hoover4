//! Admin collections list page.

use dioxus::prelude::*;

use crate::api::admin_api::{
    admin_create_collection, admin_list_collections, admin_list_unassigned_datasets,
};
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, SuccessBar, BTN_PRIMARY, HELP_TEXT, INPUT, LINK, MODULE,
    MODULE_BODY, MODULE_CAPTION, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::routes::Route;

#[component]
pub fn AdminCollectionsPage() -> Element {
    rsx! {
        Title { "Admin — Collections" }
        AdminGuard {
            AdminShell {
                title: "Select collection to change".to_string(),
                breadcrumb: "Collections".to_string(),
                active: "collections".to_string(),
                SuspendWrapper { CollectionsListContent {} }
            }
        }
    }
}

#[component]
fn CollectionsListContent() -> Element {
    let mut cols_res = use_resource(admin_list_collections);
    let mut unassigned_res = use_resource(admin_list_unassigned_datasets);
    let mut collectionname = use_signal(String::new);
    let mut fullname = use_signal(String::new);
    let mut error_msg = use_signal(|| None::<String>);
    let mut success_msg = use_signal(|| None::<String>);

    rsx! {
        if let Some(msg) = success_msg.read().clone() {
            SuccessBar { message: msg }
        }
        if let Some(err) = error_msg.read().clone() {
            ErrorBar { message: err }
        }
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Add collection" }
            div { style: "{MODULE_BODY} display: flex; gap: 8px; flex-wrap: wrap; align-items: center;",
                input { style: INPUT, placeholder: "collectionname (slug)", value: "{collectionname}", oninput: move |e| collectionname.set(e.value()) }
                input { style: INPUT, placeholder: "display name", value: "{fullname}", oninput: move |e| fullname.set(e.value()) }
                button {
                    style: BTN_PRIMARY,
                    onclick: move |_| {
                        let c = collectionname.read().clone();
                        let f = fullname.read().clone();
                        spawn(async move {
                            error_msg.set(None);
                            success_msg.set(None);
                            match admin_create_collection(c.clone(), f).await {
                                Ok(()) => {
                                    success_msg.set(Some(format!("The collection \u{201c}{c}\u{201d} was added successfully.")));
                                    collectionname.set(String::new());
                                    fullname.set(String::new());
                                    cols_res.restart();
                                    unassigned_res.restart();
                                }
                                Err(e) => error_msg.set(Some(e.to_string())),
                            }
                        });
                    },
                    "Add collection +"
                }
            }
        }
        match &*cols_res.read() {
            Some(Ok(cols)) => rsx! {
                table { style: "{TABLE} margin-bottom: 24px;",
                    thead {
                        tr {
                            th { style: TH, "Collection" }
                            th { style: TH, "Display name" }
                            th { style: TH, "Datasets" }
                            th { style: TH, "Groups with access" }
                        }
                    }
                    tbody {
                        for c in cols.clone() {
                            tr { key: "{c.collectionname}",
                                td { style: TD,
                                    Link { to: Route::AdminCollectionPage { collection_id: c.collectionname.clone() }, style: LINK, "{c.collectionname}" }
                                }
                                td { style: TD, "{c.fullname}" }
                                td { style: TD, "{c.dataset_count}" }
                                td { style: TD, "{c.group_count}" }
                            }
                        }
                    }
                }
            },
            Some(Err(e)) => rsx! { ErrorBar { message: "{e}" } },
            None => rsx! { "Loading..." },
        }
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Unassigned datasets" }
            div { style: MODULE_BODY,
                match &*unassigned_res.read() {
                    Some(Ok(list)) if list.is_empty() => rsx! {
                        p { style: "{HELP_TEXT} margin: 0;", "Every dataset is assigned to a collection." }
                    },
                    Some(Ok(list)) => rsx! {
                        p { style: "{HELP_TEXT} margin: 0 0 8px;", "These datasets belong to no collection and are invisible to non-admin users. Open a collection page to attach them." }
                        ul { style: "margin: 0; padding-left: 20px; font-size: 13px; color: #333;",
                            for ds in list.clone() {
                                li { key: "{ds}", "{ds}" }
                            }
                        }
                    },
                    Some(Err(e)) => rsx! { ErrorBar { message: "{e}" } },
                    None => rsx! { "Loading\u{2026}" },
                }
            }
        }
    }
}
