//! One operation, its re-run counts, plans and Error events.

use common::operations_types::{rerun_outcome_summary, OperationDetail};
use dioxus::prelude::*;

use crate::api::admin_api::admin_get_operation_detail;
use crate::api::error_util::user_facing_message;
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, BTN_SMALL, HELP_TEXT, LINK, MODULE, MODULE_BODY,
    MODULE_CAPTION, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::routes::Route;
use crate::tr;

#[component]
pub fn AdminOperationDetailPage(op_id: String, plans_page: u32, events_page: u32) -> Element {
    rsx! {
        Title { {tr!("admin-operation-detail-admin-operation", op_id: op_id.to_string())} }
        AdminGuard {
            AdminShell {
                title: tr!("admin-operation-detail-operation-2", op_id: op_id.to_string()),
                breadcrumb: "Operations".to_string(),
                active: "operations".to_string(),
                SuspendWrapper { OperationDetailContent { op_id, plans_page, events_page } }
            }
        }
    }
}

#[component]
fn OperationDetailContent(op_id: String, plans_page: u32, events_page: u32) -> Element {
    let mut detail_op_id = use_signal(|| op_id.clone());
    let mut detail_plans_page = use_signal(|| plans_page);
    let mut detail_events_page = use_signal(|| events_page);
    if *detail_op_id.read() != op_id {
        detail_op_id.set(op_id);
    }
    if *detail_plans_page.read() != plans_page {
        detail_plans_page.set(plans_page);
    }
    if *detail_events_page.read() != events_page {
        detail_events_page.set(events_page);
    }

    let detail_res = use_resource(move || {
        let id = detail_op_id();
        let plan_page = detail_plans_page();
        let event_page = detail_events_page();
        async move { admin_get_operation_detail(id, plan_page, event_page).await }
    });
    let data = detail_res
        .read()
        .as_ref()
        .and_then(|result| result.as_ref().ok())
        .cloned();
    let load_error = detail_res
        .read()
        .as_ref()
        .and_then(|result| result.as_ref().err().map(user_facing_message));

    let Some(data) = data else {
        return rsx! {
            if let Some(error) = load_error {
                ErrorBar { message: error }
            } else {
                p { style: HELP_TEXT, {tr!("admin-operation-detail-loading-operation")} }
            }
        };
    };

    rsx! {
        OperationDetailBody {
            data,
            plans_page: detail_plans_page(),
            events_page: detail_events_page(),
        }
    }
}

#[component]
fn OperationDetailBody(data: OperationDetail, plans_page: u32, events_page: u32) -> Element {
    let row = data.row.clone();
    let plan_has_more = (u64::from(plans_page) + 1) * u64::from(data.page_size) < data.plans_total;
    let event_has_more = (u64::from(events_page) + 1) * u64::from(data.page_size) < data.events_total;
    rsx! {
        p { style: HELP_TEXT,
            Link { to: Route::AdminOperationsPage {}, style: LINK, {tr!("admin-operation-detail-back-to-operations")} }
        }
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-operation-detail-operation")} }
            div { style: MODULE_BODY,
                p { code { "{row.op_id}" } }
                p { style: HELP_TEXT,
                    {tr!("admin-operation-detail-queued-at", row_kind: row.kind.to_string(), row_state: row.state.to_string(), row_target: row.target.to_string(), row_started_at: row.started_at.to_string())}
                }
                p { style: HELP_TEXT,
                    if let Some(run_started_at) = row.run_started_at.as_ref() {
                        {tr!("admin-operation-detail-started", run_started_at: run_started_at.to_string())}
                    } else {
                        {tr!("admin-operation-detail-not-started")}
                    }
                }
                if let Some(summary) = rerun_outcome_summary(&row) {
                    p { id: "x-op-detail-counts", "{summary}" }
                } else {
                    p { id: "x-op-detail-counts", style: HELP_TEXT, {tr!("admin-operation-detail-re-run-counts-are-not")} }
                }
                if let Some(documents) = row.failed_documents {
                    p { style: HELP_TEXT,
                        {tr!("admin-operation-detail-failed-document-s-task-failure", documents: documents.to_string(), row_failed_tasks_unwrap_or_0: (row.failed_tasks.unwrap_or(0)).to_string())}
                    }
                } else {
                    p { style: HELP_TEXT, {tr!("admin-operation-detail-failures-were-not-counted")} }
                }
                if row.has_failure_tree {
                    p {
                        Link {
                            to: Route::AdminFailureDetailPage { op_id: row.op_id.clone() },
                            style: LINK,
                            {tr!("admin-operation-detail-open-captured-failure-tree")}
                        }
                    }
                }
                p {
                    a {
                        href: "{row.temporal_url}",
                        target: "_blank",
                        style: LINK,
                        {tr!("admin-operation-detail-open-in-temporal")}
                    }
                }
            }
        }
        PlanList {
            data: data.clone(),
            page: plans_page,
            events_page,
            has_more: plan_has_more,
        }
        EventList { data, page: events_page, plans_page, has_more: event_has_more }
    }
}

#[component]
fn PlanList(
    data: OperationDetail,
    page: u32,
    events_page: u32,
    has_more: bool,
) -> Element {
    let op_id = data.row.op_id.clone();
    let next_op_id = op_id.clone();
    let navigator = navigator();
    let previous_navigator = navigator.clone();
    let next_navigator = navigator;

    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-operation-detail-plans")} }
            div { id: "x-op-detail-plans", style: MODULE_BODY,
                p { style: HELP_TEXT, {tr!("admin-operation-detail-plan-s-page", data_plans_total: data.plans_total, page_1: (page + 1).to_string())} }
                if data.plans.is_empty() {
                    p { style: HELP_TEXT, {tr!("admin-operation-detail-no-plans-were-recorded-for")} }
                } else {
                    table { style: TABLE,
                        thead {
                            tr {
                                th { style: TH, {tr!("admin-operation-detail-dataset")} }
                                th { style: TH, {tr!("admin-operation-detail-plan-hash")} }
                                th { style: TH, {tr!("admin-operation-detail-source")} }
                                th { style: TH, {tr!("admin-operation-detail-finished")} }
                            }
                        }
                        tbody {
                            for plan in data.plans.iter() {
                                tr {
                                    td { style: TD, "{plan.collection_dataset}" }
                                    td { style: TD, code { "{plan.plan_hash}" } }
                                    td { style: TD, "{plan.source}" }
                                    td { style: TD, if plan.finished { {tr!("admin-operation-detail-yes")} } else { {tr!("admin-operation-detail-no")} } }
                                }
                            }
                        }
                    }
                }
                div { style: "display: flex; gap: 8px; align-items: center; margin-top: 10px;",
                    button {
                        id: "x-op-detail-plans-previous",
                        style: BTN_SMALL,
                        disabled: page == 0,
                        onclick: move |_| {
                            let _ = previous_navigator.push(Route::AdminOperationDetailPage {
                                op_id: op_id.clone(),
                                plans_page: page.saturating_sub(1),
                                events_page,
                            });
                        },
                        {tr!("admin-operation-detail-previous")}
                    }
                    button {
                        id: "x-op-detail-plans-next",
                        style: BTN_SMALL,
                        disabled: !has_more,
                        onclick: move |_| {
                            let _ = next_navigator.push(Route::AdminOperationDetailPage {
                                op_id: next_op_id.clone(),
                                plans_page: page.saturating_add(1),
                                events_page,
                            });
                        },
                        {tr!("admin-operation-detail-next")}
                    }
                }
            }
        }
    }
}

#[component]
fn EventList(
    data: OperationDetail,
    page: u32,
    plans_page: u32,
    has_more: bool,
) -> Element {
    let op_id = data.row.op_id.clone();
    let next_op_id = op_id.clone();
    let navigator = navigator();
    let previous_navigator = navigator.clone();
    let next_navigator = navigator;

    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-operation-detail-error-events")} }
            div { id: "x-op-detail-events", style: MODULE_BODY,
                p { style: HELP_TEXT, {tr!("admin-operation-detail-error-event-s-page", data_events_total: data.events_total, page_1: (page + 1).to_string())} }
                if data.events.is_empty() {
                    p { style: HELP_TEXT, {tr!("admin-operation-detail-no-error-events-were-recorded")} }
                } else {
                    table { style: TABLE,
                        thead {
                            tr {
                                th { style: TH, {tr!("admin-operation-detail-time")} }
                                th { style: TH, {tr!("admin-operation-detail-dataset")} }
                                th { style: TH, {tr!("admin-operation-detail-hash")} }
                                th { style: TH, {tr!("admin-operation-detail-task")} }
                                th { style: TH, {tr!("admin-operation-detail-event")} }
                                th { style: TH, {tr!("admin-operation-detail-error-excerpt")} }
                            }
                        }
                        tbody {
                            for event in data.events.iter() {
                                tr {
                                    td { style: TD, "{event.created_at}" }
                                    td { style: TD, "{event.collection_dataset}" }
                                    td { style: TD, code { "{event.hash}" } }
                                    td { style: TD, code { "{event.task_name}" } }
                                    td { style: TD, "{event.event}" }
                                    td { style: TD, "{event.error_excerpt}" }
                                }
                            }
                        }
                    }
                }
                div { style: "display: flex; gap: 8px; align-items: center; margin-top: 10px;",
                    button {
                        id: "x-op-detail-events-previous",
                        style: BTN_SMALL,
                        disabled: page == 0,
                        onclick: move |_| {
                            let _ = previous_navigator.push(Route::AdminOperationDetailPage {
                                op_id: op_id.clone(),
                                plans_page,
                                events_page: page.saturating_sub(1),
                            });
                        },
                        {tr!("admin-operation-detail-previous")}
                    }
                    button {
                        id: "x-op-detail-events-next",
                        style: BTN_SMALL,
                        disabled: !has_more,
                        onclick: move |_| {
                            let _ = next_navigator.push(Route::AdminOperationDetailPage {
                                op_id: next_op_id.clone(),
                                plans_page,
                                events_page: page.saturating_add(1),
                            });
                        },
                        {tr!("admin-operation-detail-next")}
                    }
                }
            }
        }
    }
}
