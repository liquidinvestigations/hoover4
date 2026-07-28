//! Admin collection detail page.

use dioxus::prelude::*;

use crate::api::admin_api::{
    admin_delete_collection, admin_get_collection, admin_grant_permission, admin_list_groups,
    admin_revoke_permission, admin_set_collection_public, admin_update_collection,
};
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, SuccessBar, BTN, BTN_DANGER, BTN_SMALL_DANGER, HELP_TEXT,
    INPUT, LABEL, LINK, MODULE, MODULE_BODY, MODULE_CAPTION, SELECT, TABLE, TD, TH,
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
    let mut grant_group = use_signal(String::new);
    let mut delete_confirm = use_signal(String::new);
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
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 8px;",
                    "Database "
                    code { "Hoover4_Collection_{cname}" }
                    if detail.collection.db_ready {
                        span { style: "color: #5fa25f; font-weight: 700;", " \u{2714} ready" }
                    } else {
                        span { style: "color: #ba2121;", " \u{2026} provisioning" }
                    }
                }
                Link {
                    to: Route::AdminCollectionProcessingPage { collection_id: cname.clone() },
                    style: LINK,
                    "Processing status, workflows and failures \u{2192}"
                }
            }
            div { style: "{MODULE_BODY} display: flex; gap: 8px; flex-wrap: wrap; align-items: center;",
                label { style: LABEL,
                    "Display name"
                    input { style: INPUT, placeholder: "display name", value: "{fullname}", oninput: move |e| fullname.set(e.value()) }
                }
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
                p { style: "{HELP_TEXT} margin: 0 0 8px;",
                    "A dataset's collection is fixed when it is created and cannot be changed."
                }
                table { style: TABLE,
                    thead {
                        tr {
                            th { style: TH, "Dataset" }
                            th { style: TH, "Name" }
                            th { style: TH, "Type" }
                            th { style: TH, "Created" }
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
                                td { style: TD, "{ds.dataset_display_name}" }
                                td { style: TD, "{ds.dataset_type}" }
                                td { style: TD, "{ds.date_created}" }
                            }
                        }
                    }
                }
            }
        }
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Access mode" }
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 10px;",
                    if detail.collection.is_public {
                        "Public \u{2014} every signed-in user can search and read this collection. The group grants below still apply but are redundant while it is public."
                    } else {
                        "Restricted \u{2014} only members of the groups listed below can search and read this collection."
                    }
                }
                div { style: "display: flex; gap: 8px; align-items: center;",
                    button {
                        style: if detail.collection.is_public { BTN } else { BTN_DANGER },
                        onclick: {
                            let cname = cname.clone();
                            let make_public = !detail.collection.is_public;
                            move |_| {
                                let cname = cname.clone();
                                spawn(async move {
                                    msg.set(None);
                                    error_msg.set(None);
                                    match admin_set_collection_public(cname, make_public).await {
                                        Ok(()) => {
                                            msg.set(Some(
                                                if make_public {
                                                    "The collection is now public.".to_string()
                                                } else {
                                                    "The collection is now restricted.".to_string()
                                                },
                                            ));
                                            detail_res.restart();
                                        }
                                        Err(e) => error_msg.set(Some(e.to_string())),
                                    }
                                });
                            }
                        },
                        if detail.collection.is_public { "Make restricted" } else { "Make public" }
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
                p { style: "{HELP_TEXT} margin: 0 0 8px;", "A collection can only be deleted while it has no datasets." }
                p { style: "{HELP_TEXT} margin: 0 0 8px; color: #ba2121;",
                    "Deleting the collection also drops its database "
                    code { "Hoover4_Collection_{cname}" }
                    " and everything in it. This cannot be undone. Type the collection name to confirm."
                }
                div { style: "display: flex; gap: 8px; flex-wrap: wrap; align-items: center;",
                    label { style: LABEL,
                        "Collection name"
                        input {
                            style: INPUT,
                            placeholder: "{cname}",
                            value: "{delete_confirm}",
                            oninput: move |e| delete_confirm.set(e.value()),
                        }
                    }
                    button {
                        style: BTN_DANGER,
                        disabled: *delete_confirm.read() != cname,
                        onclick: {
                            let cname = cname.clone();
                            move |_| {
                                let cname = cname.clone();
                                if *delete_confirm.read() != cname {
                                    error_msg.set(Some("Type the collection name to confirm deletion.".to_string()));
                                    return;
                                }
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
}
