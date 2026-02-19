use anyhow::Context;
use axum::{body::Body, extract::Path, response::{IntoResponse, Response}};
use common::search_result::DocumentIdentifier;
use minio::s3::{creds::StaticProvider, http::BaseUrl, types::S3Api};
use minio::s3::Client;
use reqwest::StatusCode;
use tracing::info;

use crate::api::documents::download_document::{get_blob_filename, get_document_content_stream};

async fn _download_document(Path((collection_dataset, file_hash)): Path<(String, String)>) -> anyhow::Result<impl IntoResponse> {
    info!("Downloading document: {}/{}", collection_dataset, file_hash);

    let document_identifier = DocumentIdentifier {
        collection_dataset,
        file_hash,
    };
    let filename = get_blob_filename(document_identifier.clone()).await?;


    let (stream_size, stream) = get_document_content_stream(document_identifier.clone()).await?;

    let headers: [(String, String); 3] = [
        ("Content-Type".to_string(), "application/octet-stream".to_string()),
        (
           "Content-Disposition".to_string(),
            format!("attachment; filename=\"{}\"", filename),
        ),
        ("Content-Length".to_string(), format!("{}", stream_size)),
    ];

    let body = Body::from_stream(stream);
    return Ok((headers, body).into_response())

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