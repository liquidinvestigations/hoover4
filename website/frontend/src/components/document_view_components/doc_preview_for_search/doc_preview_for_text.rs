use common::document_sources::{DocumentSourceItem, DocumentTextSourceItem};
use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use crate::components::document_view_components::doc_preview_for_search::{
    text_preview_with_search::DocumentPreviewTextWithSearch
};

#[component]
pub fn DocumentPreviewForTextWithSearch(
    document_identifier: ReadSignal<DocumentIdentifier>,
    source: ReadSignal<DocumentTextSourceItem>,
) -> Element {
    rsx! {
        DocumentPreviewTextWithSearch {
            document_identifier,
            source,
            preamble: rsx! {},
        }
    }
}

fn _get_text_sources(document_sources: Vec<DocumentSourceItem>) -> Vec<DocumentTextSourceItem> {
    document_sources
        .iter()
        .filter_map(|source| match source {
            DocumentSourceItem::Text(text_source) => Some(text_source.clone()),
            _ => None,
        })
        .collect()
}
