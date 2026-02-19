//! Document preview components for search results.

mod no_document_selected;
mod preview_subtitle_bar;
mod text_data_viewer;
mod doc_preview_for_pdf;
mod doc_preview_for_text;

use common::document_text_sources::{DocumentTextSourceHit, DocumentTextSourceHitCount, DocumentTextSourceItem};
use common::pdf_to_html_conversion::PDFToHtmlConversionResponse;
use dioxus::logger::tracing;
use dioxus::prelude::*;
use common::search_query::SearchQuery;
use common::search_result::DocumentIdentifier;

use crate::components::document_view_components::doc_preview_for_search::doc_preview_for_pdf::{DocumentPreviewForPdf, get_document_type_is_pdf};
use crate::components::document_view_components::doc_preview_for_search::doc_preview_for_text::DocumentPreviewForTextWithSearch;
use crate::components::document_view_components::doc_title_bar::DocTitleBar;
use crate::components::document_view_components::raw_metadata_collector::RawMetadataCollector;
use crate::components::suspend_boundary::LoadingIndicator;
use crate::pages::search_page::DocViewerStateControl;

#[component]
pub fn DocumentPreviewForSearchRoot(
    query: ReadSignal<SearchQuery>,
    selected_result_hash: ReadSignal<Option<DocumentIdentifier>>,
) -> Element {
    let Some(document_identifier) = selected_result_hash.read().clone() else {
        return rsx! {
            no_document_selected::NoDocumentSelected {}
        }
    };

    let is_pdf = use_resource(move || {
        let document_identifier = selected_result_hash.read().clone();
        async move {
            let Some(document_identifier) = document_identifier else { return false };
            if let Ok(is_pdf) = get_document_type_is_pdf(document_identifier).await {
                return is_pdf;
            } else {
                return false;
            };
        }
    });

    match is_pdf.read().clone() {
        Some(true) => {
            rsx! {
                DocumentPreviewForPdf { document_identifier }
            }
        }
        Some(false) => {
            rsx! {
                DocumentPreviewForTextWithSearch { document_identifier }
            }
        }
        None => {
            return rsx! {
                LoadingIndicator {  }
            }
        }
    }
}

