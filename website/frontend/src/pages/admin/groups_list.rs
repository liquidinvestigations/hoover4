//! Admin groups list page.

use dioxus::prelude::*;

use crate::api::admin_api::{admin_create_group, admin_list_groups};
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, SuccessBar, BTN_PRIMARY, INPUT, LINK, MODULE, MODULE_BODY,
    MODULE_CAPTION, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::routes::Route;

#[component]
pub fn AdminGroupsPage() -> Element {
    rsx! {
        Title { "Admin — Groups" }
        AdminGuard {
            AdminShell {
                title: "Select group to change".to_string(),
                breadcrumb: "Groups".to_string(),
                active: "groups".to_string(),
                SuspendWrapper { GroupsListContent {} }
            }
        }
    }
}

#[component]
fn GroupsListContent() -> Element {
    let mut groups_res = use_resource(admin_list_groups);
    let mut groupname = use_signal(String::new);
    let mut fullname = use_signal(String::new);
    let mut error_msg = use_signal(|| None::<String>);
    let mut success_msg = use_signal(|| None::<String>);

    rsx! {
        if let Some(msg) = success_msg.read().clone() {
            SuccessBar { message: msg }
        }
        if let Some(err) = error_msg.read().clone() {
            ErrorBar { message: err }
        }
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Add group" }
            div { style: "{MODULE_BODY} display: flex; gap: 8px; flex-wrap: wrap; align-items: center;",
                input { style: INPUT, placeholder: "groupname", value: "{groupname}", oninput: move |e| groupname.set(e.value()) }
                input { style: INPUT, placeholder: "display name", value: "{fullname}", oninput: move |e| fullname.set(e.value()) }
                button {
                    style: BTN_PRIMARY,
                    onclick: move |_| {
                        let g = groupname.read().clone();
                        let f = fullname.read().clone();
                        spawn(async move {
                            error_msg.set(None);
                            success_msg.set(None);
                            match admin_create_group(g.clone(), f).await {
                                Ok(()) => {
                                    success_msg.set(Some(format!("The group \u{201c}{g}\u{201d} was added successfully.")));
                                    groupname.set(String::new());
                                    fullname.set(String::new());
                                    groups_res.restart();
                                }
                                Err(e) => error_msg.set(Some(e.to_string())),
                            }
                        });
                    },
                    "Add group +"
                }
            }
        }
        match &*groups_res.read() {
            Some(Ok(groups)) => rsx! {
                table { style: TABLE,
                    thead {
                        tr {
                            th { style: TH, "Group" }
                            th { style: TH, "Display name" }
                            th { style: TH, "Members" }
                            th { style: TH, "Collections" }
                        }
                    }
                    tbody {
                        for g in groups.clone() {
                            tr { key: "{g.groupname}",
                                td { style: TD,
                                    Link { to: Route::AdminGroupPage { groupname: g.groupname.clone() }, style: LINK, "{g.groupname}" }
                                }
                                td { style: TD, "{g.fullname}" }
                                td { style: TD, "{g.member_count}" }
                                td { style: TD, "{g.collection_count}" }
                            }
                        }
                    }
                }
            },
            Some(Err(e)) => rsx! { ErrorBar { message: "{e}" } },
            None => rsx! { "Loading..." },
        }
    }
}
