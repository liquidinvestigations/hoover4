//! Search endpoint for result lists.
//!
//! Fans out over every shard of every permitted collection (see `fanout.rs`),
//! merges the per-shard hits by score, and assembles the requested page from the
//! merged list. Deep pagination requires over-fetching `offset + limit` rows from
//! every shard; the merge then slices the global window.

use crate::api::search::fanout::{self, FanoutTarget, HitIdentity, ShardQueryParts};
use crate::api::search::search_sql::sql_options_clause;
use crate::db_utils::{
    decompose_spans::decompose_text_into_spans, manticore_utils::manticore_search_sql,
};
use common::{
    current_user::CurrentUser,
    search_query::SearchQuery,
    search_result::{DocumentIdentifier, SearchResultDocumentItem, SearchResultDocuments},
};

use crate::auth::permissions;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
struct SearchForResultsResponse {
    collection_dataset: String,
    file_hash: String,
    page_ids: String,
    filenames: String,

    highlight_text: String,
    highlight_filenames: String,

    file_types: Vec<u64>,
}

impl HitIdentity for SearchForResultsResponse {
    fn collection_dataset(&self) -> &str {
        &self.collection_dataset
    }
    fn file_hash(&self) -> &str {
        &self.file_hash
    }
}

/// Build the per-shard results query. Fetches `fetch_limit` rows from offset 0 —
/// never the page's global offset — because the global page is assembled from all
/// shards by the merge.
///
/// The `ORDER BY` is load-bearing: Manticore's order among equal-weight rows is not
/// stable across queries with different `LIMIT`/`max_matches`, and `fetch_limit`
/// grows with the requested page. Without a total order a document tied at the
/// truncation boundary can appear on two pages or on none. The key order must match
/// the merge's tie-break in `fanout::merge_hits` exactly (score, then
/// `(collection_dataset, file_hash)`), so the truncated per-shard result is a stable
/// prefix of the merged order.
fn build_results_sql(parts: &ShardQueryParts, fetch_limit: u64) -> String {
    let options_clause = sql_options_clause(fetch_limit);
    let from_clause = &parts.from_clause;
    let sql_where_clause = &parts.where_clause;
    let meta_table = &parts.meta_table;
    format!(
        "
    SELECT collection_dataset,
        file_hash,
        group_concat(page_id) AS page_ids,
        {meta_table}.filenames as filenames,

        HIGHLIGHT({{
            limit=400,
            limit_words=100,
            limit_snippets=1,
            html_strip_mode=strip,
            before_match='<hoover4_strong>',
            after_match='</hoover4_strong>',
            around=50
        }}, page_text) as highlight_text,
        HIGHLIGHT({{
            limit=400,
            limit_words=100,
            limit_snippets=1,
            html_strip_mode=strip,
            before_match='<hoover4_strong>',
            after_match='</hoover4_strong>',
            around=50
        }}, filenames) as highlight_filenames,

        {meta_table}.file_types as file_types

    {from_clause}

    {sql_where_clause}

    GROUP BY file_hash
    ORDER BY weight() DESC, collection_dataset ASC, file_hash ASC
    LIMIT {fetch_limit} OFFSET 0

    {options_clause}
    ;"
    )
}

pub async fn search_for_results(
    user: &CurrentUser,
    query: SearchQuery,
    current_search_result_page: u64,
) -> anyhow::Result<SearchResultDocuments> {
    crate::api::telemetry::record_event(&user.username, crate::api::telemetry::EVENT_USER_SEARCH, "");
    let perms = permissions::resolve_permissions(user).await?;
    let Some(query) = permissions::sanitize_query(query, &perms) else {
        return Ok(SearchResultDocuments {
            query: SearchQuery::default(),
            results: vec![],
            prev_hash: None,
            next_hash: None,
            page_number: current_search_result_page,
            partial: false,
        });
    };

    // Window on the MERGED list: page N needs one extra row before it (prev_hash)
    // and one extra row after it (next_hash).
    let page_size = common::search_const::PAGE_SIZE;
    let (merge_offset, merge_limit) = if current_search_result_page > 0 {
        ((current_search_result_page * page_size - 1) as usize, (page_size + 2) as usize)
    } else {
        (0_usize, (page_size + 1) as usize)
    };
    // Every shard must return enough rows for the merge to see the whole window.
    let fetch_limit = (merge_offset + merge_limit) as u64;

    let collections = fanout::permitted_search_collections(user, &query).await?;
    let targets = fanout::shard_targets(&collections).await;
    if targets.is_empty() {
        return Ok(SearchResultDocuments {
            query,
            results: vec![],
            prev_hash: None,
            next_hash: None,
            page_number: current_search_result_page,
            partial: false,
        });
    }

    let outcome = fanout::fan_out(targets, |target: FanoutTarget| {
        let query = query.clone();
        async move {
            let parts = fanout::shard_query_parts(&target, &query).await?;
            let sql = build_results_sql(&parts, fetch_limit);
            manticore_search_sql::<SearchForResultsResponse>(sql, &parts.salt).await
        }
    })
    .await?;
    let partial = outcome.is_partial();

    let merged = fanout::merge_hits(outcome.results, merge_offset, merge_limit);

    let mut search_results = merged
        .into_iter()
        .map(|hit| {
            // title: the first plain filename. highlight_filenames_spans: the first
            // highlighted filename line (it carries <hoover4_strong> markers), or
            // the plain title when the query matched nothing in the filenames.
            let title = hit
                ._source
                .filenames
                .split("\n")
                .next()
                .unwrap_or("")
                .to_string();
            let highlighted_filename = hit
                ._source
                .highlight_filenames
                .split("\n")
                .find(|line| line.contains("<hoover4_strong>"))
                .map(|line| line.to_string())
                .unwrap_or_else(|| title.clone());

            SearchResultDocumentItem {
                collection_dataset: hit._source.collection_dataset,
                file_hash: hit._source.file_hash,
                title: title.clone(),
                highlight_text_spans: decompose_text_into_spans(hit._source.highlight_text),
                highlight_filenames_spans: decompose_text_into_spans(highlighted_filename),
                result_index_in_page: 0_u64,
            }
        })
        .collect::<Vec<_>>();

    // Cursor logic operates on the merged, sliced list: the first row of a non-zero
    // page is the prev-page cursor and is dropped; a row beyond PAGE_SIZE is the
    // next-page cursor and is dropped.
    let mut prev_hash = None;
    if current_search_result_page > 0 && !search_results.is_empty() {
        prev_hash = Some(DocumentIdentifier {
            collection_dataset: search_results[0].collection_dataset.clone(),
            file_hash: search_results[0].file_hash.clone(),
        });
        search_results.remove(0);
    }

    let mut next_hash = None;
    if search_results.len() > common::search_const::PAGE_SIZE as usize {
        next_hash = Some(DocumentIdentifier {
            collection_dataset: search_results[common::search_const::PAGE_SIZE as usize]
                .collection_dataset
                .clone(),
            file_hash: search_results[common::search_const::PAGE_SIZE as usize]
                .file_hash
                .clone(),
        });
        search_results.remove(common::search_const::PAGE_SIZE as usize);
    }

    for (i, result) in search_results.iter_mut().enumerate() {
        result.result_index_in_page = i as u64;
    }

    let result = SearchResultDocuments {
        query: query.clone(),
        results: search_results,
        prev_hash,
        next_hash,
        page_number: current_search_result_page,
        partial,
    };
    Ok(result)
}


#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::{BTreeMap, BTreeSet};

    fn parts_for(query_string: &str, filters: &[(&str, &[common::search_result::FacetOriginalValue])]) -> ShardQueryParts {
        let mut facet_filters = BTreeMap::new();
        for (field, values) in filters {
            facet_filters.insert(
                field.to_string(),
                values.iter().cloned().collect::<BTreeSet<_>>(),
            );
        }
        let query = SearchQuery {
            collection_datasets: vec![],
            query_string: query_string.to_string(),
            facet_filters,
        };
        let (pages_table, meta_table) =
            crate::api::search::search_sql::shard_table_names("testdata_1").unwrap();
        ShardQueryParts {
            shard_name: "testdata_1".to_string(),
            from_clause: crate::api::search::search_sql::sql_from_clause("testdata_1").unwrap(),
            where_clause: crate::api::search::search_sql::build_sql_where_clause(
                &query,
                &pages_table,
                &meta_table,
            )
            .unwrap(),
            pages_table,
            meta_table,
            salt: "testdata@1-2026".to_string(),
        }
    }

    fn normalize(sql: &str) -> String {
        sql.split_whitespace().collect::<Vec<_>>().join(" ")
    }

    /// Golden string for the full per-shard results query — the largest interpolated
    /// SQL string in the repo. In particular this locks the `ORDER BY` that makes
    /// pagination a stable prefix (B3): removing it must fail loudly here.
    #[test]
    fn build_results_sql_golden() {
        let sql = build_results_sql(&parts_for("easychair", &[]), 21);
        let expected = "
            SELECT collection_dataset,
                file_hash,
                group_concat(page_id) AS page_ids,
                testdata_1_meta.filenames as filenames,
                HIGHLIGHT({ limit=400, limit_words=100, limit_snippets=1, html_strip_mode=strip,
                    before_match='<hoover4_strong>', after_match='</hoover4_strong>', around=50 },
                    page_text) as highlight_text,
                HIGHLIGHT({ limit=400, limit_words=100, limit_snippets=1, html_strip_mode=strip,
                    before_match='<hoover4_strong>', after_match='</hoover4_strong>', around=50 },
                    filenames) as highlight_filenames,
                testdata_1_meta.file_types as file_types
            FROM testdata_1_pages
            LEFT JOIN testdata_1_meta
            ON testdata_1_pages.collection_dataset = testdata_1_meta.collection_dataset
            AND testdata_1_pages.file_hash = testdata_1_meta.file_hash
            WHERE MATCH('easychair', testdata_1_pages)
            GROUP BY file_hash
            ORDER BY weight() DESC, collection_dataset ASC, file_hash ASC
            LIMIT 21 OFFSET 0
            OPTION agent_query_timeout=60000,max_query_time=60000,max_matches=21
            ;
        ";
        assert_eq!(normalize(&sql), normalize(expected));
    }

    #[test]
    fn build_results_sql_includes_facet_filters_in_where() {
        let parts = parts_for(
            "word",
            &[(
                "collection_dataset",
                &[common::search_result::FacetOriginalValue::String(
                    "testdata_testfiles".to_string(),
                )],
            )],
        );
        let sql = normalize(&build_results_sql(&parts, 1));
        assert!(sql.contains("AND collection_dataset IN ('testdata_testfiles')"), "{sql}");
        assert!(sql.contains("ORDER BY weight() DESC, collection_dataset ASC, file_hash ASC"), "{sql}");
    }
}
