//! Endpoint for resolving document file paths.

use common::search_result::DocumentIdentifier;

use crate::db_utils::clickhouse_utils::get_clickhouse_client;

pub async fn get_file_path(document_identifier: DocumentIdentifier) -> anyhow::Result<String> {
    let client = get_clickhouse_client();
    let query = "SELECT path FROM vfs_files WHERE hash = ? AND collection_dataset = ? LIMIT 1";
    let query = client.query(query).bind(&document_identifier.file_hash).bind(&document_identifier.collection_dataset);
    let result = query.fetch_all::<String>().await?;
    if let Some(path) = result.into_iter().next() {
        Ok(path)
    } else {
        anyhow::bail!("File path not found");
    }
}