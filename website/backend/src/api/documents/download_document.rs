use std::pin::Pin;

use anyhow::Context;
use clickhouse::Row;
use common::{
    document_text_sources::DocumentTextSourceHitCount, search_result::DocumentIdentifier,
};
use futures::{StreamExt, TryStreamExt};
use minio::s3::types::S3Api;
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

pub async fn get_blob_filename(document_identifier: DocumentIdentifier) -> anyhow::Result<String> {
    let client = get_clickhouse_client();
    let query = "SELECT path FROM vfs_files WHERE collection_dataset = ? AND hash = ? LIMIT 1";
    let query = client
        .query(query)
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash);
    let result = query.fetch_all::<String>().await?;
    if let Some(path) = result.into_iter().next() {
        Ok(path.split("/").last().unwrap_or("").to_string())
    } else {
        anyhow::bail!("get_blob_filename: File hash not found");
    }
}

pub async fn get_document_content_stream(
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<(
    usize,
    Pin<Box<dyn futures::Stream<Item = anyhow::Result<bytes::Bytes>> + Send + 'static>>,
)> {
    let path = format!(
        "http://localhost:8080/_download_document/{}/{}",
        document_identifier.collection_dataset, document_identifier.file_hash
    );
    tracing::info!("Downloading document from: {}", path);
    let response = reqwest::get(path).await?;
    let response = response.error_for_status()?;
    let content_size = response
        .content_length()
        .context("Failed to get content length")?;
    let content_stream = response.bytes_stream().map_err(|e| anyhow::Error::from(e));

    Ok((content_size as usize, Box::pin(content_stream)))
}
