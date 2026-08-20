//! Document preview components for search results.

pub mod doc_preview_find_query;
pub mod doc_preview_for_email;
pub mod doc_preview_for_pdf;
pub mod doc_preview_for_table;
pub mod doc_preview_for_text;
pub mod doc_preview_source_selector;
pub mod no_document_selected;
mod text_data_viewer;
pub mod text_preview_with_search;

use common::document_sources::{DocumentSourceItem, ItemHitCounts};
use common::search_query::SearchQuery;
use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use crate::components::document_view_components::doc_preview_for_search::doc_preview_find_query::DocPreviewFindQueryInputBox;
use crate::components::document_view_components::doc_preview_for_search::doc_preview_source_selector::{DocumentPreviewSourceSelectorDropdown, search_document_item_hit_counts};
use crate::components::document_view_components::doc_title_bar::DocTitleBar;
use crate::components::document_view_components::doc_preview_shared::{
    DocSourceDispatch, PreviewExtraSections, ProvidePreviewExtraSections
};
use crate::components::suspend_boundary::LoadingIndicator;
use crate::pages::search_page::DocViewerStateControl;

#[component]
pub fn DocumentPreviewForSearchRoot(
    query: ReadSignal<SearchQuery>,
    selected_result_hash: ReadSignal<Option<DocumentIdentifier>>,
    show_finder: bool,
) -> Element {
    let Some(document_identifier_value) = selected_result_hash.read().clone() else {
        return rsx! {
            no_document_selected::NoDocumentSelected {}
        };
    };
    rsx! {
        DocumentPreviewForSearchContent {query, document_identifier: document_identifier_value, show_finder}
    }
}

#[component]
fn DocumentPreviewForSearchContent(
    query: ReadSignal<SearchQuery>,
    document_identifier: ReadSignal<DocumentIdentifier>,
    show_finder: bool,
) -> Element {
    let document_identifier_value = document_identifier();
    // By value through `use_reactive`: a `ReadSignal` prop is a new signal on every
    // parent render, so a resource subscribed to it never re-runs on its own.
    let doc_sources: Resource<Vec<DocumentSourceItem>> =
        use_resource(use_reactive!(|document_identifier_value| {
            async move {
                get_document_sources(document_identifier_value)
                    .await
                    .unwrap_or_default()
            }
        }));
    let doc_sources: ReadSignal<Option<Vec<DocumentSourceItem>>> =
        use_memo(move || doc_sources.read().clone()).into();

    let control = use_context::<DocViewerStateControl>();

    let currently_selected_source: ReadSignal<Option<DocumentSourceItem>> = use_memo(move || {
        let sources = doc_sources.read().clone().unwrap_or_default();
        if let Some(state) = control.doc_viewer_state.read().clone() {
            if let Some(selected_source) = state.selected_source {
                if let Some(source) = sources.iter().find(|s| *s == &selected_source) {
                    return Some(source.clone());
                }
            }
        }
        return sources.first().cloned();
    })
    .into();

    let on_source_selected = Callback::new(move |source: DocumentSourceItem| {
        let mut state = control.doc_viewer_state.read().clone().unwrap_or_default();
        state.selected_source = Some(source);
        state.selected_source_page = None;
        control.set_doc_viewer_state.call(state);
    });

    let on_find_query_changed = Callback::new(move |query: String| {
        let mut state = control.doc_viewer_state.read().clone().unwrap_or_default();
        state.find_query = query;
        control.set_doc_viewer_state.call(state);
    });

    let find_query_input_box = rsx! {
        DocPreviewFindQueryInputBox {
            on_find_query_changed: on_find_query_changed.clone(),
        }
    };

    // ================ ITEM HIT COUNTS: ================
    let mut item_hit_counts = use_signal(move || ItemHitCounts(Vec::new()));
    let _r = use_resource(use_reactive!(|document_identifier_value| {
        let sources = doc_sources.read().clone().unwrap_or_default();
        let find_query = control
            .doc_viewer_state
            .read()
            .clone()
            .unwrap_or_default()
            .find_query;
        async move {
            {
                item_hit_counts.set(ItemHitCounts(Vec::new()));
            }
            let item =
                search_document_item_hit_counts(document_identifier_value, find_query, sources)
                    .await
                    .unwrap_or_default();
            {
                item_hit_counts.set(item);
            }
        }
    }));

    let preview_selector = rsx! {
        DocumentPreviewSourceSelectorDropdown {
            sources: doc_sources,
            selected_source: currently_selected_source,
            on_source_selected,
            item_hit_counts,
        }
    };

    match (
        doc_sources.read().as_ref(),
        currently_selected_source.read().as_ref(),
    ) {
        (Some(_sources), Some(selected_source)) => {
            rsx! {
                ProvidePreviewExtraSections {
                    find_query_input_box,
                    preview_selector,
                    children: rsx! {
                        DocTitleBar { document_identifier, show_new_tab_button: true, show_finder }
                        DocSourceDispatch { document_identifier, source: selected_source.clone() },
                    },
                    wrapper_fn: _make_preview_wrapper,
                }
                // DocumentPreviewForPdf { document_identifier, page_count }
            }
        }
        // The sources resource has answered with nothing: a document whose extraction
        // produced no text, or an identifier that resolves to no document at all. It is
        // a final answer, not a slow one, so it gets the title bar and a note rather than
        // a spinner that would never stop.
        (Some(_sources), None) => {
            rsx! {
                ProvidePreviewExtraSections {
                    find_query_input_box,
                    preview_selector,
                    children: rsx! {
                        DocTitleBar { document_identifier, show_new_tab_button: true, show_finder }
                        div {
                            style: "padding: 12px; color: rgba(0,0,0,0.45); font-style: italic;",
                            "No preview available for this document."
                        }
                    },
                    wrapper_fn: _make_preview_wrapper,
                }
            }
        }
        _ => {
            return rsx! {
                LoadingIndicator {  }
            };
        }
    }
}

#[server]
pub async fn get_document_sources(
    document_identifier: DocumentIdentifier,
) -> Result<Vec<DocumentSourceItem>, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::documents::get_document_sources::get_document_sources(&user, document_identifier)
        .await
        .map_err(crate::api::error_util::to_server_fn_error)
}

fn _make_preview_wrapper(controls: Element, page: Element) -> Element {
    let sections = use_context::<PreviewExtraSections>();
    rsx! {
        PreviewSubtitleBar {
            find_query_input_box: sections.find_query.read().clone(),
            preview_selector: sections.preview_selector.read().clone(),
            control: controls,
        }
        div {
            style: "
                width: 100%;
                height: calc(100% - 110px);
                padding: 10px;
            ",
            {page}
        }
    }
}

#[component]
fn PreviewSubtitleBar(
    find_query_input_box: Element,
    preview_selector: Element,
    control: Element,
) -> Element {
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
            {find_query_input_box}
            div { style:"flex-grow: 1;" }
            div {
                style:"flex-grow: 13; flex-shrink: 1; height: 90%;
                display: flex;
                flex-direction: row;
                align-items: center;
                justify-content: center;
                gap: 4px;
                ",
                {control}
            }
            div { style:"flex-grow: 1;" }
            {preview_selector}
        }
    }
}
