//! Locating a document's bytes: the `blobs` registry, and reading an object out of it.
//!
//! A blob lives in one of two places and the row says which. Small ones are inlined in
//! ClickHouse (`blob_values`); everything else is an object in its collection's bucket
//! named by `blobs.s3_path`. Both lookups live here so the streaming download route
//! (`server_extra::download_document`) and the in-process readers ([`read_blob_bytes`])
//! resolve a blob the same way.
//!
//! **Nothing in this module fetches the website's own HTTP port.** Reading a document by
//! calling `/_download_document/…` over `127.0.0.1` is how a server-side reader ends up
//! needing a session cookie it has no way to hold, and it puts the blob store behind two
//! extra hops for no gain. Server-side callers read the blob directly.

use anyhow::Context;
use clickhouse::Row;
use common::current_user::CurrentUser;
use common::search_result::DocumentIdentifier;
use serde::{Deserialize, Serialize};

use crate::auth::permissions;
use crate::db_utils::clickhouse_utils::get_client_for_dataset;

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

pub async fn get_blob_filename(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<String> {
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;
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

/// Where this document's bytes are, and how big they are.
pub async fn get_blob_info(
    document_identifier: &DocumentIdentifier,
) -> anyhow::Result<BlobInfo> {
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;
    let query = "SELECT blob_size_bytes, s3_path, stored_in_clickhouse FROM blobs WHERE collection_dataset = ? AND blob_hash = ? LIMIT 1";
    let result = client
        .query(query)
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash)
        .fetch_all::<BlobInfo>()
        .await?;
    result
        .into_iter()
        .next()
        .ok_or_else(|| anyhow::anyhow!("blob not found: {}", document_identifier.file_hash))
}

/// The inlined bytes of a blob whose `blobs` row says `stored_in_clickhouse`.
pub async fn get_blob_value_from_clickhouse(
    document_identifier: &DocumentIdentifier,
) -> anyhow::Result<BlobValue> {
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;
    let query = "SELECT blob_value, blob_length FROM blob_values WHERE collection_dataset = ? AND blob_hash = ? LIMIT 1";
    let result = client
        .query(query)
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash)
        .fetch_all::<BlobValue>()
        .await?;
    result
        .into_iter()
        .next()
        .ok_or_else(|| anyhow::anyhow!("blob value not found: {}", document_identifier.file_hash))
}

/// The whole document, in memory, for a caller that has to hand the bytes to something
/// else — the in-PDF search sidecar is the only one today.
///
/// `max_bytes` is checked against the **registered size** before a single byte is read, so
/// an oversized document costs one ClickHouse query rather than a multi-gigabyte
/// allocation. Callers must pass a real ceiling: whatever they hand the bytes to buffers
/// them too, so "how big can this get" is a question about the whole chain.
pub async fn read_blob_bytes(
    user: &CurrentUser,
    document_identifier: &DocumentIdentifier,
    max_bytes: u64,
) -> anyhow::Result<Vec<u8>> {
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    let blob_info = get_blob_info(document_identifier).await?;
    anyhow::ensure!(
        blob_info.blob_size_bytes <= max_bytes,
        "document is {} bytes, over the {max_bytes}-byte limit for reading it into memory",
        blob_info.blob_size_bytes
    );

    if blob_info.stored_in_clickhouse {
        return Ok(get_blob_value_from_clickhouse(document_identifier).await?.blob_value);
    }

    let (bucket, key) = crate::db_utils::split_s3_path(&blob_info.s3_path)
        .ok_or_else(|| anyhow::anyhow!("blob s3_path is not an s3 url: {}", blob_info.s3_path))?;
    read_s3_object(&bucket, &key).await
}

async fn read_s3_object(bucket: &str, key: &str) -> anyhow::Result<Vec<u8>> {
    let client = crate::db_utils::s3_client().await?;
    let object = client
        .get_object()
        .bucket(bucket)
        .key(key)
        .send()
        .await
        .context("Failed to get object")?;
    Ok(object.body.collect().await.context("Failed to read object body")?.to_vec())
}
