//! Counts per file-size bucket.
//!
//! Fans out per shard and merges exactly like the string facets, and respects the
//! partial-shard flag. A separate endpoint from `search_string_facet` because the bucket
//! keys are computed by Manticore rather than stored: buckets are a *presentation*
//! choice, and pre-baking them into the index would make adding one a schema change plus
//! a full re-index. The date equivalent is `date_histogram.rs`, which has to measure its
//! domain before it can pick its bins and so is a different shape entirely.

use crate::api::search::fanout::{self, FanoutTarget};
use crate::api::search::search_sql::sql_options_clause;
use crate::auth::permissions;
use crate::db_utils::manticore_utils::manticore_search_sql;
use common::{
    current_user::CurrentUser,
    search_query::SearchQuery,
    search_result::{FacetOriginalValue, SearchResultFacetItem, SearchResultFacets},
};
use serde::{Deserialize, Serialize};

/// Bucket edges in bytes: `<1 MB`, `1–10 MB`, `10–100 MB`, `>100 MB`.
///
/// `INTERVAL(x, a, b, c)` returns 0 for `x < a`, 1 for `a <= x < b`, and so on, so N
/// edges give N+1 buckets. The labels live next to the edges because they have to agree
/// exactly — a mislabelled bucket is a filter that returns the wrong documents and
/// looks right.
pub const SIZE_BUCKET_EDGES: [i64; 3] = [1_048_576, 10_485_760, 104_857_600];
pub const SIZE_BUCKET_LABELS: [&str; 4] = [
    "under 1 MB",
    "1 – 10 MB",
    "10 – 100 MB",
    "over 100 MB",
];

/// The `[min, max]` byte range one bucket index means, for turning a checkbox back into
/// a `RangeFilter`. The last bucket is open-ended.
pub fn size_bucket_range(bucket: usize) -> (Option<i64>, Option<i64>) {
    match bucket {
        0 => (Some(0), Some(SIZE_BUCKET_EDGES[0] - 1)),
        1 => (Some(SIZE_BUCKET_EDGES[0]), Some(SIZE_BUCKET_EDGES[1] - 1)),
        2 => (Some(SIZE_BUCKET_EDGES[1]), Some(SIZE_BUCKET_EDGES[2] - 1)),
        _ => (Some(SIZE_BUCKET_EDGES[2]), None),
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
struct BucketRow {
    bucket: i64,
    doc_count: u64,
}

fn empty(query: SearchQuery, field: &str) -> SearchResultFacets {
    SearchResultFacets {
        query,
        facet_field: field.to_string(),
        facet_values: Vec::new(),
        partial: false,
    }
}

/// Document counts per file-size bucket.
///
/// The `file_size_bytes >= 0` guard is load-bearing: a document with no `vfs_files` row
/// carries `SIZE_UNKNOWN` (-1), and `INTERVAL()` would put it in bucket 0 next to the
/// genuinely tiny files.
pub async fn search_numeric_facet(
    user: &CurrentUser,
    query: SearchQuery,
) -> anyhow::Result<SearchResultFacets> {
    crate::api::telemetry::record_event(&user.username, crate::api::telemetry::EVENT_USER_SEARCH, "");
    let perms = permissions::resolve_permissions(user).await?;
    let Some(mut query) = permissions::sanitize_query(query, &perms) else {
        return Ok(empty(SearchQuery::default(), "file_size_bytes"));
    };
    // Same rule as the string facets: a facet must not filter itself out, or every
    // unselected bucket reads 0 the moment one is ticked.
    query.range_filters.remove("file_size_bytes");

    let collections = fanout::permitted_search_collections(user, &query).await?;
    let targets = fanout::shard_targets(&collections).await;
    let mut result = empty(query.clone(), "file_size_bytes");
    if targets.is_empty() {
        return Ok(result);
    }
    let edges = SIZE_BUCKET_EDGES
        .iter()
        .map(|e| e.to_string())
        .collect::<Vec<_>>()
        .join(",");

    let outcome = fanout::fan_out(targets, |target: FanoutTarget| {
        let query = query.clone();
        let edges = edges.clone();
        async move {
            let parts = fanout::shard_query_parts(&target, &query).await?;
            let from_clause = &parts.from_clause;
            let where_clause = &parts.where_clause;
            let options_clause = sql_options_clause(1000);
            let sql = format!(
                "
                SELECT INTERVAL(file_size_bytes, {edges}) AS bucket,
                       count(distinct file_hash) AS doc_count
                {from_clause}
                {where_clause}
                AND file_size_bytes >= 0
                GROUP BY bucket
                ORDER BY bucket ASC
                LIMIT 16
                {options_clause}
                ;"
            );
            manticore_search_sql::<BucketRow>(sql, &parts.salt).await
        }
    })
    .await?;
    result.partial = outcome.is_partial();

    let mut totals = [0_u64; SIZE_BUCKET_LABELS.len()];
    for (_, response) in outcome.results {
        for hit in response.hits.hits {
            if let Ok(index) = usize::try_from(hit._source.bucket)
                && index < totals.len()
            {
                totals[index] += hit._source.doc_count;
            }
        }
    }
    // Every bucket is emitted, including the empty ones: a checkbox that vanishes when
    // its count is 0 makes the filter list jump around as the query changes.
    result.facet_values = totals
        .iter()
        .enumerate()
        .map(|(index, count)| SearchResultFacetItem {
            display_string: SIZE_BUCKET_LABELS[index].to_string(),
            original_value: FacetOriginalValue::Int(index as u64),
            count: *count,
        })
        .collect();
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn size_buckets_tile_the_range_without_gaps_or_overlap() {
        let mut previous_max = -1_i64;
        for bucket in 0..SIZE_BUCKET_LABELS.len() {
            let (min, max) = size_bucket_range(bucket);
            assert_eq!(min.unwrap(), previous_max + 1, "gap or overlap before bucket {bucket}");
            match max {
                Some(m) => previous_max = m,
                None => assert_eq!(bucket, SIZE_BUCKET_LABELS.len() - 1, "only the last bucket is open"),
            }
        }
    }

    #[test]
    fn size_bucket_edges_match_interval_semantics() {
        // INTERVAL(x, a, b, c) is 0 for x < a. The bucket-0 range must end one byte
        // below the first edge or a 1 MB file lands in two buckets.
        assert_eq!(size_bucket_range(0).1.unwrap(), SIZE_BUCKET_EDGES[0] - 1);
        assert_eq!(size_bucket_range(1).0.unwrap(), SIZE_BUCKET_EDGES[0]);
        assert_eq!(size_bucket_range(3), (Some(SIZE_BUCKET_EDGES[2]), None));
    }



}
