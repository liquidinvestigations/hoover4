//! Subtitle bar component for document previews.

use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;
use dioxus_free_icons::{Icon, icons::md_navigation_icons::{MdArrowDownward, MdArrowUpward}};

use crate::{components::{document_view_components::doc_preview_for_search::doc_preview_for_text::DocumentViewerResultStore, search_components::search_result_list_controls::NavigationButton}, data_definitions::doc_viewer_state::DocViewerState, pages::search_page::DocViewerStateControl};

#[component]
pub fn PreviewSubtitleBar(document_identifier: ReadSignal<DocumentIdentifier>) -> Element {
    let state = use_context::<DocViewerStateControl>();
    let find_query = use_memo(move || {
        let r = state.doc_viewer_state.read().clone();
        let Some(state) = &r else { return "".to_string() };
        state.find_query.clone()
    });
    let mut modified_find_query = use_signal(move || find_query.read().clone());
    use_effect(move || {
        let q = find_query.read().clone();
        modified_find_query.set(q);
    });
    rsx! {
        div {
            style: "
                display: flex;
                flex-direction: row;
                gap: 12px;
                align-items: center;
                justify-content: space-between;
                height: 48px;
                width: 100%;
                background-color:rgba(0, 0, 0, 0.04);
                flex-shrink: 0;
                flex-grow: 0;
                border: 1px solid rgba(0, 0, 0, 0.3); border-top: none;
            ",

            // SEARCH BOX
            div {
                style: "
                    flex-grow: 0;
                    flex-shrink: 0;
                ",
                input {
                    r#type: "text",
                    placeholder: "Search in document",
                    style: "
                        width: 100%;
                        height: 100%;
                        border: none;
                        outline: none;
                        background: white;
                        border: 1px solid rgba(0, 0, 0, 0.5);
                        border-radius: 14px;
                        padding: 8px 12px;
                        font-size: 14px;
                        font-weight: 400;
                        color: rgba(0, 0, 0, 0.8);
                        margin-left: 12px;
                        ",
                    value: "{find_query.read()}",
                    oninput: move |e| {
                        let q = e.value();
                        modified_find_query.set(q);
                    },
                    onkeydown: move |e| {
                        if e.key() == Key::Enter {
                            dioxus::logger::tracing::info!("Find Query: {}", find_query.read().clone());
                            state.set_doc_viewer_state.call(DocViewerState::from_find_query(modified_find_query.read().clone()));
                        }
                    },
                }
            }
            // SEARCH HIT SELECTOR
            div {
                style: "
                    flex-grow: 0;
                    flex-shrink: 0;
                ",
                SearchHitSelector {}
            }
            // SPACER
            div {style:"flex-grow: 1;"}
            // SOURCE DROP-down
            div {
                style: "
                    flex-grow: 0;
                    flex-shrink: 0;
                    display: inline-flex;
                ",
                // "Source: ",
                // div {
                //     style: "
                //         border: 1px solid rgba(0, 0, 0, 0.3);
                //         border-radius: 24px;
                //     ",
                //     "Drop-down ▼"
                // }
            }
            // SPACER
            div {style:"flex-grow: 1;"}

        }
    }
}

#[component]
fn SearchHitSelector() -> Element {
    let max_highlighted_word_index = use_context::<DocumentViewerResultStore>().max_highlighted_word_index;
    let mut current_highlighted_word_index = use_context::<DocumentViewerResultStore>().current_highlighted_word_index;
    let have_hits = use_memo(move || {
        *max_highlighted_word_index.read() > 0
    });
    let hit_string = use_memo(move || {
        if have_hits() {
            let current = 1+*current_highlighted_word_index.read();
            let max = *max_highlighted_word_index.read();
            format!("{current} / {max}")
        } else {
            "- / -".to_string()
        }
    });
    let disable_next = use_memo(move || {
        !have_hits() ||
        *current_highlighted_word_index.read()+1 >= *max_highlighted_word_index.read()
    });
    let disable_previous = use_memo(move || {
        !have_hits() ||
        *current_highlighted_word_index.read() == 0
    });
    rsx! {
        div {
            style: "
                flex-grow: 0;
                flex-shrink: 0;
                display: flex;
                flex-direction: row;
                align-items: center;
                justify-content: center;
                gap: 12px;
                padding: 12px;
            ",
            // up button
            NavigationButton { icon: MdArrowUpward, label: "Previous Hit", disabled: disable_previous, onclick: move |_| {
                dioxus::logger::tracing::info!("Go previous hit");
                *current_highlighted_word_index.write() -= 1;
            } }
            // hit string
            div {
                style: "
                    min-width: 60px;
                    font-size: 20px;
                    line-height: 28px;
                ",
                "{hit_string()}"
            }
            // down button
            NavigationButton { icon: MdArrowDownward, label: "Next Hit", disabled: disable_next, onclick: move |_| {
                dioxus::logger::tracing::info!("Go next hit");
                *current_highlighted_word_index.write() += 1;
            } }
        }
    }
}