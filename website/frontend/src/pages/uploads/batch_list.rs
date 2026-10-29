//! `/uploads?collection`, the batch list. It shows 200 batches, newest first. "Show all"
//! reads the remaining batches in pages of 200.

use common::upload_pages::{batch_state_label, UploadBatchCursor, UploadBatchRow};
use common::uploads::{format_count, format_upload_size};
use dioxus::prelude::*;

use super::upload_page::{H1_STYLE, PAGE_STYLE, SURFACE_STYLE};
use crate::api::error_util::user_facing_message;
use crate::api::uploads_api::list_upload_batches;
use crate::components::admin_components::{ErrorBar, BTN, SELECT, TABLE, TD, TH};
use crate::routes::Route;

/// `YYYY-MM-DD HH:MM`, in UTC.
pub(super) fn started_label(ms: i64) -> String {
    let full = crate::pages::admin::llm_reports::format_utc_ms(ms);
    full.get(..16).unwrap_or(&full).to_string()
}

/// `collection / dataset folder`.
pub(super) fn destination_label(row: &UploadBatchRow) -> String {
    format!("{} / {} {}", row.collection, row.upload_dataset, row.folder)
}

#[component]
pub fn UploadsPage(collection: String) -> Element {
    let filter = use_memo(use_reactive!(|collection| collection));
    let first = use_resource(move || async move { list_upload_batches(filter(), None).await });
    // The rows that "Show all" adds, and the cursor after them. Both reset with the filter.
    let mut extra = use_signal(Vec::<UploadBatchRow>::new);
    let mut cursor = use_signal(|| None::<Option<UploadBatchCursor>>);
    let mut more_error = use_signal(|| None::<String>);
    let mut loading = use_signal(|| false);
    use_effect(move || {
        filter();
        extra.set(Vec::new());
        cursor.set(None);
        more_error.set(None);
    });

    let page = first.read().clone();
    let body = match page {
        None => rsx! { p { "Loading..." } },
        Some(Err(e)) => rsx! { ErrorBar { message: user_facing_message(&e) } },
        Some(Ok(page)) => {
            let next = cursor().unwrap_or(page.next.clone());
            let mut rows = page.rows.clone();
            rows.extend(extra());
            let collections = page.collections.clone();
            let selected = filter();
            rsx! {
                div { style: "display: flex; align-items: center; gap: 8px; justify-content: flex-end;",
                    label { r#for: "x-uploads-filter", "Collection" }
                    select {
                        id: "x-uploads-filter",
                        style: SELECT,
                        value: "{selected}",
                        onchange: move |e| { navigator().replace(Route::UploadsPage { collection: e.value() }); },
                        option { value: "", selected: selected.is_empty(), "All collections" }
                        for c in collections.iter() {
                            option { key: "{c}", value: "{c}", selected: *c == selected, "{c}" }
                        }
                    }
                }
                if rows.is_empty() {
                    p { class: "x-uploads-empty", "No uploads yet." }
                } else {
                    table { class: "x-uploads-table", style: TABLE,
                        thead {
                            tr {
                                th { style: TH, "Started" }
                                th { style: TH, "Destination" }
                                th { style: TH, "Uploaded by" }
                                th { style: TH, "Files" }
                                th { style: TH, "Size" }
                                th { style: TH, "State" }
                            }
                        }
                        tbody {
                            for row in rows.iter() {
                                BatchListLine { key: "{row.collection}-{row.batch_id}", row: row.clone() }
                            }
                        }
                    }
                }
                if let Some(e) = more_error() {
                    ErrorBar { message: e }
                }
                if let Some(next) = next {
                    div {
                        button {
                            class: "x-uploads-show-all",
                            style: BTN,
                            disabled: loading(),
                            onclick: move |_| {
                                let start = next.clone();
                                spawn(async move {
                                    loading.set(true);
                                    let mut at = Some(start);
                                    while let Some(position) = at.take() {
                                        match list_upload_batches(filter(), Some(position)).await {
                                            Ok(page) => {
                                                extra.write().extend(page.rows);
                                                cursor.set(Some(page.next.clone()));
                                                at = page.next;
                                            }
                                            Err(e) => {
                                                more_error.set(Some(user_facing_message(&e)));
                                                break;
                                            }
                                        }
                                    }
                                    loading.set(false);
                                });
                            },
                            "Show all"
                        }
                    }
                }
            }
        }
    };

    rsx! {
        Title { "Hoover Search - Uploads" }
        div { style: PAGE_STYLE,
            div { style: "max-width: 1100px; margin: 0 auto;",
                h1 { style: "{H1_STYLE} margin-bottom: 15px;", "Uploads" }
                div { style: SURFACE_STYLE, {body} }
            }
        }
    }
}

#[component]
fn BatchListLine(row: UploadBatchRow) -> Element {
    let to = Route::UploadBatchPage { collection: row.collection.clone(), batch_id: row.batch_id.clone(), page: 0 };
    let state_style = if matches!(row.state.as_str(), "failed" | "completed_with_errors") {
        "color: var(--x-danger);"
    } else {
        ""
    };
    rsx! {
        tr {
            class: "x-uploads-row hoover4-hover-shadow-background",
            "data-batch": "{row.batch_id}",
            style: "cursor: pointer;",
            onclick: move |_| { navigator().push(to.clone()); },
            td { style: "{TD} white-space: nowrap;", "{started_label(row.created_ms)}" }
            td { style: "{TD} overflow-wrap: anywhere;", "{destination_label(&row)}" }
            td { style: TD, "{row.username}" }
            td { style: TD, "{format_count(row.file_count as u64)}" }
            td { style: "{TD} white-space: nowrap;", "{format_upload_size(row.byte_count)}" }
            td { style: "{TD} {state_style}", "{batch_state_label(&row.state)}" }
        }
    }
}
