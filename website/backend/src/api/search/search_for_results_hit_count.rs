use crate::{api::search::search_sql::build_sql_where_clause, db_utils::manticore_utils::manticore_search_sql};
use common::search_query::SearchQuery;
use serde::{Deserialize, Serialize};
use crate::api::search::search_sql::{SQL_FROM_CLAUSE, SQL_OPTIONS_CLAUSE};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SearchForResultsHitCountResponse {
    pub total_count: u64,
}

pub async fn search_for_results_hit_count(query: SearchQuery) -> anyhow::Result<u64> {
    let sql_where_clause = build_sql_where_clause(&query);
    let sql = format!(
        "
        SELECT count(distinct file_hash) as total_count
        {SQL_FROM_CLAUSE}
        {sql_where_clause}
        {SQL_OPTIONS_CLAUSE}
        ;",
    );
    let response = manticore_search_sql::<SearchForResultsHitCountResponse>(sql).await?;
    let response = response.hits.hits;
    if response.is_empty() {
        return Ok(0);
    }
    let response = response[0]._source.total_count;
    Ok(response)
}
