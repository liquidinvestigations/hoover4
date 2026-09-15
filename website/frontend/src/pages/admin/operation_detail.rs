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

#[component]
pub fn AdminOperationDetailPage(op_id: String, plans_page: u32, events_page: u32) -> Element {
    rsx! {
        Title { "Admin: operation {op_id}" }
        AdminGuard {
            AdminShell {
                title: "Operation".to_string(),
                breadcrumb: format!("Operations / {op_id}"),
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
                p { style: HELP_TEXT, "Loading operation…" }
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
            Link { to: Route::AdminOperationsPage {}, style: LINK, "Back to operations" }
        }
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Operation" }
            div { style: MODULE_BODY,
                p { code { "{row.op_id}" } }
                p { style: HELP_TEXT,
                    "{row.kind} · {row.state} · {row.target} · {row.started_at}"
                }
                if let Some(summary) = rerun_outcome_summary(&row) {
                    p { id: "x-op-detail-counts", "{summary}" }
                } else {
                    p { id: "x-op-detail-counts", style: HELP_TEXT, "Re-run counts are not available." }
                }
                if let Some(documents) = row.failed_documents {
                    p { style: HELP_TEXT,
                        "{documents} failed document(s), {row.failed_tasks.unwrap_or(0)} task failure(s)"
                    }
                } else {
                    p { style: HELP_TEXT, "Failures were not counted." }
                }
                if row.has_failure_tree {
                    p {
                        Link {
                            to: Route::AdminFailureDetailPage { op_id: row.op_id.clone() },
                            style: LINK,
                            "Open captured Failure tree"
                        }
                    }
                }
                p {
                    a {
                        href: "{row.temporal_url}",
                        target: "_blank",
                        style: LINK,
                        "Open in Temporal"
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
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Plans" }
            div { id: "x-op-detail-plans", style: MODULE_BODY,
                p { style: HELP_TEXT, "{data.plans_total} plan(s), page {page + 1}" }
                if data.plans.is_empty() {
                    p { style: HELP_TEXT, "No plans were recorded for this operation." }
                } else {
                    table { style: TABLE,
                        thead {
                            tr {
                                th { style: TH, "Dataset" }
                                th { style: TH, "Plan hash" }
                                th { style: TH, "Source" }
                                th { style: TH, "Finished" }
                            }
                        }
                        tbody {
                            for plan in data.plans.iter() {
                                tr {
                                    td { style: TD, "{plan.collection_dataset}" }
                                    td { style: TD, code { "{plan.plan_hash}" } }
                                    td { style: TD, "{plan.source}" }
                                    td { style: TD, if plan.finished { "yes" } else { "no" } }
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
                        "Previous"
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
                        "Next"
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
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Error events" }
            div { id: "x-op-detail-events", style: MODULE_BODY,
                p { style: HELP_TEXT, "{data.events_total} Error event(s), page {page + 1}" }
                if data.events.is_empty() {
                    p { style: HELP_TEXT, "No Error events were recorded for this operation." }
                } else {
                    table { style: TABLE,
                        thead {
                            tr {
                                th { style: TH, "Time" }
                                th { style: TH, "Dataset" }
                                th { style: TH, "Hash" }
                                th { style: TH, "Task" }
                                th { style: TH, "Event" }
                                th { style: TH, "Error excerpt" }
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
                        "Previous"
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
                        "Next"
                    }
                }
            }
        }
    }
}
