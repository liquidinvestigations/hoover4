//! Admin group detail page.

use dioxus::prelude::*;

use crate::api::error_util::user_facing_message;
use crate::api::admin_api::{
    admin_add_member, admin_delete_group, admin_get_group, admin_grant_permission,
    admin_list_collections, admin_remove_member, admin_revoke_permission, admin_set_group_admin, admin_set_uploader,
    admin_update_group,
};
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, SuccessBar, BTN, BTN_DANGER, BTN_SMALL_DANGER, HELP_TEXT,
    INPUT, LABEL, MODULE, MODULE_BODY, MODULE_CAPTION, SELECT, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::routes::Route;
use crate::tr;

#[component]
pub fn AdminGroupPage(groupname: String) -> Element {
    let groupname_for_content = groupname.clone();
    rsx! {
        Title { {tr!("admin-group-detail-admin-group", groupname: groupname.to_string())} }
        AdminGuard {
            AdminShell {
                title: tr!("admin-group-detail-group-2", groupname: groupname.to_string()),
                breadcrumb: "Groups".to_string(),
                active: "groups".to_string(),
                SuspendWrapper { GroupDetailContent { groupname: groupname_for_content } }
            }
        }
    }
}

#[component]
fn GroupDetailContent(groupname: String) -> Element {
    let groupname_for_res = groupname.clone();
    let mut membership_busy = use_signal(|| false);
    let mut membership_refreshing = use_signal(|| false);
    let mut detail_res = use_resource(move || {
        let name = groupname_for_res.clone();
        async move {
            let result = admin_get_group(name).await;
            if *membership_refreshing.peek() {
                membership_refreshing.set(false);
                membership_busy.set(false);
            }
            result
        }
    });
    let collections_res = use_resource(admin_list_collections);
    let mut fullname = use_signal(String::new);
    let mut add_user = use_signal(String::new);
    let mut grant_collection = use_signal(String::new);
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
            fullname.set(d.group.fullname.clone());
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
                ErrorBar { message: tr!("admin-group-detail-failed-to-load-group") }
            } else {
                {tr!("admin-group-detail-loading")}
            }
        };
    };

    let gname = groupname.clone();
    let is_reserved = gname == "admin" || gname == "superuser";
    let all_collections = collections_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned();
    let members = detail.members.clone();
    let granted_collections = detail.collections.clone();

    rsx! {
        if let Some(m) = msg.read().clone() {
            SuccessBar { message: m }
        }
        if let Some(err) = error_msg.read().clone() {
            ErrorBar { message: err }
        }
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-group-detail-group")} }
            div { style: "{MODULE_BODY} display: flex; gap: 8px; flex-wrap: wrap; align-items: center;",
                label { style: LABEL,
                    {tr!("admin-group-detail-display-name")}
                    input { style: INPUT, placeholder: tr!("admin-group-detail-display-name-2"), value: "{fullname}", oninput: move |e| fullname.set(e.value()) }
                }
                button {
                    style: BTN,
                    onclick: {
                        let gname = gname.clone();
                        move |_| {
                            let gname = gname.clone();
                            let f = fullname.read().clone();
                            spawn(async move {
                                msg.set(None);
                                error_msg.set(None);
                                match admin_update_group(gname, f).await {
                                    Ok(()) => {
                                        msg.set(Some("The group was changed successfully.".to_string()));
                                        crate::components::session_context::invalidate_storage_tree();
                                        detail_res.restart();
                                    }
                                    Err(e) => error_msg.set(Some(user_facing_message(&e))),
                                }
                            });
                        }
                    },
                    {tr!("admin-group-detail-save")}
                }
            }
        }
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-group-detail-members")} }
            div { style: MODULE_BODY,
                if membership_busy() { p { role: "status", {tr!("admin-group-detail-saving-membership")} } }
                table { style: TABLE,
                    thead {
                        tr {
                            th { style: TH, {tr!("admin-group-detail-username")} }
                            th { style: TH, {tr!("admin-group-detail-origin")} }
                            th { style: TH, {tr!("admin-group-detail-group-admin")} }
                            th { style: TH, {tr!("admin-group-detail-uploader")} }
                            th { style: TH, "" }
                        }
                    }
                    tbody {
                        for m in members {
                            tr { key: "{m.username}",
                                td { style: TD,
                                    Link {
                                        to: Route::AdminUserPage { username: m.username.clone() },
                                        style: "color: var(--x-link); text-decoration: none; font-weight: 600;",
                                        "{m.username}"
                                    }
                                }
                                td { style: TD,
                                    span { style: "background: #eef4f8; color: var(--x-link); padding: 2px 8px; border-radius: 4px; font-size: var(--x-text-xs);", "{m.origin}" }
                                }
                                td { style: TD,
                                    input {
                                        r#type: "checkbox",
                                        aria_label: tr!("admin-group-detail-group-admin"),
                                        checked: m.is_group_admin,
                                        disabled: membership_busy(),
                                        onchange: {
                                            let gname = gname.clone();
                                            let uname = m.username.clone();
                                            let val = !m.is_group_admin;
                                            move |_| {
                                                if *membership_busy.peek() { return; }
                                                let gname = gname.clone();
                                                let uname = uname.clone();
                                                membership_busy.set(true);
                                                spawn(async move {
                                                    if let Err(e) = admin_set_group_admin(gname.clone(), uname, val).await {
                                                        error_msg.set(Some(user_facing_message(&e)));
                                                    }
                                                    membership_refreshing.set(true);
                                                    crate::components::session_context::invalidate_storage_tree();
                                                    detail_res.restart();
                                                });
                                            }
                                        },
                                    }
                                }
                                td { style: TD,
                                    input {
                                        r#type: "checkbox",
                                        aria_label: tr!("admin-group-detail-uploader"),
                                        checked: m.is_uploader,
                                        disabled: membership_busy(),
                                        onchange: {
                                            let gname = gname.clone();
                                            let uname = m.username.clone();
                                            let val = !m.is_uploader;
                                            move |_| {
                                                if *membership_busy.peek() { return; }
                                                let gname = gname.clone();
                                                let uname = uname.clone();
                                                membership_busy.set(true);
                                                spawn(async move {
                                                    if let Err(e) = admin_set_uploader(gname.clone(), uname, val).await {
                                                        error_msg.set(Some(user_facing_message(&e)));
                                                    }
                                                    membership_refreshing.set(true);
                                                    crate::components::session_context::invalidate_storage_tree();
                                                    detail_res.restart();
                                                });
                                            }
                                        },
                                    }
                                }
                                td { style: TD,
                                    button {
                                        style: BTN_SMALL_DANGER,
                                        disabled: membership_busy(),
                                        onclick: {
                                            let gname = gname.clone();
                                            let uname = m.username.clone();
                                            move |_| {
                                                if *membership_busy.peek() { return; }
                                                let gname = gname.clone();
                                                let uname = uname.clone();
                                                membership_busy.set(true);
                                                spawn(async move {
                                                    if let Err(e) = admin_remove_member(gname.clone(), uname).await {
                                                        error_msg.set(Some(user_facing_message(&e)));
                                                    }
                                                    membership_refreshing.set(true);
                                                    crate::components::session_context::invalidate_storage_tree();
                                                    detail_res.restart();
                                                });
                                            }
                                        },
                                        {tr!("admin-group-detail-remove")}
                                    }
                                }
                            }
                        }
                    }
                }
                div { style: "margin-top: 12px; display: flex; gap: 8px;",
                    input { style: INPUT, placeholder: tr!("admin-group-detail-username-to-add"), value: "{add_user}", oninput: move |e| add_user.set(e.value()) }
                    button {
                        style: BTN,
                        disabled: membership_busy(),
                        onclick: {
                            let gname = gname.clone();
                            move |_| {
                                if *membership_busy.peek() { return; }
                                let gname = gname.clone();
                                let u = add_user.read().clone();
                                if u.is_empty() {
                                    return;
                                }
                                membership_busy.set(true);
                                spawn(async move {
                                    if let Err(e) = admin_add_member(gname.clone(), u, false).await {
                                        error_msg.set(Some(user_facing_message(&e)));
                                    } else {
                                        add_user.set(String::new());
                                    }
                                    membership_refreshing.set(true);
                                    crate::components::session_context::invalidate_storage_tree();
                                    detail_res.restart();
                                });
                            }
                        },
                        {tr!("admin-group-detail-add-member")}
                    }
                }
            }
        }
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-group-detail-collection-access")} }
            div { style: MODULE_BODY,
                if granted_collections.is_empty() {
                    p { style: "{HELP_TEXT} margin: 0 0 8px;", {tr!("admin-group-detail-this-group-has-no-collection")} }
                }
                ul { style: "list-style: none; padding: 0; margin: 0;",
                    for c in granted_collections {
                        li {
                            key: "{c}",
                            style: "display: flex; gap: 8px; align-items: center; padding: 6px 0; border-bottom: 1px solid; border-bottom-color: var(--x-border); font-size: var(--x-text-sm);",
                            span { style: "flex: 1;", "{c}" }
                            button {
                                style: BTN_SMALL_DANGER,
                                onclick: {
                                    let gname = gname.clone();
                                    let cn = c.clone();
                                    move |_| {
                                        let gname = gname.clone();
                                        let cn = cn.clone();
                                        spawn(async move {
                                            if let Err(e) = admin_revoke_permission(gname, cn).await {
                                                error_msg.set(Some(user_facing_message(&e)));
                                            }
                                            crate::components::session_context::invalidate_storage_tree();
                                            detail_res.restart();
                                        });
                                    }
                                },
                                {tr!("admin-group-detail-revoke")}
                            }
                        }
                    }
                }
                if let Some(cols) = all_collections {
                    div { style: "display: flex; gap: 8px; margin-top: 12px;",
                        select {
                            style: SELECT,
                            onchange: move |e| grant_collection.set(e.value()),
                            option { value: "", {tr!("admin-group-detail-grant-collection-u")} }
                            for c in cols {
                                if !detail.collections.contains(&c.collectionname) {
                                    option { key: "{c.collectionname}", value: "{c.collectionname}", "{c.collectionname}" }
                                }
                            }
                        }
                        button {
                            style: BTN,
                            onclick: {
                                let gname = gname.clone();
                                move |_| {
                                    let gname = gname.clone();
                                    let cn = grant_collection.read().clone();
                                    if cn.is_empty() {
                                        return;
                                    }
                                    spawn(async move {
                                        if let Err(e) = admin_grant_permission(gname, cn).await {
                                            error_msg.set(Some(user_facing_message(&e)));
                                        }
                                        crate::components::session_context::invalidate_storage_tree();
                                        detail_res.restart();
                                    });
                                }
                            },
                            {tr!("admin-group-detail-grant")}
                        }
                    }
                }
            }
        }
        if !is_reserved {
            div { class: "x-admin-module", style: MODULE,
                h2 { style: "{MODULE_CAPTION} color: var(--x-danger);", {tr!("admin-group-detail-danger-zone")} }
                div { style: MODULE_BODY,
                    button {
                        style: BTN_DANGER,
                        onclick: {
                            let gname = gname.clone();
                            move |_| {
                                let gname = gname.clone();
                                spawn(async move {
                                    match admin_delete_group(gname).await {
                                        Ok(()) => {
                                        crate::components::session_context::invalidate_storage_tree();
                                            let _ = navigator().push(Route::AdminGroupsPage {});
                                        }
                                        Err(e) => error_msg.set(Some(user_facing_message(&e))),
                                    }
                                });
                            }
                        },
                        {tr!("admin-group-detail-delete-group")}
                    }
                }
            }
        }
    }
}
