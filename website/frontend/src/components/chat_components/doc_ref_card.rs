//! Inline document card for a [`ChatDocRef`], reusing the search result card.

use std::cell::RefCell;
use std::rc::Rc;

use common::chat_types::{ChatDocRef, card_find_phrase, clamp_display_text};
use common::search_result::{DocumentCardFacts, DocumentIdentifier, SearchResultDocumentItem};
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

/// The chat page's record of its scroll to the selected document. The first card of the
/// selected document scrolls to the middle of the transcript when it mounts, once for each
/// session, as the search page does with a selected result. A card on a page without this
/// context (the board page) does not scroll.
#[derive(Clone, Copy)]
pub struct ChatScrolledToSelection {
    pub session_id: ReadSignal<String>,
    /// The session whose selected card has scrolled into view, `None` before the scroll.
    pub scrolled_for: Signal<Option<String>>,
}

#[component]
pub fn ChatDocRefCard(doc: ChatDocRef, index: u64, #[props(default)] passages: Vec<ChatDocRef>) -> Element {
    // The click reads the document and its find query of the latest render, because a
    // card instance can receive another document while it stays mounted.
    let target = use_hook(|| Rc::new(RefCell::new((doc.document_identifier(), String::new()))));
    *target.borrow_mut() = (doc.document_identifier(), card_find_phrase(&doc.find_query));
    let chat_open = try_use_context::<ChatDocOpen>();
    let parent = use_context::<SearchResultsState>();
    let scroll_record = try_use_context::<ChatScrolledToSelection>();
    // The card's own identifier, never the one the result card builds, because that one
    // joins every dataset of a collapsed document.
    let own_identifier = doc.document_identifier();
    let on_card_mounted = move |event: Event<MountedData>| {
        let Some(mut record) = scroll_record else { return };
        let session = record.session_id.peek().clone();
        if record.scrolled_for.peek().as_deref() == Some(session.as_str())
            || parent.selected_result_hash.peek().as_ref() != Some(&own_identifier)
        {
            return;
        }
        record.scrolled_for.set(Some(session));
        spawn(async move {
            let _ = event.scroll_to_with_options(ScrollToOptions {
                behavior: ScrollBehavior::Instant,
                vertical: ScrollLogicalPosition::Center,
                horizontal: ScrollLogicalPosition::Nearest,
            }).await;
        });
    };
    // The size and the dates of the document, which a stored citation does not hold. The
    // lines stay empty while they load and after a failure. This hook stays above the
    // early return of the stub card, so the hook order does not change.
    let identifier = doc.document_identifier();
    let facts = use_resource(use_reactive!(|identifier| async move {
        if identifier.collection_dataset.is_empty() || identifier.file_hash.is_empty() {
            return DocumentCardFacts::default();
        }
        get_document_card_facts(identifier).await.unwrap_or_else(|error| {
            dioxus::logger::tracing::warn!("card facts failed: {error}");
            DocumentCardFacts::default()
        })
    }));
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
                style: "margin: 8px 0; padding: 12px 16px; border: 1px solid; border-color: var(--x-border); \
                        border-radius: 8px; background: white; font-size: var(--x-text-md); color: var(--x-ink-muted);",
                "{doc.display_title()}"
                if !doc.collectionname.is_empty() {
                    span { style: "margin-left: 8px; font-style: italic;", "({doc.collectionname})" }
                }
                div {
                    style: "font-size: var(--x-text-xs); color: var(--x-ink-faint); margin-top: 4px;",
                    "Not openable: {reason}."
                }
            }
        };
    }

    let card_facts = facts.read().unwrap_or_default();
    let title = doc.display_title();
    // A verified passage line below shows the quote. The snippet then does not repeat it.
    let passage_shows_quote = !doc.quote.is_empty()
        && passages.iter().any(|passage| passage.quote_verified && passage.quote == doc.quote);
    // Clamped, not raw: a search hit's snippet is up to 1200 characters of page text and a
    // turn can return a dozen of them, so one result could bury the conversation it is
    // meant to support. `display_snippet` says what the clamp is for.
    let snippet = if !doc.search_snippet.is_empty() {
        clamp_display_text(&doc.search_snippet, 600)
    } else if doc.snippet.is_empty() && passage_shows_quote {
        String::new()
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
        file_size_bytes: card_facts.file_size_bytes,
        document_date: card_facts.date_min,
        document_date_max: card_facts.date_max,
    };

    let mut quotes = Vec::new();
    let passages = passages.into_iter().filter(|passage| {
        if !passage.quote_verified || passage.quote.is_empty() || quotes.contains(&passage.quote) { return false; }
        quotes.push(passage.quote.clone());
        true
    }).collect::<Vec<_>>();
    let selected_target = (doc.document_identifier(), card_find_phrase(&doc.find_query));
    rsx! {
        div {
            button { "data-citation-select": "true", hidden: true, tabindex: "-1", onclick: move |_| { if let Some(open) = chat_open { open.open.call(selected_target.clone()); } } }
            SearchResultItemCard {
                result,
                onmounted: on_card_mounted,
                citation_excerpt: !doc.search_snippet.is_empty(),
                citation_handle: doc.handle.clone(),
                children: Some(rsx! {
                    for (index, passage) in passages.into_iter().enumerate() {
                        {
                            let target = (passage.document_identifier(), card_find_phrase(&passage.find_query));
                            let key_target = target.clone();
                            rsx! {
                                // A `div`, not a `button`: the card's three-line limit does
                                // not count the lines inside a button. No vertical padding,
                                // because the limit does not count padding either.
                                div { key: "{index}", role: "button", tabindex: "0", style: "cursor: pointer;",
                                    onclick: move |event| { event.stop_propagation(); if let Some(open) = chat_open { open.open.call(target.clone()); } },
                                    onkeydown: move |event: Event<KeyboardData>| {
                                        if event.key() == Key::Enter || event.key() == Key::Character(" ".to_string()) {
                                            event.prevent_default();
                                            event.stop_propagation();
                                            if let Some(open) = chat_open { open.open.call(key_target.clone()); }
                                        }
                                    },
                                    "{passage.quote}"
                                }
                            }
                        }
                    }
                }),
            }
            if !doc.term.is_empty() && !doc.search_route.is_empty() {
                div { "data-citation-search-term": "{doc.term}", style: "padding: 0 12px; font-size: var(--x-text-xs);",
                    Link { to: doc.search_route.clone(), style: "color: var(--x-ink);",
                        "The search term was "
                        strong { em { code { "{doc.term}" } } }
                        "."
                    }
                }
            }
        }
    }
}

/// The size and the dates of one document for a chat or board card
/// (`backend::api::documents::get_document_card_facts`).
#[server]
async fn get_document_card_facts(
    document_identifier: DocumentIdentifier,
) -> Result<DocumentCardFacts, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::documents::get_document_card_facts::get_document_card_facts(&user, document_identifier)
        .await
        .map_err(crate::api::error_util::to_server_fn_error)
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
            style: "display: flex; align-items: baseline; gap: 10px; font-size: var(--x-text-sm); \
                    padding: 4px 8px; background: white; border: 1px solid; border-color: var(--x-border); \
                    border-radius: 6px;",
            span { style: "flex: 1; min-width: 0; word-break: break-all; color: var(--x-ink-strong);", "{label}" }
            if !doc.collectionname.is_empty() {
                span { style: "flex-shrink: 0; font-style: italic; color: var(--x-ink-muted);", "{doc.collectionname}" }
            }
            match (openable, chat_open) {
                (true, Some(chat_open)) => rsx! {
                    button {
                        style: "flex-shrink: 0; background: none; border: none; padding: 0; \
                                cursor: pointer; color: var(--x-link); text-decoration: underline; \
                                font-size: var(--x-text-xs);",
                        onclick: move |_| chat_open.open.call(target.clone()),
                        "Open"
                    }
                },
                _ => rsx! {
                    span { style: "flex-shrink: 0; font-size: var(--x-text-xs); color: var(--x-ink-faint);", "Not openable" }
                },
            }
        }
    }
}


/// The characters of a snippet without its `**` highlight markers, and a mark for each
/// character that a pair of markers enclosed. A marker without a partner stays as text.
fn strip_highlight_markers(text: &str) -> (Vec<char>, Vec<bool>) {
    let mut pieces: Vec<String> = text.split("**").map(str::to_string).collect();
    if pieces.len() % 2 == 0 {
        let last = pieces.pop().unwrap_or_default();
        if let Some(previous) = pieces.last_mut() {
            previous.push_str("**");
            previous.push_str(&last);
        }
    }
    let mut chars = Vec::new();
    let mut marked = Vec::new();
    for (index, piece) in pieces.iter().enumerate() {
        for character in piece.chars() {
            chars.push(character);
            marked.push(index % 2 == 1);
        }
    }
    (chars, marked)
}

fn search_snippet_parts(text: &str, query: &str) -> Vec<(String, bool)> {
    let (chars, mut marked) = strip_highlight_markers(text);
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

    #[test]
    fn highlight_markers_become_highlights_and_leave_the_text() {
        let parts = search_snippet_parts("the **Raptor** deal and **LJM", "");
        assert_eq!(parts.iter().map(|part| part.0.as_str()).collect::<String>(), "the Raptor deal and **LJM");
        assert_eq!(parts.iter().filter(|part| part.1).map(|part| part.0.as_str()).collect::<Vec<_>>(), vec!["Raptor"]);
        let joined = search_snippet_parts("**a** b **c**", "b");
        assert_eq!(joined.iter().map(|part| part.0.as_str()).collect::<String>(), "a b c");
        assert!(joined.iter().all(|part| part.1 || part.0.trim().is_empty()));
    }
}
