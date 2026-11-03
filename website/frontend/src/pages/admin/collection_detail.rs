//! Admin collection detail page.

use dioxus::prelude::*;

use crate::api::error_util::user_facing_message;
use crate::api::admin_api::{
    admin_delete_collection, admin_get_collection, admin_grant_permission, admin_list_groups,
    admin_revoke_permission, admin_set_collection_public,
    admin_update_collection, admin_get_collection_vectors, admin_set_collection_vectors,
};
use crate::components::admin_components::{
    AdminGuard, AdminShell, DatasetCreatePanel, ErrorBar, ProcessingUpdatesPanel, SuccessBar, UploadsBadge, BTN, BTN_DANGER,
    BTN_SMALL_DANGER, HELP_TEXT, INPUT, LABEL, LINK, MODULE, MODULE_BODY, MODULE_CAPTION, SELECT,
    TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::pages::admin::collections_list::{short_date, DatasetStatCells, DatasetStateCell};
use crate::pages::admin::operations::CollectionOperationsPanel;
use crate::routes::Route;
use crate::tr;

#[component]
pub fn AdminCollectionPage(collection_id: String) -> Element {
    let collection_id_for_content = collection_id.clone();
    rsx! {
        Title { {tr!("admin-collection-detail-admin-collection", collection_id: collection_id.to_string())} }
        AdminGuard {
            AdminShell {
                title: tr!("admin-collection-detail-collection", collection_id: collection_id.to_string()),
                breadcrumb: "Collections".to_string(),
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
                ErrorBar { message: tr!("admin-collection-detail-failed-to-load-collection") }
            } else {
                {tr!("admin-collection-detail-loading")}
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
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-collection-detail-datasets")} }
            div { style: MODULE_BODY,
                table { style: TABLE,
                    thead {
                        tr {
                            th { style: TH, {tr!("admin-collection-detail-dataset")} }
                            th { style: "{TH} text-align: right;", {tr!("admin-collection-detail-documents")} }
                            th { style: "{TH} text-align: right;", {tr!("admin-collection-detail-size")} }
                            th { style: "{TH} text-align: right;", {tr!("admin-collection-detail-indexed")} }
                            th { style: "{TH} text-align: right;", {tr!("admin-collection-detail-errors")} }
                            th { style: TH, {tr!("admin-collection-detail-state")} }
                            th { style: TH, {tr!("admin-collection-detail-created")} }
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
                                        "{ds.dataset_name}"
                                    }
                                    if ds.accepts_uploads { UploadsBadge {} }
                                    if !ds.dataset_display_name.is_empty() && ds.dataset_display_name != ds.dataset_name {
                                        div { style: HELP_TEXT, "{ds.dataset_display_name}" }
                                    }
                                }
                                DatasetStatCells { collectionname: collection_id.clone(), stats: ds.stats.clone() }
                                DatasetStateCell { stats: ds.stats.clone() }
                                td { style: "{TD} white-space: nowrap;", "{short_date(&ds.date_created)}" }
                            }
                        }
                    }
                }
            }
        }
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-collection-detail-settings")} }
            div { style: MODULE_BODY,
                if !detail.collection.db_ready {
                    p { style: "margin: 0 0 8px; color: var(--x-danger);", {tr!("admin-collection-detail-the-collection-database-is-not")} }
                }
                if detail.provisioning_state == "errored" {
                    p { style: "margin: 0 0 8px; color: var(--x-danger);",
                        {tr!("admin-collection-detail-the-last-storage-provisioning-failed", detail_provisioning_error: detail.provisioning_error.to_string())}
                    }
                }
                Link {
                    to: Route::AdminCollectionProcessingPage { collection_id: cname.clone() },
                    style: LINK,
                    {tr!("admin-collection-detail-processing-progress-and-estimates")}
                }
            }
            div { style: "{MODULE_BODY} display: flex; gap: 8px; flex-wrap: wrap; align-items: center;",
                label { style: LABEL,
                    {tr!("admin-collection-detail-display-name")}
                    input { style: INPUT, placeholder: tr!("admin-collection-detail-display-name-2"), value: "{fullname}", oninput: move |e| fullname.set(e.value()) }
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
                                    Err(e) => error_msg.set(Some(user_facing_message(&e))),
                                }
                            });
                        }
                    },
                    {tr!("admin-collection-detail-save")}
                }
            }
        }
        ProcessingUpdatesPanel { scope_kind: "collection".to_string(), scope_id: collection_id.clone() }
        CollectionVectorsControl { collectionname: collection_id.clone() }
        DatasetCreatePanel {
            collectionname: collection_id.clone(),
            existing_datasets: detail.datasets.iter().map(|d| d.dataset_name.clone()).collect::<Vec<_>>(),
            on_created: move |_| detail_res.restart(),
        }
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-collection-detail-access")} }
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 10px;",
                    if detail.collection.is_public {
                        {tr!("admin-collection-detail-public-every-signed-in-user")}
                    } else {
                        {tr!("admin-collection-detail-restricted-only-members-of-the")}
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
                                                    {tr!("admin-collection-detail-the-collection-is-now-public")}.to_string()
                                                } else {
                                                    {tr!("admin-collection-detail-the-collection-is-now-restricted")}.to_string()
                                                },
                                            ));
                                            detail_res.restart();
                                        }
                                        Err(e) => error_msg.set(Some(user_facing_message(&e))),
                                    }
                                });
                            }
                        },
                        if detail.collection.is_public { {tr!("admin-collection-detail-make-restricted")} } else { {tr!("admin-collection-detail-make-public")} }
                    }
                }
            }
        }
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-collection-detail-group-permissions")} }
            div { style: MODULE_BODY,
                if groups_with_access.is_empty() {
                    p { style: "{HELP_TEXT} margin: 0 0 8px;", {tr!("admin-collection-detail-no-group-can-read-this")} }
                }
                ul { style: "list-style: none; padding: 0; margin: 0;",
                    for g in groups_with_access {
                        li {
                            key: "{g}",
                            style: "display: flex; gap: 8px; align-items: center; padding: 6px 0; border-bottom: 1px solid; border-bottom-color: var(--x-border); font-size: var(--x-text-sm);",
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
                                                error_msg.set(Some(user_facing_message(&e)));
                                            }
                                            detail_res.restart();
                                        });
                                    }
                                },
                                {tr!("admin-collection-detail-revoke")}
                            }
                        }
                    }
                }
                if let Some(groups) = all_groups {
                    div { style: "display: flex; gap: 8px; margin-top: 12px;",
                        select {
                            style: SELECT,
                            onchange: move |e| grant_group.set(e.value()),
                            option { value: "", {tr!("admin-collection-detail-grant-group-u")} }
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
                                            error_msg.set(Some(user_facing_message(&e)));
                                        }
                                        detail_res.restart();
                                    });
                                }
                            },
                            {tr!("admin-collection-detail-grant")}
                        }
                    }
                }
            }
        }
        CollectionOperationsPanel { collectionname: cname.clone() }
        div { class: "x-admin-module", style: MODULE,
            h2 { style: "{MODULE_CAPTION} color: var(--x-danger);", {tr!("admin-collection-detail-danger-zone")} }
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 8px;", {tr!("admin-collection-detail-a-collection-can-only-be")} }
                p { style: "{HELP_TEXT} margin: 0 0 8px; color: var(--x-danger);",
                    {tr!("admin-collection-detail-deleting-the-collection-also-drops")}
                    code { {tr!("admin-collection-detail-hoover4-collection", cname: cname.to_string())} }
                    {tr!("admin-collection-detail-and-everything-in-it-this")}
                }
                div { style: "display: flex; gap: 8px; flex-wrap: wrap; align-items: center;",
                    label { style: LABEL,
                        {tr!("admin-collection-detail-collection-name")}
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
                                        Err(e) => error_msg.set(Some(user_facing_message(&e))),
                                    }
                                });
                            }
                        },
                        {tr!("admin-collection-detail-delete-collection")}
                    }
                }
            }
        }
    }
}

/// The Vectors switch of a collection. A collection without its own value follows the
/// installation.
#[component]
fn CollectionVectorsControl(collectionname: String) -> Element {
    let for_res = collectionname.clone();
    let mut state_res = use_resource(move || admin_get_collection_vectors(for_res.clone()));
    let mut error_msg = use_signal(|| None::<String>);
    let mut saving = use_signal(|| false);
    let state = state_res.read().as_ref().and_then(|r| r.as_ref().ok()).cloned();
    let load_error = state_res.read().as_ref().and_then(|r| r.as_ref().err().map(user_facing_message));
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-collection-detail-features")} }
            div { style: MODULE_BODY,
                if let Some(err) = error_msg.read().clone() { ErrorBar { message: err } }
                if let Some(err) = load_error {
                    ErrorBar { message: tr!("admin-collection-detail-the-vectors-setting-could-not", err: err.to_string()) }
                }
                if let Some((enabled, explicit, installation)) = state {
                    label { style: LABEL,
                        input {
                            r#type: "checkbox",
                            class: "x-collection-vectors",
                            checked: enabled,
                            disabled: !installation || *saving.read(),
                            onchange: {
                                let name = collectionname.clone();
                                move |e: Event<FormData>| {
                                    let name = name.clone();
                                    let on = e.checked();
                                    saving.set(true);
                                    spawn(async move {
                                        error_msg.set(None);
                                        if let Err(err) = admin_set_collection_vectors(name, on).await {
                                            error_msg.set(Some(user_facing_message(&err)));
                                        }
                                        saving.set(false);
                                        state_res.restart();
                                    });
                                }
                            },
                        }
                        {tr!("admin-collection-detail-vectors")}
                    }
                    p { style: "{HELP_TEXT} margin: 4px 0 0;",
                        if !installation {
                            {tr!("admin-collection-detail-this-installation-runs-no-embedding")}
                        } else if explicit {
                            {tr!("admin-collection-detail-vectors-find-passages-by-meaning")}
                        } else {
                            {tr!("admin-collection-detail-this-collection-follows-the-installation")}
                        }
                    }
                }
            }
        }
    }
}
