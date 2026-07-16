//! Client API calls for search endpoints.

use common::{
    search_query::SearchQuery,
    search_result::{SearchResultDocuments, SearchResultFacets},
};
use dioxus::prelude::*;

#[cfg(feature = "server")]
use crate::api::error_util::to_server_fn_error;

#[server]
pub async fn search_for_results(
    input: SearchQuery,
    current_search_result_page: u64,
) -> Result<SearchResultDocuments, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::search::search_for_results(&user, input, current_search_result_page)
        .await
        .map_err(to_server_fn_error)
}

#[server]
pub async fn search_for_results_hit_count(input: SearchQuery) -> Result<u64, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::search::search_for_results_hit_count(&user, input)
        .await
        .map_err(to_server_fn_error)
}

#[server]
pub async fn search_string_facet(
    input: SearchQuery,
    column: String,
    map_string_terms: Option<String>,
) -> Result<SearchResultFacets, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::search::search_string_facet(&user, input, column, map_string_terms)
        .await
        .map_err(to_server_fn_error)
}
