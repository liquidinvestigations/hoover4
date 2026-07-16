//! Admin users list page.

use dioxus::prelude::*;

use crate::api::admin_api::{admin_create_user, admin_list_users};
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, SuccessBar, BTN_PRIMARY, INPUT, LABEL, LINK, MODULE,
    MODULE_BODY, MODULE_CAPTION, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::routes::Route;

#[component]
pub fn AdminUsersPage() -> Element {
    rsx! {
        Title { "Admin — Users" }
        AdminGuard {
            AdminShell {
                title: "Select user to change".to_string(),
                breadcrumb: "Users".to_string(),
                active: "users".to_string(),
                SuspendWrapper { UsersListContent {} }
            }
        }
    }
}

#[component]
fn UsersListContent() -> Element {
    let mut users_res = use_resource(admin_list_users);
    let mut search = use_signal(String::new);
    let mut username = use_signal(String::new);
    let mut fullname = use_signal(String::new);
    let mut email = use_signal(String::new);
    let mut is_admin = use_signal(|| false);
    let mut error_msg = use_signal(|| None::<String>);
    let mut success_msg = use_signal(|| None::<String>);

    rsx! {
        if let Some(msg) = success_msg.read().clone() {
            SuccessBar { message: msg }
        }
        if let Some(err) = error_msg.read().clone() {
            ErrorBar { message: err }
        }
        div { style: "display: flex; gap: 8px; margin-bottom: 16px; align-items: center;",
            span { style: "color: #999; font-size: 16px;", "\u{1F50D}" }
            input {
                style: "{INPUT} flex: 0 1 320px;",
                placeholder: "Search users",
                value: "{search}",
                oninput: move |e| search.set(e.value()),
            }
        }
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Add user" }
            div { style: "{MODULE_BODY} display: flex; gap: 8px; flex-wrap: wrap; align-items: center;",
                input { style: INPUT, placeholder: "username", value: "{username}", oninput: move |e| username.set(e.value()) }
                input { style: INPUT, placeholder: "full name", value: "{fullname}", oninput: move |e| fullname.set(e.value()) }
                input { style: INPUT, placeholder: "email", value: "{email}", oninput: move |e| email.set(e.value()) }
                label { style: LABEL,
                    input { r#type: "checkbox", checked: *is_admin.read(), onchange: move |_| is_admin.toggle() }
                    "Superuser"
                }
                button {
                    style: BTN_PRIMARY,
                    onclick: move |_| {
                        let u = username.read().clone();
                        let f = fullname.read().clone();
                        let e = email.read().clone();
                        let a = *is_admin.read();
                        spawn(async move {
                            error_msg.set(None);
                            success_msg.set(None);
                            match admin_create_user(u.clone(), f, e, a).await {
                                Ok(()) => {
                                    success_msg.set(Some(format!("The user \u{201c}{u}\u{201d} was added successfully.")));
                                    username.set(String::new());
                                    fullname.set(String::new());
                                    email.set(String::new());
                                    is_admin.set(false);
                                    users_res.restart();
                                }
                                Err(err) => error_msg.set(Some(err.to_string())),
                            }
                        });
                    },
                    "Add user +"
                }
            }
        }
        match &*users_res.read() {
            Some(Ok(users)) => {
                let needle = search.read().to_lowercase();
                let filtered: Vec<_> = users
                    .iter()
                    .filter(|u| {
                        needle.is_empty()
                            || u.username.to_lowercase().contains(&needle)
                            || u.fullname.to_lowercase().contains(&needle)
                            || u.email.to_lowercase().contains(&needle)
                    })
                    .cloned()
                    .collect();
                rsx! {
                    table { style: TABLE,
                        thead {
                            tr {
                                th { style: TH, "Username" }
                                th { style: TH, "Full name" }
                                th { style: TH, "Email address" }
                                th { style: TH, "Superuser" }
                                th { style: TH, "Groups" }
                                th { style: TH, "Created" }
                            }
                        }
                        tbody {
                            for user in filtered {
                                tr { key: "{user.username}",
                                    td { style: TD,
                                        Link { to: Route::AdminUserPage { username: user.username.clone() }, style: LINK, "{user.username}" }
                                    }
                                    td { style: TD, "{user.fullname}" }
                                    td { style: TD, "{user.email}" }
                                    td { style: TD,
                                        if user.is_admin {
                                            span { style: "color: #5fa25f; font-weight: 700;", "\u{2714}" }
                                        } else {
                                            span { style: "color: #ba2121;", "\u{2716}" }
                                        }
                                    }
                                    td { style: TD, "{user.group_count}" }
                                    td { style: TD, "{user.created_at}" }
                                }
                            }
                        }
                    }
                }
            }
            Some(Err(e)) => rsx! { ErrorBar { message: "{e}" } },
            None => rsx! { "Loading..." },
        }
    }
}
