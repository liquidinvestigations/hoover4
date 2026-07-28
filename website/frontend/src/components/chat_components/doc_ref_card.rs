//! Inline document card for a [`ChatDocRef`], reusing the search result card.

use common::chat_types::ChatDocRef;
use common::search_result::SearchResultDocumentItem;
use common::text_highlight::HighlightTextSpan;
use dioxus::prelude::*;

use crate::components::search_components::search_result_item_card::SearchResultItemCard;

#[component]
pub fn ChatDocRefCard(doc: ChatDocRef, index: u64) -> Element {
    if doc.collection_dataset.is_empty() || doc.file_hash.is_empty() {
        // get_document_text often returns collectionname without collection_dataset —
        // we still show a non-clickable stub rather than a broken DocumentIdentifier.
        return rsx! {
            div {
                style: "margin: 8px 0; padding: 12px 16px; border: 1px solid #E5E7EB; \
                        border-radius: 8px; background: white; font-size: 14px; color: #64748B;",
                "{doc.display_title()}"
                if !doc.collectionname.is_empty() {
                    span { style: "margin-left: 8px; font-style: italic;", "({doc.collectionname})" }
                }
            }
        };
    }

    let title = doc.display_title();
    let snippet = if doc.snippet.is_empty() {
        title.clone()
    } else {
        doc.snippet.clone()
    };
    let result = SearchResultDocumentItem {
        title: title.clone(),
        highlight_text_spans: vec![HighlightTextSpan {
            text: snippet,
            is_highlighted: false,
            index: 0,
        }],
        highlight_filenames_spans: vec![HighlightTextSpan {
            text: title,
            is_highlighted: false,
            index: 0,
        }],
        file_hash: doc.file_hash.clone(),
        collection_dataset: doc.collection_dataset.clone(),
        result_index_in_page: index,
    };

    rsx! {
        SearchResultItemCard {
            result,
            onmounted: |_| {},
        }
    }
}
