//! Admin users list page.

use dioxus::prelude::*;

use crate::api::admin_api::admin_list_users;
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, INPUT, LINK, TABLE, TD, TH,
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
    let users_res = use_resource(admin_list_users);
    let mut search = use_signal(String::new);

    rsx! {
        div { style: "display: flex; gap: 8px; margin-bottom: 16px; align-items: center;",
            span { style: "color: #999; font-size: 16px;", "\u{1F50D}" }
            input {
                style: "{INPUT} flex: 0 1 320px;",
                placeholder: "Search users",
                value: "{search}",
                oninput: move |e| search.set(e.value()),
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
                                th { style: TH, "Last login" }
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
                                    td { style: TD,
                                        if let Some(ref last_login) = user.last_login {
                                            "{last_login}"
                                        } else {
                                            "\u{2014}"
                                        }
                                    }
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
