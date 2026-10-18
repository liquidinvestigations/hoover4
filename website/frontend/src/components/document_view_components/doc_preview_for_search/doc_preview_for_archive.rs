//! The Archive tab of the viewer: what an archive or a mail store holds, and where to browse
//! it. The facts come from `get_document_sources::archive_info`, which the agent tools read
//! too.

use common::document_provenance::{format_epoch_utc, DocumentDates};
use common::document_sources::DocumentArchiveSourceItem;
use common::search_query::SearchQuery;
use common::search_result::{DocumentIdentifier, FacetOriginalValue};
use common::storage_tree::format_size;
use common::vfs::PathDescriptor;
use dioxus::prelude::*;

use crate::api::search_api::search_date_histogram;
use crate::components::document_view_components::doc_preview_shared::PreviewWrapper;
use crate::routes::Route;

const LINE: &str = "margin: 0 0 8px 0;";
const MUTED: &str = "margin: 0 0 8px 0; color: rgba(0,0,0,0.6);";

/// The facts of one archive, the dates inside it, and a link to the file browser.
#[component]
pub fn DocumentPreviewForArchive(
    document_identifier: ReadSignal<DocumentIdentifier>,
    source: DocumentArchiveSourceItem,
) -> Element {
    let identifier = document_identifier();
    let dataset = identifier.collection_dataset.clone();
    let files = match source.extracted_file_count {
        Some(1) => "The pipeline extracted 1 file from this archive".to_string(),
        Some(count) => format!("The pipeline extracted {count} files from this archive"),
        None => "The pipeline extracted no files from this archive".to_string(),
    };
    let inside = source.extracted_size_bytes.map(|bytes| format!(", {} in total.", format_size(bytes)))
        .unwrap_or_else(|| ".".to_string());
    let size = source.size_bytes.map(format_size);
    let errors = match source.processing_errors {
        0 => None,
        1 => Some("1 processing task recorded an error for the archive file.".to_string()),
        n => Some(format!("{n} processing tasks recorded an error for the archive file.")),
    };
    let browse = source.node_id.as_ref().map(|_| {
        Route::file_browser_page(dataset.clone(),
                                 PathDescriptor { container_hash: identifier.file_hash.clone(), path: "/".to_string() },
                                 None)
    });
    let term = source.folder_term_id;
    let histogram_dataset = dataset.clone();
    // The date range of the files inside, from a search scoped to the archive folder. It
    // loads when the tab opens.
    let dates_inside = use_resource(use_reactive!(|(term, histogram_dataset)| async move {
        let term = term?;
        let mut query = SearchQuery { collection_datasets: vec![histogram_dataset], ..Default::default() };
        query.facet_filters.entry("file_paths".to_string()).or_default().insert(FacetOriginalValue::Int(term));
        Some(search_date_histogram(query).await)
    }));
    let own_identifier = identifier.clone();
    let own_dates = use_resource(use_reactive!(|own_identifier| async move {
        crate::components::document_view_components::doc_viewer_full_page::get_document_dates(own_identifier).await
    }));
    let inside_text = match &*dates_inside.read() {
        None => "Loading the dates inside\u{2026}".to_string(),
        Some(None) => "The archive has no folder to search, so the dates inside are unknown.".to_string(),
        Some(Some(Err(error))) => format!("The dates inside could not load: {error}"),
        Some(Some(Ok(histogram))) if histogram.domain_end <= histogram.domain_start =>
            "No file inside has a confirmed date.".to_string(),
        Some(Some(Ok(histogram))) => format!(
            "Dates inside: {} to {}.",
            format_epoch_utc(histogram.domain_start),
            format_epoch_utc(histogram.domain_end - 1)
        ),
    };
    let own_text = match &*own_dates.read() {
        None => "Loading the dates of the archive\u{2026}".to_string(),
        Some(Err(error)) => format!("The dates of the archive could not load: {error}"),
        Some(Ok(DocumentDates { dates })) if dates.is_empty() => "The archive file has no confirmed date.".to_string(),
        Some(Ok(DocumentDates { dates })) => format!(
            "Dates of the archive file: {}.",
            dates.iter().map(|d| format_epoch_utc(d.epoch_seconds)).collect::<Vec<_>>().join(", ")
        ),
    };
    rsx! {
        PreviewWrapper {
            controls: rsx! { "{source.label()}" },
            page: rsx! {
                div { class: "x-archive-preview", style: "padding: 12px 16px; font-size: var(--x-text-body);",
                    p { class: "x-archive-files", style: LINE, "{files}{inside}" }
                    if source.extracted_file_count.is_some() {
                        p { style: MUTED,
                            "An extracted file can be missing from search while processing runs or after a processing failure."
                        }
                    }
                    if let Some(size) = size {
                        p { style: LINE, "Size of the archive file: {size}." }
                    }
                    p { class: "x-archive-own-dates", style: LINE, "{own_text}" }
                    p { class: "x-archive-dates-inside", style: LINE, "{inside_text}" }
                    if let Some(errors) = errors {
                        p { style: MUTED, "{errors}" }
                    }
                    if let Some(route) = browse {
                        Link { class: "x-archive-browse", to: route, style: "color: var(--x-link);", "Browse the archive" }
                    } else {
                        p { style: MUTED, "The archive has no extracted folder to browse." }
                    }
                }
            },
        }
    }
}
