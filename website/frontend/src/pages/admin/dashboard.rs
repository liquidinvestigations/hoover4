//! Admin dashboard page.

use dioxus::prelude::*;

use crate::api::admin_api::admin_dashboard_counts;
use crate::components::admin_components::{AdminGuard, AdminShell, ErrorBar};
use crate::pages::admin::collections_list::DATASETS_SECTION_ID;
use crate::components::suspend_boundary::{LoadingIndicator, SuspendWrapper};
use crate::routes::Route;

#[component]
pub fn AdminDashboardPage() -> Element {
    rsx! {
        Title { "Admin: dashboard" }
        AdminGuard {
            AdminShell {
                title: "Administration".to_string(),
                breadcrumb: String::new(),
                active: "dashboard".to_string(),
                SuspendWrapper { DashboardContent {} }
            }
        }
    }
}

#[component]
fn DashboardContent() -> Element {
    let counts = use_resource(admin_dashboard_counts);
    // A route has no fragment, so the Datasets card is a plain link that opens the
    // Collections page at its Datasets section.
    let datasets_href = format!("{}#{DATASETS_SECTION_ID}", Route::AdminCollectionsPage {});
    rsx! {
        match &*counts.read() {
            Some(Ok((users, groups, collections, datasets))) => rsx! {
                div {
                    style: "display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 16px; max-width: 900px;",
                    DashboardCard { label: "Users", count: *users, href: Route::AdminUsersPage {}.to_string() }
                    DashboardCard { label: "Groups", count: *groups, href: Route::AdminGroupsPage {}.to_string() }
                    DashboardCard { label: "Collections", count: *collections, href: Route::AdminCollectionsPage {}.to_string() }
                    DashboardCard { label: "Datasets", count: *datasets, href: datasets_href.clone() }
                }
            },
            Some(Err(e)) => rsx! { ErrorBar { message: "Failed to load counts: {e}" } },
            None => rsx! { LoadingIndicator {} },
        }
    }
}

#[component]
fn DashboardCard(label: String, count: u32, href: String) -> Element {
    rsx! {
        a {
            class: "x-admin-dashboard-card",
            href: "{href}",
            style: "display: flex; flex-direction: column; gap: 4px; padding: 16px 18px; border: 1px solid; border-color: var(--x-border); border-radius: var(--x-radius); text-decoration: none; background: white;",
            span { style: "font-size: var(--x-text-lg); font-weight: 600; color: var(--x-ink-strong);", "{label}" }
            span { style: "font-size: 28px; font-weight: 500; color: var(--x-ink-strong);", "{count}" }
        }
    }
}
