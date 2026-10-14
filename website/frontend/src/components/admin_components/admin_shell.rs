//! Admin page frame: a section navigation list, a breadcrumb line and the page title.

use dioxus::prelude::*;

use dioxus_free_icons::icons::{
    md_action_icons::{MdBugReport, MdDashboard, MdDns, MdHistory, MdQuestionAnswer, MdReportProblem, MdSettings},
    md_device_icons::MdStorage,
    md_editor_icons::MdInsertChart,
    md_social_icons::{MdGroup, MdPerson},
};
use dioxus_free_icons::{Icon, IconShape};

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
                // As wide as its longest label, so the page keeps the rest of the width.
                style: "width: max-content; flex-shrink: 0; height: 100%; overflow-y: auto; padding: 16px 0; background-color: var(--x-surface-muted); border-right: 1px solid; border-right-color: var(--x-border);",
                NavLink { to: Route::AdminDashboardPage {}, icon: MdDashboard, label: "Dashboard", selected: active == "dashboard" }
                NavLink { to: Route::AdminCollectionsPage {}, icon: MdStorage, label: "Collections", selected: active == "collections" }
                NavLink { to: Route::AdminOperationsPage {}, icon: MdHistory, label: "Operations", selected: active == "operations" }
                NavLink { to: crate::pages::admin::failures::failures_route("", ""), icon: MdReportProblem, label: "Errors/Failures", selected: active == "failures" }
                NavLink {
                    to: Route::AdminFeedbackPage { search: String::new(), status: String::new(), page: 1 },
                    icon: MdBugReport,
                    label: "Feedback",
                    selected: active == "feedback",
                }
                NavLink { to: Route::AdminUsersPage {}, icon: MdPerson, label: "Users", selected: active == "users" }
                NavLink { to: Route::AdminGroupsPage {}, icon: MdGroup, label: "Groups", selected: active == "groups" }
                NavLink { to: Route::AdminSettingsPage {}, icon: MdSettings, label: "Settings", selected: active == "settings" }
                NavLink { to: Route::AdminLlmPage {}, icon: MdQuestionAnswer, label: "LLM", selected: active == "llm" }
                NavLink { to: Route::AdminAiStatusPage {}, icon: MdDns, label: "AI status", selected: active == "ai_status" }
                NavLink { to: Route::AdminMetricsPage {}, icon: MdInsertChart, label: "Metrics", selected: active == "metrics" }
            }
            main {
                style: "flex: 1; min-width: 0; height: 100%; overflow: auto; padding: 15px 23px 23px;",
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
fn NavLink<T: IconShape + Clone + PartialEq + 'static>(
    to: Route,
    icon: T,
    label: String,
    selected: bool,
) -> Element {
    let row_style = if selected {
        "display: flex; align-items: center; gap: 10px; padding: 8px 20px 8px 16px; color: var(--x-ink-strong); background-color: var(--x-selected); font-size: var(--x-text-md); font-weight: 600; text-decoration: none; white-space: nowrap;"
    } else {
        "display: flex; align-items: center; gap: 10px; padding: 8px 20px 8px 16px; color: var(--x-ink); background-color: transparent; font-size: var(--x-text-md); font-weight: 400; text-decoration: none; white-space: nowrap;"
    };
    rsx! {
        Link { to: to, style: row_style,
            Icon { icon: icon, style: "width: 20px; height: 20px; flex-shrink: 0; color: var(--x-ink-muted);" }
            "{label}"
        }
    }
}
