//! Search facets endpoint and response shaping.
//!
//! Facets fan out per shard like the result list (see `fanout.rs`). Each shard
//! over-fetches buckets ([`fanout::per_shard_facet_limit`]) and the backend sums
//! counts per key, re-sorts and truncates to the display limit.

use std::{
    collections::{BTreeSet, HashMap, HashSet},
    u64,
};

use crate::api::search::fanout::{self, FanoutTarget};
use crate::api::search::search_sql::{qualify_field_name, sql_options_clause};
use crate::{
    db_utils::{
        clickhouse_utils::get_collection_client,
        manticore_utils::manticore_search_sql,
    },
};
use common::{
    current_user::CurrentUser,
    search_query::SearchQuery,
    search_result::{FacetOriginalValue, SearchResultFacetItem, SearchResultFacets},
};

use crate::auth::permissions;
use serde::{Deserialize, Serialize};

pub async fn search_string_facet(
    user: &CurrentUser,
    query: SearchQuery,
    column: String,
    map_string_terms: Option<String>,
) -> anyhow::Result<SearchResultFacets> {

    crate::api::telemetry::record_event(&user.username, crate::api::telemetry::EVENT_USER_SEARCH, "");
    let x = _search_string_facet(user, query, column.clone(), map_string_terms).await?;
    if column == "collection_dataset" {
        return _search_enrich_collection_list(user, x).await;
    }
    Ok(x)
}

async fn _search_enrich_collection_list(
    user: &CurrentUser,
    mut x: SearchResultFacets,
) -> anyhow::Result<SearchResultFacets> {
    let collection_list = crate::api::list_datasets::list_permitted_dataset_ids(user).await?;
    let mut collection_list
    : BTreeSet<_> = collection_list.into_iter().collect();

    for z in &x.facet_values {
        if let FacetOriginalValue::String(z) = &z.original_value {
            let _r = collection_list.remove(z);
        }
    }
    for z in collection_list {
        x.facet_values.push(SearchResultFacetItem { display_string: z.clone(), original_value: FacetOriginalValue::String(z.clone()), count: 0 });
    }


    Ok(x)
}

/// Turn merged `(key, count)` facet pairs into UI items.
fn facet_items_from_pairs(
    pairs: Vec<(serde_json::Value, u64)>,
) -> anyhow::Result<Vec<SearchResultFacetItem>> {
    let mut items = Vec::new();
    let mut present_values = HashSet::new();
    for (value, count) in pairs {
        if present_values.contains(&value) {
            continue;
        }
        present_values.insert(value.clone());
        items.push(SearchResultFacetItem {
            display_string: match &value {
                serde_json::Value::String(s) => s.clone(),
                serde_json::Value::Number(n) => n.as_u64().unwrap_or(0).to_string(),
                _ => anyhow::bail!(
                    "Invalid value from manticore related to facets: {:#?}",
                    value
                ),
            },
            original_value: match &value {
                serde_json::Value::String(s) => FacetOriginalValue::String(s.clone()),
                serde_json::Value::Number(n) => FacetOriginalValue::Int(n.as_u64().unwrap_or(0)),
                _ => anyhow::bail!(
                    "Invalid value from manticore related to facets: {:#?}",
                    value
                ),
            },
            count,
        });
    }
    Ok(items)
}

/// Resolve display strings for integer term ids and rewrite the items in place.
async fn map_term_display_strings(
    user: &CurrentUser,
    facet_values: &mut [SearchResultFacetItem],
    map_string_terms: String,
) -> anyhow::Result<()> {
    let mut ints = Vec::new();
    for item in facet_values.iter() {
        if let FacetOriginalValue::Int(i) = item.original_value {
            ints.push(i);
        }
    }
    let collections = crate::db_utils::clickhouse_utils::list_permitted_collections(user).await?;
    let display_strings = fetch_db_terms_for_ints(&collections, ints, map_string_terms).await?;
    for item in facet_values.iter_mut() {
        if let FacetOriginalValue::Int(i) = item.original_value
            && let Some(display_string) = display_strings.get(&i)
        {
            item.display_string = display_string.clone();
        }
    }
    Ok(())
}

async fn _search_string_facet(
    user: &CurrentUser,
    query: SearchQuery,
    column: String,
    map_string_terms: Option<String>,
) -> anyhow::Result<SearchResultFacets> {
    let perms = permissions::resolve_permissions(user).await?;
    let Some(mut query) = permissions::sanitize_query(query, &perms) else {
        return Ok(SearchResultFacets {
            query: SearchQuery::default(),
            facet_field: column,
            facet_values: Vec::new(),
            partial: false,
        });
    };
    if map_string_terms.is_some() {
        return search_mva_facet(user, query, column, map_string_terms).await;
    }
    // remove all filters on current column, as we don't want to filter out unselected values from the facet.
    // NOTE: this also drops the `collection_dataset` filter sanitize_query injected for
    // permissions. That is safe ONLY because permissions are collection-granular
    // (collection_group_permissions grants a whole collection, so a permitted
    // collection implies all its datasets). If dataset-level permissions are ever
    // added, this line becomes a data leak.
    query.facet_filters.remove(&column);

    let collections = fanout::permitted_search_collections(user, &query).await?;
    let targets = fanout::shard_targets(&collections).await;
    let mut result = SearchResultFacets {
        query: query.clone(),
        facet_field: column.clone(),
        facet_values: Vec::new(),
        partial: false,
    };
    if targets.is_empty() {
        return Ok(result);
    }
    let bucket_limit = fanout::per_shard_facet_limit(targets.len());

    let outcome = fanout::fan_out(targets, |target: FanoutTarget| {
        let query = query.clone();
        let column = column.clone();
        async move {
            let parts = fanout::shard_query_parts(&target, &query).await?;
            let from_clause = &parts.from_clause;
            let sql_where_clause = &parts.where_clause;
            let options_clause = sql_options_clause(1000);
            let column = qualify_field_name(&column, &parts.meta_table)?;
            let sql = format!(
                "
                SELECT file_hash
                {from_clause}
                {sql_where_clause}
                LIMIT 0

                {options_clause}

                FACET {column} DISTINCT file_hash ORDER BY count(distinct file_hash) DESC LIMIT {bucket_limit}
                ;",
            );
            manticore_search_sql::<serde_json::Value>(sql, &parts.salt).await
        }
    })
    .await?;
    result.partial = outcome.is_partial();

    // Merge buckets across shards: sum doc_count per key. The aggregation name in
    // each response is the qualified column; there is exactly one aggregation per
    // response, so take the first map entry regardless of its name.
    let per_shard_buckets: Vec<Vec<(serde_json::Value, u64)>> = outcome
        .results
        .into_iter()
        .map(|(_, response)| {
            response
                .aggregations
                .unwrap_or_default()
                .into_values()
                .next()
                .unwrap_or_default()
                .buckets
                .into_iter()
                .map(|bucket| (bucket.key, bucket.doc_count))
                .collect()
        })
        .collect();
    let merged = fanout::merge_facet_pairs(per_shard_buckets, fanout::FACET_DISPLAY_LIMIT);

    result.facet_values = facet_items_from_pairs(merged)?;

    result
        .facet_values
        .sort_by_key(|item| (u64::MAX - item.count, item.display_string.clone()));

    Ok(result)
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
struct SearchMvaFacetResponse {
    term: serde_json::Value,
    doc_count: u64,
}

pub async fn search_mva_facet(
    user: &CurrentUser,
    query: SearchQuery,
    column: String,
    map_string_terms: Option<String>,
) -> anyhow::Result<SearchResultFacets> {
    let perms = permissions::resolve_permissions(user).await?;
    let Some(mut query) = permissions::sanitize_query(query, &perms) else {
        return Ok(SearchResultFacets {
            query: SearchQuery::default(),
            facet_field: column,
            facet_values: Vec::new(),
            partial: false,
        });
    };
    // remove all filters on current column, as we don't want to filter out unselected values from the facet.
    // Same permission caveat as in _search_string_facet: safe only while permissions
    // are collection-granular.
    query.facet_filters.remove(&column);

    let collections = fanout::permitted_search_collections(user, &query).await?;
    let targets = fanout::shard_targets(&collections).await;
    let mut result = SearchResultFacets {
        query: query.clone(),
        facet_field: column.clone(),
        facet_values: Vec::new(),
        partial: false,
    };
    if targets.is_empty() {
        return Ok(result);
    }
    let bucket_limit = fanout::per_shard_facet_limit(targets.len());

    let outcome = fanout::fan_out(targets, |target: FanoutTarget| {
        let query = query.clone();
        let column = column.clone();
        async move {
            let parts = fanout::shard_query_parts(&target, &query).await?;
            let from_clause = &parts.from_clause;
            let sql_where_clause = &parts.where_clause;
            // MVA grouping must be qualified: the attribute may live on either side
            // of the join and an unqualified name errors when ambiguous.
            let column = qualify_field_name(&column, &parts.meta_table)?;
            let sql = format!(
                "
                SELECT groupby() term, count(distinct file_hash) as doc_count
                {from_clause}
                {sql_where_clause}

                GROUP BY {column}
                ORDER BY doc_count DESC LIMIT {bucket_limit}
                ;",
            );
            manticore_search_sql::<SearchMvaFacetResponse>(sql, &parts.salt).await
        }
    })
    .await?;
    result.partial = outcome.is_partial();

    let per_shard_buckets: Vec<Vec<(serde_json::Value, u64)>> = outcome
        .results
        .into_iter()
        .map(|(_, response)| {
            response
                .hits
                .hits
                .into_iter()
                .map(|bucket| (bucket._source.term, bucket._source.doc_count))
                .collect()
        })
        .collect();
    let merged = fanout::merge_facet_pairs(per_shard_buckets, fanout::FACET_DISPLAY_LIMIT);

    result.facet_values = facet_items_from_pairs(merged)?;

    if let Some(map_string_terms) = map_string_terms {
        map_term_display_strings(user, &mut result.facet_values, map_string_terms).await?;
    }
    result
        .facet_values
        .sort_by_key(|item| (u64::MAX - item.count, item.display_string.clone()));

    Ok(result)
}

/// Resolve display strings for string-term ids across every permitted collection.
///
/// `string_term_id_to_text` is per-collection since the database split, while the facet
/// code has only a list of term ids and no collection context. Term ids are
/// content-derived hashes (`hash_string_to_uint63`), so the same string has the same id
/// in every collection: each collection's database is queried (through the shared
/// bounded `fan_out` helper) and the results merged, first non-empty value wins. A
/// genuine conflict means a hash collision — the lexicographically smallest value is
/// kept to stay deterministic and a WARNING is logged.
pub async fn fetch_db_terms_for_ints(
    collections: &[String],
    ints: Vec<u64>,
    field_name: String,
) -> anyhow::Result<HashMap<u64, String>> {
    if ints.is_empty() || collections.is_empty() {
        return Ok(HashMap::new());
    }
    let sql = "
    SELECT term_id, term_value
    FROM string_term_id_to_text
    WHERE term_field = ?
    AND term_id in ?
    ";
    let targets: Vec<FanoutTarget> = collections
        .iter()
        .map(|c| FanoutTarget::collection(c.clone()))
        .collect();
    let outcome = fanout::fan_out(targets, |target: FanoutTarget| {
        let ints = ints.clone();
        let field_name = field_name.clone();
        async move {
            let client = get_collection_client(target.collectionname());
            let rows = client
                .query(sql)
                .bind(field_name)
                .bind(ints)
                .fetch_all::<(u64, String)>()
                .await?;
            Ok(rows)
        }
    })
    .await?;

    let mut merged: HashMap<u64, String> = HashMap::new();
    for (_target, rows) in outcome.results {
        for (term_id, term_value) in rows {
            if term_value.is_empty() {
                continue;
            }
            match merged.get(&term_id) {
                None => {
                    merged.insert(term_id, term_value);
                }
                Some(existing) => {
                    // A genuine conflict means a hash collision: warn on ANY
                    // disagreement (not just when the new value sorts lower) and
                    // keep the lexicographically smallest value to stay deterministic.
                    if term_value != *existing {
                        tracing::warn!(
                            "string term id {term_id} maps to both {existing:?} and {term_value:?} \
                             across collections (hash collision?); keeping the smaller"
                        );
                        if term_value < *existing {
                            merged.insert(term_id, term_value);
                        }
                    }
                }
            }
        }
    }
    Ok(merged)
}
