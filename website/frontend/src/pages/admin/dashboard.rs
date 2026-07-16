//! Admin dashboard page.

use dioxus::prelude::*;

use crate::api::admin_api::admin_dashboard_counts;
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, C_HEADER, C_LINK, MODULE, MODULE_CAPTION,
};
use crate::components::suspend_boundary::{LoadingIndicator, SuspendWrapper};
use crate::routes::Route;

#[component]
pub fn AdminDashboardPage() -> Element {
    rsx! {
        Title { "Admin — Dashboard" }
        AdminGuard {
            AdminShell {
                title: "Site administration".to_string(),
                breadcrumb: "Dashboard".to_string(),
                active: "dashboard".to_string(),
                SuspendWrapper { DashboardContent {} }
            }
        }
    }
}

#[component]
fn DashboardContent() -> Element {
    let counts = use_resource(admin_dashboard_counts);
    rsx! {
        match &*counts.read() {
            Some(Ok((users, groups, collections, datasets))) => rsx! {
                div {
                    style: "display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 20px; max-width: 1000px;",
                    DashboardCard { label: "Users", count: *users, to: Route::AdminUsersPage {} }
                    DashboardCard { label: "Groups", count: *groups, to: Route::AdminGroupsPage {} }
                    DashboardCard { label: "Collections", count: *collections, to: Route::AdminCollectionsPage {} }
                    DashboardCard { label: "Datasets", count: *datasets, to: Route::AdminCollectionsPage {} }
                }
            },
            Some(Err(e)) => rsx! { ErrorBar { message: "Failed to load counts: {e}" } },
            None => rsx! { LoadingIndicator {} },
        }
    }
}

#[component]
fn DashboardCard(label: String, count: u32, to: Route) -> Element {
    rsx! {
        div {
            style: MODULE,
            div { style: MODULE_CAPTION, "{label}" }
            Link {
                to: to,
                style: "display: block; padding: 16px 12px; text-decoration: none;",
                div { style: "font-size: 32px; font-weight: 600; color: {C_HEADER};", "{count}" }
                div { style: "color: {C_LINK}; font-size: 12px; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px;", "Manage {label}" }
            }
        }
    }
}
