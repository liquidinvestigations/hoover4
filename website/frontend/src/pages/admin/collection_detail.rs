//! Admin collection detail page.

use dioxus::prelude::*;

use crate::api::admin_api::{
    admin_assign_dataset, admin_delete_collection, admin_get_collection, admin_grant_permission,
    admin_list_groups, admin_revoke_permission, admin_unassign_dataset, admin_update_collection,
};
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, SuccessBar, BTN, BTN_DANGER, BTN_SMALL_DANGER, HELP_TEXT,
    INPUT, LINK, MODULE, MODULE_BODY, MODULE_CAPTION, SELECT, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::routes::Route;

#[component]
pub fn AdminCollectionPage(collection_id: String) -> Element {
    let collection_id_for_content = collection_id.clone();
    rsx! {
        Title { "Admin — Collection {collection_id}" }
        AdminGuard {
            AdminShell {
                title: "Change collection".to_string(),
                breadcrumb: format!("Collections \u{203a} {collection_id}"),
                active: "collections".to_string(),
                SuspendWrapper { CollectionDetailContent { collection_id: collection_id_for_content } }
            }
        }
    }
}

#[component]
fn CollectionDetailContent(collection_id: String) -> Element {
    let collection_id_for_res = collection_id.clone();
    let mut detail_res = use_resource(move || admin_get_collection(collection_id_for_res.clone()));
    let groups_res = use_resource(admin_list_groups);
    let mut fullname = use_signal(String::new);
    let mut attach_ds = use_signal(String::new);
    let mut grant_group = use_signal(String::new);
    let mut msg = use_signal(|| None::<String>);
    let mut error_msg = use_signal(|| None::<String>);
    let mut form_seeded = use_signal(|| false);

    let detail = detail_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned();

    if let Some(ref d) = detail {
        if !*form_seeded.read() {
            fullname.set(d.collection.fullname.clone());
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
                ErrorBar { message: "Failed to load collection" }
            } else {
                "Loading..."
            }
        };
    };

    let cname = collection_id.clone();
    let all_groups = groups_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned();
    let datasets = detail.datasets.clone();
    let unassigned = detail.unassigned_datasets.clone();
    let groups_with_access = detail.groups_with_access.clone();

    rsx! {
        if let Some(m) = msg.read().clone() {
            SuccessBar { message: m }
        }
        if let Some(err) = error_msg.read().clone() {
            ErrorBar { message: err }
        }
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Collection" }
            div { style: "{MODULE_BODY} display: flex; gap: 8px; flex-wrap: wrap; align-items: center;",
                input { style: INPUT, placeholder: "display name", value: "{fullname}", oninput: move |e| fullname.set(e.value()) }
                button {
                    style: BTN,
                    onclick: {
                        let cname = cname.clone();
                        move |_| {
                            let cname = cname.clone();
                            let f = fullname.read().clone();
                            spawn(async move {
                                msg.set(None);
                                error_msg.set(None);
                                match admin_update_collection(cname, f).await {
                                    Ok(()) => {
                                        msg.set(Some("The collection was changed successfully.".to_string()));
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
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Datasets" }
            div { style: MODULE_BODY,
                table { style: TABLE,
                    thead {
                        tr {
                            th { style: TH, "Dataset" }
                            th { style: TH, "Name" }
                            th { style: TH, "Type" }
                            th { style: TH, "Created" }
                            th { style: TH, "" }
                        }
                    }
                    tbody {
                        for ds in datasets {
                            tr { key: "{ds.collection_dataset}",
                                td { style: TD,
                                    Link {
                                        to: Route::AdminDatasetPage {
                                            collection_id: collection_id.clone(),
                                            dataset_id: ds.collection_dataset.clone(),
                                        },
                                        style: LINK,
                                        "{ds.collection_dataset}"
                                    }
                                }
                                td { style: TD, "{ds.dataset_name}" }
                                td { style: TD, "{ds.dataset_type}" }
                                td { style: TD, "{ds.date_created}" }
                                td { style: TD,
                                    button {
                                        style: BTN_SMALL_DANGER,
                                        onclick: {
                                            let cd = ds.collection_dataset.clone();
                                            move |_| {
                                                let cd = cd.clone();
                                                spawn(async move {
                                                    if let Err(e) = admin_unassign_dataset(cd).await {
                                                        error_msg.set(Some(e.to_string()));
                                                    }
                                                    detail_res.restart();
                                                });
                                            }
                                        },
                                        "Detach"
                                    }
                                }
                            }
                        }
                    }
                }
                div { style: "display: flex; gap: 8px; margin-top: 12px;",
                    select {
                        style: SELECT,
                        onchange: move |e| attach_ds.set(e.value()),
                        option { value: "", "Attach dataset\u{2026}" }
                        for ds in unassigned {
                            option { key: "{ds}", value: "{ds}", "{ds}" }
                        }
                    }
                    button {
                        style: BTN,
                        onclick: {
                            let cname = cname.clone();
                            move |_| {
                                let cname = cname.clone();
                                let ds = attach_ds.read().clone();
                                if ds.is_empty() {
                                    return;
                                }
                                spawn(async move {
                                    if let Err(e) = admin_assign_dataset(cname, ds).await {
                                        error_msg.set(Some(e.to_string()));
                                    }
                                    detail_res.restart();
                                });
                            }
                        },
                        "Attach"
                    }
                }
            }
        }
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Group permissions" }
            div { style: MODULE_BODY,
                if groups_with_access.is_empty() {
                    p { style: "{HELP_TEXT} margin: 0 0 8px;", "No group can read this collection yet." }
                }
                ul { style: "list-style: none; padding: 0; margin: 0;",
                    for g in groups_with_access {
                        li {
                            key: "{g}",
                            style: "display: flex; gap: 8px; align-items: center; padding: 6px 0; border-bottom: 1px solid #eee; font-size: 13px;",
                            Link {
                                to: Route::AdminGroupPage { groupname: g.clone() },
                                style: "{LINK} flex: 1;",
                                "{g}"
                            }
                            button {
                                style: BTN_SMALL_DANGER,
                                onclick: {
                                    let cname = cname.clone();
                                    let gn = g.clone();
                                    move |_| {
                                        let cname = cname.clone();
                                        let gn = gn.clone();
                                        spawn(async move {
                                            if let Err(e) = admin_revoke_permission(gn, cname).await {
                                                error_msg.set(Some(e.to_string()));
                                            }
                                            detail_res.restart();
                                        });
                                    }
                                },
                                "Revoke"
                            }
                        }
                    }
                }
                if let Some(groups) = all_groups {
                    div { style: "display: flex; gap: 8px; margin-top: 12px;",
                        select {
                            style: SELECT,
                            onchange: move |e| grant_group.set(e.value()),
                            option { value: "", "Grant group\u{2026}" }
                            for g in groups {
                                if !detail.groups_with_access.contains(&g.groupname) {
                                    option { key: "{g.groupname}", value: "{g.groupname}", "{g.groupname}" }
                                }
                            }
                        }
                        button {
                            style: BTN,
                            onclick: {
                                let cname = cname.clone();
                                move |_| {
                                    let cname = cname.clone();
                                    let gn = grant_group.read().clone();
                                    if gn.is_empty() {
                                        return;
                                    }
                                    spawn(async move {
                                        if let Err(e) = admin_grant_permission(gn, cname).await {
                                            error_msg.set(Some(e.to_string()));
                                        }
                                        detail_res.restart();
                                    });
                                }
                            },
                            "Grant"
                        }
                    }
                }
            }
        }
        div { style: MODULE,
            h2 { style: "{MODULE_CAPTION} background: #ba2121;", "Danger zone" }
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 8px;", "A collection can only be deleted after all its datasets are detached." }
                button {
                    style: BTN_DANGER,
                    onclick: {
                        let cname = cname.clone();
                        move |_| {
                            let cname = cname.clone();
                            spawn(async move {
                                match admin_delete_collection(cname).await {
                                    Ok(()) => {
                                        let _ = navigator().push(Route::AdminCollectionsPage {});
                                    }
                                    Err(e) => error_msg.set(Some(e.to_string())),
                                }
                            });
                        }
                    },
                    "Delete collection"
                }
            }
        }
    }
}
