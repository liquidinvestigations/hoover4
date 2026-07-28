//! Endpoint for retrieving document text snippets.
//!
//! These queries search **within one document**, so they know the
//! `collection_dataset` up front: the owning collection is resolved via the global
//! dataset registry and the document's shard via that collection's
//! `manticore_shard_assignments` table. Only that one `<shard>_pages` table is
//! queried — no fan-out, and the results never cross collection boundaries.

use common::{
    current_user::CurrentUser,
    document_sources::{DocumentTextSourceHit, DocumentTextSourceHitCount},
    search_result::DocumentIdentifier,
};
use serde::{Deserialize, Serialize};

use crate::auth::permissions;
use crate::db_utils::clickhouse_utils::{
    find_shard_for_document, get_client_for_dataset, resolve_collection, shard_generation,
};
use crate::{api::search::search_sql::{shard_table_names, sql_options_clause}};
use crate::db_utils::{
    decompose_spans::decompose_text_into_spans, manticore_utils::manticore_search_sql,
};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
struct DocumentHits {
    extracted_by: String,
    page_id: u32,
    text: String,
}

/// The `<shard>_pages` table holding this document, plus the cache salt for its
/// collection. `Ok(None)` means the document has not been indexed yet.
async fn pages_table_for_document(
    document_identifier: &DocumentIdentifier,
) -> anyhow::Result<Option<(String, String)>> {
    let collectionname = resolve_collection(&document_identifier.collection_dataset).await?;
    let Some(shard_name) = find_shard_for_document(
        &collectionname,
        &document_identifier.collection_dataset,
        &document_identifier.file_hash,
    )
    .await?
    else {
        return Ok(None);
    };
    let (pages_table, _) = shard_table_names(&shard_name)?;
    let generation = shard_generation(&collectionname).await?;
    Ok(Some((pages_table, format!("{collectionname}@{generation}"))))
}

pub async fn search_document_text_for_hits(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
    find_query: String,
    extracted_by: String,
    page_id: u32,
) -> anyhow::Result<Vec<DocumentTextSourceHit>> {
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    let Some((pages_table, salt)) = pages_table_for_document(&document_identifier).await? else {
        return Ok(vec![]);
    };
    let options_clause = sql_options_clause(1000);
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
            FROM {pages_table}
            WHERE file_hash = {} AND collection_dataset = {} AND extracted_by = {} AND page_id = {}
            AND MATCH({})
            LIMIT 1000
            {options_clause}
        "#,
        format_sql_query::QuotedData(&document_identifier.file_hash),
        format_sql_query::QuotedData(&document_identifier.collection_dataset),
        format_sql_query::QuotedData(&extracted_by),
        page_id,
        format_sql_query::QuotedData(&find_query),
    );
    let response = manticore_search_sql::<DocumentHits>(sql, &salt).await?;
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
    let Some((pages_table, salt)) = pages_table_for_document(&document_identifier).await? else {
        return Ok(vec![]);
    };
    let options_clause = sql_options_clause(1000);
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
        FROM {pages_table}
        WHERE file_hash = {} AND collection_dataset = {}
        AND MATCH({})
        LIMIT 1000
        {options_clause}
    "#,
        format_sql_query::QuotedData(&document_identifier.file_hash),
        format_sql_query::QuotedData(&document_identifier.collection_dataset),
        format_sql_query::QuotedData(&find_query),
    );
    let response = manticore_search_sql::<DocumentHits>(sql, &salt).await?;
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
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;

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
