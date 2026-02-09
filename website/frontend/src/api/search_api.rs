//! Client API calls for search endpoints.

use common::{search_query::SearchQuery, search_result::{SearchResultDocuments, SearchResultFacets}};
use dioxus::prelude::*;




#[server]
pub async fn search_for_results(input: SearchQuery, current_search_result_page: u64) -> Result<SearchResultDocuments, ServerFnError> {
    let x = backend::api::search::search_for_results(input, current_search_result_page).await;
    x.map_err(|e| ServerFnError::ServerError { message: e.to_string(), code: 500, details: None })
}

#[server]
pub async fn search_for_results_hit_count(input: SearchQuery) -> Result<u64, ServerFnError> {
    let x = backend::api::search::search_for_results_hit_count(input).await;
    x.map_err(|e| ServerFnError::ServerError { message: e.to_string(), code: 500, details: None })
}

#[server]
pub async fn search_string_facet(input: SearchQuery, column: String, map_string_terms: Option<String>) -> Result<SearchResultFacets, ServerFnError> {
    let x = backend::api::search::search_string_facet(input, column, map_string_terms).await;
    x.map_err(|e| ServerFnError::ServerError { message: e.to_string(), code: 500, details: None })
}
