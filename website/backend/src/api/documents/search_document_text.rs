//! Endpoint for retrieving document text snippets.

use common::{document_text_sources::{DocumentTextSourceHit, DocumentTextSourceHitCount}, search_result::DocumentIdentifier};
use serde::{Deserialize, Serialize};

use crate::db_utils::{decompose_spans::decompose_text_into_spans, manticore_utils::manticore_search_sql};
use crate::api::search::search_sql::SQL_OPTIONS_CLAUSE;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
struct DocumentHits {
    extracted_by: String,
    page_id: u32,
    text: String,
}

pub async fn search_document_text_for_hits(
    document_identifier: DocumentIdentifier,
    find_query: String,
    extracted_by: String,
    page_id: u32,
) -> anyhow::Result<Vec<DocumentTextSourceHit>>
{
    let sql = format!(r#"
            SELECT
                extracted_by,
                page_id,
                highlight({{
                    limit=0,
                    force_all_words=1,
                    html_strip_mode=retain,
                    around=0,
                    before_match='<hoover4_strong>',
                    after_match='</hoover4_strong>',
                    force_snippets=1
                }}) as text
            FROM doc_text_pages
            WHERE file_hash = {} AND collection_dataset = {} AND extracted_by = {} AND page_id = {}
            AND MATCH({})
            LIMIT 1000
            {SQL_OPTIONS_CLAUSE}
        "#,
        format_sql_query::QuotedData(&document_identifier.file_hash),
        format_sql_query::QuotedData(&document_identifier.collection_dataset),
        format_sql_query::QuotedData(&extracted_by),
        page_id,
        format_sql_query::QuotedData(&find_query),
    );
    let response = manticore_search_sql::<DocumentHits>(sql).await?;
    let hits = response.hits.hits;
    let result = hits.into_iter().map(|hit| DocumentTextSourceHit {
        extracted_by: hit._source.extracted_by,
        page_id: hit._source.page_id,
        highlight_text_spans: decompose_text_into_spans(hit._source.text),
    }).collect::<Vec<_>>();

    Ok(result)
}

pub async fn search_document_text_for_hit_count(
    document_identifier: DocumentIdentifier,
    find_query: String
) -> anyhow::Result<Vec<DocumentTextSourceHitCount>> {

    let sql = format!(r#"
        SELECT
            extracted_by,
            page_id,
            highlight({{
                limit=0,
                force_all_words=1,
                html_strip_mode=retain,
                around=0,
                before_match='<hoover4_strong>',
                after_match='</hoover4_strong>',
                force_snippets=1
            }}) as text
        FROM doc_text_pages
        WHERE file_hash = {} AND collection_dataset = {}
        AND MATCH({})
        LIMIT 1000
        {SQL_OPTIONS_CLAUSE}
    "#,
    format_sql_query::QuotedData(&document_identifier.file_hash),
    format_sql_query::QuotedData(&document_identifier.collection_dataset),
    format_sql_query::QuotedData(&find_query),
    );
    let response = manticore_search_sql::<DocumentHits>(sql).await?;
    let hits = response.hits.hits;
    let result = hits.into_iter().map(|hit| DocumentTextSourceHit {
        extracted_by: hit._source.extracted_by,
        page_id: hit._source.page_id,
        highlight_text_spans: decompose_text_into_spans(hit._source.text),
    }).collect::<Vec<_>>();

    let result = result.into_iter().map(|hits| {
        let hit_count = hits.highlight_text_spans.iter().filter(|h| h.is_highlighted).count();

        DocumentTextSourceHitCount {
            extracted_by: hits.extracted_by,
            page_id: hits.page_id,
            hit_count: hit_count as u64,
        }
    }).collect::<Vec<_>>();
    Ok(result)
}

