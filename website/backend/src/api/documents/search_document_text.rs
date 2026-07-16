//! Endpoint for retrieving document text snippets.

use common::{
    current_user::CurrentUser,
    document_sources::{DocumentTextSourceHit, DocumentTextSourceHitCount},
    search_result::DocumentIdentifier,
};
use serde::{Deserialize, Serialize};

use crate::auth::permissions;
use crate::{api::search::search_sql::SQL_OPTIONS_CLAUSE, db_utils::clickhouse_utils::get_clickhouse_client};
use crate::db_utils::{
    decompose_spans::decompose_text_into_spans, manticore_utils::manticore_search_sql,
};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
struct DocumentHits {
    extracted_by: String,
    page_id: u32,
    text: String,
}

pub async fn search_document_text_for_hits(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
    find_query: String,
    extracted_by: String,
    page_id: u32,
) -> anyhow::Result<Vec<DocumentTextSourceHit>> {
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    let sql = format!(
        r#"
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
    let result = hits
        .into_iter()
        .map(|hit| DocumentTextSourceHit {
            extracted_by: hit._source.extracted_by,
            page_id: hit._source.page_id,
            highlight_text_spans: decompose_text_into_spans(hit._source.text),
        })
        .collect::<Vec<_>>();

    Ok(result)
}

pub async fn search_document_text_for_hit_count(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
    find_query: String,
) -> anyhow::Result<Vec<DocumentTextSourceHitCount>> {
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    let sql = format!(
        r#"
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
    let result = hits
        .into_iter()
        .map(|hit| DocumentTextSourceHit {
            extracted_by: hit._source.extracted_by,
            page_id: hit._source.page_id,
            highlight_text_spans: decompose_text_into_spans(hit._source.text),
        })
        .collect::<Vec<_>>();

    let result = result
        .into_iter()
        .map(|hits| {
            let hit_count = hits
                .highlight_text_spans
                .iter()
                .filter(|h| h.is_highlighted)
                .count();

            DocumentTextSourceHitCount {
                extracted_by: hits.extracted_by,
                page_id: hits.page_id,
                hit_count: hit_count as u64,
            }
        })
        .collect::<Vec<_>>();

    let mut dedup = vec![];
    let mut seen = std::collections::BTreeSet::new();

    for r in result.into_iter().rev() {
        if seen.insert((r.extracted_by.clone(), r.page_id)) {
            dedup.push(r.clone());
        }
    }
    Ok(dedup)
}


pub async fn get_document_text_by_id_and_source(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
    extracted_by: String,
    page_id: u32,
) -> anyhow::Result<String> {
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    let client = get_clickhouse_client();

    let query = "
    SELECT text from text_content
    WHERE collection_dataset = ?
    AND file_hash = ?
    AND extracted_by = ?
    AND page_id = ?   
    LIMIT 1 
    ";
    let query = client.query(query)
    .bind(&document_identifier.collection_dataset)
    .bind(&document_identifier.file_hash)
    .bind(&extracted_by)
    .bind(page_id);

    let rows = query.fetch_all::<String>().await?;

    if let Some(row) = rows.into_iter().next() {
        Ok(row)
    }  else {
        anyhow::bail!("document not found!")
    }
}