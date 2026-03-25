//! Document preview components for search results.

mod doc_preview_for_pdf;
mod doc_preview_for_text;
mod no_document_selected;
mod preview_subtitle_bar;
mod text_data_viewer;

use common::document_sources::DocumentSourceItem;
use common::search_query::SearchQuery;
use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use crate::components::document_view_components::doc_preview_for_search::doc_preview_for_pdf::DocumentPreviewForPdf;
use crate::components::document_view_components::doc_preview_for_search::doc_preview_for_text::DocumentPreviewForTextWithSearch;
use crate::components::suspend_boundary::LoadingIndicator;
use crate::pages::search_page::DocViewerStateControl;

#[component]
pub fn DocumentPreviewForSearchRoot(
    query: ReadSignal<SearchQuery>,
    selected_result_hash: ReadSignal<Option<DocumentIdentifier>>,
) -> Element {
    let Some(document_identifier) = selected_result_hash.read().clone() else {
        return rsx! {
            no_document_selected::NoDocumentSelected {}
        };
    };

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

    let on_page_selected = Callback::new(move |page: u32| {
        let mut state = control.doc_viewer_state.read().clone().unwrap_or_default();
        state.selected_source_page = Some(page);
        control.set_doc_viewer_state.call(state);
    });

    let preview_selector = rsx! {
        DocumentPreviewSourceSelector {
            sources: doc_sources,
            selected_source: currently_selected_source,
            on_source_selected
        }
    };

    match (
        doc_sources.read().as_ref(),
        currently_selected_source.read().as_ref(),
    ) {
        (Some(_sources), Some(selected_source)) => {
            rsx! {
                DocumentPreviewSection {
                    preview_selector,
                    document_identifier,
                    source: selected_source.clone(),
                    on_page_selected: on_page_selected.clone(),
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

#[component]
fn DocumentPreviewSourceSelector(
    sources: ReadSignal<Option<Vec<DocumentSourceItem>>>,
    selected_source: ReadSignal<Option<DocumentSourceItem>>,
    on_source_selected: Callback<DocumentSourceItem>,
) -> Element {
    let sources = sources.read().clone().unwrap_or_default();
    if sources.is_empty() {
        return rsx! {
            "No Sources!"
        };
    };
    let Some(selected_source) = selected_source.read().clone() else {
        return rsx! {
            "No Selected Source!"
        };
    };
    rsx! {
        ul {
            for source in sources.into_iter() {
                li {
                    key: "{source:?}",
                    style: {
                        if source == selected_source {
                            "color: blue; text-decoration: underline;"
                        } else {
                            "color: black;"
                        }
                    },
                    onclick: move |_| {
                        on_source_selected(source.clone());
                    },
                    "{source:?}",
                }
            }
        }
    }
}

#[component]
fn DocumentPreviewSection(
    preview_selector: Element,
    document_identifier: ReadSignal<DocumentIdentifier>,
    source: ReadSignal<DocumentSourceItem>,
    on_page_selected: Callback<u32>,
) -> Element {
    rsx! {
        {preview_selector}
        "DOCUMENT PREVIEW SECTION FOR {document_identifier.read().clone():?} / {source.read().clone():?}"
    }
}
