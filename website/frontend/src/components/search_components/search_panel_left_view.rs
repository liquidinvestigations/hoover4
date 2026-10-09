//! Left panel view for search filters and facets.

use std::collections::BTreeMap;

use dioxus::prelude::*;

use crate::{
    api::search_api::{search_for_results, search_for_results_hit_count},
    components::{
        error_boundary::ServerErrorDisplay,
        search_components::{
            search_result_item_card::SearchResultItemCard,
            search_result_list_controls::SearchResultListControls,
        },
        suspend_boundary::{LoadingIndicator, SuspendWrapper},
    },
    data_definitions::doc_viewer_state::DocViewerState,
    routes::Route,
};
use common::{
    search_query::SearchQuery,
    search_result::{DocumentIdentifier, SearchResultDocuments, SearchResultHitCount},
};
#[derive(Copy, Clone)]
pub struct SearchResultsState {
    pub query: ReadSignal<SearchQuery>,
    pub hit_count: ReadSignal<Option<Result<SearchResultHitCount, ServerFnError>>>,
    pub search_result: ReadSignal<Option<Result<SearchResultDocuments, ServerFnError>>>,
    pub current_search_result_page: ReadSignal<u64>,
    pub set_current_page: Callback<u64>,
    pub selected_result_hash: ReadSignal<Option<DocumentIdentifier>>,
    pub set_selected_result_hash: Callback<Option<DocumentIdentifier>>,
    pub set_selected_result_hash_and_page: Callback<(Option<DocumentIdentifier>, u64)>,
}

#[component]
pub fn SearchPanelLeftView(
    query: ReadSignal<SearchQuery>,
    current_search_result_page: ReadSignal<u64>,
    selected_result_hash: ReadSignal<Option<DocumentIdentifier>>,
) -> Element {
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
    let viewer_find_query = move |hash: &Option<DocumentIdentifier>| {
        let by_filename = search_result.read().as_ref().and_then(|result| result.as_ref().ok())
            .map(|result| hash.as_ref().is_some_and(|identifier| result.filename_only_cursors.contains(identifier))
                || result.results.iter().any(|item| Some(item.document_identifier()) == *hash && item.matched_by_filename))
            .unwrap_or(false);
        if by_filename { String::new() } else { query.read().query_string.clone() }
    };
    let set_selected_result_hash = Callback::new(move |hash: Option<DocumentIdentifier>| {
        let find_query = viewer_find_query(&hash);
        let route = Route::SearchPage {
            query: query.read().clone().into(),
            current_search_result_page: *current_search_result_page.read(),
            selected_result_hash: hash.into(),
            doc_viewer_state: Some(DocViewerState::from_find_query(
                find_query,
            ))
            .into(),
        };
        navigator().push(route);
    });
    let set_selected_result_hash_and_page =
        Callback::new(move |(hash, page): (Option<DocumentIdentifier>, u64)| {
            let find_query = viewer_find_query(&hash);
            let route = Route::SearchPage {
                query: query.read().clone().into(),
                current_search_result_page: page,
                selected_result_hash: hash.into(),
                doc_viewer_state: Some(DocViewerState::from_find_query(
                    find_query,
                ))
                .into(),
            };
            navigator().push(route);
        });
    use_context_provider(move || SearchResultsState {
        query,
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
                margin: 0;
                padding: 7px;
                padding-top: 0px;
                height: 100%;
                min-height: 0;
                width: 100%;
            ",
            SearchResultListControls {}

            div {
                style: "
                flex: 1 1 auto;
                min-height: 0;
                overflow: hidden;
                width: 100%;
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
    let mut result_mounted_thing =
        use_signal(move || BTreeMap::<DocumentIdentifier, Event<MountedData>>::new());
    use_effect(move || {
        let selected = search_results_state.selected_result_hash.read().clone();
        if let Some(selected) = selected {
            if let Some(mounted_data) = result_mounted_thing.read().get(&selected) {
                let _x = mounted_data.scroll_to_with_options(ScrollToOptions {
                    behavior: ScrollBehavior::Smooth,
                    vertical: ScrollLogicalPosition::Center,
                    horizontal: ScrollLogicalPosition::Center,
                });
                // if let Err(e) = _x {dioxus::logger::tracing::error!("Error scrolling to selected result: {e}");}
            }
        }
    });

    let search_result = search_results_state.search_result;
    // .suspend()?.cloned();
    let search_result = search_result.read();
    let search_result = match search_result.as_ref() {
        Some(Err(e)) => return rsx! {ServerErrorDisplay { error: e.clone() }},
        Some(Ok(s)) => s,
        None => return rsx! { LoadingIndicator{} },
    };

    let result_list = search_result.results.clone();
    // Partial hit count: one or more shards failed, so the total is a lower bound.
    let hit_count_partial = search_results_state
        .hit_count
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .map(|h| h.partial)
        .unwrap_or(false);

    rsx! {
        div {
            id: "x-search-results-scroll",
            style: "height: 100%; width: 100%; overflow-y: auto;",
            if let Some(notice) = common::search_query::short_infix_notice(&search_result.query.query_string) {
                div { role: "status", style: "padding: 8px 12px;", "{notice}" }
            }
            // Partial-results notice: one or more shards could not be searched (see the
            // backend fan-out partial-failure policy). The list and the hit count may
            // be incomplete.
            if search_result.partial || hit_count_partial {
                div {
                    style: "
                        width: 100%;
                        padding: 8px 11px;
                        margin-bottom: 4px;
                        border: 1px solid rgba(200, 120, 0, 0.6);
                        border-radius: 6px;
                        background-color: rgba(255, 180, 60, 0.15);
                        color: rgb(120, 70, 0);
                        font-size: 13px;
                    ",
                    "Some collections could not be searched, so results may be incomplete."
                }
            }
            if result_list.is_empty() && !search_result.query.query_string.trim().is_empty()
                && !search_result.partial && !hit_count_partial
                && search_result.query == *search_results_state.query.read()
                && search_results_state.hit_count.read().as_ref().is_some_and(|r| r.as_ref().is_ok_and(|h| h.total == 0)) {
                NoResults { query: search_results_state.query }
            }
            ul {
                id: "x-search-panel-results-wrapper",
                style: "
                    width: 100%;
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
}

/// Offer checked query variants under the same filters after a zero-result search.
#[component]
fn NoResults(query: ReadSignal<SearchQuery>) -> Element {
    let suggestions = use_resource(move || {
        let current = query.read().clone();
        crate::api::search_api::search_suggestions(current)
    });
    let current = suggestions.read().clone();
    rsx! {
        section { id: "x-search-no-results", style: "padding: 24px 12px;",
            h2 { style: "font-size: var(--x-text-page); line-height: var(--x-line-page); margin-bottom: 8px;", "No results" }
            p { "The query was {query.read().query_string}." }
            match current {
                None => rsx! { p { role: "status", "Loading similar words." } },
                Some(Err(error)) => rsx! { ServerErrorDisplay { error } },
                Some(Ok(found)) => rsx! {
                    if found.partial {
                        p { role: "status", "Some collections could not be searched, so suggestions may be incomplete." }
                    }
                    if found.queries.is_empty() {
                        p { "No similar words were found in the selected collections." }
                    } else {
                        p { "Search for a similar word:" }
                        for suggestion in found.queries {
                            button {
                                key: "{suggestion.query}",
                                class: "x-search-suggestion",
                                style: "padding: 8px 12px; margin: 4px; border: 1px solid; border-color: var(--x-link); border-radius: 6px;",
                                onclick: move |_| {
                                    let mut corrected = query.read().clone();
                                    corrected.query_string = suggestion.query.clone();
                                    navigator().push(Route::SearchPage {
                                        query: corrected.into(), current_search_result_page: 0,
                                        selected_result_hash: None.into(), doc_viewer_state: None.into(),
                                    });
                                },
                                "{suggestion.query} ({suggestion.count})"
                            }
                        }
                    }
                },
            }
        }
    }
}
