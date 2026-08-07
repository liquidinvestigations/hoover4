//! Client API calls for search endpoints.

use common::{
    date_histogram::DateHistogram,
    search_query::SearchQuery,
    search_result::{SearchResultDocuments, SearchResultFacets, SearchResultHitCount},
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
pub async fn search_for_results_hit_count(input: SearchQuery) -> Result<SearchResultHitCount, ServerFnError> {
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

/// Document counts per file-size bucket, for the File size filter pane.
///
/// A separate endpoint from `search_string_facet` because the bucket keys are computed
/// by Manticore at query time (`INTERVAL()`) rather than stored — buckets are a
/// presentation choice, and pre-baking them would make adding one a re-index.
#[server]
pub async fn search_numeric_facet(input: SearchQuery) -> Result<SearchResultFacets, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::search::search_numeric_facet(&user, input)
        .await
        .map_err(to_server_fn_error)
}

/// The display text of string-term ids, across every collection the user may read.
///
/// The inverse direction as well as the forward one: the folder picker seeds its ticks
/// by resolving the `vfs_node` ids already in `file_paths` back into node keys, which is
/// the only way a reopened pane can know what is selected — the query stores ids, and a
/// node key is not derivable from one.
#[server]
pub async fn fetch_db_terms_for_ints(
    ints: Vec<u64>,
    field_name: String,
) -> Result<std::collections::HashMap<u64, String>, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    let collections = backend::db_utils::clickhouse_utils::list_permitted_collections(&user)
        .await
        .map_err(to_server_fn_error)?;
    backend::api::search::fetch_db_terms_for_ints(&collections, ints, field_name)
        .await
        .map_err(to_server_fn_error)
}

/// Document counts per computed date bin, for the histogram under the Date filter pane.
///
/// Takes the whole query INCLUDING its date filter: the cutoffs place the bin edges and
/// are then stripped, so the bars show what the rest of the query narrows to and the
/// selection is drawn on top of them.
#[server]
pub async fn search_date_histogram(input: SearchQuery) -> Result<DateHistogram, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::search::search_date_histogram(&user, input)
        .await
        .map_err(to_server_fn_error)
}
