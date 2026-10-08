//! Admin page frame: a section navigation list, a breadcrumb line and the page title.

use dioxus::prelude::*;

use crate::components::admin_components::{FONT, PAGE_TITLE};
use crate::routes::Route;

/// `active` selects the highlighted navigation row: one of
/// "dashboard", "collections", "operations", "failures", "feedback", "users", "groups", "settings",
/// "llm", "ai_status", "metrics".
///
/// `breadcrumb` is the path below Administration, for example "Collections › testdata".
#[component]
pub fn AdminShell(
    title: String,
    breadcrumb: String,
    active: String,
    children: Element,
) -> Element {
    rsx! {
        div {
            style: "display: flex; width: 100%; height: 100%; background: white; {FONT}",
            nav {
                "aria-label": "Administration",
                style: "width: 200px; flex-shrink: 0; height: 100%; overflow-y: auto; padding: 16px 0; background: var(--x-surface-muted); border-right: 1px solid var(--x-border);",
                NavLink { to: Route::AdminDashboardPage {}, label: "Dashboard", selected: active == "dashboard" }
                NavLink { to: Route::AdminCollectionsPage {}, label: "Collections", selected: active == "collections" }
                NavLink { to: Route::AdminOperationsPage {}, label: "Operations", selected: active == "operations" }
                NavLink { to: Route::AdminFailuresPage {}, label: "Failures", selected: active == "failures" }
                NavLink {
                    to: Route::AdminFeedbackPage { search: String::new(), status: String::new(), page: 1 },
                    label: "Feedback",
                    selected: active == "feedback",
                }
                NavLink { to: Route::AdminUsersPage {}, label: "Users", selected: active == "users" }
                NavLink { to: Route::AdminGroupsPage {}, label: "Groups", selected: active == "groups" }
                NavLink { to: Route::AdminSettingsPage {}, label: "Settings", selected: active == "settings" }
                NavLink { to: Route::AdminLlmPage {}, label: "LLM", selected: active == "llm" }
                NavLink { to: Route::AdminAiStatusPage {}, label: "AI status", selected: active == "ai_status" }
                NavLink { to: Route::AdminMetricsPage {}, label: "Metrics", selected: active == "metrics" }
            }
            main {
                style: "flex: 1; min-width: 0; height: 100%; overflow: auto; padding: 16px 32px 32px;",
                div {
                    style: "font-size: var(--x-text-sm); color: var(--x-ink-muted); margin-bottom: 8px;",
                    Link {
                        to: Route::AdminDashboardPage {},
                        style: "color: var(--x-ink-muted); text-decoration: none;",
                        "Administration"
                    }
                    if !breadcrumb.is_empty() {
                        span { " \u{203a} {breadcrumb}" }
                    }
                }
                h1 { style: PAGE_TITLE, "{title}" }
                {children}
            }
        }
    }
}

#[component]
fn NavLink(to: Route, label: String, selected: bool) -> Element {
    let row_style = if selected {
        "display: block; padding: 8px 20px; color: var(--x-ink-strong); background: var(--x-selected); font-size: var(--x-text-md); font-weight: 600; text-decoration: none;"
    } else {
        "display: block; padding: 8px 20px; color: var(--x-ink); font-size: var(--x-text-md); text-decoration: none;"
    };
    rsx! {
        Link { to: to, style: row_style, "{label}" }
    }
}
