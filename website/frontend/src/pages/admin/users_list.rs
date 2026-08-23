//! Admin users list page.

use dioxus::prelude::*;

use crate::api::error_util::user_facing_message;
use crate::api::admin_api::admin_list_users;
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, HELP_TEXT, INPUT, LINK, TABLE, TD, TH,
};
use crate::components::session_gate::use_session_user;
use crate::components::suspend_boundary::SuspendWrapper;
use crate::routes::Route;

#[component]
pub fn AdminUsersPage() -> Element {
    rsx! {
        Title { "Admin: users" }
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

    // The SUPERUSER column is the stored account flag, and on a demo deployment that is
    // not the whole answer: an anonymous `guest-*` session is treated as an administrator
    // for as long as it lasts, while its row keeps `is_admin = false`. The two are
    // supposed to disagree (the grant belongs to the deployment, not to the account)
    // but a reader comparing this table against what `whoami` says about them has no way
    // to know that from the table alone. The current session is the evidence: being a
    // guest and an admin at once is only possible under that grant.
    let session = use_session_user();
    let guest_admin_grant = session
        .as_ref()
        .is_some_and(|user| user.is_guest && user.is_admin);

    rsx! {
        if guest_admin_grant {
            p { style: "{HELP_TEXT} margin: 0 0 16px;",
                "Demo mode is on: any visitor without a proxy identity gets an anonymous guest session with administrator access, for the length of that session. The Superuser column below is the stored account flag and does not include that grant, so guest accounts correctly read as not superusers while still reaching every page in this section."
            }
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
            Some(Err(e)) => rsx! { ErrorBar { message: user_facing_message(e) } },
            None => rsx! { "Loading..." },
        }
    }
}
