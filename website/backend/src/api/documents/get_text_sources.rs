//! Endpoint for fetching document text sources.

use common::{document_text_sources::DocumentTextSourceItem, search_result::DocumentIdentifier};

use crate::db_utils::clickhouse_utils::get_clickhouse_client;

pub async fn get_text_sources(document_identifier: DocumentIdentifier) -> anyhow::Result<Vec<DocumentTextSourceItem>> {
    let client = get_clickhouse_client();
    let query = r#"
    SELECT extracted_by,min(page_id) as min_page,max(page_id) as max_page FROM text_content
    WHERE file_hash = ? AND collection_dataset = ?
    GROUP BY extracted_by
    LIMIT 1000"#;
    let query = client.query(query).bind(&document_identifier.file_hash).bind(&document_identifier.collection_dataset);
    let result = query.fetch_all::<(String, u32, u32)>().await?;
    let result = result.into_iter().map(|(extracted_by, min_page, max_page)| DocumentTextSourceItem { extracted_by, min_page, max_page }).collect::<Vec<_>>();
    Ok(result)
}