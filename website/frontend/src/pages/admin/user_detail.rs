//! Admin user detail page.

use dioxus::prelude::*;

use crate::api::admin_api::{
    admin_add_member, admin_delete_user, admin_get_user, admin_list_groups, admin_remove_member,
    admin_set_group_admin, admin_update_user,
};
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, SuccessBar, BTN, BTN_DANGER, BTN_SMALL_DANGER, HELP_TEXT,
    INPUT, LABEL, MODULE, MODULE_BODY, MODULE_CAPTION, SELECT, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::routes::Route;

#[component]
pub fn AdminUserPage(username: String) -> Element {
    let username_for_content = username.clone();
    rsx! {
        Title { "Admin — User {username}" }
        AdminGuard {
            AdminShell {
                title: "Change user".to_string(),
                breadcrumb: format!("Users \u{203a} {username}"),
                active: "users".to_string(),
                SuspendWrapper {
                    UserDetailContent { username: username_for_content }
                }
            }
        }
    }
}

#[component]
fn UserDetailContent(username: String) -> Element {
    let username_for_res = username.clone();
    let mut detail_res = use_resource(move || admin_get_user(username_for_res.clone()));
    let groups_res = use_resource(admin_list_groups);
    let mut fullname = use_signal(String::new);
    let mut email = use_signal(String::new);
    let mut is_admin = use_signal(|| false);
    let mut add_group = use_signal(String::new);
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
            fullname.set(d.user.fullname.clone());
            email.set(d.user.email.clone());
            is_admin.set(d.user.is_admin);
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
                ErrorBar { message: "Failed to load user" }
            } else {
                "Loading..."
            }
        };
    };

    let uname = detail.user.username.clone();
    let all_groups = groups_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned();
    let memberships = detail.memberships.clone();

    rsx! {
        if let Some(m) = msg.read().clone() {
            SuccessBar { message: m }
        }
        if let Some(err) = error_msg.read().clone() {
            ErrorBar { message: err }
        }
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "User" }
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 12px;",
                    "For header-authenticated users, full name, email and superuser status are overwritten at next login."
                }
                div { style: "display: flex; gap: 8px; flex-wrap: wrap; align-items: center;",
                    input { style: INPUT, placeholder: "full name", value: "{fullname}", oninput: move |e| fullname.set(e.value()) }
                    input { style: INPUT, placeholder: "email", value: "{email}", oninput: move |e| email.set(e.value()) }
                    label { style: LABEL,
                        input { r#type: "checkbox", checked: *is_admin.read(), onchange: move |_| is_admin.toggle() }
                        "Superuser"
                    }
                    button {
                        style: BTN,
                        onclick: {
                            let uname = uname.clone();
                            move |_| {
                                let uname = uname.clone();
                                let f = fullname.read().clone();
                                let e = email.read().clone();
                                let a = *is_admin.read();
                                spawn(async move {
                                    msg.set(None);
                                    error_msg.set(None);
                                    match admin_update_user(uname, f, e, a).await {
                                        Ok(()) => {
                                            msg.set(Some("The user was changed successfully.".to_string()));
                                            detail_res.restart();
                                        }
                                        Err(err) => error_msg.set(Some(err.to_string())),
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
            h2 { style: MODULE_CAPTION, "Groups" }
            div { style: MODULE_BODY,
                table { style: TABLE,
                    thead {
                        tr {
                            th { style: TH, "Group" }
                            th { style: TH, "Origin" }
                            th { style: TH, "Group admin" }
                            th { style: TH, "" }
                        }
                    }
                    tbody {
                        for m in memberships {
                            tr { key: "{m.groupname}",
                                td { style: TD, "{m.groupname}" }
                                td { style: TD,
                                    span { style: "background: #eef4f8; color: #447e9b; padding: 2px 8px; border-radius: 4px; font-size: 11px;", "{m.origin}" }
                                }
                                td { style: TD,
                                    input {
                                        r#type: "checkbox",
                                        checked: m.is_group_admin,
                                        onchange: {
                                            let uname = uname.clone();
                                            let gname = m.groupname.clone();
                                            let val = !m.is_group_admin;
                                            move |_| {
                                                let uname = uname.clone();
                                                let gname = gname.clone();
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
                                            let uname = uname.clone();
                                            let gname = m.groupname.clone();
                                            move |_| {
                                                let uname = uname.clone();
                                                let gname = gname.clone();
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
                if let Some(groups) = all_groups {
                    div { style: "margin-top: 12px; display: flex; gap: 8px;",
                        select {
                            style: SELECT,
                            onchange: move |e| add_group.set(e.value()),
                            option { value: "", "Add to group\u{2026}" }
                            for g in groups {
                                if !detail.memberships.iter().any(|mb| mb.groupname == g.groupname) {
                                    option { key: "{g.groupname}", value: "{g.groupname}", "{g.groupname}" }
                                }
                            }
                        }
                        button {
                            style: BTN,
                            onclick: {
                                let uname = uname.clone();
                                move |_| {
                                    let uname = uname.clone();
                                    let g = add_group.read().clone();
                                    if g.is_empty() {
                                        return;
                                    }
                                    spawn(async move {
                                        if let Err(e) = admin_add_member(g, uname, false).await {
                                            error_msg.set(Some(e.to_string()));
                                        }
                                        detail_res.restart();
                                    });
                                }
                            },
                            "Add"
                        }
                    }
                }
            }
        }
        div { style: MODULE,
            h2 { style: "{MODULE_CAPTION} background: #ba2121;", "Danger zone" }
            div { style: MODULE_BODY,
                button {
                    style: BTN_DANGER,
                    onclick: {
                        let uname = uname.clone();
                        move |_| {
                            let uname = uname.clone();
                            spawn(async move {
                                match admin_delete_user(uname).await {
                                    Ok(()) => {
                                        let _ = navigator().push(Route::AdminUsersPage {});
                                    }
                                    Err(e) => error_msg.set(Some(e.to_string())),
                                }
                            });
                        }
                    },
                    "Delete user"
                }
            }
        }
    }
}
