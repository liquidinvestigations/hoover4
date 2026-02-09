//! Search facets endpoint and response shaping.

use std::{collections::{HashMap, HashSet}, u64};

use crate::{api::search::search_sql::build_sql_where_clause, db_utils::{clickhouse_utils::get_clickhouse_client, manticore_utils::{RawSearchResultAggregation, manticore_search_sql}}};
use common::{search_query::SearchQuery, search_result::{FacetOriginalValue, SearchResultFacetItem, SearchResultFacets}};
use serde::{Deserialize, Serialize};
use crate::api::search::search_sql::{SQL_FROM_CLAUSE, SQL_OPTIONS_CLAUSE};

pub async fn search_string_facet(mut query: SearchQuery, column: String, map_string_terms: Option<String>) -> anyhow::Result<SearchResultFacets> {

    if map_string_terms.is_some() {
        return search_mva_facet(query, column, map_string_terms).await;
    }
    // remove all filters on current column, as we don't want to filter out unselected values from the facet
    query.facet_filters.remove(&column);

    let sql_where_clause = build_sql_where_clause(&query);
    let sql = format!(
        "
        SELECT file_hash
        {SQL_FROM_CLAUSE}
        {sql_where_clause}
        LIMIT 0

        {SQL_OPTIONS_CLAUSE}
        
        FACET {} DISTINCT file_hash ORDER BY count(distinct file_hash) DESC LIMIT 21
        ;",
        column,
    );
    let facets = manticore_search_sql::<serde_json::Value>(sql).await?;
    let facets = facets.aggregations.unwrap_or_default();
    let facets = facets.get(&column).unwrap_or(&RawSearchResultAggregation::default()).buckets.clone();

    let mut result = SearchResultFacets {
        query: query.clone(),
        facet_field: column.clone(),
        facet_values: Vec::new(),
    };

    if facets.is_empty() {
        return Ok(result);
    }

    let mut response = facets.into_iter().map(|bucket| (bucket.key, bucket.doc_count)).collect::<Vec<_>>();
    response.sort_by_key(|(_v, count)| u64::MAX - *count);
    let mut present_values = HashSet::new();
    for (value, count) in response {
        if present_values.contains(&value) {
            continue;
        }
        present_values.insert(value.clone());
        result.facet_values.push(SearchResultFacetItem {
            display_string: match &value {
                serde_json::Value::String(s) => s.clone(),
                serde_json::Value::Number(n) => n.as_u64().unwrap_or(0).to_string(),
                _ => anyhow::bail!("Invalid value from manticore related to facets: {:#?}", value),
            },
            original_value: match &value {
                serde_json::Value::String(s) => FacetOriginalValue::String(s.clone()),
                serde_json::Value::Number(n) => FacetOriginalValue::Int(n.as_u64().unwrap_or(0)),
                _ => anyhow::bail!("Invalid value from manticore related to facets: {:#?}", value),
            },
            count: count,
        });
    }
    drop(present_values);

    if let Some(map_string_terms) = map_string_terms {
        let mut ints = Vec::new();
        for item in &result.facet_values {
            if let FacetOriginalValue::Int(i) = item.original_value {
                ints.push(i);
            }
        }
        let display_strings = fetch_db_terms_for_ints(ints, map_string_terms).await?;
        for item in &mut result.facet_values {
            if let FacetOriginalValue::Int(i) = item.original_value {
                if let Some(display_string) = display_strings.get(&i) {
                    item.display_string = display_string.clone();
                }
            }
        }
    }
    result.facet_values.sort_by_key(|item| (u64::MAX - item.count, item.display_string.clone()));

    Ok(result)
}


#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
struct SearchMvaFacetResponse {
    term: serde_json::Value,
    doc_count: u64,
}

pub async fn search_mva_facet(mut query: SearchQuery, column: String, map_string_terms: Option<String>) -> anyhow::Result<SearchResultFacets> {
    // remove all filters on current column, as we don't want to filter out unselected values from the facet
    query.facet_filters.remove(&column);

    let sql_where_clause = build_sql_where_clause(&query);
    let sql = format!(
        "
        SELECT groupby() term, count(distinct file_hash) as doc_count
        {SQL_FROM_CLAUSE}
        {sql_where_clause}

        GROUP BY {}
        ORDER BY doc_count DESC LIMIT 21
        ;",
        column,
    );
    println!("sql: {}", sql);
    let facets = manticore_search_sql::<SearchMvaFacetResponse>(sql).await?;
    let facets = facets.hits.hits;

    let mut result = SearchResultFacets {
        query: query.clone(),
        facet_field: column.clone(),
        facet_values: Vec::new(),
    };

    if facets.is_empty() {
        return Ok(result);
    }

    let mut response = facets.into_iter().map(
        |bucket|
        (bucket._source.term, bucket._source.doc_count)).collect::<Vec<_>>();
    response.sort_by_key(|(_v, count)| u64::MAX - *count);
    let mut present_values = HashSet::new();
    for (value, count) in response {
        if present_values.contains(&value) {
            continue;
        }
        present_values.insert(value.clone());
        result.facet_values.push(SearchResultFacetItem {
            display_string: match &value {
                serde_json::Value::String(s) => s.clone(),
                serde_json::Value::Number(n) => n.as_u64().unwrap_or(0).to_string(),
                _ => anyhow::bail!("Invalid value from manticore related to facets: {:#?}", value),
            },
            original_value: match &value {
                serde_json::Value::String(s) => FacetOriginalValue::String(s.clone()),
                serde_json::Value::Number(n) => FacetOriginalValue::Int(n.as_u64().unwrap_or(0)),
                _ => anyhow::bail!("Invalid value from manticore related to facets: {:#?}", value),
            },
            count: count,
        });
    }
    drop(present_values);

    if let Some(map_string_terms) = map_string_terms {
        let mut ints = Vec::new();
        for item in &result.facet_values {
            if let FacetOriginalValue::Int(i) = item.original_value {
                ints.push(i);
            }
        }
        let display_strings = fetch_db_terms_for_ints(ints, map_string_terms).await?;
        for item in &mut result.facet_values {
            if let FacetOriginalValue::Int(i) = item.original_value {
                if let Some(display_string) = display_strings.get(&i) {
                    item.display_string = display_string.clone();
                }
            }
        }
    }
    result.facet_values.sort_by_key(|item| (u64::MAX - item.count, item.display_string.clone()));

    Ok(result)
}


async fn fetch_db_terms_for_ints(ints: Vec<u64>, field_name: String) -> anyhow::Result<HashMap<u64, String>> {
    let client = get_clickhouse_client();
    let sql = "
    SELECT term_id, term_value
    FROM string_term_id_to_text
    WHERE term_field = ?
    AND term_id in ?
    ";
    let result = client.query(sql).bind(field_name).bind(ints).fetch_all::<(u64, String)>().await?;
    Ok(HashMap::from_iter(result))
}
