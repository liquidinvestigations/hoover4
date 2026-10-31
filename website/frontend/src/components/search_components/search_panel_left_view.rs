//! Left panel view for search filters and facets.

use std::collections::BTreeMap;

use dioxus::prelude::*;
use dioxus_free_icons::Icon;
use dioxus_free_icons::icons::md_action_icons::MdFindInPage;

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
use crate::tr;
use crate::i18n::SharedText;
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
    /// Runs the failed search again. Pages that show no search give a callback that does
    /// nothing.
    pub retry_search: Callback<()>,
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
        retry_search: Callback::new(move |_| {
            hit_count.clear();
            search_result.clear();
            hit_count.restart();
            search_result.restart();
        }),
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
        Some(Err(e)) => return rsx! { SearchFailure { error: e.clone(), on_retry: search_results_state.retry_search } },
        Some(Ok(s)) => s,
        None => return rsx! { LoadingIndicator{} },
    };

    match search_results_state.hit_count.read().as_ref() {
        Some(Err(e)) => return rsx! { SearchFailure { error: e.clone(), on_retry: search_results_state.retry_search } },
        None => return rsx! { LoadingIndicator {} },
        Some(Ok(_)) => {}
    }

    let result_list = search_result.results.clone();
    // An empty state describes only a completed answer to the current address.
    let total = match search_results_state.hit_count.read().as_ref() {
        Some(Ok(count)) => count.total,
        _ => 0,
    };
    let empty_state = if result_list.is_empty()
        && search_result.query == *search_results_state.query.read()
        && search_result.page_number == *search_results_state.current_search_result_page.read()
    {
        Some(EmptyState::classify(&search_result.query, total))
    } else {
        None
    };

    rsx! {
        div {
            id: "x-search-results-scroll",
            style: "height: 100%; width: 100%; overflow-y: auto;",
            if let Some(notice) = common::search_query::short_infix_notice(&search_result.query.query_string).shared() {
                div { role: "status", style: "padding: 8px 12px;", "{notice}" }
            }
            if let Some(state) = empty_state {
                EmptySearchResults { state, query: search_results_state.query }
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

/// A search that failed after its retries. A query the reader can correct keeps its
/// advice. Any other failure says that the search did not complete and offers a retry.
#[component]
fn SearchFailure(error: ServerFnError, on_retry: Callback<()>) -> Element {
    if crate::api::error_util::is_user_input_error(&error) {
        return rsx! { ServerErrorDisplay { error } };
    }
    let detail = crate::api::error_util::user_facing_message(&error);
    rsx! {
        section {
            id: "x-search-failed",
            role: "alert",
            style: "padding: 24px 12px; display: flex; flex-direction: column; align-items: center; gap: 8px;",
            h2 { style: "font-size: var(--x-text-page); line-height: var(--x-line-page);", {tr!("panel-left-view-the-search-did-not-complete")} }
            p { {tr!("panel-left-view-some-collections-did-not-answer")} }
            button {
                style: "
                    border: 1px solid rgba(0,0,0,0.3); background: white;
                    border-radius: 100px; padding: 6px 16px; cursor: pointer;
                    font-size: 15px;
                ",
                class: "hoover4-hover-shadow-background",
                onclick: move |_| on_retry.call(()),
                {tr!("panel-left-view-retry")}
            }
            p { style: "font-size: 13px; color: rgba(0, 0, 0, 0.55); max-width: 560px; overflow-wrap: anywhere;", "{detail}" }
        }
    }
}

/// Why a completed search shows no result cards.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EmptyState {
    /// The query has words and no document matches them under the filters.
    NoMatch,
    /// The query has no words and no document matches the filters.
    FiltersMatchNothing,
    /// Documents match, and the page in the address is after the last page.
    AfterLastPage,
}

impl EmptyState {
    /// Classify an empty page of a completed search with `total` matches.
    pub fn classify(query: &SearchQuery, total: u64) -> Self {
        if total > 0 {
            EmptyState::AfterLastPage
        } else if query.query_string.trim().is_empty() {
            EmptyState::FiltersMatchNothing
        } else {
            EmptyState::NoMatch
        }
    }
}

/// The query of the Clear filters action: the same words and sort, with no facet or
/// range filter.
pub fn without_filters(query: &SearchQuery) -> SearchQuery {
    SearchQuery {
        facet_filters: Default::default(),
        range_filters: Default::default(),
        ..query.clone()
    }
}

/// Keep the selected document and viewer state when an empty-result action changes the search.
fn empty_result_route(mut route: Route, clear_filters: bool) -> Route {
    if let Route::SearchPage { query, current_search_result_page, .. } = &mut route {
        if clear_filters {
            *query = without_filters(&query.0).into();
        }
        *current_search_result_page = 0;
    }
    route
}

const EMPTY_ACTION_STYLE: &str = "
    border: 1px solid rgba(0,0,0,0.3); background: white;
    border-radius: 100px; padding: 6px 16px; cursor: pointer;
    font-size: var(--x-text-body);
";

/// The empty-result view of a completed search, in the layout of the empty preview pane:
/// a centred column with a large grey icon, a title and one explanation line.
///
/// A query with words offers the checked similar words under the same filters. A query
/// without words offers Clear filters. A page after the last page offers Go to page 1.
/// Both actions change only the part of the address that they name.
#[component]
fn EmptySearchResults(state: EmptyState, query: ReadSignal<SearchQuery>) -> Element {
    let route = use_route::<Route>();
    let clear_route = empty_result_route(route.clone(), true);
    let first_route = empty_result_route(route, false);
    let (id, title, explanation) = match state {
        EmptyState::NoMatch => (
            "x-search-no-results",
            tr!("panel-left-view-no-results"),
            tr!("panel-left-view-no-document-matches-query", query: query.read().query_string.trim().to_string()),
        ),
        EmptyState::FiltersMatchNothing => (
            "x-search-no-filter-results",
            tr!("panel-left-view-no-results"),
            tr!("panel-left-view-no-document-matches-the-selected"),
        ),
        EmptyState::AfterLastPage => (
            "x-search-after-last-page",
            tr!("panel-left-view-this-page-is-empty"),
            tr!("panel-left-view-the-page-is-after-the"),
        ),
    };
    rsx! {
        section {
            id,
            class: "x-empty-search-results",
            style: "display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100%; width: 100%; padding: 24px 12px; box-sizing: border-box;",
            div {
                style: "max-width: 360px; display: flex; flex-direction: column; align-items: center; text-align: center; gap: 11px;",
                Icon { icon: MdFindInPage, style: "width: 96px; height: 96px; color: rgba(0, 0, 0, 0.5);" }
                h2 { style: "font-size: var(--x-text-page); line-height: var(--x-line-page); font-weight: 500; color: rgb(0, 0, 0);", "{title}" }
                p { style: "font-size: var(--x-text-body); line-height: var(--x-line-body); color: rgba(0, 0, 0, 0.5); overflow-wrap: anywhere;", "{explanation}" }
                match state {
                    EmptyState::NoMatch => rsx! { SimilarWords { query } },
                    EmptyState::FiltersMatchNothing => rsx! {
                        button {
                            id: "x-search-clear-filters",
                            style: EMPTY_ACTION_STYLE,
                            class: "hoover4-hover-shadow-background",
                            onclick: move |_| {
                                navigator().push(clear_route.clone());
                            },
                            {tr!("panel-left-view-clear-filters")}
                        }
                    },
                    EmptyState::AfterLastPage => rsx! {
                        button {
                            id: "x-search-first-page",
                            style: EMPTY_ACTION_STYLE,
                            class: "hoover4-hover-shadow-background",
                            onclick: move |_| {
                                navigator().push(first_route.clone());
                            },
                            {tr!("panel-left-view-go-to-page-1")}
                        }
                    },
                }
            }
        }
    }
}

/// Offer checked query variants under the same filters after a zero-result search.
#[component]
fn SimilarWords(query: ReadSignal<SearchQuery>) -> Element {
    let suggestions = use_resource(move || {
        let current = query.read().clone();
        crate::api::search_api::search_suggestions(current)
    });
    let current = suggestions.read().clone();
    rsx! {
        div { class: "x-search-similar-words", style: "display: flex; flex-direction: column; align-items: center; gap: 6px;",
            match current {
                None => rsx! { p { role: "status", {tr!("panel-left-view-loading-similar-words")} } },
                Some(Err(error)) => rsx! { ServerErrorDisplay { error } },
                Some(Ok(found)) => rsx! {
                    if found.queries.is_empty() {
                        p { {tr!("panel-left-view-no-similar-words-were-found")} }
                    } else {
                        p { {tr!("panel-left-view-search-for-a-similar-word")} }
                        div {
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
                    }
                },
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common::search_query::RangeFilter;
    use common::search_result::FacetOriginalValue;

    #[test]
    fn empty_states_follow_the_count_and_the_words() {
        let mut query = SearchQuery::default();
        assert_eq!(EmptyState::classify(&query, 0), EmptyState::FiltersMatchNothing);
        query.query_string = "  ".to_string();
        assert_eq!(EmptyState::classify(&query, 0), EmptyState::FiltersMatchNothing);
        query.query_string = "zzxqvtrplmx".to_string();
        assert_eq!(EmptyState::classify(&query, 0), EmptyState::NoMatch);
        assert_eq!(EmptyState::classify(&query, 12), EmptyState::AfterLastPage);
        query.query_string.clear();
        assert_eq!(EmptyState::classify(&query, 3), EmptyState::AfterLastPage);
    }

    #[test]
    fn clear_filters_keeps_the_words_and_the_sort() {
        let mut query = SearchQuery { query_string: "invoice".to_string(), ..Default::default() };
        query.sort.desc = true;
        query.facet_filters.insert("filetype".to_string(), [FacetOriginalValue::String("pdf".to_string())].into());
        query.range_filters.insert("dates".to_string(), RangeFilter { min: Some(1), ..Default::default() });
        let cleared = without_filters(&query);
        assert_eq!(cleared.query_string, "invoice");
        assert_eq!(cleared.sort, query.sort);
        assert!(!cleared.has_any_filter());
    }

    #[test]
    fn empty_actions_preserve_the_selected_document_and_viewer() {
        let mut query = SearchQuery { query_string: "invoice".to_string(), ..Default::default() };
        query.facet_filters.insert("filetype".to_string(), [FacetOriginalValue::String("pdf".to_string())].into());
        let selected_result_hash = Some(DocumentIdentifier {
            collection_dataset: "test_docs".to_string(), file_hash: "abc".to_string(),
        }).into();
        let doc_viewer_state = Some(DocViewerState::from_find_query("invoice".to_string())).into();
        let original = Route::SearchPage {
            query: query.clone().into(), current_search_result_page: 40,
            selected_result_hash, doc_viewer_state,
        };
        for clear in [false, true] {
            let mut expected = original.clone();
            if let Route::SearchPage { query: expected_query, current_search_result_page, .. } = &mut expected {
                *current_search_result_page = 0;
                *expected_query = if clear { without_filters(&query) } else { query.clone() }.into();
            }
            assert_eq!(empty_result_route(original.clone(), clear), expected);
        }
    }
}
