//! Search endpoint for result lists.
//!
//! Fans out over every shard of every permitted collection (see `fanout.rs`),
//! merges the per-shard hits by score, and assembles the requested page from the
//! merged list. Deep pagination requires over-fetching `offset + limit` rows from
//! every shard; the merge then slices the global window.

use crate::api::search::fanout::{self, FanoutTarget, HitIdentity, ShardQueryParts, SortValue};
use crate::api::search::search_sql::{EXCLUDE_FILENAME_ROW, sql_options_clause, sort_order_by};
use crate::db_utils::{
    decompose_spans::decompose_text_into_spans, manticore_utils::manticore_search_sql,
};
use common::{
    current_user::CurrentUser,
    search_query::{SearchQuery, SortKey, SortSpec},
    search_result::{DocumentIdentifier, SearchResultDocumentItem, SearchResultDocuments},
};

use crate::auth::permissions;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
struct SearchForResultsResponse {
    collection_dataset: String,
    file_hash: String,
    /// The result-card title. A string ATTRIBUTE on meta since the `filenames` text
    /// field was dropped — see `database/manticore.py::meta_table_ddl`.
    primary_filename: String,

    highlight_text: String,

    file_types: Vec<u64>,

    // The active sort key's value, selected so the cross-shard merge can reproduce the
    // per-shard ORDER BY. Manticore always returns every selected column, so all three
    // are here rather than one conditional column: a SELECT list that changed shape
    // with the sort would need the response struct to change shape with it.
    date_min: i64,
    date_max: i64,
    file_size_bytes: i64,

    /// 1 when at least one row in this document's group came from something other than
    /// the synthetic filename row. Computed in the same grouped query — knowing it needs
    /// the group, and a second round trip per result to learn it is not worth a snippet.
    has_text_match: i64,
}

impl HitIdentity for SearchForResultsResponse {
    fn collection_dataset(&self) -> &str {
        &self.collection_dataset
    }
    fn file_hash(&self) -> &str {
        &self.file_hash
    }
    fn sort_value(&self, sort: SortSpec) -> Option<SortValue> {
        match sort.key {
            SortKey::Relevance => None,
            // Same split as `search_sql::sort_column`: newest-first compares the LATEST
            // date a document carries, oldest-first the earliest.
            SortKey::Date if sort.desc => Some(SortValue::Int(self.date_max)),
            SortKey::Date => Some(SortValue::Int(self.date_min)),
            SortKey::FileSize => Some(SortValue::Int(self.file_size_bytes)),
            SortKey::Name => Some(SortValue::Text(self.primary_filename.clone())),
        }
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
fn build_results_sql(parts: &ShardQueryParts, sort: SortSpec, fetch_limit: u64) -> String {
    let options_clause = sql_options_clause(fetch_limit);
    let from_clause = &parts.from_clause;
    let sql_where_clause = &parts.where_clause;
    let meta_table = &parts.meta_table;
    let order_by = sort_order_by(&sort, meta_table);
    format!(
        "
    SELECT collection_dataset,
        file_hash,
        {meta_table}.primary_filename as primary_filename,

        HIGHLIGHT({{
            limit=400,
            limit_words=100,
            limit_snippets=1,
            html_strip_mode=strip,
            before_match='<hoover4_strong>',
            after_match='</hoover4_strong>',
            around=50
        }}, page_text) as highlight_text,

        {meta_table}.file_types as file_types,
        {meta_table}.date_min as date_min,
        {meta_table}.date_max as date_max,
        {meta_table}.file_size_bytes as file_size_bytes,

        MAX(IF({EXCLUDE_FILENAME_ROW}, 1, 0)) AS has_text_match

    {from_clause}

    {sql_where_clause}

    GROUP BY file_hash
    {order_by}
    LIMIT {fetch_limit} OFFSET 0

    {options_clause}
    ;"
    )
}

/// Highlight the query's terms inside the result title, client-side.
///
/// Route (b) of the two the plan allows. With `meta.filenames` gone the filename
/// highlight can no longer come from a `HIGHLIGHT()` over a meta text field, and the
/// alternative — a second `HIGHLIGHT` scoped to the `filename_index` pages row — needs a
/// per-result subquery for a decoration. Matching the query's whitespace-separated terms
/// against the title is simpler, has no extra round trip, and is honest about what it is:
/// a visual aid, not the thing that decided the document matched.
///
/// Case-insensitive substring matching, longest term first so `report` does not consume
/// the start of `reports` and leave a stray fragment.
fn highlight_title(title: &str, query_string: &str) -> String {
    let mut terms: Vec<String> = query_string
        .split_whitespace()
        .map(|t| t.trim_matches(|c: char| !c.is_alphanumeric() && c != '_').to_lowercase())
        .filter(|t| !t.is_empty())
        .collect();
    terms.sort_by_key(|t| std::cmp::Reverse(t.len()));
    terms.dedup();
    if terms.is_empty() {
        return title.to_string();
    }

    let lower = title.to_lowercase();
    // Mark every matched byte range, then emit once. Marking avoids the classic bug of
    // rewriting the string term by term and then matching the markers themselves.
    let mut marked = vec![false; title.len()];
    for term in &terms {
        let mut from = 0;
        while let Some(found) = lower[from..].find(term.as_str()) {
            let start = from + found;
            let end = start + term.len();
            for flag in marked.iter_mut().take(end).skip(start) {
                *flag = true;
            }
            from = end;
        }
    }

    let mut out = String::with_capacity(title.len() + 32);
    let mut inside = false;
    for (index, ch) in title.char_indices() {
        let hit = marked.get(index).copied().unwrap_or(false);
        if hit && !inside {
            out.push_str("<hoover4_strong>");
            inside = true;
        } else if !hit && inside {
            out.push_str("</hoover4_strong>");
            inside = false;
        }
        out.push(ch);
    }
    if inside {
        out.push_str("</hoover4_strong>");
    }
    out
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

    // Relevance is meaningless without something to be relevant to; the resolution is
    // done here as well as in the UI so a hand-written URL cannot ask for it.
    let sort = query.sort.resolved(&query.query_string);

    let outcome = fanout::fan_out(targets, |target: FanoutTarget| {
        let query = query.clone();
        async move {
            let parts = fanout::shard_query_parts(&target, &query).await?;
            let sql = build_results_sql(&parts, sort, fetch_limit);
            manticore_search_sql::<SearchForResultsResponse>(sql, &parts.salt).await
        }
    })
    .await?;
    let partial = outcome.is_partial();

    let merged = fanout::merge_hits_sorted(outcome.results, sort, merge_offset, merge_limit);

    let query_string = query.query_string.clone();
    let mut search_results = merged
        .into_iter()
        .map(|hit| {
            // The title is `primary_filename` — the lexicographically first basename of
            // the document, written by the indexer. The highlight is applied here rather
            // than by Manticore; see `highlight_title`.
            let title = hit._source.primary_filename.clone();
            let highlighted_filename = highlight_title(&title, &query_string);

            SearchResultDocumentItem {
                collection_dataset: hit._source.collection_dataset,
                file_hash: hit._source.file_hash,
                title: title.clone(),
                highlight_text_spans: decompose_text_into_spans(hit._source.highlight_text),
                highlight_filenames_spans: decompose_text_into_spans(highlighted_filename),
                result_index_in_page: 0_u64,
                matched_by_filename: hit._source.has_text_match == 0,
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
            query_string: query_string.to_string(),
            facet_filters,
            ..Default::default()
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

    fn relevance() -> SortSpec {
        SortSpec { key: SortKey::Relevance, desc: true }
    }

    /// Golden string for the full per-shard results query — the largest interpolated
    /// SQL string in the repo. In particular this locks the `ORDER BY` that makes
    /// pagination a stable prefix (B3): removing it must fail loudly here. It also
    /// locks the SELECT list, which the cross-shard merge depends on: the sort key must
    /// be selected or the merge has nothing to compare.
    #[test]
    fn build_results_sql_golden() {
        let sql = build_results_sql(&parts_for("easychair", &[]), relevance(), 21);
        let expected = "
            SELECT collection_dataset,
                file_hash,
                testdata_1_meta.primary_filename as primary_filename,
                HIGHLIGHT({ limit=400, limit_words=100, limit_snippets=1, html_strip_mode=strip,
                    before_match='<hoover4_strong>', after_match='</hoover4_strong>', around=50 },
                    page_text) as highlight_text,
                testdata_1_meta.file_types as file_types,
                testdata_1_meta.date_min as date_min,
                testdata_1_meta.date_max as date_max,
                testdata_1_meta.file_size_bytes as file_size_bytes,
                MAX(IF(extracted_by != 'filename_index', 1, 0)) AS has_text_match
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
        let sql = normalize(&build_results_sql(&parts, relevance(), 1));
        assert!(sql.contains("AND collection_dataset IN ('testdata_testfiles')"), "{sql}");
        assert!(sql.contains("ORDER BY weight() DESC, collection_dataset ASC, file_hash ASC"), "{sql}");
    }

    /// Every sort key must both order the query AND appear in the SELECT list. A key
    /// that is ordered but not selected produces per-shard pages the merge cannot
    /// reproduce, which shows up as documents appearing on two pages.
    #[test]
    fn every_sort_key_orders_and_selects_its_column() {
        for (sort, expected_order, expected_select) in [
            (SortSpec { key: SortKey::Date, desc: true },
             "ORDER BY testdata_1_meta.date_max DESC", "date_max as date_max"),
            (SortSpec { key: SortKey::Date, desc: false },
             "ORDER BY testdata_1_meta.date_min ASC", "date_min as date_min"),
            (SortSpec { key: SortKey::FileSize, desc: true },
             "ORDER BY testdata_1_meta.file_size_bytes DESC", "file_size_bytes as file_size_bytes"),
            (SortSpec { key: SortKey::Name, desc: false },
             "ORDER BY testdata_1_meta.primary_filename ASC", "primary_filename as primary_filename"),
        ] {
            let sql = normalize(&build_results_sql(&parts_for("word", &[]), sort, 5));
            assert!(sql.contains(expected_order), "{sort:?} -> {sql}");
            assert!(sql.contains(expected_select), "{sort:?} -> {sql}");
            assert!(sql.contains("collection_dataset ASC, file_hash ASC"),
                    "{sort:?} lost the stable tie-break: {sql}");
        }
    }

    #[test]
    fn highlight_title_marks_query_terms() {
        assert_eq!(
            highlight_title("EasyChair.docx", "easychair"),
            "<hoover4_strong>EasyChair</hoover4_strong>.docx"
        );
        // Two terms, one of them a prefix of the other: the longest wins and there is
        // no stray fragment left over.
        assert_eq!(
            highlight_title("annual_report_2024.pdf", "report reports"),
            "annual_<hoover4_strong>report</hoover4_strong>_2024.pdf"
        );
    }

    #[test]
    fn highlight_title_leaves_non_matches_alone() {
        assert_eq!(highlight_title("notes.txt", "easychair"), "notes.txt");
        assert_eq!(highlight_title("notes.txt", "   "), "notes.txt");
        assert_eq!(highlight_title("", "word"), "");
    }

    #[test]
    fn highlight_title_survives_multibyte_titles() {
        // Byte-indexed marking over a UTF-8 title: the char boundaries must line up or
        // this panics rather than merely looking wrong.
        assert_eq!(
            highlight_title("Räksmörgås-raport.pdf", "raport"),
            "Räksmörgås-<hoover4_strong>raport</hoover4_strong>.pdf"
        );
    }
}
