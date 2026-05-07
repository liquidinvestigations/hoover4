//! Document preview components for search results.

pub mod doc_preview_find_query;
pub mod doc_preview_for_email;
pub mod doc_preview_for_pdf;
pub mod doc_preview_for_text;
pub mod doc_preview_source_selector;
pub mod no_document_selected;
mod text_data_viewer;
pub mod text_preview_with_search;

use common::document_sources::DocumentSourceItem;
use common::search_query::SearchQuery;
use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use crate::components::document_view_components::doc_preview_for_search::doc_preview_find_query::DocPreviewFindQueryInputBox;
use crate::components::document_view_components::doc_preview_for_search::doc_preview_source_selector::DocumentPreviewSourceSelectorDropdown;
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
) -> Element {
    let Some(document_identifier_value) = selected_result_hash.read().clone() else {
        return rsx! {
            no_document_selected::NoDocumentSelected {}
        };
    };
    let document_identifier: ReadSignal<DocumentIdentifier> =
        use_signal(move || document_identifier_value.clone()).into();

    let mut doc_sources: Resource<Vec<DocumentSourceItem>> = use_resource(move || {
        let document_identifier = selected_result_hash.peek().clone();
        async move {
            let Some(document_identifier) = document_identifier else {
                return vec![];
            };
            get_document_sources(document_identifier)
                .await
                .unwrap_or_default()
        }
    });
    use_effect(move || {
        let _document_identifier = selected_result_hash.read().clone();
        // let Some(_document_identifier) = document_identifier else { return };
        doc_sources.clear();
        doc_sources.restart();
    });
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

    let preview_selector = rsx! {
        DocumentPreviewSourceSelectorDropdown {
            sources: doc_sources,
            selected_source: currently_selected_source,
            on_source_selected
        }
    };

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
                        DocTitleBar { document_identifier, show_new_tab_button: true }
                        DocSourceDispatch { document_identifier, source: selected_source.clone() },
                    },
                    wrapper_fn: _make_preview_wrapper,
                }
                // DocumentPreviewForPdf { document_identifier, page_count }
            }
        }
        // Some((false, _)) => {
        //     rsx! {
        //         DocumentPreviewForTextWithSearch { document_identifier }
        //     }
        // }
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
    let sources =
        backend::api::documents::get_document_sources::get_document_sources(document_identifier)
            .await
            .map_err(|e| ServerFnError::from(e))?;
    Ok(sources)
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
