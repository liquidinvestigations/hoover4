use std::collections::{BTreeMap, BTreeSet};

use dioxus::prelude::*;

use common::{search_query::SearchQuery, search_result::{DocumentIdentifier, SearchResultDocuments}};
use crate::{
    api::search_api::{search_for_results, search_for_results_hit_count},
    components::{document_view_components::doc_preview_for_search::DocumentPreviewForSearchRoot, error_boundary::ComponentErrorDisplay, search_components::{search_input_top_bar::SearchInputTopBar, search_panel_left_view::SearchPanelLeftView, search_result_item_card::SearchResultItemCard, search_result_list_controls::SearchResultListControls}, suspend_boundary::{LoadingIndicator, SuspendWrapper}},
    data_definitions::{doc_viewer_state::DocViewerState, url_param::UrlParam}, routes::Route
};


fn title_ellipsis(title: String) -> String {
    if title.len() > 20 {
        title[..18].to_string() + "..."
    } else {
        title
    }
}

/// Home page
#[component]
pub fn SearchPage(
    query: UrlParam<SearchQuery>,
    current_search_result_page: u64,
    selected_result_hash: UrlParam<Option<DocumentIdentifier>>,
    doc_viewer_state: UrlParam<Option<DocViewerState>>,
) -> Element {
    // let url_param = <UrlParam<SearchQuery> as std::str::FromStr>::from_str(&query_base64);

    rsx! {
        Title { "Hoover Search: {title_ellipsis(query.0.query_string.clone())}" }
        SearchPageRootComponent {
            query: query.0.clone(),
            current_search_result_page,
            selected_result_hash: selected_result_hash.0.clone(),
            doc_viewer_state: doc_viewer_state.0.clone(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Copy)]
pub struct DocViewerStateControl {
    pub doc_viewer_state: ReadSignal<Option<DocViewerState>>,
    pub set_doc_viewer_state: Callback<DocViewerState>,
}

#[component]
fn SearchPageRootComponent(
    query: ReadSignal<SearchQuery>,
    current_search_result_page: ReadSignal<u64>,
    selected_result_hash: ReadSignal<Option<DocumentIdentifier>>,
    doc_viewer_state: ReadSignal<Option<DocViewerState>>,
) -> Element {

    use_context_provider(move || DocViewerStateControl {
        doc_viewer_state: doc_viewer_state.into(),
        set_doc_viewer_state: Callback::new(move |state: DocViewerState| {
            if let Some(old_state) = doc_viewer_state.read().clone() {
                if old_state == state {
                    return;
                }
                // new state different: push path
                navigator().push(Route::SearchPage {
                    query: query.read().clone().into(),
                    current_search_result_page: current_search_result_page.read().clone(),
                    selected_result_hash: selected_result_hash.read().clone().into(),
                    doc_viewer_state: Some(state).into(),
                });
            } else {
                // no state: replace path
                navigator().replace(Route::SearchPage {
                    query: query.read().clone().into(),
                    current_search_result_page: current_search_result_page.read().clone(),
                    selected_result_hash: selected_result_hash.read().clone().into(),
                    doc_viewer_state: Some(state).into(),
                });
            }
        }),
    });

    rsx! {
        div {
            id: "x-search-page-root-component",
            style: r#"
                height: 100%;
                width: 100%;
                display: flex;
                flex-direction: column;
            "#,
            div {
                id: "x-search-input-top-bar",
                style: "
                    border-bottom: 1px solid rgb(164, 164, 164);
                    background-color: #F8FCFF;
                    flex-shrink: 0;
                    display: flex;
                    flex-direction: row;
                    align-items: center;
                    height: 76px;
                    width: 100%;
                ",

                SearchInputTopBar { original_query: query }
            }

            div {
                id: "x-search-results-bottom-space",
                style: r#"
                    width: 100%;
                    display: flex;
                    flex-direction: row;
                    flex-grow: 1;
                    max-height: calc(100% - 76px);
                "#,
                div {
                    id: "x-search-results-left-panel",
                    style: "
                        height: 100%;
                        background-color: #ECEEF2;
                        flex-grow: 1;
                        min-width: 400px;
                        max-width: 3800px;
                        width: 60%;
                    ",
                    SuspendWrapper{SearchPanelLeftView {query, current_search_result_page, selected_result_hash}}
                }
                div {
                    id: "x-search-results-right-panel",
                    style: "
                        height: 100%;
                        min-width: 300px;
                        width: 40%;
                    ",
                    SuspendWrapper{DocumentPreviewForSearchRoot {query, selected_result_hash}}

                }
            }
        }
    }
}

