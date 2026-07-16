//! Admin page chrome — Django-admin-style top bar, breadcrumbs, sidebar and content frame.

use dioxus::prelude::*;

use crate::api::auth_api::whoami;
use crate::components::admin_components::{C_ACCENT, C_HEADER, C_LINK, C_YELLOW, FONT, PAGE_TITLE};
use crate::routes::Route;

/// `active` selects the highlighted sidebar row: one of
/// "dashboard", "collections", "users", "groups", "settings".
#[component]
pub fn AdminShell(
    title: String,
    breadcrumb: String,
    active: String,
    children: Element,
) -> Element {
    let user = use_resource(whoami);
    let welcome = user
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .map(|u| {
            if u.fullname.is_empty() {
                u.username.clone()
            } else {
                u.fullname.clone()
            }
        })
        .unwrap_or_default();

    rsx! {
        div {
            style: "display: flex; flex-direction: column; width: 100%; height: 100%; background: white; overflow: auto; {FONT}",
            // Top header bar
            header {
                style: "background: {C_HEADER}; padding: 12px 40px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;",
                Link {
                    to: Route::AdminDashboardPage {},
                    style: "color: {C_YELLOW}; font-size: 22px; font-weight: 400; text-decoration: none;",
                    "Hoover4 administration"
                }
                div {
                    style: "color: white; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; display: flex; gap: 6px; align-items: center;",
                    if !welcome.is_empty() {
                        span { "Welcome, " b { "{welcome}" } "." }
                    }
                    Link {
                        to: Route::HomePage {},
                        style: "color: white; text-decoration: underline;",
                        "View site"
                    }
                }
            }
            // Breadcrumbs bar
            div {
                style: "background: {C_ACCENT}; padding: 10px 40px; color: white; font-size: 13px;",
                Link {
                    to: Route::AdminDashboardPage {},
                    style: "color: white; text-decoration: none;",
                    "Home"
                }
                span { style: "opacity: 0.7;", " \u{203a} " }
                span { "{breadcrumb}" }
            }
            // Sidebar + content
            div {
                style: "display: flex; flex: 1; align-items: stretch; min-height: 0;",
                aside {
                    style: "width: 220px; flex-shrink: 0; background: #f8f8f8; border-right: 1px solid #eaeaea;",
                    div {
                        style: "background: {C_HEADER}; color: white; padding: 10px 16px; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;",
                        "Administration"
                    }
                    SidebarLink { to: Route::AdminDashboardPage {}, label: "Dashboard", selected: active == "dashboard" }
                    SidebarLink { to: Route::AdminCollectionsPage {}, label: "Collections", selected: active == "collections" }
                    SidebarLink { to: Route::AdminUsersPage {}, label: "Users", selected: active == "users" }
                    SidebarLink { to: Route::AdminGroupsPage {}, label: "Groups", selected: active == "groups" }
                    SidebarLink { to: Route::AdminSettingsPage {}, label: "Settings", selected: active == "settings" }
                }
                main {
                    style: "flex: 1; padding: 24px 40px; min-width: 0;",
                    h1 { style: PAGE_TITLE, "{title}" }
                    {children}
                }
            }
        }
    }
}

#[component]
fn SidebarLink(to: Route, label: String, selected: bool) -> Element {
    let row_style = if selected {
        "display: block; padding: 10px 16px; background: #fffbcc; color: #333; font-size: 13px; font-weight: 600; text-decoration: none; border-bottom: 1px solid #eaeaea;".to_string()
    } else {
        format!("display: block; padding: 10px 16px; color: {C_LINK}; font-size: 13px; text-decoration: none; border-bottom: 1px solid #eaeaea;")
    };
    rsx! {
        Link { to: to, style: row_style, "{label}" }
    }
}
