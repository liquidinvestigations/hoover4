//! The Errors/Failures page at `/admin/failures`, in two sections.
//!
//! Operational failures: captured operation failures, grouped by the stored `signature`
//! so identical failures collapse to one line with a count. Document errors: the newest
//! error of each document and task from `processing_errors`, with statistics over the
//! filters and pages. The document error filters and page are in the address.
//! Filters, sort and page are read inside the resources: a prop is not reactive, and a
//! value captured outside the resource never updates the list.

use common::failure_types::{
    FailureGroupRow, FailureInstanceRow, FailureListFilter, FailureListSort,
};
use dioxus::prelude::*;

use common::processing_types::{DocumentErrorFilter, DOCUMENT_ERRORS_PAGE_SIZE};

use crate::api::admin_api::{
    admin_list_document_errors, admin_list_failure_instances, admin_list_operation_failures,
};
use crate::api::error_util::user_facing_message;
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, BTN_SMALL, HELP_TEXT, INPUT, LABEL, LINK, MODULE,
    MODULE_BODY, MODULE_CAPTION, SELECT, SUBHEADING, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::routes::Route;

const PAGE_SIZES: [u32; 4] = [1, 10, 25, 50];

/// The id of the document error section. A dataset's error count links to it.
pub const DOCUMENT_ERRORS_SECTION_ID: &str = "document-errors";

/// The Errors/Failures page with its document errors filtered to a collection and a
/// dataset. Empty strings select every collection or dataset.
pub fn failures_route(collection: &str, dataset: &str) -> Route {
    Route::AdminFailuresPage {
        collection: collection.to_string(),
        dataset: dataset.to_string(),
        task: String::new(),
        search: String::new(),
        page: 1,
    }
}

#[component]
pub fn AdminFailuresPage(collection: String, dataset: String, task: String, search: String, page: u32) -> Element {
    rsx! {
        Title { "Admin: errors and failures" }
        AdminGuard {
            AdminShell {
                title: "Errors/Failures".to_string(),
                breadcrumb: String::new(),
                active: "failures".to_string(),
                SuspendWrapper {
                    FailuresContent {}
                    DocumentErrorsSection { collection, dataset, task, search, page }
                }
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
    let instances_ready = instances_res.read();
    let instances_error = instances_ready
        .as_ref()
        .and_then(|r| r.as_ref().err().map(user_facing_message));
    let instances_loading = expanded().is_some() && instances_ready.is_none();
    let instances: Vec<FailureInstanceRow> = instances_ready
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned()
        .unwrap_or_default();
    drop(instances_ready);
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

    let filtered = !collection_filter().is_empty() || !dataset_filter().is_empty()
        || !task_filter().is_empty() || !class_filter().is_empty() || !kind_filter().is_empty()
        || !from_filter().is_empty() || !to_filter().is_empty();
    if data.groups.is_empty() && !filtered && current_page == 0 {
        return rsx! {
            section { class: "x-admin-module", style: MODULE,
                h2 { style: MODULE_CAPTION, "Operational failures" }
                p { id: "x-failures-none", style: HELP_TEXT, "No operational failures at this time." }
            }
        };
    }

    rsx! {
        section { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, "Operational failures" }
            div { style: "{MODULE_BODY} display: flex; gap: 16px; flex-wrap: wrap; align-items: center; margin-bottom: 12px;",
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
                                    instances_loading: expanded_sig.as_deref() == Some(group.signature.as_str()) && instances_loading,
                                    instances_error: if expanded_sig.as_deref() == Some(group.signature.as_str()) { instances_error.clone() } else { None },
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
                // `selected` on each option, because the options can arrive after the
                // value, and a `value` set before its option exists selects nothing.
                option { value: "", selected: value.is_empty(), "{empty_label}" }
                for opt in options.iter() {
                    option { value: "{opt}", selected: *opt == value, "{opt}" }
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
    instances_loading: bool,
    instances_error: Option<String>,
    on_toggle: EventHandler<()>,
) -> Element {
    let expand_label = if expanded { "Hide" } else { "Show" };
    rsx! {
        tr {
            td { style: TD,
                code { style: "font-size: var(--x-text-xs); overflow-wrap: anywhere;", title: "{group.signature}",
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
                    if let Some(e) = instances_error {
                        p { id: "x-failures-instances-error-{index}", style: HELP_TEXT, "{e}" }
                    } else if instances_loading {
                        p { style: HELP_TEXT, "Loading instances…" }
                    } else if instances.is_empty() {
                        p { id: "x-failures-instances-empty-{index}", style: HELP_TEXT,
                            "No instances for this signature."
                        }
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
                                    div { style: "font-size: var(--x-text-xs);", "{inst.message}" }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

/// The document error section. The filters and the page are props from the address,
/// copied into signals that the resource reads.
#[component]
fn DocumentErrorsSection(collection: String, dataset: String, task: String, search: String, page: u32) -> Element {
    let page = page.max(1);
    let filter = DocumentErrorFilter {
        collectionname: collection.clone(),
        collection_dataset: dataset.clone(),
        task_name: task.clone(),
        search: search.clone(),
    };
    let mut query = use_signal(|| (filter.clone(), page));
    if *query.peek() != (filter.clone(), page) {
        query.set((filter.clone(), page));
    }
    let collections_res = use_resource(crate::api::admin_api::admin_list_collections);
    let errors_res = use_resource(move || {
        let (filter, page) = query();
        async move { admin_list_document_errors(filter, page).await }
    });
    let mut search_draft = use_signal(|| search.clone());
    let nav = navigator();
    // A link from an error count carries the section id. The section loads after the
    // page, so the browser's own scroll finds no target.
    use_effect(move || {
        if errors_res.read().is_some() {
            document::eval(&format!(
                "if (location.hash === '#{DOCUMENT_ERRORS_SECTION_ID}') document.getElementById('{DOCUMENT_ERRORS_SECTION_ID}')?.scrollIntoView();"
            ));
        }
    });

    let go = move |filter: DocumentErrorFilter, page: u32| {
        nav.push(Route::AdminFailuresPage {
            collection: filter.collectionname,
            dataset: filter.collection_dataset,
            task: filter.task_name,
            search: filter.search,
            page: page.max(1),
        });
    };
    let collection_choices: Vec<String> = collections_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .map(|cols| cols.iter().map(|c| c.collectionname.clone()).collect())
        .unwrap_or_default();

    rsx! {
        section { id: DOCUMENT_ERRORS_SECTION_ID, class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, "Document errors" }
            div { style: "{MODULE_BODY} display: flex; gap: 16px; flex-wrap: wrap; align-items: center; margin-bottom: 12px;",
                FilterSelect {
                    id: "x-doc-errors-collection",
                    label: "Collection",
                    value: filter.collectionname.clone(),
                    empty_label: "All collections",
                    options: collection_choices,
                    onchange: {
                        let filter = filter.clone();
                        move |v: String| go(DocumentErrorFilter { collectionname: v, collection_dataset: String::new(), ..filter.clone() }, 1)
                    },
                }
                FilterSelect {
                    id: "x-doc-errors-dataset",
                    label: "Dataset",
                    value: filter.collection_dataset.clone(),
                    empty_label: "All datasets",
                    options: errors_res.read().as_ref().and_then(|r| r.as_ref().ok()).map(|d| d.dataset_choices.clone()).unwrap_or_default(),
                    onchange: {
                        let filter = filter.clone();
                        move |v: String| go(DocumentErrorFilter { collection_dataset: v, ..filter.clone() }, 1)
                    },
                }
                FilterSelect {
                    id: "x-doc-errors-task",
                    label: "Task",
                    value: filter.task_name.clone(),
                    empty_label: "All tasks",
                    options: errors_res.read().as_ref().and_then(|r| r.as_ref().ok()).map(|d| d.task_choices.clone()).unwrap_or_default(),
                    onchange: {
                        let filter = filter.clone();
                        move |v: String| go(DocumentErrorFilter { task_name: v, ..filter.clone() }, 1)
                    },
                }
                label { style: LABEL,
                    "Error text"
                    input {
                        id: "x-doc-errors-search",
                        style: INPUT,
                        value: "{search_draft}",
                        oninput: move |e| search_draft.set(e.value()),
                        onkeydown: {
                            let filter = filter.clone();
                            move |e: KeyboardEvent| {
                                if e.key() == Key::Enter {
                                    go(DocumentErrorFilter { search: search_draft(), ..filter.clone() }, 1);
                                }
                            }
                        },
                    }
                }
            }
            match &*errors_res.read() {
                None => rsx! { p { style: HELP_TEXT, "Loading document errors\u{2026}" } },
                Some(Err(e)) => rsx! { ErrorBar { message: user_facing_message(e) } },
                Some(Ok(data)) if data.total == 0 => rsx! {
                    p { id: "x-doc-errors-none", style: HELP_TEXT, "No document errors match these filters." }
                },
                Some(Ok(data)) => {
                    let pages = data.total.div_ceil(u64::from(DOCUMENT_ERRORS_PAGE_SIZE)).max(1);
                    let documents: u64 = data.stats.iter().map(|s| s.documents).sum();
                    rsx! {
                        h3 { style: SUBHEADING, "Errors by dataset and task" }
                        table { id: "x-doc-errors-stats", style: TABLE,
                            thead {
                                tr {
                                    th { style: TH, "Dataset" }
                                    th { style: TH, "Task" }
                                    th { style: "{TH} text-align: right;", "Documents" }
                                    th { style: TH, "Last seen" }
                                }
                            }
                            tbody {
                                for stat in data.stats.iter() {
                                    tr { key: "{stat.collection_dataset}/{stat.task_name}",
                                        td { style: TD, "{stat.collection_dataset}" }
                                        td { style: TD,
                                            button {
                                                style: "background: none; border: none; padding: 0; cursor: pointer; font: inherit; color: var(--x-link);",
                                                title: "Show only this dataset and task",
                                                onclick: {
                                                    let filter = filter.clone();
                                                    let ds = stat.collection_dataset.clone();
                                                    let task = stat.task_name.clone();
                                                    move |_| go(DocumentErrorFilter { collection_dataset: ds.clone(), task_name: task.clone(), ..filter.clone() }, 1)
                                                },
                                                "{stat.task_name}"
                                            }
                                        }
                                        td { style: "{TD} text-align: right;", "{stat.documents}" }
                                        td { style: "{TD} white-space: nowrap;", "{short_time(&stat.last_seen)}" }
                                    }
                                }
                                tr {
                                    td { style: "{TD} font-weight: 600;", colspan: 2, "Total" }
                                    td { style: "{TD} text-align: right; font-weight: 600;", "{documents}" }
                                    td { style: TD, "" }
                                }
                            }
                        }
                        h3 { style: SUBHEADING, "Errors" }
                        table { id: "x-doc-errors-table", style: TABLE,
                            thead {
                                tr {
                                    th { style: TH, "Last seen" }
                                    th { style: TH, "Dataset" }
                                    th { style: TH, "Document" }
                                    th { style: TH, "Task" }
                                    th { style: "{TH} text-align: right;", "Runs" }
                                    th { style: TH, "Error" }
                                }
                            }
                            tbody {
                                for row in data.rows.iter() {
                                    tr { key: "{row.collection_dataset}/{row.hash}/{row.task_name}", class: "x-doc-errors-row",
                                        td { style: "{TD} white-space: nowrap;", "{short_time(&row.last_seen)}" }
                                        td { style: TD, "{row.collection_dataset}" }
                                        td { style: "{TD} word-break: break-all;",
                                            if row.hash.is_empty() {
                                                span { style: HELP_TEXT, "Dataset step" }
                                            } else {
                                                a {
                                                    href: "{document_href(&row.collection_dataset, &row.hash)}",
                                                    target: "_blank",
                                                    rel: "noopener",
                                                    style: LINK,
                                                    title: "{row.hash}",
                                                    {row.path.clone().unwrap_or_else(|| row.hash.chars().take(16).collect())}
                                                }
                                            }
                                        }
                                        td { style: TD, "{row.task_name}" }
                                        td { style: "{TD} text-align: right;", "{row.runs}" }
                                        td { style: "{TD} font-family: ui-monospace, monospace; font-size: var(--x-text-xs); word-break: break-word;", "{row.error}" }
                                    }
                                }
                            }
                        }
                        div { style: "display: flex; gap: 12px; align-items: center; margin-top: 10px;",
                            button {
                                id: "x-doc-errors-previous",
                                style: BTN_SMALL,
                                disabled: page <= 1,
                                onclick: {
                                    let filter = filter.clone();
                                    move |_| go(filter.clone(), page - 1)
                                },
                                "Previous page"
                            }
                            span { id: "x-doc-errors-page", style: HELP_TEXT,
                                if data.total == 1 { "Page {page} of {pages}, 1 error" } else { "Page {page} of {pages}, {data.total} errors" }
                            }
                            button {
                                id: "x-doc-errors-next",
                                style: BTN_SMALL,
                                disabled: u64::from(page) >= pages,
                                onclick: {
                                    let filter = filter.clone();
                                    move |_| go(filter.clone(), page + 1)
                                },
                                "Next page"
                            }
                        }
                    }
                }
            }
        }
    }
}

/// `YYYY-MM-DD HH:MM` of an RFC 3339 timestamp.
fn short_time(rfc3339: &str) -> String {
    let (date, rest) = rfc3339.split_once('T').unwrap_or((rfc3339, ""));
    format!("{date} {}", rest.get(..5).unwrap_or(rest)).trim().to_string()
}

/// The document view of one blob, in a new tab.
fn document_href(collection_dataset: &str, hash: &str) -> String {
    let id = common::search_result::DocumentIdentifier {
        collection_dataset: collection_dataset.to_string(),
        file_hash: hash.to_string(),
    };
    Route::ViewDocumentPage {
        document_identifier: id.into(),
        doc_viewer_state: None.into(),
        viewer_right_tab_state: crate::data_definitions::doc_viewer_state::ViewerRightTabState::default().into(),
    }
    .to_string()
}
