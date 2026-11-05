//! Admin user detail page.

use dioxus::prelude::*;

use crate::api::error_util::user_facing_message;
use crate::api::admin_api::{
    admin_add_member, admin_delete_user, admin_get_user, admin_list_groups, admin_remove_member,
    admin_set_group_admin, admin_set_uploader, admin_update_user,
};
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, SuccessBar, BTN, BTN_DANGER, BTN_SMALL_DANGER, HELP_TEXT,
    INPUT, LABEL, LINK, MODULE, MODULE_BODY, MODULE_CAPTION, SELECT, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::routes::Route;
use crate::tr;

#[component]
pub fn AdminUserPage(username: String) -> Element {
    let username_for_content = username.clone();
    rsx! {
        Title { {tr!("admin-user-detail-admin-user", username: username.to_string())} }
        AdminGuard {
            AdminShell {
                title: tr!("admin-user-detail-user-2", username: username.to_string()),
                breadcrumb: "Users".to_string(),
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
    let mut membership_busy = use_signal(|| false);
    let mut membership_refreshing = use_signal(|| false);
    let mut detail_res = use_resource(move || {
        let name = username_for_res.clone();
        async move {
            let result = admin_get_user(name).await;
            if *membership_refreshing.peek() {
                membership_refreshing.set(false);
                membership_busy.set(false);
            }
            result
        }
    });
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
                ErrorBar { message: tr!("admin-user-detail-failed-to-load-user") }
            } else {
                {tr!("admin-user-detail-loading")}
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
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-user-detail-user")} }
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 12px;",
                    {tr!("admin-user-detail-the-next-login-replaces-the")}
                }
                p { style: "margin: 0 0 12px;",
                    Link {
                        to: Route::AdminUserLlmPage { username: uname.clone() },
                        style: LINK,
                        {tr!("admin-user-detail-llm-usage-u")}
                    }
                }
                div { style: "display: flex; gap: 8px; flex-wrap: wrap; align-items: center;",
                    label { style: LABEL,
                        {tr!("admin-user-detail-full-name")}
                        input { style: INPUT, placeholder: tr!("admin-user-detail-full-name-2"), value: "{fullname}", oninput: move |e| fullname.set(e.value()) }
                    }
                    label { style: LABEL,
                        {tr!("admin-user-detail-email")}
                        input { style: INPUT, placeholder: tr!("admin-user-detail-email-2"), value: "{email}", oninput: move |e| email.set(e.value()) }
                    }
                    label { style: LABEL,
                        input { r#type: "checkbox", checked: *is_admin.read(), onchange: move |_| is_admin.toggle() }
                        {tr!("admin-user-detail-superuser")}
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
                                            crate::components::session_context::invalidate_storage_tree();
                                            detail_res.restart();
                                        }
                                        Err(err) => error_msg.set(Some(err.to_string())),
                                    }
                                });
                            }
                        },
                        {tr!("admin-user-detail-save")}
                    }
                }
            }
        }
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-user-detail-groups")} }
            div { style: MODULE_BODY,
                if membership_busy() { p { role: "status", {tr!("admin-user-detail-saving-membership")} } }
                table { style: TABLE,
                    thead {
                        tr {
                            th { style: TH, {tr!("admin-user-detail-group")} }
                            th { style: TH, {tr!("admin-user-detail-origin")} }
                            th { style: TH, {tr!("admin-user-detail-group-admin")} }
                            th { style: TH, {tr!("admin-user-detail-uploader")} }
                            th { style: TH, "" }
                        }
                    }
                    tbody {
                        for m in memberships {
                            tr { key: "{m.groupname}",
                                td { style: TD, "{m.groupname}" }
                                td { style: TD,
                                    span { style: "background: #eef4f8; color: var(--x-link); padding: 2px 8px; border-radius: 4px; font-size: var(--x-text-xs);", "{m.origin}" }
                                }
                                td { style: TD,
                                    input {
                                        r#type: "checkbox",
                                        aria_label: tr!("admin-user-detail-group-admin"),
                                        checked: m.is_group_admin,
                                        disabled: membership_busy(),
                                        onchange: {
                                            let uname = uname.clone();
                                            let gname = m.groupname.clone();
                                            let val = !m.is_group_admin;
                                            move |_| {
                                                if *membership_busy.peek() { return; }
                                                let uname = uname.clone();
                                                let gname = gname.clone();
                                                membership_busy.set(true);
                                                spawn(async move {
                                                    if let Err(e) = admin_set_group_admin(gname, uname.clone(), val).await {
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
                                        aria_label: tr!("admin-user-detail-uploader"),
                                        checked: m.is_uploader,
                                        disabled: membership_busy(),
                                        onchange: {
                                            let uname = uname.clone();
                                            let gname = m.groupname.clone();
                                            let val = !m.is_uploader;
                                            move |_| {
                                                if *membership_busy.peek() { return; }
                                                let uname = uname.clone();
                                                let gname = gname.clone();
                                                membership_busy.set(true);
                                                spawn(async move {
                                                    if let Err(e) = admin_set_uploader(gname, uname.clone(), val).await {
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
                                            let uname = uname.clone();
                                            let gname = m.groupname.clone();
                                            move |_| {
                                                if *membership_busy.peek() { return; }
                                                let uname = uname.clone();
                                                let gname = gname.clone();
                                                membership_busy.set(true);
                                                spawn(async move {
                                                    if let Err(e) = admin_remove_member(gname, uname.clone()).await {
                                                        error_msg.set(Some(user_facing_message(&e)));
                                                    }
                                                    membership_refreshing.set(true);
                                                    crate::components::session_context::invalidate_storage_tree();
                                                    detail_res.restart();
                                                });
                                            }
                                        },
                                        {tr!("admin-user-detail-remove")}
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
                            option { value: "", {tr!("admin-user-detail-add-to-group-u")} }
                            for g in groups {
                                if !detail.memberships.iter().any(|mb| mb.groupname == g.groupname) {
                                    option { key: "{g.groupname}", value: "{g.groupname}", "{g.groupname}" }
                                }
                            }
                        }
                        button {
                            style: BTN,
                            disabled: membership_busy(),
                            onclick: {
                                let uname = uname.clone();
                                move |_| {
                                    if *membership_busy.peek() { return; }
                                    let uname = uname.clone();
                                    let g = add_group.read().clone();
                                    if g.is_empty() {
                                        return;
                                    }
                                    membership_busy.set(true);
                                    spawn(async move {
                                        if let Err(e) = admin_add_member(g, uname.clone(), false).await {
                                            error_msg.set(Some(user_facing_message(&e)));
                                        }
                                        membership_refreshing.set(true);
                                        crate::components::session_context::invalidate_storage_tree();
                                        detail_res.restart();
                                    });
                                }
                            },
                            {tr!("admin-user-detail-add")}
                        }
                    }
                }
            }
        }
        div { class: "x-admin-module", style: MODULE,
            h2 { style: "{MODULE_CAPTION} color: var(--x-danger);", {tr!("admin-user-detail-danger-zone")} }
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
                                        crate::components::session_context::invalidate_storage_tree();
                                        let _ = navigator().push(Route::AdminUsersPage {});
                                    }
                                    Err(e) => error_msg.set(Some(user_facing_message(&e))),
                                }
                            });
                        }
                    },
                    {tr!("admin-user-detail-delete-user")}
                }
            }
        }
    }
}
