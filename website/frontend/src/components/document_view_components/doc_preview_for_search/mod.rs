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

use common::document_sources::{DocumentSourceItem, DocumentSourcesStatus, ItemHitCounts};
use common::search_query::SearchQuery;
use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use crate::components::document_view_components::doc_preview_for_search::doc_preview_find_query::DocPreviewFindQueryInputBox;
use crate::components::document_view_components::doc_preview_for_search::doc_preview_source_selector::{DocumentPreviewSourceSelectorDropdown, search_document_item_hit_counts};
use crate::components::document_view_components::doc_title_bar::DocTitleBar;
use crate::components::document_view_components::doc_preview_shared::{
    DocSourceDispatch, PreviewExtraSections, ProvidePreviewExtraSections, SourceLoadNotice,
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
    let mut source_request: Resource<Result<DocumentSourcesStatus, ServerFnError>> =
        use_resource(use_reactive!(|document_identifier_value| {
            async move { get_document_sources(document_identifier_value).await }
        }));
    let doc_sources: ReadSignal<Option<Vec<DocumentSourceItem>>> =
        use_memo(move || source_request.read().as_ref()
            .and_then(|r| r.as_ref().ok().map(|status| status.sources.clone()))).into();
    let source_error = use_memo(move || source_request.read().as_ref().and_then(|result| {
        match result {
            Ok(status) if !status.errors.is_empty() => Some(status.errors.join(", ")),
            Err(error) => Some(error.to_string()),
            _ => None,
        }
    }));

    let empty_source_message = use_memo(move || source_request.read().as_ref()
        .and_then(|result| result.as_ref().ok())
        .map(|status| status.processing.empty_source_message()).unwrap_or_default());

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
        if let Some(table) = &mut state.table_state {
            table.page = 0;
        }
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

    let source_notice = rsx! {
        if let Some(error) = source_error() {
            SourceLoadNotice { error, on_retry: move |_| source_request.restart() }
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
                        {source_notice}
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
                        {source_notice}
                        div {
                            style: "padding: 12px; color: rgba(0,0,0,0.45); font-style: italic;",
                            "{empty_source_message()}"
                        }
                    },
                    wrapper_fn: _make_preview_wrapper,
                }
            }
        }
        _ if source_error().is_some() => rsx! {
            DocTitleBar { document_identifier, show_new_tab_button: true, show_finder }
            {source_notice}
        },
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
) -> Result<DocumentSourcesStatus, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::documents::get_document_sources::get_document_sources_status(&user, document_identifier)
        .await
        .map_err(crate::api::error_util::to_server_fn_error)
}

fn _make_preview_wrapper(controls: Element, page: Element) -> Element {
    let sections = use_context::<PreviewExtraSections>();
    // One column under the 54 px title bar. The bar is one row, and the page takes the
    // height that is left.
    rsx! {
        div {
            style: "display: flex; flex-direction: column; width: 100%; height: calc(100% - 54px); min-height: 0;",
            PreviewSubtitleBar {
                find_query_input_box: sections.find_query.read().clone(),
                preview_selector: sections.preview_selector.read().clone(),
                control: controls,
            }
            div {
                style: "flex: 1 1 auto; min-height: 0; width: 100%; padding: 10px; box-sizing: border-box;",
                {page}
            }
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
            class: "x-preview-subtitle-bar",
            style: "
                display: flex;
                flex-direction: row;
                flex-wrap: nowrap;
                gap: 8px;
                align-items: center;
                min-height: 42px;
                padding: 4px 8px;
                box-sizing: border-box;
                width: 100%;
                background-color: rgba(0, 0, 0, 0.04);
                flex: 0 0 auto;
                border: 1px solid rgba(0, 0, 0, 0.3); border-top: none;
            ",
            // The find box takes every pixel the other two parts leave. The selector keeps
            // its natural width, which its own 160 px limit bounds. The controls shrink
            // when the pane is narrow and cut long sheet names short.
            div { style: "flex: 1 1 0; min-width: 160px;", {find_query_input_box} }
            div {
                style: "flex: 0 1 auto; min-width: 0;
                display: flex;
                flex-direction: row;
                flex-wrap: nowrap;
                align-items: center;
                gap: 4px;
                ",
                {control}
            }
            div { style: "flex: 0 0 auto; min-width: 0;", {preview_selector} }
        }
    }
}
