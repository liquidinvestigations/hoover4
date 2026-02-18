use clickhouse::{Row};
use common::{document_text_sources::DocumentTextSourceHitCount, search_result::DocumentIdentifier};
use serde::{Deserialize, Serialize};

use crate::db_utils::clickhouse_utils::get_clickhouse_client;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Row)]
pub struct BlobInfo {
    pub blob_size_bytes: u64,
    pub s3_path: String,
    pub stored_in_clickhouse: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Row)]
pub struct BlobValue {
    #[serde(with = "serde_bytes")]
    pub blob_value: Vec<u8>,
    pub blob_length: u64,
}

pub async fn get_document_s3_blob_download_path(document_identifier: DocumentIdentifier) -> anyhow::Result< BlobInfo> {
    let client = get_clickhouse_client();
    let query = "SELECT blob_size_bytes, s3_path, stored_in_clickhouse FROM blobs WHERE collection_dataset = ? AND blob_hash = ? LIMIT 1";
    let query = client.query(query).bind(&document_identifier.collection_dataset).bind(&document_identifier.file_hash);
    let result = query.fetch_all::<BlobInfo>().await?;
    if let Some(blob_info) = result.into_iter().next() {
        Ok(blob_info)
    } else {
        anyhow::bail!("get_blob_filename: File hash not found");
    }
}

pub async fn get_document_blob_content_from_clickhouse(document_identifier: DocumentIdentifier) -> anyhow::Result<BlobValue> {
    let client = get_clickhouse_client();
    let query = "SELECT blob_value, blob_length FROM blob_values WHERE collection_dataset = ? AND blob_hash = ? LIMIT 1";
    let query = client.query(query).bind(&document_identifier.collection_dataset).bind(&document_identifier.file_hash);
    let result = query.fetch_all::<BlobValue>().await?;
    if let Some(blob_value) = result.into_iter().next() {
        Ok(blob_value)
    } else {
        anyhow::bail!("get_blob_filename: File hash not found");
    }
}

pub async fn get_blob_filename(document_identifier: DocumentIdentifier) -> anyhow::Result<String> {
    let client = get_clickhouse_client();
    let query = "SELECT path FROM vfs_files WHERE collection_dataset = ? AND hash = ? LIMIT 1";
    let query = client.query(query).bind(&document_identifier.collection_dataset).bind(&document_identifier.file_hash);
    let result = query.fetch_all::<String>().await?;
    if let Some(path) = result.into_iter().next() {
        Ok(path.split("/").last().unwrap_or("").to_string())
    } else {
        anyhow::bail!("get_blob_filename: File hash not found");
    }
}