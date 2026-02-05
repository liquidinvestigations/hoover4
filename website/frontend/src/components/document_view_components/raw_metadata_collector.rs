use common::{document_metadata::DocumentMetadataTableInfo, search_result::DocumentIdentifier};
use dioxus::prelude::*;

use crate::components::{error_boundary::ComponentErrorDisplay, suspend_boundary::LoadingIndicator};


#[component]
pub fn RawMetadataCollector(document_identifier: ReadSignal<DocumentIdentifier>) -> Element {
    let table_list: Vec<DocumentMetadataTableInfo> = vec![
        DocumentMetadataTableInfo::new("text_content", "file_hash"),
        DocumentMetadataTableInfo::new("archives", "archive_hash"),
        DocumentMetadataTableInfo::new("vfs_files", "container_hash"),
        DocumentMetadataTableInfo::new("vfs_files", "hash"),
        DocumentMetadataTableInfo::new3("audio_metadata", "hash", vec!["audio_metadata_json"]),
        DocumentMetadataTableInfo::new("blobs", "blob_hash"),
        DocumentMetadataTableInfo::new3("email_headers", "email_hash", vec!["raw_headers_json"]),
        DocumentMetadataTableInfo::new("entity_hit", "file_hash"),
        DocumentMetadataTableInfo::new("file_types", "hash"),
        DocumentMetadataTableInfo::new3("image", "image_hash", vec!["image_metadata"]),
        DocumentMetadataTableInfo::new3("pdf_metadata", "hash", vec!["pdf_metadata_json"]),
        DocumentMetadataTableInfo::new("pdfs", "pdf_hash"),
        DocumentMetadataTableInfo::new3("tika_metadata", "hash", vec!["tika_metadata_json"]),
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
        async move {
            get_raw_metadata(document_identifier, table_info).await
    }});
    use_effect(move || {
        let _document_identifier = document_identifier();
        let _table_info = table_info();
        raw_metadata.clear();
        raw_metadata.restart();
    });
    let result = match raw_metadata().clone() {
        Some(Ok(result)) => result,
        Some(Err(e)) => return rsx! { div {
            // {section_header},
            ComponentErrorDisplay { error_txt: format!("{:#?}", e) }
        }},
        None => return rsx! { div {
            // {section_header},
            LoadingIndicator{}
        }},
    };
    if result.is_empty() {
        return rsx!{}
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
                pre {
                    style: "font-size: 14px;text-wrap: auto; max-width: 100%;",
                    "{serde_json::to_string_pretty(&item).unwrap()}"
                }
            }
        }
    }
}


#[server]
async fn get_raw_metadata(
    document_identifier: DocumentIdentifier,
    table_info: DocumentMetadataTableInfo)
-> Result<Vec<serde_json::Value>, ServerFnError> {
    backend::api::documents::get_raw_metadata::get_raw_metadata(
        document_identifier,
        table_info
    )
    .await
    .map_err(|e| ServerFnError::from(e))
}