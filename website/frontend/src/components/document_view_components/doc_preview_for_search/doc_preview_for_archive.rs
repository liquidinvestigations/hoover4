//! The Archive tab of the viewer: what an archive or a mail store holds, and where to browse
//! and search it. The facts come from `get_document_sources::archive_info`, which the agent
//! tools read too. This view changes none of them.

use common::document_provenance::{format_epoch_utc, DocumentDates};
use std::collections::BTreeSet;

use common::document_sources::{ARCHIVE, DocumentArchiveSourceItem};
use common::search_query::SearchQuery;
use common::search_result::{DocumentIdentifier, FacetOriginalValue};
use common::storage_tree::format_size;
use common::vfs::PathDescriptor;
use dioxus::prelude::*;
use dioxus_free_icons::{Icon, icons::md_content_icons::MdArchive};

use crate::api::search_api::search_date_histogram;
use crate::components::document_view_components::doc_preview_shared::PreviewWrapper;
use crate::components::document_view_components::doc_viewer_full_page::{METADATA_KEY_STYLE, SECTION_HEADER_STYLE, SECTION_STYLE};
use crate::routes::Route;

/// The canonical MIME types that establish the ZIP format. The archive kind and the file
/// name do not.
const ZIP_TYPES: &[&str] = &["application/zip", "application/x-zip-compressed"];

/// The facts of one archive in a metadata section, the dates inside it, and links to browse
/// the archive and to search inside it.
#[component]
pub fn DocumentPreviewForArchive(
    document_identifier: ReadSignal<DocumentIdentifier>,
    source: DocumentArchiveSourceItem,
) -> Element {
    let identifier = document_identifier();
    let dataset = identifier.collection_dataset.clone();
    let browse = source.node_id.as_ref().map(|_| {
        Route::file_browser_page(dataset.clone(),
                                 PathDescriptor { container_hash: identifier.file_hash.clone(), path: "/".to_string() },
                                 None)
    });
    let term = source.folder_term_id;
    let search = term.map(|term| archive_search_route(&dataset, term));
    let search_text = if source.kind == ARCHIVE && ZIP_TYPES.contains(&source.mime.as_str()) {
        "search inside this zip file"
    } else {
        "search inside this archive"
    };
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
        None => "Loading\u{2026}".to_string(),
        Some(None) => "Unknown. The archive has no folder to search.".to_string(),
        Some(Some(Err(error))) => format!("Could not load: {error}"),
        Some(Some(Ok(histogram))) if histogram.domain_end <= histogram.domain_start =>
            "No file inside has a confirmed date.".to_string(),
        Some(Some(Ok(histogram))) => format!(
            "{} to {}",
            format_epoch_utc(histogram.domain_start),
            format_epoch_utc(histogram.domain_end - 1)
        ),
    };
    let own_text = match &*own_dates.read() {
        None => "Loading\u{2026}".to_string(),
        Some(Err(error)) => format!("Could not load: {error}"),
        Some(Ok(DocumentDates { dates })) if dates.is_empty() => "No confirmed date.".to_string(),
        Some(Ok(DocumentDates { dates })) =>
            dates.iter().map(|d| format_epoch_utc(d.epoch_seconds)).collect::<Vec<_>>().join(", "),
    };
    let extracted_files = source.extracted_file_count.map(|count| count.to_string());
    let extracted_size = source.extracted_size_bytes.map(format_size);
    let size = source.size_bytes.map(format_size);
    let errors = source.processing_errors.to_string();
    let label = source.label();
    rsx! {
        PreviewWrapper {
            controls: rsx! { "{label}" },
            page: rsx! {
                div { class: "x-archive-preview", style: "padding: 12px 0; overflow-y: auto; height: 100%; box-sizing: border-box;",
                    section {
                        class: "x-archive-section",
                        style: SECTION_STYLE,
                        h1 {
                            style: SECTION_HEADER_STYLE,
                            Icon { icon: MdArchive, style: "width: 19px; height: 19px;" }
                            "{label}"
                        }
                        table {
                            style: "width: 100%; border-collapse: collapse;",
                            tbody {
                                ArchiveRow { key_text: "Extracted files", value: extracted_files, class: "x-archive-files" }
                                ArchiveRow { key_text: "Extracted size", value: extracted_size }
                                ArchiveRow { key_text: "Archive file size", value: size }
                                tr {
                                    class: "x-archive-own-dates",
                                    td { style: METADATA_KEY_STYLE, "Archive file dates" }
                                    td { style: VALUE_STYLE, "{own_text}" }
                                }
                                tr {
                                    class: "x-archive-dates-inside",
                                    td { style: METADATA_KEY_STYLE, "Dates inside" }
                                    td { style: VALUE_STYLE, "{inside_text}" }
                                }
                                ArchiveRow { key_text: "Processing errors", value: Some(errors), class: "x-archive-errors" }
                            }
                        }
                        if browse.is_some() || search.is_some() {
                            div {
                                class: "x-archive-links",
                                style: "display: flex; flex-wrap: wrap; gap: 4px 16px; margin-top: 8px;",
                                if let Some(route) = browse {
                                    Link { class: "x-archive-browse", to: route, new_tab: true, style: "color: var(--x-link);", "Browse the archive" }
                                }
                                if let Some(route) = search {
                                    Link { class: "x-archive-search", to: route, new_tab: true, style: "color: var(--x-link);", "{search_text}" }
                                }
                            }
                        } else {
                            p { style: "margin: 8px 0 0 0; color: rgba(0,0,0,0.6);", "The archive has no extracted folder to browse." }
                        }
                    }
                }
            },
        }
    }
}

const VALUE_STYLE: &str = "padding: 4px 0;";

/// One fact row. A count or a size shows in `code`. An unknown value shows as `Unknown`,
/// so it never reads as zero.
#[component]
fn ArchiveRow(key_text: &'static str, value: Option<String>, #[props(default)] class: &'static str) -> Element {
    rsx! {
        tr {
            class: "{class}",
            td { style: METADATA_KEY_STYLE, "{key_text}" }
            td {
                style: VALUE_STYLE,
                match value {
                    Some(value) => rsx! { code { "{value}" } },
                    None => rsx! { "Unknown" },
                }
            }
        }
    }
}

/// The search page scoped to the files inside the archive: the archive folder as the
/// `file_paths` parent, in the dataset of the archive only.
fn archive_search_route(dataset: &str, folder_term_id: u64) -> Route {
    let mut query = SearchQuery { collection_datasets: vec![dataset.to_string()], ..Default::default() };
    query.facet_filters.insert("file_paths".to_string(), BTreeSet::from([FacetOriginalValue::Int(folder_term_id)]));
    query.facet_filters.insert("collection_dataset".to_string(), BTreeSet::from([FacetOriginalValue::String(dataset.to_string())]));
    Route::search_page_from_query(query)
}
