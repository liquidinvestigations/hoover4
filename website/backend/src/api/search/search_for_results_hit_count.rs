//! Search count endpoint for result totals.

use crate::api::search::fanout::{self, FanoutTarget};
use crate::api::search::search_sql::sql_options_clause;
use crate::db_utils::manticore_utils::manticore_search_sql;
use common::{current_user::CurrentUser, search_query::SearchQuery, search_result::SearchResultHitCount};
use serde::{Deserialize, Serialize};

use crate::auth::permissions;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SearchForResultsHitCountResponse {
    pub total_count: u64,
}

/// Sum of `count(distinct file_hash)` across all shards of all searched
/// collections.
///
/// **Upper bound, not an exact total:** the same `file_hash` can exist in two
/// collections (the same file ingested twice), so per-shard distinct counts are
/// not strictly additive. When one or more shards fail (`partial` in the
/// response) the failed shards' counts are missing and the total is a *lower*
/// bound instead.
pub async fn search_for_results_hit_count(user: &CurrentUser, query: SearchQuery) -> anyhow::Result<SearchResultHitCount> {
    crate::api::telemetry::record_event(&user.username, crate::api::telemetry::EVENT_USER_SEARCH, "");
    let perms = permissions::resolve_permissions(user).await?;
    let Some(query) = permissions::sanitize_query(query, &perms) else {
        return Ok(SearchResultHitCount { total: 0, partial: false });
    };
    let collections = fanout::permitted_search_collections(user, &query).await?;
    let targets = fanout::shard_targets(&collections).await;
    if targets.is_empty() {
        return Ok(SearchResultHitCount { total: 0, partial: false });
    }

    let outcome = fanout::fan_out(targets, |target: FanoutTarget| {
        let query = query.clone();
        async move {
            let parts = fanout::shard_query_parts(&target, &query).await?;
            let from_clause = &parts.from_clause;
            let sql_where_clause = &parts.where_clause;
            let options_clause = sql_options_clause(1000);
            let sql = format!(
                "
                SELECT count(distinct file_hash) as total_count
                {from_clause}
                {sql_where_clause}
                {options_clause}
                ;",
            );
            manticore_search_sql::<SearchForResultsHitCountResponse>(sql, &parts.salt).await
        }
    })
    .await?;
    let partial = outcome.is_partial();

    let total_count_upper_bound: u64 = outcome
        .results
        .into_iter()
        .map(|(_, response)| {
            response
                .hits
                .hits
                .first()
                .map(|hit| hit._source.total_count)
                .unwrap_or(0)
        })
        .sum();
    Ok(SearchResultHitCount { total: total_count_upper_bound, partial })
}
