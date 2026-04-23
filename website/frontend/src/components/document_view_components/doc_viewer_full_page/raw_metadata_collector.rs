//! Component for rendering raw metadata.

use common::{document_metadata::DocumentMetadataTableInfo, search_result::DocumentIdentifier};
use dioxus::prelude::*;
use std::collections::BTreeMap;

use crate::components::{
    error_boundary::ComponentErrorDisplay, suspend_boundary::LoadingIndicator,
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

    rsx! {
        ul {
            style: "
                display: flex;
                flex-direction: column;
                gap: 10px;
                overflow-y: scroll;
                max-height: 100%;
            ",
            for table_info in table_list {
                RawMetadataCollectorSection {
                    document_identifier,
                    table_info
                }
            }
        }
    }
}

#[component]
fn RawMetadataCollectorSection(
    document_identifier: ReadSignal<DocumentIdentifier>,
    table_info: ReadSignal<DocumentMetadataTableInfo>,
) -> Element {
    let section_header = rsx! {
        h1 {
            style: "font-size: 28px; display: flex; flex-direction: row; gap: 10px;",
            "{table_info().table_name}",
            span {
                style: "font-size: 14px;",
                "{table_info().hash_column_name}"
            }
        }
    };
    let mut raw_metadata = use_resource(move || {
        let document_identifier = document_identifier();
        let table_info = table_info();
        async move { get_raw_metadata(document_identifier, table_info).await }
    });
    use_effect(move || {
        let _document_identifier = document_identifier();
        let _table_info = table_info();
        raw_metadata.clear();
        raw_metadata.restart();
    });
    let result = match raw_metadata().clone() {
        Some(Ok(result)) => result,
        Some(Err(e)) => {
            return rsx! { div {
                // {section_header},
                ComponentErrorDisplay { error_txt: format!("{:#?}", e) }
            }};
        }
        None => {
            return rsx! { div {
                // {section_header},
                LoadingIndicator{}
            }};
        }
    };
    if result.is_empty() {
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
            key: "{document_identifier():?}-{table_info():?}",
            {section_header}
            for item in result {
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
                                    dioxus::logger::tracing::info!("Data copied to clipboard: {:#?}", v);
                                },
                                span { style: "font-size: 16px; line-height: 18px;", "📋" }
                            }
                        }
                    }
                }
            }
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
async fn get_raw_metadata(
    document_identifier: DocumentIdentifier,
    table_info: DocumentMetadataTableInfo,
) -> Result<Vec<serde_json::Value>, ServerFnError> {
    backend::api::documents::get_raw_metadata::get_raw_metadata(document_identifier, table_info)
        .await
        .map_err(|e| ServerFnError::from(e))
}
