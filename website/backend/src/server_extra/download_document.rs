use anyhow::Context;
use axum::{body::Body, extract::Path, response::{IntoResponse, Response}};
use common::search_result::DocumentIdentifier;
use minio::s3::{creds::StaticProvider, http::BaseUrl, types::S3Api};
use minio::s3::Client;
use reqwest::StatusCode;
use tracing::info;

use crate::api::documents::download_document::{get_blob_filename, get_document_blob_content_from_clickhouse, get_document_s3_blob_download_path};

async fn _download_document(Path((collection_dataset, file_hash)): Path<(String, String)>) -> anyhow::Result<impl IntoResponse> {
    info!("Downloading document: {}/{}", collection_dataset, file_hash);

    let document_identifier = DocumentIdentifier {
        collection_dataset,
        file_hash,
    };
    let filename = get_blob_filename(document_identifier.clone()).await?;
    let headers: [(String, String); 2] = [
        ("Content-Type".to_string(), "application/octet-stream".to_string()),
        (
           "Content-Disposition".to_string(),
            format!("attachment; filename=\"{}\"", filename),
        ),
    ];

    let blob_info = get_document_s3_blob_download_path(document_identifier.clone()).await?;
    let blob_size = blob_info.blob_size_bytes;
    tracing::info!("Blob size: {}", blob_size);
    tracing::info!("Blob info: {:#?}", blob_info);
    if blob_info.stored_in_clickhouse {
        tracing::info!("Downloading document from clickhouse");
        let blob_value = get_document_blob_content_from_clickhouse(document_identifier.clone()).await?;
        let data = blob_value.blob_value;
        assert_eq!(data.len(), blob_size as usize);
        let body = Body::from(data);

        return Ok((headers, body).into_response())
    } else {
        tracing::info!("Downloading document from s3");
        let s3_path = blob_info.s3_path.replace("s3://hoover4-blobs/", "");
        tracing::info!("S3 path: {}", s3_path);
        let s3_bucket = "hoover4-blobs";
        let s3_endpoint = std::env::var("S3_ENDPOINT").context("S3_ENDPOINT is not set")?;
        let base_url = s3_endpoint.parse::<BaseUrl>().context("Failed to parse s3 endpoint")?;
        let static_provider = StaticProvider::new("hoover4", "hoover4-secret", None);
        let client = Client::new(base_url, Some(Box::new(static_provider)), None, None).context("Failed to create s3 client")?;
        let object = client.get_object(s3_bucket, s3_path).send().await.context("Failed to get object")?;
        let object_size = object.object_size as usize;
        assert_eq!(object_size, blob_size as usize);
        let (stream, _size) = object.content.to_stream().await.context("Failed to get object stream")?;

        // let stream = client.get_object(s3_bucket, s3_path).await?.bytes_stream();
        let body = Body::from_stream(stream);
        return Ok((headers, body).into_response())
    }
}

pub async fn download_document(Path((collection_dataset, file_hash)): Path<(String, String)>) ->   Response {
    match _download_document(Path((collection_dataset, file_hash))).await {
        Ok(response) => response.into_response(),
        Err(e) => {
            tracing::error!("download_document: request failed: {:#?}", e);
            return (StatusCode::INTERNAL_SERVER_ERROR, Body::from(e.to_string())).into_response();
        }
    }
}