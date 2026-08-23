//! Inline document card for a [`ChatDocRef`], reusing the search result card.

use common::chat_types::ChatDocRef;
use common::search_result::SearchResultDocumentItem;
use common::text_highlight::HighlightTextSpan;
use dioxus::prelude::*;

use crate::components::search_components::search_result_item_card::SearchResultItemCard;

#[component]
pub fn ChatDocRefCard(doc: ChatDocRef, index: u64) -> Element {
    if doc.collection_dataset.is_empty() || doc.file_hash.is_empty() {
        // A card needs the dataset as well as the hash to open the document, so without
        // one it renders as a non-clickable stub rather than as a broken link.
        //
        // Every document tool returns `collection_dataset`, so this branch should be
        // unreachable. It stays as a defence and it names its own cause, because the
        // failure it guards against is a card that says nothing about why it is thin,
        // which is diagnosable only by finding the tool that produced it.
        let reason = if doc.file_hash.is_empty() {
            "no document id"
        } else {
            "no dataset, because the tool that returned this document did not name one"
        };
        return rsx! {
            div {
                style: "margin: 8px 0; padding: 12px 16px; border: 1px solid #E5E7EB; \
                        border-radius: 8px; background: white; font-size: 14px; color: #64748B;",
                "{doc.display_title()}"
                if !doc.collectionname.is_empty() {
                    span { style: "margin-left: 8px; font-style: italic;", "({doc.collectionname})" }
                }
                div {
                    style: "font-size: 12px; color: #94A3B8; margin-top: 4px;",
                    "Not openable: {reason}."
                }
            }
        };
    }

    let title = doc.display_title();
    // Clamped, not raw: a search hit's snippet is up to 1200 characters of page text and a
    // turn can return a dozen of them, so one result could bury the conversation it is
    // meant to support. `display_snippet` says what the clamp is for.
    let snippet = if doc.snippet.is_empty() {
        title.clone()
    } else {
        doc.display_snippet()
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
        // Every dataset the document was found in, not just the one whose row won the
        // collapse. `ComponentNameSection` clamps and ellipsises this, with the full list
        // in its tooltip.
        collection_dataset: if doc.also_in.is_empty() {
            doc.collection_dataset.clone()
        } else {
            let mut all = vec![doc.collection_dataset.clone()];
            all.extend(doc.also_in.iter().cloned());
            all.join(", ")
        },
        result_index_in_page: index,
        // The chat tool hands back a snippet it chose; whether the underlying hit was
        // filename-only is not part of that contract, so the card shows the snippet.
        matched_by_filename: false,
        // The chat's document card draws no type glyph of its own.
        file_type: String::new(),
    };

    rsx! {
        SearchResultItemCard {
            result,
            onmounted: |_| {},
        }
    }
}
