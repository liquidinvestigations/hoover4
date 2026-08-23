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

/// One facet's buckets.
///
/// `restrict_to_ids` carries a search box's needle, already resolved to term ids by
/// [`search_entity_terms`]. `Some(vec![])` means the needle matched nothing and returns
/// no buckets; `None` means there is no needle and returns the whole facet.
#[server]
pub async fn search_string_facet(
    input: SearchQuery,
    column: String,
    map_string_terms: Option<String>,
    restrict_to_ids: Option<Vec<u64>>,
) -> Result<SearchResultFacets, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::search::search_string_facet(&user, input, column, map_string_terms, restrict_to_ids)
        .await
        .map_err(to_server_fn_error)
}

/// Terms matching a needle across the whole corpus, for a filter pane's search box.
///
/// The pane cannot answer this itself: it holds the twenty-one buckets one query
/// returned, and the value being looked for is usually not among them. The ids that come
/// back are what `search_string_facet`'s `restrict_to_ids` then narrows with.
#[server]
pub async fn search_entity_terms(
    input: SearchQuery,
    needle: String,
    columns: Vec<String>,
) -> Result<common::entity_cards::EntityTermHits, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::search::search_entity_terms(&user, input, needle, columns)
        .await
        .map_err(to_server_fn_error)
}

/// Mention counts per computed date bin, for the histogram under the Mentioned Date pane.
///
/// Separate from [`search_date_histogram`] because it answers a different question: a
/// document's own dates are an interval it occupies, the dates it mentions are points,
/// and the bars here count mentions rather than documents.
#[server]
pub async fn search_mentioned_date_histogram(
    input: SearchQuery,
) -> Result<DateHistogram, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::search::search_mentioned_date_histogram(&user, input)
        .await
        .map_err(to_server_fn_error)
}

/// The explainer card for one matched value, from the scanner that produced it.
///
/// `None` is the answer for an undocumented rule and for an unreachable scanner alike:
/// a card is a decoration, and the caller does the same thing in both cases.
#[server]
pub async fn explain_entity(
    rule_id: String,
    value_json: String,
    surface_text: Option<String>,
) -> Result<Option<common::entity_cards::EntityExplanation>, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::search::explain_entity(&user, rule_id, value_json, surface_text)
        .await
        .map_err(to_server_fn_error)
}

/// Document counts per file-size bucket, for the File size filter pane.
///
/// A separate endpoint from `search_string_facet` because the bucket keys are computed
/// by Manticore at query time (`INTERVAL()`) rather than stored. Buckets are a
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
/// the only way a reopened pane can know what is selected. The query stores ids, and a
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
