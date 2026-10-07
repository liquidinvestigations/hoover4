//! Inline document card for a [`ChatDocRef`], reusing the search result card.

use std::cell::RefCell;
use std::rc::Rc;

use common::chat_types::{ChatDocRef, clamp_display_text};
use common::search_result::{DocumentIdentifier, SearchResultDocumentItem};
use common::text_highlight::HighlightTextSpan;
use dioxus::prelude::*;

use crate::components::search_components::search_panel_left_view::SearchResultsState;
use crate::components::search_components::search_result_item_card::SearchResultItemCard;

/// Opens one document in the chat page's side pane at a find query. The chat page
/// provides it. A card with no provider opens the document the way a search result does.
#[derive(Clone, Copy)]
pub struct ChatDocOpen {
    pub open: Callback<(DocumentIdentifier, String)>,
}

#[component]
pub fn ChatDocRefCard(doc: ChatDocRef, index: u64, #[props(default)] passages: Vec<ChatDocRef>) -> Element {
    // The click reads the document and its find query of the latest render, because a
    // card instance can receive another document while it stays mounted.
    let target = use_hook(|| Rc::new(RefCell::new((doc.document_identifier(), String::new()))));
    *target.borrow_mut() = (doc.document_identifier(), doc.find_query.clone());
    let chat_open = try_use_context::<ChatDocOpen>();
    let parent = use_context::<SearchResultsState>();
    use_context_provider({
        let target = target.clone();
        move || SearchResultsState {
            set_selected_result_hash: Callback::new(move |id: Option<DocumentIdentifier>| {
                match (chat_open, id) {
                    // The card's own identifier, never the one the result card builds,
                    // because that one joins every dataset of a collapsed document.
                    (Some(chat_open), Some(_)) => chat_open.open.call(target.borrow().clone()),
                    (_, id) => parent.set_selected_result_hash.call(id),
                }
            }),
            ..parent
        }
    });

    if doc.collection_dataset.is_empty() || doc.file_hash.is_empty() {
        // A card needs the dataset as well as the hash to open the document, so without
        // one it renders as a non-clickable stub rather than as a broken link.
        //
        // `search_collections` rows, `read_documents` entries and `cite_documents`
        // results name `collection_dataset`. A row stored before a tool named it, and a
        // tool result that holds a document with no dataset, reach this branch. It names
        // its own cause, because a card that says nothing about why it is thin is
        // diagnosable only by finding the tool that produced it.
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
    let snippet = if !doc.search_snippet.is_empty() {
        clamp_display_text(&doc.search_snippet, 600)
    } else if doc.snippet.is_empty() && !doc.quote.is_empty() {
        clamp_display_text(&doc.quote, 600)
    } else if doc.snippet.is_empty() {
        title.clone()
    } else {
        doc.display_snippet()
    };
    let result = SearchResultDocumentItem {
        title: title.clone(),
        highlight_text_spans: search_snippet_parts(&snippet, &doc.term).into_iter().enumerate()
            .map(|(index, (text, is_highlighted))| HighlightTextSpan { text, is_highlighted, index: index as u64 }).collect(),
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
        file_size_bytes: None,
        document_date: None,
    };

    let mut quotes = Vec::new();
    let passages = passages.into_iter().filter(|passage| {
        if !passage.quote_verified || passage.quote.is_empty() || quotes.contains(&passage.quote) { return false; }
        quotes.push(passage.quote.clone());
        true
    }).collect::<Vec<_>>();
    let selected_target = (doc.document_identifier(), doc.find_query.clone());
    rsx! {
        div {
            button { "data-citation-select": "true", hidden: true, tabindex: "-1", onclick: move |_| { if let Some(open) = chat_open { open.open.call(selected_target.clone()); } } }
            SearchResultItemCard {
                result,
                onmounted: |_| {},
                citation_excerpt: !doc.search_snippet.is_empty(),
                children: Some(rsx! {
                    for (index, passage) in passages.into_iter().enumerate() {
                        button { key: "{index}", r#type: "button", style: "border: 0; background: transparent; color: inherit; text-align: left; padding: 6px 0; font: inherit; cursor: pointer;",
                            onclick: move |event| { event.stop_propagation(); if let Some(open) = chat_open { open.open.call((passage.document_identifier(), passage.find_query.clone())); } },
                            "{passage.quote}"
                        }
                    }
                }),
            }
            if !doc.term.is_empty() && !doc.search_route.is_empty() {
                div { "data-citation-search-term": "{doc.term}", style: "padding: 0 12px; font-size: 12px;",
                    Link { to: doc.search_route.clone(), style: "color: #475569;",
                        "The search term was "
                        strong { em { code { "{doc.term}" } } }
                        "."
                    }
                }
            }
        }
    }
}

/// One document of a search row as a line: path, collection and an "Open" action. The
/// action opens the document in the side pane at the query that matched it.
#[component]
pub fn ChatDocRefRow(doc: ChatDocRef) -> Element {
    let chat_open = try_use_context::<ChatDocOpen>();
    let openable = !doc.collection_dataset.is_empty() && !doc.file_hash.is_empty();
    let label = if doc.path.is_empty() { doc.display_title() } else { doc.path.clone() };
    let target = (doc.document_identifier(), doc.find_query.clone());
    rsx! {
        div {
            class: "x-chat-docref-row",
            style: "display: flex; align-items: baseline; gap: 10px; font-size: 13px; \
                    padding: 4px 8px; background: white; border: 1px solid #E5E7EB; \
                    border-radius: 6px;",
            span { style: "flex: 1; min-width: 0; word-break: break-all; color: #1E293B;", "{label}" }
            if !doc.collectionname.is_empty() {
                span { style: "flex-shrink: 0; font-style: italic; color: #64748B;", "{doc.collectionname}" }
            }
            match (openable, chat_open) {
                (true, Some(chat_open)) => rsx! {
                    button {
                        style: "flex-shrink: 0; background: none; border: none; padding: 0; \
                                cursor: pointer; color: #4F46E5; text-decoration: underline; \
                                font-size: 12px;",
                        onclick: move |_| chat_open.open.call(target.clone()),
                        "Open"
                    }
                },
                _ => rsx! {
                    span { style: "flex-shrink: 0; font-size: 12px; color: #94A3B8;", "Not openable" }
                },
            }
        }
    }
}


fn search_snippet_parts(text: &str, query: &str) -> Vec<(String, bool)> {
    let chars: Vec<char> = text.chars().collect();
    let mut marked = vec![false; chars.len()];
    for word in query.split(|character: char| !character.is_alphanumeric())
        .filter(|word| !word.is_empty() && !matches!(*word, "AND" | "OR" | "NOT"))
    {
        let length = word.chars().count();
        let needle = word.to_lowercase();
        for start in 0..chars.len() {
            if start + length <= chars.len()
                && chars[start..start + length].iter().collect::<String>().to_lowercase() == needle
            {
                marked[start..start + length].fill(true);
            }
        }
    }
    let mut parts: Vec<(String, bool)> = Vec::new();
    for (character, highlight) in chars.into_iter().zip(marked) {
        if let Some(last) = parts.last_mut() && last.1 == highlight {
            last.0.push(character);
        } else {
            parts.push((character.to_string(), highlight));
        }
    }
    parts
}

#[cfg(test)]
mod tests {
    use super::search_snippet_parts;

    #[test]
    fn search_highlighting_preserves_unicode_and_marks_query_words() {
        let text = "ȘTEFAN approved the budget.";
        let parts = search_snippet_parts(text, "Ștefan AND budget");
        assert_eq!(parts.iter().map(|part| part.0.as_str()).collect::<String>(), text);
        assert_eq!(parts.iter().filter(|part| part.1).map(|part| part.0.as_str()).collect::<Vec<_>>(),
            vec!["ȘTEFAN", "budget"]);
    }
}
