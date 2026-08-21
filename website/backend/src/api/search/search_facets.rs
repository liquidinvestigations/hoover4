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
use crate::api::search::search_sql::{search_field_name, sql_options_clause};
use crate::{
    db_utils::{
        clickhouse_utils::get_collection_client,
        manticore_utils::manticore_search_sql,
    },
};
use common::{
    current_user::CurrentUser,
    entity_stoplist::{ENTITY_TERM_FIELD, is_stopped_entity},
    search_query::SearchQuery,
    search_result::{FacetOriginalValue, SearchResultFacetItem, SearchResultFacets},
};

use crate::auth::permissions;
use serde::{Deserialize, Serialize};

/// One facet's buckets.
///
/// `restrict_to_ids` is the set a search box resolved its needle to. When it is `Some`,
/// only those terms are counted and only those terms come back -- an empty set is a
/// needle that matched nothing, and it returns no buckets rather than every bucket.
/// That distinction is why it is an `Option<Vec<u64>>` and not a `Vec<u64>`.
pub async fn search_string_facet(
    user: &CurrentUser,
    query: SearchQuery,
    column: String,
    map_string_terms: Option<String>,
    restrict_to_ids: Option<Vec<u64>>,
) -> anyhow::Result<SearchResultFacets> {

    crate::api::telemetry::record_event(&user.username, crate::api::telemetry::EVENT_USER_SEARCH, "");
    let x =
        _search_string_facet(user, query, column.clone(), map_string_terms, restrict_to_ids).await?;
    if column == "collection_dataset" {
        return _search_enrich_collection_list(user, x).await;
    }
    Ok(x)
}

async fn _search_enrich_collection_list(
    user: &CurrentUser,
    x: SearchResultFacets,
) -> anyhow::Result<SearchResultFacets> {
    let registered: BTreeSet<String> = crate::api::list_datasets::list_permitted_dataset_ids(user)
        .await?
        .into_iter()
        .collect();
    Ok(reconcile_dataset_facets(x, &registered))
}

/// Make the Collections facet agree with the dataset registry, in both directions.
///
/// The index is not the authority on which datasets exist — `dataset` is. Manticore
/// keeps whatever was written under a name until something deletes it, so a dataset
/// that was abandoned (a failed ingest, a re-ingest under a new name) goes on producing
/// buckets with real counts long after its registry row is gone. Offering one is worse
/// than merely untidy: ticking it applies a filter no document can match, so the UI
/// hands the user a control whose only outcome is `0 documents found`.
///
/// So a value that names no readable dataset is **dropped**, and a readable dataset the
/// index returned no bucket for is **added with a count of 0** — the pane then lists
/// exactly the datasets the file-location tree lists, which is the other half of the
/// same modal.
///
/// This is a display guard, not a repair: the orphan rows are still in the index and
/// still inflate unfiltered hit counts. `main.py purge-dataset` is what removes them.
fn reconcile_dataset_facets(
    mut facets: SearchResultFacets,
    registered: &BTreeSet<String>,
) -> SearchResultFacets {
    facets.facet_values.retain(|item| match &item.original_value {
        FacetOriginalValue::String(value) => registered.contains(value),
        // A non-string bucket cannot name a dataset; leave it to the generic path
        // rather than silently dropping something this function does not understand.
        _ => true,
    });

    let mut missing: BTreeSet<&String> = registered.iter().collect();
    for item in &facets.facet_values {
        if let FacetOriginalValue::String(value) = &item.original_value {
            missing.remove(value);
        }
    }
    for value in missing {
        facets.facet_values.push(SearchResultFacetItem {
            display_string: value.clone(),
            original_value: FacetOriginalValue::String(value.clone()),
            count: 0,
        });
    }

    facets
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
    restrict_to_ids: Option<Vec<u64>>,
) -> anyhow::Result<SearchResultFacets> {
    let perms = permissions::resolve_permissions(user).await?;
    let Some(query) = permissions::sanitize_query(query, &perms) else {
        return Ok(SearchResultFacets {
            query: SearchQuery::default(),
            facet_field: column,
            facet_values: Vec::new(),
            partial: false,
        });
    };
    if map_string_terms.is_some() {
        return search_mva_facet(user, query, column, map_string_terms, restrict_to_ids).await;
    }
    // Remove this column's own selection, so an unticked value still has a count to tick
    // with. It is done by mutating the query because there is nowhere else to do it:
    // Manticore's per-facet `EXCLUDE FILTERS` clause is not in this server's SQL grammar
    // (`P01: syntax error … near 'EXCLUDE FILTERS'`), in any position a `FACET` clause
    // accepts.
    //
    // NOTE: this also drops the `collection_dataset` filter sanitize_query injected for
    // permissions. That is safe ONLY because permissions are collection-granular
    // (collection_group_permissions grants a whole collection, so a permitted
    // collection implies all its datasets). If dataset-level permissions are ever
    // added, this line becomes a data leak.
    let mut query = query;
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
            let column = search_field_name(&column)?;
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

/// Buckets for one multi-value column.
///
/// A separate path from the `FACET` clause because the values are term ids and the
/// display strings live in ClickHouse: the ids come back here and are resolved
/// afterwards, in one query per collection rather than one per bucket.
///
/// `restrict_to_ids` is what makes a facet search box exact. The needle is resolved to
/// term ids first (`search_entity_terms`), the ids narrow the query, and the returned
/// buckets are intersected with the same set. The counts stay true document counts: a
/// document holding term X satisfies `ANY(column) IN (ids)` by holding X, so bucket X's
/// count is unchanged by the restriction.
pub async fn search_mva_facet(
    user: &CurrentUser,
    query: SearchQuery,
    column: String,
    map_string_terms: Option<String>,
    restrict_to_ids: Option<Vec<u64>>,
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
    // remove all filters on current column, as we don't want to filter out unselected
    // values from the facet. Same mechanism and same caveat as the `FACET` path above:
    // Manticore's per-facet filter-exclusion clause is not in this server's grammar, so
    // the mutation is the only way. Safe only while permissions are collection-granular:
    // it also drops the `collection_dataset` filter sanitisation injected, and that is
    // harmless exactly because a permitted collection implies all of its datasets.
    query.facet_filters.remove(&column);

    // An empty restriction is a needle that matched nothing, and it must return no
    // buckets. Treating it as "no restriction" would answer a failed search with the
    // whole facet, which reads as the search box being ignored.
    let restriction: Option<Vec<u64>> = restrict_to_ids;
    if restriction.as_ref().is_some_and(|ids| ids.is_empty()) {
        return Ok(SearchResultFacets {
            query,
            facet_field: column,
            facet_values: Vec::new(),
            partial: false,
        });
    }

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

    // Every id is a `hash_string_to_uint63`, so the list is digits only and cannot carry
    // anything into the SQL text. Built once rather than per shard.
    let restrict_clause = restriction.as_ref().map(|ids| {
        let list = ids.iter().map(|id| id.to_string()).collect::<Vec<_>>().join(", ");
        format!("AND ANY({{column}}) IN ({list})")
    });
    let outcome = fanout::fan_out(targets, |target: FanoutTarget| {
        let query = query.clone();
        let column = column.clone();
        let restrict_clause = restrict_clause.clone();
        async move {
            let parts = fanout::shard_query_parts(&target, &query).await?;
            let from_clause = &parts.from_clause;
            let sql_where_clause = &parts.where_clause;
            let column = search_field_name(&column)?;
            let restrict_clause = restrict_clause
                .as_deref()
                .map(|clause| clause.replace("{column}", column))
                .unwrap_or_default();
            let options_clause = sql_options_clause(1000);
            let sql = format!(
                "
                SELECT groupby() term, count(distinct file_hash) as doc_count
                {from_clause}
                {sql_where_clause}
                {restrict_clause}

                GROUP BY {column}
                ORDER BY doc_count DESC LIMIT {bucket_limit}
                {options_clause}
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

    // `ANY(column) IN (ids)` selects DOCUMENTS, and a selected document brings its other
    // terms' buckets with it. Intersecting here is what makes the pane list only what
    // the needle matched.
    if let Some(ids) = &restriction {
        result.facet_values = retain_restricted_buckets(
            std::mem::take(&mut result.facet_values),
            ids,
        );
    }

    if let Some(map_string_terms) = map_string_terms {
        let is_entity_facet = map_string_terms == ENTITY_TERM_FIELD;
        map_term_display_strings(user, &mut result.facet_values, map_string_terms).await?;
        if is_entity_facet {
            // Header names, encoding fragments and letter-spaced PDF headings. The
            // pipeline stops these before they are stored, so this only has work to do on
            // rows the NLP stage wrote without that rule — but on a mail corpus those
            // outrank every real entity, which is the whole facet.
            result
                .facet_values
                .retain(|item| !is_stopped_entity(&item.display_string));
        }
    }
    result
        .facet_values
        .sort_by_key(|item| (u64::MAX - item.count, item.display_string.clone()));

    Ok(result)
}

/// Keep only the buckets whose key is in the restriction set.
///
/// The keys arrive as JSON numbers because that is what Manticore returns for a term id;
/// a bucket whose key is not a number cannot be a term id and is dropped, rather than
/// kept on the theory that it might be something else.
fn retain_restricted_buckets(
    values: Vec<SearchResultFacetItem>,
    ids: &[u64],
) -> Vec<SearchResultFacetItem> {
    let wanted: HashSet<u64> = ids.iter().copied().collect();
    values
        .into_iter()
        .filter(|item| match item.original_value {
            FacetOriginalValue::Int(id) => wanted.contains(&id),
            FacetOriginalValue::String(_) => false,
        })
        .collect()
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

#[cfg(test)]
mod tests {
    use super::*;
    use common::search_query::SearchQuery;

    fn facets(values: &[(&str, u64)]) -> SearchResultFacets {
        SearchResultFacets {
            query: SearchQuery::default(),
            facet_field: "collection_dataset".to_string(),
            facet_values: values
                .iter()
                .map(|(value, count)| SearchResultFacetItem {
                    display_string: value.to_string(),
                    original_value: FacetOriginalValue::String(value.to_string()),
                    count: *count,
                })
                .collect(),
            partial: false,
        }
    }

    fn offered(facets: &SearchResultFacets) -> Vec<(String, u64)> {
        facets
            .facet_values
            .iter()
            .map(|item| match &item.original_value {
                FacetOriginalValue::String(value) => (value.clone(), item.count),
                other => (format!("{other:?}"), item.count),
            })
            .collect()
    }

    /// D3: `epstein_epstein` is still in the index with a count of 2 888, and is not a
    /// dataset. Offering it hands the user a filter that returns nothing.
    #[test]
    fn a_facet_value_that_is_not_a_registered_dataset_is_not_offered() {
        let registered: BTreeSet<String> = ["epstein_docs".to_string()].into_iter().collect();
        let result = reconcile_dataset_facets(
            facets(&[("epstein_docs", 2888), ("epstein_epstein", 2888)]),
            &registered,
        );
        assert_eq!(offered(&result), vec![("epstein_docs".to_string(), 2888)]);
    }

    #[test]
    fn a_registered_dataset_with_no_bucket_is_offered_at_zero() {
        let registered: BTreeSet<String> = ["a_one".to_string(), "a_two".to_string()]
            .into_iter()
            .collect();
        let result = reconcile_dataset_facets(facets(&[("a_one", 5)]), &registered);
        assert_eq!(
            offered(&result),
            vec![("a_one".to_string(), 5), ("a_two".to_string(), 0)]
        );
    }

    /// The permission set is the same list, so a dataset the user may not read is not
    /// registered as far as this function is concerned — and must not be advertised by
    /// a facet either.
    #[test]
    fn an_unreadable_dataset_is_dropped_like_a_ghost_one() {
        let registered: BTreeSet<String> = ["ok_one".to_string()].into_iter().collect();
        let result = reconcile_dataset_facets(
            facets(&[("ok_one", 3), ("secret_two", 99)]),
            &registered,
        );
        assert_eq!(offered(&result), vec![("ok_one".to_string(), 3)]);
    }

    #[test]
    fn nothing_registered_means_nothing_offered() {
        let result = reconcile_dataset_facets(facets(&[("gone_one", 7)]), &BTreeSet::new());
        assert!(result.facet_values.is_empty());
    }
}
