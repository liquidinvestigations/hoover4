//! Component for rendering raw metadata.

use common::{
    document_metadata::DocumentMetadataTableInfo,
    document_provenance::{DocumentDates, DocumentEmail, format_epoch_utc},
    search_result::DocumentIdentifier,
};
use dioxus::prelude::*;
use dioxus_free_icons::{
    Icon,
    icons::{
        go_icons::GoCopy,
        md_action_icons::MdDateRange,
        md_communication_icons::MdEmail,
        md_file_icons::MdAttachment,
    },
};
use std::collections::BTreeMap;

use crate::components::{
    error_boundary::ServerErrorDisplay, suspend_boundary::LoadingIndicator,
};

#[component]
pub fn RawMetadataCollector(document_identifier: ReadSignal<DocumentIdentifier>) -> Element {
    let table_list: Vec<DocumentMetadataTableInfo> = vec![
        // DocumentMetadataTableInfo::new("text_content", "file_hash"),
        DocumentMetadataTableInfo::new("blobs", "blob_hash"),
        DocumentMetadataTableInfo::new("file_types", "hash"),
        DocumentMetadataTableInfo::new3("tika_metadata", "hash", vec!["tika_metadata_json"]),
        DocumentMetadataTableInfo::new("archives", "archive_hash"),
        DocumentMetadataTableInfo::new("vfs_files", "container_hash"),
        DocumentMetadataTableInfo::new("vfs_files", "hash"),
        DocumentMetadataTableInfo::new3("audio_metadata", "hash", vec!["audio_metadata_json"]),
        DocumentMetadataTableInfo::new3("email_headers", "email_hash", vec!["raw_headers_json"]),
        // DocumentMetadataTableInfo::new("entity_hit", "file_hash"),
        DocumentMetadataTableInfo::new3("image", "image_hash", vec!["image_metadata"]),
        DocumentMetadataTableInfo::new3("pdf_metadata", "hash", vec!["pdf_metadata_json"]),
        DocumentMetadataTableInfo::new("pdfs", "pdf_hash"),
        DocumentMetadataTableInfo::new3("video_metadata", "hash", vec!["video_metadata_json"]),
        DocumentMetadataTableInfo::new3("raw_ocr_results", "image_hash", vec!["raw_json"]),
        DocumentMetadataTableInfo::new("processing_errors", "hash"),
    ];

    let document_identifier_value = document_identifier();
    // One request for every table. Reading the values (not the signals) through
    // `use_reactive` is what makes this re-fetch when the document actually changes:
    // a `ReadSignal` prop is a fresh signal on every parent render, so a resource that
    // subscribes to it is subscribed to a signal nobody will ever write to.
    let raw_metadata = use_resource(use_reactive!(|document_identifier_value, table_list| {
        async move { get_raw_metadata_tables(document_identifier_value, table_list).await }
    }));

    let sections = match raw_metadata().clone() {
        Some(Ok(results)) => rsx! {
            for (table_info, rows) in table_list.iter().cloned().zip(results) {
                RawMetadataCollectorSection {
                    key: "{document_identifier_value:?}-{table_info:?}",
                    table_info,
                    rows,
                }
            }
        },
        Some(Err(e)) => rsx! {
            div { ServerErrorDisplay { error: e } }
        },
        None => rsx! {
            div { LoadingIndicator {} }
        },
    };

    rsx! {
        ul {
            style: "
                display: flex;
                flex-direction: column;
                gap: 10px;
                overflow-y: scroll;
                max-height: 100%;
            ",
            // Curated first, raw dumps after. These two answer the questions people
            // arrive with; the tables below answer "what else is there".
            DatesSection { document_identifier }
            EmailSection { document_identifier }
            {sections}
        }
    }
}

#[component]
fn RawMetadataCollectorSection(
    table_info: ReadSignal<DocumentMetadataTableInfo>,
    rows: ReadSignal<Vec<serde_json::Value>>,
) -> Element {
    if rows().is_empty() {
        return rsx! {};
    }
    rsx! {
        li {
            style: "
                border: 1px solid black;
                border-radius: 20px;
                padding: 20px;
                margin: 15px 30px;
            ",
            h1 {
                style: "font-size: 28px; display: flex; flex-direction: row; gap: 10px;",
                "{table_info().table_name}",
                span {
                    style: "font-size: 14px;",
                    "{table_info().hash_column_name}"
                }
            }
            for item in rows() {
                RawMetadataTable { value: item }
            }
        }
    }
}

#[component]
fn RawMetadataTable(value: serde_json::Value) -> Element {
    let rows = flatten_json_for_table(&value);
    rsx! {
        table {
            style: "
                width: 100%;
                border-collapse: separate;
                border-spacing: 0;
                margin-top: 6px;
                font-size: 14px;
            ",
            tbody {
                for (k, v) in rows.into_iter().take(100) {
                    tr {
                        td {
                            style: "
                                width: 35%;
                                padding: 3px;
                                vertical-align: top;
                                color: rgba(0, 0, 0, 0.85);
                                font-weight: 500;
                                word-break: break-word;
                                border-bottom: 1px solid rgba(0, 0, 0, 0.18);
                            ",
                            "{k}"
                        }
                        td {
                            style: "
                                padding: 3px;
                                vertical-align: top;
                                color: rgba(0, 0, 0, 0.95);
                                word-break: break-word;
                                font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, \"Liberation Mono\", \"Courier New\", monospace;
                                border-bottom: 1px solid rgba(0, 0, 0, 0.18);
                            ",
                            "{ truncate_for_table(&v, 150) }"
                        }
                        td {
                            style: "
                                width: 44px;
                                padding: 3px;
                                vertical-align: top;
                                border-bottom: 1px solid rgba(0, 0, 0, 0.18);
                            ",
                            button {
                                style: "
                                    width: 24px;
                                    height: 24px;
                                    cursor: pointer;
                                    border: 1px solid rgba(0, 0, 0, 0.35);
                                    border-radius: 8px;
                                    background: white;
                                    color: black;
                                    display: inline-flex;
                                    align-items: center;
                                    justify-content: center;
                                ",
                                onclick: move |_e| {
                                    _e.prevent_default();
                                    _e.stop_propagation();
                                    // TODO: Copy full, untruncated value to browser clipboard.

                                    let _r = web_sys::window()
                                        .unwrap()
                                        .navigator()
                                        .clipboard()
                                        .write_text(&v);
                                    let k = truncate_for_table(&k, 16);

                                    let toast_api = dioxus_primitives::toast::consume_toast();
                                    toast_api.info(
                                        "Data copied to clipboard.".to_string(),

                                        dioxus_primitives::toast::ToastOptions::new()
                                            .description(format!("The data for key = '{k}' has been copied to your clipboard."))
                                            .duration(std::time::Duration::from_secs(7))
                                            .permanent(false),
                                    );

                                },
                                CopyIcon{}
                            }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn CopyIcon() -> Element {
    rsx! {
        Icon {
            icon: GoCopy,
            style: "width: 24px; height: 24px;",
            width: 24,
            height: 24,
        }
    }
}

fn flatten_json_for_table(value: &serde_json::Value) -> Vec<(String, String)> {
    let mut map = BTreeMap::<String, String>::new();
    flatten_json_into_map(value, "", &mut map);
    map.into_iter().map(|(k, v)| (k, v)).collect()
}

fn flatten_json_into_map(
    value: &serde_json::Value,
    prefix: &str,
    out: &mut BTreeMap<String, String>,
) {
    match value {
        serde_json::Value::Object(obj) => {
            for (k, v) in obj {
                let next_prefix = if prefix.is_empty() {
                    k.to_string()
                } else {
                    format!("{prefix}.{k}")
                };
                flatten_json_into_map(v, &next_prefix, out);
            }
        }
        serde_json::Value::Array(arr) => {
            for (idx, v) in arr.iter().enumerate() {
                let next_prefix = if prefix.is_empty() {
                    format!("[{idx}]")
                } else {
                    format!("{prefix}[{idx}]")
                };
                flatten_json_into_map(v, &next_prefix, out);
            }
        }
        _ => {
            let key = if prefix.is_empty() {
                "(root)".to_string()
            } else {
                prefix.to_string()
            };
            let rendered = match value {
                serde_json::Value::String(s) => s.clone(),
                _ => value.to_string(),
            };
            out.insert(key, rendered);
        }
    }
}

fn truncate_for_table(s: &str, max_chars: usize) -> String {
    let mut it = s.chars();
    let prefix: String = it.by_ref().take(max_chars).collect();
    if it.next().is_some() {
        format!("{prefix}…")
    } else {
        prefix
    }
}

#[server]
async fn get_raw_metadata_tables(
    document_identifier: DocumentIdentifier,
    table_list: Vec<DocumentMetadataTableInfo>,
) -> Result<Vec<Vec<serde_json::Value>>, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::documents::get_raw_metadata::get_raw_metadata_tables(
        &user,
        document_identifier,
        table_list,
    )
    .await
    .map_err(crate::api::error_util::to_server_fn_error)
}


// ---------- Curated provenance sections ----------

const SECTION_STYLE: &str = "
    border: 1px solid black;
    border-radius: 20px;
    padding: 20px;
    margin: 15px 30px;
";

const SECTION_HEADER_STYLE: &str = "
    font-size: 28px;
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 10px;
";

/// Every date the indexer confirmed, with the metadata key it came from.
///
/// Always rendered, even when empty. "This document has no confirmed dates" is the
/// answer to "why did my date filter miss it", and an absent section is not an answer —
/// it is indistinguishable from a section that failed to load.
#[component]
fn DatesSection(document_identifier: ReadSignal<DocumentIdentifier>) -> Element {
    let document_identifier_value = document_identifier();
    let dates = use_resource(use_reactive!(|document_identifier_value| {
        async move { get_document_dates(document_identifier_value).await }
    }));

    let body = match dates().clone() {
        // Named states, unlike the anonymous red boxes the raw sections render.
        None => rsx! {
            div { style: "color: rgba(0,0,0,0.55);", "Loading dates…" }
        },
        Some(Err(error)) => rsx! {
            div {
                class: "x-error-display",
                style: "color: rgb(160,30,30);",
                "Could not load the dates for this document: {error}"
            }
        },
        Some(Ok(DocumentDates { dates })) if dates.is_empty() => rsx! {
            div {
                style: "color: rgba(0,0,0,0.6);",
                "No confirmed dates. Nothing in this document's metadata gave a date we
                 trust, so it will not match any date range — only "
                b { "Unknown only" }
                "."
            }
        },
        Some(Ok(DocumentDates { dates })) => rsx! {
            table {
                style: "width: 100%; border-collapse: collapse;",
                tbody {
                    for date in dates {
                        tr {
                            key: "{date.epoch_seconds}-{date.source}",
                            td {
                                style: "padding: 4px 12px 4px 0; white-space: nowrap; font-variant-numeric: tabular-nums;",
                                "{format_epoch_utc(date.epoch_seconds)}"
                            }
                            td {
                                style: "padding: 4px 0; color: rgba(0,0,0,0.65); font-size: 14px;",
                                "{date.source}"
                            }
                        }
                    }
                }
            }
        },
    };

    rsx! {
        li {
            style: SECTION_STYLE,
            h1 {
                style: SECTION_HEADER_STYLE,
                Icon { icon: MdDateRange, style: "width: 26px; height: 26px;" }
                "Dates"
            }
            {body}
        }
    }
}

/// Subject, participants grouped by role, and the send date when it is real.
///
/// Rendered only when the document IS an email — unlike Dates, an absent Email section
/// on a PDF is the correct answer rather than a missing one.
#[component]
fn EmailSection(document_identifier: ReadSignal<DocumentIdentifier>) -> Element {
    let document_identifier_value = document_identifier();
    let email = use_resource(use_reactive!(|document_identifier_value| {
        async move { get_document_email(document_identifier_value).await }
    }));

    let value = match email().clone() {
        None => return rsx! {},
        Some(Err(error)) => {
            return rsx! {
                li {
                    style: SECTION_STYLE,
                    h1 {
                        style: SECTION_HEADER_STYLE,
                        Icon { icon: MdEmail, style: "width: 26px; height: 26px;" }
                        "Email"
                    }
                    div {
                        class: "x-error-display",
                        style: "color: rgb(160,30,30);",
                        "Could not load the email header: {error}"
                    }
                }
            };
        }
        Some(Ok(None)) => return rsx! {},
        Some(Ok(Some(value))) => value,
    };

    rsx! {
        li {
            style: SECTION_STYLE,
            h1 {
                style: SECTION_HEADER_STYLE,
                Icon { icon: MdEmail, style: "width: 26px; height: 26px;" }
                "Email"
            }
            table {
                style: "width: 100%; border-collapse: collapse;",
                tbody {
                    if !value.subject.is_empty() {
                        tr {
                            td { style: "padding: 4px 12px 4px 0; color: rgba(0,0,0,0.6); vertical-align: top; white-space: nowrap;", "Subject" }
                            td { style: "padding: 4px 0;", "{value.subject}" }
                        }
                    }
                    if let Some(sent) = value.date_sent {
                        tr {
                            td { style: "padding: 4px 12px 4px 0; color: rgba(0,0,0,0.6); vertical-align: top; white-space: nowrap;", "Sent" }
                            td { style: "padding: 4px 0; font-variant-numeric: tabular-nums;", "{format_epoch_utc(sent)}" }
                        }
                    }
                    for (role, label) in [("from", "From"), ("to", "To"), ("cc", "Cc"), ("bcc", "Bcc")] {
                        {
                            let people = value.participants_with_role(role);
                            if people.is_empty() {
                                rsx! {}
                            } else {
                                let rendered: Vec<String> = people.iter().map(|p| p.display()).collect();
                                rsx! {
                                    tr {
                                        key: "{role}",
                                        td { style: "padding: 4px 12px 4px 0; color: rgba(0,0,0,0.6); vertical-align: top; white-space: nowrap;", "{label}" }
                                        td {
                                            style: "padding: 4px 0;",
                                            for person in rendered {
                                                div { key: "{person}", "{person}" }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            if value.attachment_count > 0 {
                div {
                    style: "display: flex; align-items: center; gap: 6px; margin-top: 10px; color: rgba(0,0,0,0.7);",
                    Icon { icon: MdAttachment, style: "width: 20px; height: 20px;" }
                    "{value.attachment_count} attachment(s) — browse them by opening this email in Storage."
                }
            }
        }
    }
}

#[server]
async fn get_document_dates(
    document_identifier: DocumentIdentifier,
) -> Result<DocumentDates, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::documents::get_document_provenance::get_document_dates(&user, document_identifier)
        .await
        .map_err(crate::api::error_util::to_server_fn_error)
}

#[server]
async fn get_document_email(
    document_identifier: DocumentIdentifier,
) -> Result<Option<DocumentEmail>, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::documents::get_document_provenance::get_document_email(&user, document_identifier)
        .await
        .map_err(crate::api::error_util::to_server_fn_error)
}
