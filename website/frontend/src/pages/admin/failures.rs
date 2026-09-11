//! Grouped list of captured operation failures at `/admin/failures`.
//!
//! Rows are grouped by the stored `signature` so identical failures collapse to one
//! line with a count. Filters, sort and page are read inside the resource: a prop is
//! not reactive, and a value captured outside the resource never updates the list.

use common::failure_types::{
    FailureGroupRow, FailureInstanceRow, FailureListFilter, FailureListSort,
};
use dioxus::prelude::*;

use crate::api::admin_api::{admin_list_failure_instances, admin_list_operation_failures};
use crate::api::error_util::user_facing_message;
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, BTN_SMALL, HELP_TEXT, INPUT, LABEL, LINK, MODULE,
    MODULE_BODY, MODULE_CAPTION, SELECT, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::routes::Route;

const PAGE_SIZES: [u32; 4] = [1, 10, 25, 50];

#[component]
pub fn AdminFailuresPage() -> Element {
    rsx! {
        Title { "Admin: failures" }
        AdminGuard {
            AdminShell {
                title: "Failures".to_string(),
                breadcrumb: "Failures".to_string(),
                active: "failures".to_string(),
                SuspendWrapper { FailuresContent {} }
            }
        }
    }
}

#[component]
fn FailuresContent() -> Element {
    let mut collection_filter = use_signal(String::new);
    let mut dataset_filter = use_signal(String::new);
    let mut task_filter = use_signal(String::new);
    let mut class_filter = use_signal(String::new);
    let mut kind_filter = use_signal(String::new);
    let mut from_filter = use_signal(String::new);
    let mut to_filter = use_signal(String::new);
    let mut sort_column = use_signal(|| "last_seen".to_string());
    let mut sort_desc = use_signal(|| true);
    let mut page = use_signal(|| 0_u32);
    let mut page_size = use_signal(|| 25_u32);
    let mut expanded = use_signal(|| None::<String>);

    let list_res = use_resource(move || {
        let filter = FailureListFilter {
            collectionname: collection_filter(),
            collection_dataset: dataset_filter(),
            task_name: task_filter(),
            error_class: class_filter(),
            operation_kind: kind_filter(),
            captured_from: from_filter(),
            captured_to: to_filter(),
        };
        let sort = FailureListSort {
            column: sort_column(),
            descending: sort_desc(),
        };
        let limit = page_size();
        let offset = page() * limit;
        async move { admin_list_operation_failures(filter, sort, limit, offset).await }
    });
    let instances_res = use_resource(move || {
        let signature = expanded();
        let filter = FailureListFilter {
            collectionname: collection_filter(),
            collection_dataset: dataset_filter(),
            task_name: task_filter(),
            error_class: class_filter(),
            operation_kind: kind_filter(),
            captured_from: from_filter(),
            captured_to: to_filter(),
        };
        async move {
            match signature {
                Some(s) => admin_list_failure_instances(filter, s, 50, 0).await,
                None => Ok(Vec::new()),
            }
        }
    });

    let data = list_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned();
    let load_error = list_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().err().map(user_facing_message));
    let instances: Vec<FailureInstanceRow> = instances_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned()
        .unwrap_or_default();
    let expanded_sig = expanded();

    let Some(data) = data else {
        return rsx! {
            if let Some(e) = load_error {
                ErrorBar { message: e }
            } else {
                p { style: HELP_TEXT, "Loading failures…" }
            }
        };
    };

    let has_more = data.has_more;
    let current_page = page();
    let current_size = page_size();
    let current_sort = sort_column();
    let current_desc = sort_desc();

    rsx! {
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Filters" }
            div { style: "{MODULE_BODY} display: flex; gap: 16px; flex-wrap: wrap; align-items: center;",
                FilterSelect {
                    id: "x-failures-filter-collection",
                    label: "Collection",
                    value: collection_filter(),
                    empty_label: "All collections",
                    options: data.collections.clone(),
                    onchange: move |v| { collection_filter.set(v); page.set(0); },
                }
                FilterSelect {
                    id: "x-failures-filter-dataset",
                    label: "Dataset",
                    value: dataset_filter(),
                    empty_label: "All datasets",
                    options: data.datasets.clone(),
                    onchange: move |v| { dataset_filter.set(v); page.set(0); },
                }
                FilterSelect {
                    id: "x-failures-filter-task",
                    label: "Task name",
                    value: task_filter(),
                    empty_label: "All tasks",
                    options: data.task_names.clone(),
                    onchange: move |v| { task_filter.set(v); page.set(0); },
                }
                FilterSelect {
                    id: "x-failures-filter-class",
                    label: "Error class",
                    value: class_filter(),
                    empty_label: "All classes",
                    options: data.error_classes.clone(),
                    onchange: move |v| { class_filter.set(v); page.set(0); },
                }
                FilterSelect {
                    id: "x-failures-filter-kind",
                    label: "Operation kind",
                    value: kind_filter(),
                    empty_label: "All kinds",
                    options: data.operation_kinds.clone(),
                    onchange: move |v| { kind_filter.set(v); page.set(0); },
                }
                label { style: LABEL,
                    "From"
                    input {
                        id: "x-failures-filter-from",
                        r#type: "date",
                        style: INPUT,
                        value: "{from_filter}",
                        onchange: move |e| { from_filter.set(e.value()); page.set(0); },
                    }
                }
                label { style: LABEL,
                    "To"
                    input {
                        id: "x-failures-filter-to",
                        r#type: "date",
                        style: INPUT,
                        value: "{to_filter}",
                        onchange: move |e| { to_filter.set(e.value()); page.set(0); },
                    }
                }
            }
        }

        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Failures, grouped by signature" }
            div { style: MODULE_BODY,
                if data.groups.is_empty() {
                    p { style: HELP_TEXT, "No captured failures match these filters." }
                } else {
                    table { style: TABLE,
                        thead {
                            tr {
                                SortHead { id: "x-failures-sort-signature", label: "Signature", column: "signature", current: current_sort.clone(), desc: current_desc,
                                    onsort: move |c| { toggle_sort(&mut sort_column, &mut sort_desc, c); page.set(0); } }
                                SortHead { id: "x-failures-sort-count", label: "Count", column: "failure_count", current: current_sort.clone(), desc: current_desc,
                                    onsort: move |c| { toggle_sort(&mut sort_column, &mut sort_desc, c); page.set(0); } }
                                SortHead { id: "x-failures-sort-class", label: "Class", column: "error_class", current: current_sort.clone(), desc: current_desc,
                                    onsort: move |c| { toggle_sort(&mut sort_column, &mut sort_desc, c); page.set(0); } }
                                SortHead { id: "x-failures-sort-task", label: "Task", column: "task_name", current: current_sort.clone(), desc: current_desc,
                                    onsort: move |c| { toggle_sort(&mut sort_column, &mut sort_desc, c); page.set(0); } }
                                SortHead { id: "x-failures-sort-collection", label: "Collection", column: "collectionname", current: current_sort.clone(), desc: current_desc,
                                    onsort: move |c| { toggle_sort(&mut sort_column, &mut sort_desc, c); page.set(0); } }
                                SortHead { id: "x-failures-sort-last-seen", label: "Last seen", column: "last_seen", current: current_sort.clone(), desc: current_desc,
                                    onsort: move |c| { toggle_sort(&mut sort_column, &mut sort_desc, c); page.set(0); } }
                                th { style: TH, "" }
                            }
                        }
                        tbody {
                            for (idx, group) in data.groups.iter().enumerate() {
                                GroupRows {
                                    key: "{group.signature}",
                                    index: idx,
                                    group: group.clone(),
                                    expanded: expanded_sig.as_deref() == Some(group.signature.as_str()),
                                    instances: if expanded_sig.as_deref() == Some(group.signature.as_str()) { instances.clone() } else { Vec::new() },
                                    on_toggle: {
                                        let sig = group.signature.clone();
                                        move |_| {
                                            if expanded() == Some(sig.clone()) {
                                                expanded.set(None);
                                            } else {
                                                expanded.set(Some(sig.clone()));
                                            }
                                        }
                                    },
                                }
                            }
                        }
                    }
                }
                div { style: "display: flex; gap: 8px; align-items: center; margin-top: 10px; flex-wrap: wrap;",
                    button {
                        id: "x-failures-page-newer",
                        style: BTN_SMALL,
                        disabled: current_page == 0,
                        onclick: move |_| page.set(current_page.saturating_sub(1)),
                        "Newer"
                    }
                    span { id: "x-failures-page-label", style: HELP_TEXT, "Page {current_page + 1}" }
                    button {
                        id: "x-failures-page-older",
                        style: BTN_SMALL,
                        disabled: !has_more,
                        onclick: move |_| page.set(current_page + 1),
                        "Older"
                    }
                    label { style: LABEL,
                        "Per page"
                        select {
                            id: "x-failures-page-size",
                            style: SELECT,
                            value: "{current_size}",
                            onchange: move |e| {
                                if let Ok(n) = e.value().parse::<u32>() {
                                    page_size.set(n);
                                    page.set(0);
                                }
                            },
                            for n in PAGE_SIZES {
                                option { value: "{n}", "{n}" }
                            }
                        }
                    }
                }
            }
        }
    }
}

fn toggle_sort(column: &mut Signal<String>, desc: &mut Signal<bool>, next: String) {
    if column() == next {
        desc.set(!desc());
    } else {
        column.set(next);
        desc.set(true);
    }
}

#[component]
fn FilterSelect(
    id: &'static str,
    label: &'static str,
    value: String,
    empty_label: &'static str,
    options: Vec<String>,
    onchange: EventHandler<String>,
) -> Element {
    rsx! {
        label { style: LABEL,
            "{label}"
            select {
                id: "{id}",
                style: SELECT,
                value: "{value}",
                onchange: move |e| onchange.call(e.value()),
                option { value: "", "{empty_label}" }
                for opt in options.iter() {
                    option { value: "{opt}", "{opt}" }
                }
            }
        }
    }
}

#[component]
fn SortHead(
    id: &'static str,
    label: &'static str,
    column: &'static str,
    current: String,
    desc: bool,
    onsort: EventHandler<String>,
) -> Element {
    let marker = if current == column {
        if desc { " \u{25bc}" } else { " \u{25b2}" }
    } else {
        ""
    };
    rsx! {
        th { style: TH,
            button {
                id: "{id}",
                style: "background: none; border: none; padding: 0; font: inherit; color: inherit; text-transform: inherit; letter-spacing: inherit; cursor: pointer;",
                onclick: move |_| onsort.call(column.to_string()),
                "{label}{marker}"
            }
        }
    }
}

#[component]
fn GroupRows(
    index: usize,
    group: FailureGroupRow,
    expanded: bool,
    instances: Vec<FailureInstanceRow>,
    on_toggle: EventHandler<()>,
) -> Element {
    let expand_label = if expanded { "Hide" } else { "Show" };
    rsx! {
        tr {
            td { style: TD,
                code { style: "font-size: 11px; overflow-wrap: anywhere;", title: "{group.signature}",
                    "{group.signature}"
                }
                div { style: HELP_TEXT, "{group.sample_message}" }
            }
            td { style: TD,
                span { id: "x-failures-count-{index}", "{group.failure_count}" }
                div { style: HELP_TEXT, "{group.operation_count} operation(s)" }
            }
            td { style: TD, "{group.error_class}" }
            td { style: TD, "{group.task_name}" }
            td { style: TD,
                "{group.collectionname}"
                div { style: HELP_TEXT, "{group.collection_dataset}" }
            }
            td { style: TD, "{group.last_seen}" }
            td { style: TD,
                button {
                    id: "x-failures-expand-{index}",
                    style: BTN_SMALL,
                    onclick: move |_| on_toggle.call(()),
                    "{expand_label}"
                }
            }
        }
        if expanded {
            tr {
                td { style: TD, colspan: "7",
                    if instances.is_empty() {
                        p { style: HELP_TEXT, "Loading instances…" }
                    } else {
                        ul { id: "x-failures-instances-{index}", style: "margin: 0; padding-left: 18px;",
                            for inst in instances.iter() {
                                li { key: "{inst.op_id}:{inst.node_index}",
                                    Link {
                                        to: Route::AdminFailureDetailPage { op_id: inst.op_id.clone() },
                                        style: LINK,
                                        "{inst.op_id}"
                                    }
                                    span { style: HELP_TEXT,
                                        " node {inst.node_index} · {inst.source} · {inst.stage} · {inst.captured_at}"
                                    }
                                    div { style: "font-size: 12px;", "{inst.message}" }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
