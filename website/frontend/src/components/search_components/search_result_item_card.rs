//! Search result item card component.

use dioxus::{logger::tracing, prelude::*};
use common::{search_result::{DocumentIdentifier, SearchResultDocumentItem}, text_highlight::HighlightTextSpan};
use dioxus_free_icons::{Icon, icons::{go_icons::GoDatabase, md_action_icons::{MdDonutLarge, MdOpenInNew}, md_editor_icons::MdInsertDriveFile, md_navigation_icons::MdMoreVert}};

use crate::{components::search_components::{card_action_buttons::{DocCardActionButtonMore, DocCardActionButtonOpenNewTab}, search_panel_left_view::SearchResultsState}, routes::Route};

#[component]
pub fn SearchResultItemCard(result: ReadSignal<SearchResultDocumentItem>, onmounted: Callback<Event<MountedData>>) -> Element {
    let search_results_state = use_context::<SearchResultsState>();
    let current_search_result_page = search_results_state.current_search_result_page;
    let set_selected_result_hash = search_results_state.set_selected_result_hash;
    let selected_result_hash = search_results_state.selected_result_hash;
    let SearchResultDocumentItem {
        title,
        highlight_text_spans,
        highlight_filenames_spans,
        file_hash,
        collection_dataset,
        result_index_in_page,
    } = result.read().clone();
    let we_are_selected = selected_result_hash.read().clone() == Some(result().document_identifier());

    let item_index = 1 + (*current_search_result_page.read() * common::search_const::PAGE_SIZE) + result_index_in_page;
    let border_color = if we_are_selected { "#367ED899" } else { "#AAAAAA33" };
    let background_color = if we_are_selected { "#4096FF33" } else { "white" };

    rsx! {
        div {
            style: "
                display: flex;
                flex-direction: column;
                align-items: stretch;
                gap: 7px;
                background: {background_color};
                border: 3px solid {border_color};
                border-radius: 8px;
                padding: 12px 16px;
                margin: 8px 8px;
                height: 148px;
                width: calc(100% - 16px);
                box-sizing: border-box;
            ",
            onclick: move |_| {
                set_selected_result_hash(Some(result().document_identifier()));
            },
            onmounted: move |_e| {
                onmounted.call(_e);
            },
            // Row 1: ICON - TITLE - SPACER - ICON - COLLECTION
            div {
                style: "
                    display: flex;
                    flex-direction: row;
                    align-items: center;
                    gap: 12px;
                    width: 100%;
                    padding: 1px;
                    border: 1px;
                ",
                span {
                    style: "font-size: 20px; font-weight: 200; color: rgba(0, 0, 0, 0.5); padding: 1px 4px; border-radius: 4px; margin: -4px",
                    "{item_index}."
                }
                // ICON FOR TITLE
                FileTypeIcon {}
                // TITLE
                CardTitleSection {highlight_filenames_spans}

                // SPACER
                div {
                    style: "
                        flex: 1 1 auto;
                    ",
                }
                // ICON FOR COLLECTION
                CollectionIcon {}

                // COLLECTION NAME
                ComponentNameSection {collection_dataset}
            }
            // Row 2: TEXT SNIPPET - BUTTONS
            div {
                style: "
                    display: flex;
                    flex-direction: row;
                    align-items: flex-start;
                    justify-content: space-between;
                    gap: 12px;
                    width: 100%;
                    flex: 1;
                    min-height: 0;
                    padding: 2px;
                    border: 2px;
                ",
                HighlightTextSnippetSection {highlight_text_spans}
                div {
                    style: "
                        display: flex;
                        flex-direction: row;
                        align-items: center;
                        gap: 8px;
                        flex-shrink: 0;
                    ",
                    DocCardActionButtonOpenNewTab {document_identifier: result().document_identifier()}
                    DocCardActionButtonMore {document_identifier: result().document_identifier()}
                }
            }
        }
    }
}


#[component]
fn FileTypeIcon() -> Element {
    rsx! {
        div {
            style: "
                width: 24px;
                height: 24px;
                background: transparent;
                color: rgba(0, 0, 0, 0.5);
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 16px;
                font-weight: 600;
                border-radius: 4px;
                flex-shrink: 0;
            ",
            Icon {
                icon: MdInsertDriveFile,
                style: "width: 18px; height: 18px;"
            }
        }
    }
}

#[component]
fn CardTitleSection(highlight_filenames_spans: Vec<HighlightTextSpan>) -> Element {
    rsx! {
        div {
            style: "
                font-size: 20px;
                line-height: 28px;
                font-weight: 400;
                color: rgb(0, 0, 0);
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
                min-width: 0;
            ",
            {render_highlight_text_span(highlight_filenames_spans)}
        }
    }
}

#[component]
fn CollectionIcon() -> Element {
    rsx! {
        div {
            style: "
                width: 21px;
                height: 21px;
                background: transparent;
                color: rgba(0, 0, 0, 0.5);
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 16px;
                border-radius: 4px;
                flex-shrink: 0;
            ",
            Icon {
                icon: GoDatabase,
                style: "width: 18px; height: 18px;"
            }
        }
    }
}

#[component]
fn ComponentNameSection(collection_dataset: String) -> Element {
    rsx! {
        span {
            style: "
                font-size: 20px;
                line-height: 28px;
                font-weight: 300;
                color: rgba(0, 0, 0, 0.5);
                font-family: Roboto, sans-serif;
                font-style: italic;
            ",
            "{collection_dataset}"
        }
    }
}

#[component]
fn HighlightTextSnippetSection(highlight_text_spans: Vec<HighlightTextSpan>) -> Element {

    rsx! {
        div {
            // TEXT SNIPPET
            style: "
                font-size: 16px;
                line-height: 23px;
                font-weight: 400;
                color: rgb(0, 0, 0);
                overflow: hidden;
                display: -webkit-box;
                -webkit-line-clamp: 4;
                -webkit-box-orient: vertical;
                flex: 1;
                min-width: 0;
                letter-spacing: 0.0em;
            ",
            {render_highlight_text_span(highlight_text_spans)}
        }
    }
}

fn render_highlight_text_span(spans: Vec<HighlightTextSpan>) -> Element {
    let spans = spans.into_iter().map(|i| {
        let color = if i.is_highlighted { "#EB3E014D" } else { "transparent" };
        rsx! {
            span {
                style: "background-color: {color}; color: rgb(0, 0, 0);",
                "{i.text}"
            }
        }
    }).collect::<Vec<_>>();
    rsx! {
        {spans.into_iter()}
    }
}

