//! Admin group detail page.

use dioxus::prelude::*;

use crate::api::admin_api::{
    admin_add_member, admin_delete_group, admin_get_group, admin_grant_permission,
    admin_list_collections, admin_remove_member, admin_revoke_permission, admin_set_group_admin,
    admin_update_group,
};
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, SuccessBar, BTN, BTN_DANGER, BTN_SMALL_DANGER, HELP_TEXT,
    INPUT, MODULE, MODULE_BODY, MODULE_CAPTION, SELECT, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::routes::Route;

#[component]
pub fn AdminGroupPage(groupname: String) -> Element {
    let groupname_for_content = groupname.clone();
    rsx! {
        Title { "Admin — Group {groupname}" }
        AdminGuard {
            AdminShell {
                title: "Change group".to_string(),
                breadcrumb: format!("Groups \u{203a} {groupname}"),
                active: "groups".to_string(),
                SuspendWrapper { GroupDetailContent { groupname: groupname_for_content } }
            }
        }
    }
}

#[component]
fn GroupDetailContent(groupname: String) -> Element {
    let groupname_for_res = groupname.clone();
    let mut detail_res = use_resource(move || admin_get_group(groupname_for_res.clone()));
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
                ErrorBar { message: "Failed to load group" }
            } else {
                "Loading..."
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
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Group" }
            div { style: "{MODULE_BODY} display: flex; gap: 8px; flex-wrap: wrap; align-items: center;",
                input { style: INPUT, placeholder: "display name", value: "{fullname}", oninput: move |e| fullname.set(e.value()) }
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
            h2 { style: MODULE_CAPTION, "Members" }
            div { style: MODULE_BODY,
                table { style: TABLE,
                    thead {
                        tr {
                            th { style: TH, "Username" }
                            th { style: TH, "Origin" }
                            th { style: TH, "Group admin" }
                            th { style: TH, "" }
                        }
                    }
                    tbody {
                        for m in members {
                            tr { key: "{m.username}",
                                td { style: TD,
                                    Link {
                                        to: Route::AdminUserPage { username: m.username.clone() },
                                        style: "color: #447e9b; text-decoration: none; font-weight: 600;",
                                        "{m.username}"
                                    }
                                }
                                td { style: TD,
                                    span { style: "background: #eef4f8; color: #447e9b; padding: 2px 8px; border-radius: 4px; font-size: 11px;", "{m.origin}" }
                                }
                                td { style: TD,
                                    input {
                                        r#type: "checkbox",
                                        checked: m.is_group_admin,
                                        onchange: {
                                            let gname = gname.clone();
                                            let uname = m.username.clone();
                                            let val = !m.is_group_admin;
                                            move |_| {
                                                let gname = gname.clone();
                                                let uname = uname.clone();
                                                spawn(async move {
                                                    if let Err(e) = admin_set_group_admin(gname, uname, val).await {
                                                        error_msg.set(Some(e.to_string()));
                                                    }
                                                    detail_res.restart();
                                                });
                                            }
                                        },
                                    }
                                }
                                td { style: TD,
                                    button {
                                        style: BTN_SMALL_DANGER,
                                        onclick: {
                                            let gname = gname.clone();
                                            let uname = m.username.clone();
                                            move |_| {
                                                let gname = gname.clone();
                                                let uname = uname.clone();
                                                spawn(async move {
                                                    if let Err(e) = admin_remove_member(gname, uname).await {
                                                        error_msg.set(Some(e.to_string()));
                                                    }
                                                    detail_res.restart();
                                                });
                                            }
                                        },
                                        "Remove"
                                    }
                                }
                            }
                        }
                    }
                }
                div { style: "margin-top: 12px; display: flex; gap: 8px;",
                    input { style: INPUT, placeholder: "username to add", value: "{add_user}", oninput: move |e| add_user.set(e.value()) }
                    button {
                        style: BTN,
                        onclick: {
                            let gname = gname.clone();
                            move |_| {
                                let gname = gname.clone();
                                let u = add_user.read().clone();
                                if u.is_empty() {
                                    return;
                                }
                                spawn(async move {
                                    if let Err(e) = admin_add_member(gname, u, false).await {
                                        error_msg.set(Some(e.to_string()));
                                    } else {
                                        add_user.set(String::new());
                                    }
                                    detail_res.restart();
                                });
                            }
                        },
                        "Add member"
                    }
                }
            }
        }
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Collection access" }
            div { style: MODULE_BODY,
                if granted_collections.is_empty() {
                    p { style: "{HELP_TEXT} margin: 0 0 8px;", "This group has no collection permissions." }
                }
                ul { style: "list-style: none; padding: 0; margin: 0;",
                    for c in granted_collections {
                        li {
                            key: "{c}",
                            style: "display: flex; gap: 8px; align-items: center; padding: 6px 0; border-bottom: 1px solid #eee; font-size: 13px;",
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
                if let Some(cols) = all_collections {
                    div { style: "display: flex; gap: 8px; margin-top: 12px;",
                        select {
                            style: SELECT,
                            onchange: move |e| grant_collection.set(e.value()),
                            option { value: "", "Grant collection\u{2026}" }
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
        if !is_reserved {
            div { style: MODULE,
                h2 { style: "{MODULE_CAPTION} background: #ba2121;", "Danger zone" }
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
                                            let _ = navigator().push(Route::AdminGroupsPage {});
                                        }
                                        Err(e) => error_msg.set(Some(e.to_string())),
                                    }
                                });
                            }
                        },
                        "Delete group"
                    }
                }
            }
        }
    }
}
