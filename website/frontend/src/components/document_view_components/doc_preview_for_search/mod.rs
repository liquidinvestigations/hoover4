//! Document preview components for search results.

mod doc_preview_for_pdf;
mod doc_preview_for_text;
mod no_document_selected;
mod preview_subtitle_bar;
mod text_data_viewer;

use common::search_query::SearchQuery;
use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use crate::components::document_view_components::doc_preview_for_search::doc_preview_for_pdf::{
    DocumentPreviewForPdf, get_document_type_is_pdf,
};
use crate::components::document_view_components::doc_preview_for_search::doc_preview_for_text::DocumentPreviewForTextWithSearch;
use crate::components::suspend_boundary::LoadingIndicator;

#[component]
pub fn DocumentPreviewForSearchRoot(
    query: ReadSignal<SearchQuery>,
    selected_result_hash: ReadSignal<Option<DocumentIdentifier>>,
) -> Element {
    let Some(document_identifier) = selected_result_hash.read().clone() else {
        return rsx! {
            no_document_selected::NoDocumentSelected {}
        };
    };

    let mut is_pdf = use_resource(move || {
        let document_identifier = selected_result_hash.peek().clone();
        async move {
            let Some(document_identifier) = document_identifier else {
                return (false, 0_u32);
            };
            if let Ok(is_pdf) = get_document_type_is_pdf(document_identifier).await {
                return is_pdf;
            } else {
                return (false, 0_u32);
            };
        }
    });
    use_effect(move || {
        let _document_identifier = selected_result_hash.read().clone();
        // let Some(_document_identifier) = document_identifier else { return };
        is_pdf.clear();
        is_pdf.restart();
    });

    match is_pdf.read().clone() {
        Some((true, page_count)) => {
            rsx! {
                DocumentPreviewForPdf { document_identifier, page_count }
            }
        }
        Some((false, _)) => {
            rsx! {
                DocumentPreviewForTextWithSearch { document_identifier }
            }
        }
        None => {
            return rsx! {
                LoadingIndicator {  }
            };
        }
    }
}
