//! Search result item card component.

use common::{search_result::SearchResultDocumentItem, text_highlight::HighlightTextSpan};
use dioxus::prelude::*;
use dioxus_free_icons::{
    Icon,
    icons::{go_icons::GoDatabase, md_editor_icons::MdInsertDriveFile},
};

use crate::components::search_components::{
    card_action_buttons::{DocCardActionButtonMore, DocCardActionButtonOpenNewTab},
    search_panel_left_view::SearchResultsState,
};

#[component]
pub fn SearchResultItemCard(
    result: ReadSignal<SearchResultDocumentItem>,
    onmounted: Callback<Event<MountedData>>,
) -> Element {
    let search_results_state = use_context::<SearchResultsState>();
    let current_search_result_page = search_results_state.current_search_result_page;
    let set_selected_result_hash = search_results_state.set_selected_result_hash;
    let selected_result_hash = search_results_state.selected_result_hash;
    let SearchResultDocumentItem {
        highlight_text_spans,
        highlight_filenames_spans,
        collection_dataset,
        result_index_in_page,
        matched_by_filename,
        ..
    } = result.read().clone();
    let we_are_selected =
        selected_result_hash.read().clone() == Some(result().document_identifier());

    let item_index = 1
        + (*current_search_result_page.read() * common::search_const::PAGE_SIZE)
        + result_index_in_page;
    let border_color = if we_are_selected {
        "#367ED899"
    } else {
        "#AAAAAA33"
    };
    let background_color = if we_are_selected {
        "#4096FF33"
    } else {
        "rgba(255,255,255,1.0)"
    };

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
                HighlightTextSnippetSection {highlight_text_spans, matched_by_filename}
                div {
                    style: "
                        display: flex;
                        flex-direction: row;
                        align-items: center;
                        gap: 8px;
                        flex-shrink: 0;
                    ",
                    DocCardActionButtonOpenNewTab {document_identifier: result().document_identifier()}
                    DocCardActionButtonMore {
                        document_identifier: result().document_identifier(),
                        show_finder: true,
                    }
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
        // Bounded, like the title beside it. A chat card can name several datasets for
        // one document, and at 20px italic an unbounded comma-joined list pushes the
        // card's header out of shape; the full value stays in `title`, which is the only
        // place a truncated label can be read whole.
        span {
            style: "
                font-size: 20px;
                line-height: 28px;
                font-weight: 300;
                color: rgba(0, 0, 0, 0.5);
                font-family: Roboto, sans-serif;
                font-style: italic;
                max-width: min(260px, 24ch);
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
                flex-shrink: 1;
            ",
            title: "{collection_dataset}",
            "{collection_dataset}"
        }
    }
}

/// The body snippet, or — when the filename is the only thing that matched — a note plus
/// the matching part of the filename.
///
/// The snippet for such a hit is `HIGHLIGHT()` over the synthetic filename row, so on its
/// own it renders the title a second time (`easychair.docx` → `easychair docx`) in the
/// place a reader takes for "here is the sentence that matched". The note says what
/// happened, and the highlighted path below it says *where* — clamped to three lines so
/// the hit keeps one line of context above and below it and a deep path cannot grow the
/// card.
#[component]
fn HighlightTextSnippetSection(
    highlight_text_spans: Vec<HighlightTextSpan>,
    matched_by_filename: bool,
) -> Element {
    if matched_by_filename {
        let has_spans = !highlight_text_spans.is_empty();
        return rsx! {
            div {
                style: "
                    display: flex;
                    flex-direction: column;
                    align-items: stretch;
                    flex: 1;
                    min-width: 0;
                ",
                div {
                    class: "x-matched-by-filename",
                    style: "
                        font-size: 15px;
                        line-height: 23px;
                        font-weight: 400;
                        font-style: italic;
                        color: rgba(0, 0, 0, 0.55);
                        min-width: 0;
                    ",
                    "Matched by filename — no matching text inside this document."
                }
                if has_spans {
                    div {
                        class: "x-filename-hit-snippet",
                        // Monospace because it is a path, not prose. `overflow-wrap:
                        // anywhere` is what keeps a long unbroken path segment from
                        // widening the card instead of wrapping inside it.
                        style: "
                            font-size: 14px;
                            line-height: 20px;
                            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                            color: rgba(0, 0, 0, 0.7);
                            background: rgba(0, 0, 0, 0.03);
                            border-left: 2px solid rgba(235, 62, 1, 0.35);
                            padding: 4px 8px;
                            margin-top: 4px;
                            border-radius: 0 6px 6px 0;
                            overflow: hidden;
                            display: -webkit-box;
                            -webkit-line-clamp: 3;
                            -webkit-box-orient: vertical;
                            overflow-wrap: anywhere;
                            min-width: 0;
                        ",
                        {render_highlight_text_span(highlight_text_spans)}
                    }
                }
            }
        };
    }
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
    let spans = spans
        .into_iter()
        .map(|i| {
            let color = if i.is_highlighted {
                "#EB3E014D"
            } else {
                "transparent"
            };
            rsx! {
                span {
                    style: "background-color: {color}; color: rgb(0, 0, 0);",
                    "{i.text}"
                }
            }
        })
        .collect::<Vec<_>>();
    rsx! {
        {spans.into_iter()}
    }
}
