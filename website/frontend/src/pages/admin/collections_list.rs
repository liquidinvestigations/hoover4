//! Admin collections page: the collections, the datasets of every collection, and the
//! form that adds a collection.

use common::admin_types::{AdminCollectionItem, AdminDatasetListItem};
use common::storage_tree::{format_size, state_label, CollectionAggregates, DatasetAggregates};
use dioxus::prelude::*;

use crate::api::error_util::user_facing_message;
use crate::api::admin_api::{admin_create_collection, admin_list_collections, admin_list_datasets};
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, SuccessBar, BTN_PRIMARY, HELP_TEXT, INPUT, LINK, MODULE,
    MODULE_BODY, MODULE_CAPTION, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::routes::Route;

/// The id of the Datasets section. The dashboard Datasets card links to it.
pub const DATASETS_SECTION_ID: &str = "datasets";

#[component]
pub fn AdminCollectionsPage() -> Element {
    rsx! {
        Title { "Admin: collections" }
        AdminGuard {
            AdminShell {
                title: "Collections".to_string(),
                breadcrumb: String::new(),
                active: "collections".to_string(),
                SuspendWrapper { CollectionsListContent {} }
            }
        }
    }
}

/// A numeric cell. Right-aligned so the digits of a column line up.
const NUM_TD: &str = "text-align: right; white-space: nowrap;";

#[component]
fn CollectionsListContent() -> Element {
    let mut cols_res = use_resource(admin_list_collections);
    let datasets_res = use_resource(admin_list_datasets);
    let mut collectionname = use_signal(String::new);
    let mut fullname = use_signal(String::new);
    let mut error_msg = use_signal(|| None::<String>);
    let mut success_msg = use_signal(|| None::<String>);
    // The dashboard links here with a fragment. Both tables load after the page does, so
    // the browser's own fragment scroll finds no target. The scroll waits until both
    // tables are on the page, because the collection table moves the section down.
    use_effect(move || {
        if cols_res.read().is_some() && datasets_res.read().is_some() {
            document::eval(&format!(
                "if (location.hash === '#{DATASETS_SECTION_ID}') document.getElementById('{DATASETS_SECTION_ID}')?.scrollIntoView();"
            ));
        }
    });

    rsx! {
        if let Some(msg) = success_msg.read().clone() {
            SuccessBar { message: msg }
        }
        if let Some(err) = error_msg.read().clone() {
            ErrorBar { message: err }
        }
        section { class: "x-admin-module", style: MODULE,
            match &*cols_res.read() {
                Some(Ok(cols)) => rsx! { CollectionsTable { cols: cols.clone() } },
                Some(Err(e)) => rsx! { ErrorBar { message: user_facing_message(e) } },
                None => rsx! { p { style: HELP_TEXT, "Loading collections\u{2026}" } },
            }
        }
        section {
            id: DATASETS_SECTION_ID,
            class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, "Datasets" }
            match &*datasets_res.read() {
                Some(Ok(datasets)) => rsx! { DatasetsTable { datasets: datasets.clone() } },
                Some(Err(e)) => rsx! { ErrorBar { message: user_facing_message(e) } },
                None => rsx! { p { style: HELP_TEXT, "Loading datasets\u{2026}" } },
            }
        }
        section { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, "Add a collection" }
            div { style: "{MODULE_BODY} display: flex; gap: 8px; flex-wrap: wrap; align-items: center;",
                input { style: INPUT, placeholder: "Name, for example enron", value: "{collectionname}", oninput: move |e| collectionname.set(e.value()) }
                input { style: INPUT, placeholder: "Display name", value: "{fullname}", oninput: move |e| fullname.set(e.value()) }
                button {
                    style: BTN_PRIMARY,
                    onclick: move |_| {
                        let c = collectionname.read().clone();
                        let f = fullname.read().clone();
                        spawn(async move {
                            error_msg.set(None);
                            success_msg.set(None);
                            match admin_create_collection(c.clone(), f).await {
                                Ok(()) => {
                                    success_msg.set(Some(format!("The collection \u{201c}{c}\u{201d} was added.")));
                                    collectionname.set(String::new());
                                    fullname.set(String::new());
                                    cols_res.restart();
                                }
                                Err(e) => error_msg.set(Some(user_facing_message(&e))),
                            }
                        });
                    },
                    "Add collection"
                }
            }
        }
    }
}

#[component]
fn CollectionsTable(cols: Vec<AdminCollectionItem>) -> Element {
    rsx! {
        table { style: TABLE,
            thead {
                tr {
                    th { style: TH, "Collection" }
                    th { style: "{TH} text-align: right;", "Datasets" }
                    th { style: "{TH} text-align: right;", "Documents" }
                    th { style: "{TH} text-align: right;", "Size" }
                    th { style: "{TH} text-align: right;", "Errors" }
                    th { style: TH, "State" }
                    th { style: TH, "Access" }
                }
            }
            tbody {
                for c in cols {
                    tr { key: "{c.collectionname}",
                        td { style: TD,
                            Link { to: Route::AdminCollectionPage { collection_id: c.collectionname.clone() }, style: LINK, "{c.collectionname}" }
                            if !c.fullname.is_empty() && c.fullname != c.collectionname {
                                div { style: HELP_TEXT, "{c.fullname}" }
                            }
                        }
                        td { style: "{TD} {NUM_TD}", "{c.dataset_count}" }
                        CollectionStatCells { stats: c.stats.clone() }
                        if c.stats.counted_dataset_count == 0 {
                            td { style: "{TD} {NUM_TD}", "" }
                        } else {
                            ErrorCountCell { collectionname: c.collectionname.clone(), collection_dataset: String::new(), count: c.stats.error_count }
                        }
                        td { style: TD,
                            if !c.db_ready {
                                span { style: "color: var(--x-danger);", "Database not ready" }
                            } else {
                                StateText { stats_known: c.stats.counted_dataset_count > 0, processing: c.stats.processing }
                            }
                        }
                        td { style: TD,
                            if c.is_public {
                                "Public"
                            } else if c.group_count == 1 {
                                "1 group"
                            } else {
                                "{c.group_count} groups"
                            }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn CollectionStatCells(stats: CollectionAggregates) -> Element {
    if stats.counted_dataset_count == 0 {
        return rsx! {
            td { style: "{TD} {NUM_TD} {HELP_TEXT}", colspan: 2, "Not counted yet" }
        };
    }
    let (note, note_title) = if stats.is_complete() {
        ("", "")
    } else {
        (" *", "Some datasets are not counted yet.")
    };
    rsx! {
        td { style: "{TD} {NUM_TD}", title: note_title, "{stats.document_count}{note}" }
        td { style: "{TD} {NUM_TD}", "{format_size(stats.total_size_bytes)}" }
    }
}

#[component]
fn StateText(stats_known: bool, processing: bool) -> Element {
    if !stats_known {
        return rsx! { span { style: HELP_TEXT, "Unknown" } };
    }
    let colour = if processing { "var(--x-link)" } else { "var(--x-ink)" };
    rsx! {
        span { style: "color: {colour};", "{state_label(processing)}" }
    }
}

#[component]
fn DatasetsTable(datasets: Vec<AdminDatasetListItem>) -> Element {
    if datasets.is_empty() {
        return rsx! { p { style: HELP_TEXT, "No collection has a dataset." } };
    }
    rsx! {
        table { style: TABLE,
            thead {
                tr {
                    th { style: TH, "Dataset" }
                    th { style: TH, "Collection" }
                    th { style: "{TH} text-align: right;", "Documents" }
                    th { style: "{TH} text-align: right;", "Size" }
                    th { style: "{TH} text-align: right;", "Indexed" }
                    th { style: "{TH} text-align: right;", "Errors" }
                    th { style: TH, "State" }
                    th { style: TH, "Created" }
                }
            }
            tbody {
                for d in datasets {
                    tr { key: "{d.collection_dataset}",
                        td { style: TD,
                            Link {
                                to: Route::AdminDatasetPage {
                                    collection_id: d.collectionname.clone(),
                                    dataset_id: d.collection_dataset.clone(),
                                },
                                style: LINK,
                                "{d.dataset_name}"
                            }
                            if !d.dataset_display_name.is_empty() && d.dataset_display_name != d.dataset_name {
                                div { style: HELP_TEXT, "{d.dataset_display_name}" }
                            }
                        }
                        td { style: TD,
                            Link { to: Route::AdminCollectionPage { collection_id: d.collectionname.clone() }, style: LINK, "{d.collectionname}" }
                        }
                        DatasetStatCells { collectionname: d.collectionname.clone(), stats: d.stats.clone() }
                        td { style: TD, StateText { stats_known: d.stats.is_some(), processing: d.stats.as_ref().is_some_and(|s| s.processing) } }
                        td { style: "{TD} white-space: nowrap;", "{short_date(&d.date_created)}" }
                    }
                }
            }
        }
    }
}

/// The statistics cells of one dataset row. Shared with the collection page. A non-zero
/// error count links to the dataset's document errors.
#[component]
pub fn DatasetStatCells(collectionname: String, stats: Option<DatasetAggregates>) -> Element {
    match stats {
        None => rsx! {
            td { style: "{TD} {NUM_TD} {HELP_TEXT}", colspan: 4, "Not counted yet" }
        },
        Some(s) => {
            rsx! {
                td { style: "{TD} {NUM_TD}", "{s.document_count}" }
                td { style: "{TD} {NUM_TD}", "{format_size(s.total_size_bytes)}" }
                td { style: "{TD} {NUM_TD}", "{s.indexed_count}" }
                ErrorCountCell { collectionname, collection_dataset: s.collection_dataset.clone(), count: s.error_count }
            }
        }
    }
}

/// The date part of an RFC 3339 timestamp.
pub fn short_date(rfc3339: &str) -> &str {
    rfc3339.split('T').next().unwrap_or(rfc3339)
}

/// The processing state cell of one dataset row. Shared with the collection page.
#[component]
pub fn DatasetStateCell(stats: Option<DatasetAggregates>) -> Element {
    rsx! {
        td { style: TD, StateText { stats_known: stats.is_some(), processing: stats.as_ref().is_some_and(|s| s.processing) } }
    }
}

/// An error count. A non-zero count links to the matching document errors.
#[component]
fn ErrorCountCell(collectionname: String, collection_dataset: String, count: u64) -> Element {
    if count == 0 {
        return rsx! { td { style: "{TD} {NUM_TD}", "0" } };
    }
    let to = format!(
        "{}#{}",
        crate::pages::admin::failures::failures_route(&collectionname, &collection_dataset),
        crate::pages::admin::failures::DOCUMENT_ERRORS_SECTION_ID
    );
    rsx! {
        td { style: "{TD} {NUM_TD}",
            a { class: "x-admin-error-count", href: "{to}", style: "color: var(--x-warning); font-weight: 600;", "{count}" }
        }
    }
}
