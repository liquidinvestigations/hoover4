use std::pin::Pin;

use anyhow::Context;
use clickhouse::{Row};
use common::{document_text_sources::DocumentTextSourceHitCount, search_result::DocumentIdentifier};
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

async fn get_document_s3_blob_download_path(document_identifier: DocumentIdentifier) -> anyhow::Result< BlobInfo> {
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

async fn get_document_blob_content_from_clickhouse(document_identifier: DocumentIdentifier) -> anyhow::Result<BlobValue> {
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


pub async fn get_document_content_stream(document_identifier: DocumentIdentifier) -> anyhow::Result<(usize, Pin<Box<
dyn futures::Stream<Item = anyhow::Result<bytes::Bytes>> + Send + 'static>>)> {

    let blob_info = get_document_s3_blob_download_path(document_identifier.clone()).await?;
    if blob_info.stored_in_clickhouse {
        tracing::info!("Downloading document from clickhouse");
        let blob_value = get_document_blob_content_from_clickhouse(document_identifier.clone()).await?;
        let data = blob_value.blob_value;
        let data = anyhow::Ok(bytes::Bytes::from(data));
        return Ok((blob_value.blob_length as usize, Box::pin(futures::stream::iter([data]))))
    }

    tracing::info!("Downloading document from s3");
    let s3_path = blob_info.s3_path.replace("s3://hoover4-blobs/", "");
    tracing::info!("S3 path: {}", s3_path);
    let s3_bucket = "hoover4-blobs";
    let s3_endpoint = std::env::var("S3_ENDPOINT").context("S3_ENDPOINT is not set")?;
    let base_url = s3_endpoint.parse::<minio::s3::http::BaseUrl>().context("Failed to parse s3 endpoint")?;
    let static_provider = minio::s3::creds::StaticProvider::new("hoover4", "hoover4-secret", None);
    let client = minio::s3::Client::new(base_url, Some(Box::new(static_provider)), None, None).context("Failed to create s3 client")?;
    let object = client.get_object(s3_bucket, s3_path).send().await.context("Failed to get object")?;
    let object_size = object.object_size as usize;
    assert_eq!(object_size, blob_info.blob_size_bytes as usize);
    let (stream, _size) = object.content.to_stream().await.context("Failed to get object stream")?;

    let stream2 = stream.map_err(|x| anyhow::Error::from(x));

    Ok((object_size, Box::pin(stream2)))

}