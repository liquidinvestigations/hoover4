//! Search endpoint for result lists.

use common::{
    search_query::SearchQuery,
    search_result::{DocumentIdentifier, SearchResultDocumentItem, SearchResultDocuments},
};
use serde::{Deserialize, Serialize};
use crate::api::search::search_sql::{SQL_FROM_CLAUSE, build_sql_where_clause, SQL_OPTIONS_CLAUSE};
use crate::{db_utils::{decompose_spans::decompose_text_into_spans, manticore_utils::manticore_search_sql}};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
struct SearchForResultsResponse {
    collection_dataset: String,
    file_hash: String,
    page_ids: String,
    filenames: String,

    highlight_text: String,
    highlight_filenames: String,

    file_types: Vec<u64>,
    // file_mime_types: Vec<u64>,
    // file_extensions: Vec<u64>,
    // file_paths: Vec<u64>,
}

pub async fn search_for_results(query: SearchQuery, current_search_result_page: u64) -> anyhow::Result<SearchResultDocuments> {
    let sql_where_clause = build_sql_where_clause(&query);
    let mut offset = current_search_result_page * common::search_const::PAGE_SIZE;
    let mut limit = common::search_const::PAGE_SIZE + 1;
    let mut drop_first = false;
    if current_search_result_page > 0 {
        drop_first = true;
        offset -= 1;
        limit += 1;
    }

    // tokio::time::sleep(std::time::Duration::from_secs(1)).await;



    let sql = format!(
        "
    SELECT collection_dataset,
        file_hash,
        group_concat(page_id) AS page_ids,
        doc_metadata.filenames as filenames,

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

        doc_metadata.file_types as file_types

    {SQL_FROM_CLAUSE}

    {sql_where_clause}

    GROUP BY file_hash
    LIMIT {limit} OFFSET {offset}

    {SQL_OPTIONS_CLAUSE}
    ;",
    /*
    ,
        doc_metadata.file_mime_types as file_mime_types,
        doc_metadata.file_extensions as file_extensions,
        doc_metadata.file_paths as file_pathsr
     */
        /* FACET collection_dataset
           FACET file_types
           FACET file_mime_types
           FACET file_extensions
           FACET file_paths
        */
    );
    let response = manticore_search_sql::<SearchForResultsResponse>(sql).await?;

    let mut search_results = response
        .hits
        .hits
        .into_iter().enumerate()
        .map(|(hit_index_in_page, hit)| {

            let filenames = hit._source.filenames.split("\n").map(|i| i.to_string()).collect::<Vec<_>>();
            let mut title =hit
            ._source
            .filenames
            .split("\n")
            .next()
            .unwrap_or("")
            .to_string();

            if !hit._source.filenames.is_empty() {
                for x in filenames {
                    if x.contains("<strong>") {
                        title = x.clone();
                    }
                }
            }

            SearchResultDocumentItem {
            collection_dataset: hit._source.collection_dataset,
            file_hash: hit._source.file_hash,
            title: hit
                ._source
                .filenames
                .split("\n")
                .next()
                .unwrap_or("")
                .to_string(),
            highlight_text_spans: decompose_text_into_spans(hit._source.highlight_text),
            highlight_filenames_spans: decompose_text_into_spans(title.clone()),
            result_index_in_page: 0_u64,
        }})
        .collect::<Vec<_>>();

    let mut prev_hash = None;
    if drop_first {
        prev_hash = Some(DocumentIdentifier {
            collection_dataset: search_results[0].collection_dataset.clone(),
            file_hash: search_results[0].file_hash.clone(),
        });
        search_results.remove(0);
    }

    let mut next_hash = None;
    if search_results.len() > common::search_const::PAGE_SIZE as usize {
        next_hash = Some(DocumentIdentifier {
            collection_dataset: search_results[common::search_const::PAGE_SIZE as usize].collection_dataset.clone(),
            file_hash: search_results[common::search_const::PAGE_SIZE as usize].file_hash.clone(),
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
    };
    Ok(result)
}
