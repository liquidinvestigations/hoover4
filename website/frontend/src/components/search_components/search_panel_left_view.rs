//! Left panel view for search filters and facets.

use std::collections::BTreeMap;

use dioxus::prelude::*;

use common::{search_query::SearchQuery, search_result::{DocumentIdentifier, SearchResultDocuments}};
use crate::{api::search_api::{search_for_results, search_for_results_hit_count}, components::{error_boundary::ComponentErrorDisplay, search_components::{search_result_item_card::SearchResultItemCard, search_result_list_controls::SearchResultListControls}, suspend_boundary::{LoadingIndicator, SuspendWrapper}}, data_definitions::doc_viewer_state::DocViewerState, routes::Route};
#[derive(Copy, Clone)]
pub struct SearchResultsState {
    // pub query: ReadSignal<SearchQuery>,
    pub hit_count: ReadSignal<Option<Result<u64, ServerFnError>>>,
    pub search_result: ReadSignal<Option<Result<SearchResultDocuments, ServerFnError>>>,
    pub current_search_result_page: ReadSignal<u64>,
    pub set_current_page: Callback<u64>,
    pub selected_result_hash: ReadSignal<Option<DocumentIdentifier>>,
    pub set_selected_result_hash: Callback<Option<DocumentIdentifier>>,
    pub set_selected_result_hash_and_page: Callback<(Option<DocumentIdentifier>, u64)>,
}

#[component]
pub fn SearchPanelLeftView(query: ReadSignal<SearchQuery>, current_search_result_page: ReadSignal<u64>, selected_result_hash: ReadSignal<Option<DocumentIdentifier>>) -> Element {

    let mut hit_count = use_resource(move || {
        let q = query.read().clone();
        search_for_results_hit_count(q)
    });
    // when the query changes, we need to restart the hit count resource
    use_effect(move || {
        let _ = query.read();
        hit_count.clear();
        hit_count.restart();
    });

    let mut search_result = use_resource(move || {
        let q = query.read().clone();
        search_for_results(q, *current_search_result_page.read())
    });
    // when the current search result page or query changes, we need to restart the search result resource
    use_effect(move || {
        let _ = current_search_result_page.read();
        let _ = query.read();
        search_result.clear();
        search_result.restart();
    });


    let set_current_page = Callback::new(move |page: u64| {
        let route = Route::SearchPage {
            query: query.read().clone().into(),
            current_search_result_page: page,
            selected_result_hash: None.into(),
            doc_viewer_state: None.into(),
        };
        navigator().push(route);
    });
    let set_selected_result_hash = Callback::new(move |hash: Option<DocumentIdentifier>| {
        let route = Route::SearchPage {
            query: query.read().clone().into(),
            current_search_result_page: *current_search_result_page.read(),
            selected_result_hash: hash.into(),
            doc_viewer_state: Some(DocViewerState::from_find_query(query.read().clone().query_string.clone())).into(),
        };
        navigator().push(route);
    });
    let set_selected_result_hash_and_page = Callback::new(move |(hash, page): (Option<DocumentIdentifier>, u64)| {
        let route = Route::SearchPage {
            query: query.read().clone().into(),
            current_search_result_page: page,
            selected_result_hash: hash.into(),
            doc_viewer_state: Some(DocViewerState::from_find_query(query.read().clone().query_string.clone())).into(),
        };
        navigator().push(route);
    });
    use_context_provider(move || SearchResultsState {
        hit_count: hit_count.into(),
        search_result: search_result.into(),
        current_search_result_page,
        set_current_page,
        selected_result_hash,
        set_selected_result_hash,
        set_selected_result_hash_and_page,
    });


    rsx! {
        div {
            id: "x-search-panel-left-wrapper",
            style: "
                display: flex;
                flex-direction: column;
                gap: 1px;
                margin: 1px;
                padding: 7px;
                padding-top: 0px;
                height: 100%;
                width: 100%;
            ",
            SearchResultListControls {}

            div {
                style: "
                flex-grow: 1;
                width: 100%;
                max-height: calc(100% - 56px);
                ",
                SuspendWrapper {
                    SearchResultsView { }
                }
            }
        }
    }
}
#[component]
fn SearchResultsView() -> Element {
    let search_results_state = use_context::<SearchResultsState>();
    let search_result = search_results_state.search_result;
    // .suspend()?.cloned();
    let search_result = search_result.read();
    let search_result = match search_result.as_ref() {
        Some( Err(e)) => return rsx! {ComponentErrorDisplay { error_txt: format!("{:#?}", e) }},
        Some(Ok(s)) => s,
        None => return rsx! { LoadingIndicator{} },
    };

    let result_list = search_result.results.clone();
    let mut result_mounted_thing = use_signal(move || BTreeMap::<DocumentIdentifier, Event<MountedData>>::new());
    use_effect(move || {
        let selected = search_results_state.selected_result_hash.read().clone();
        if let Some(selected) = selected {
            if let Some(mounted_data) = result_mounted_thing.read().get(&selected) {
                let _x = mounted_data.scroll_to_with_options( ScrollToOptions {
                    behavior: ScrollBehavior::Smooth,
                    vertical: ScrollLogicalPosition::Center,
                    horizontal: ScrollLogicalPosition::Center
                });
                // if let Err(e) = _x {dioxus::logger::tracing::error!("Error scrolling to selected result: {e}");}
            }
        }
    });

    rsx! {
        ul {
            id: "x-search-panel-results-wrapper",
            style: "
                width: 100%;
                height: 100%;
                overflow-y: auto;
            ",
            for result in result_list.iter().cloned() {
                li {
                    key: "{result.collection_dataset}-{result.file_hash}-{result.result_index_in_page}",
                    SearchResultItemCard {result: result.clone(), onmounted: move |_e| {
                        result_mounted_thing.write().insert(result.document_identifier(), _e);
                    }}
                }
            }
        }
    }
}
