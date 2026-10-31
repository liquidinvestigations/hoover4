//! Admin groups list page.

use dioxus::prelude::*;

use crate::api::admin_api::{admin_create_group, admin_list_groups};
use crate::api::error_util::user_facing_message;
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, HELP_TEXT, SuccessBar, BTN_PRIMARY, INPUT, LINK, MODULE, MODULE_BODY,
    MODULE_CAPTION, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::routes::Route;
use crate::tr;

#[component]
pub fn AdminGroupsPage() -> Element {
    rsx! {
        Title { {tr!("admin-groups-list-admin-groups")} }
        AdminGuard {
            AdminShell {
                title: tr!("admin-groups-list-groups").to_string(),
                breadcrumb: String::new(),
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
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-groups-list-add-group")} }
            div { style: "{MODULE_BODY} display: flex; gap: 8px; flex-wrap: wrap; align-items: center;",
                input { style: INPUT, placeholder: tr!("admin-groups-list-groupname"), value: "{groupname}", oninput: move |e| groupname.set(e.value()) }
                input { style: INPUT, placeholder: tr!("admin-groups-list-display-name"), value: "{fullname}", oninput: move |e| fullname.set(e.value()) }
                // The rule, next to the field it constrains. The dataset form on the
                // collection page states its own the same way; this one asked for a
                // value in a format it never named, so the first thing a person types
                // ("TestGroup") is rejected by a rule they had no way to know.
                p { style: "{HELP_TEXT} width: 100%; margin: 0;",
                    {tr!("admin-groups-list-use-lowercase-letters-digits-underscores")}
                }
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
                                    success_msg.set(Some(tr!("admin-groups-list-the-group-was-added-successfully", g: g.to_string())));
                                    groupname.set(String::new());
                                    fullname.set(String::new());
                                    groups_res.restart();
                                }
                                Err(e) => error_msg.set(Some(user_facing_message(&e))),
                            }
                        });
                    },
                    {tr!("admin-groups-list-add-group-2")}
                }
            }
        }
        match &*groups_res.read() {
            Some(Ok(groups)) => rsx! {
                table { style: TABLE,
                    thead {
                        tr {
                            th { style: TH, {tr!("admin-groups-list-group")} }
                            th { style: TH, {tr!("admin-groups-list-display-name-2")} }
                            th { style: TH, {tr!("admin-groups-list-members")} }
                            th { style: TH, {tr!("admin-groups-list-collections")} }
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
            Some(Err(e)) => rsx! { ErrorBar { message: user_facing_message(e) } },
            None => rsx! { {tr!("admin-groups-list-loading")} },
        }
    }
}
