use std::pin::Pin;

use anyhow::Context;
use axum::{
    body::Body,
    extract::{Extension, Path},
    response::{IntoResponse, Response},
};
use common::current_user::CurrentUser;
use common::search_result::DocumentIdentifier;
use futures::TryStreamExt;
use reqwest::StatusCode;
use tracing::debug;

use crate::{
    api::documents::download_document::{
        get_blob_filename, get_blob_info, get_blob_value_from_clickhouse,
    },
    auth::{guard, permissions},
};

/// The response body, streamed rather than buffered: this route serves whole documents,
/// which have no useful upper bound.
async fn get_document_content_stream(
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<(
    usize,
    Pin<Box<dyn futures::Stream<Item = anyhow::Result<bytes::Bytes>> + Send + 'static>>,
)> {
    let blob_info = get_blob_info(&document_identifier).await?;
    if blob_info.stored_in_clickhouse {
        tracing::debug!("serving blob from clickhouse");
        let blob_value = get_blob_value_from_clickhouse(&document_identifier).await?;
        let data = blob_value.blob_value;
        let data = anyhow::Ok(bytes::Bytes::from(data));
        return Ok((
            blob_value.blob_length as usize,
            Box::pin(futures::stream::iter([data])),
        ));
    }

    let (bucket, key) = crate::db_utils::split_s3_path(&blob_info.s3_path)
        .ok_or_else(|| anyhow::anyhow!("blob s3_path is not an s3 url: {}", blob_info.s3_path))?;
    tracing::debug!("serving blob from s3: {bucket}/{key}");
    let client = crate::db_utils::s3_client().await?;
    let object = client
        .get_object()
        .bucket(&bucket)
        .key(&key)
        .send()
        .await
        .context("Failed to get object")?;
    let object_size = object.content_length().unwrap_or_default() as usize;
    assert_eq!(object_size, blob_info.blob_size_bytes as usize);

    // `ByteStream` has a `Stream` impl only through a `futures-core` version that is not
    // the one this workspace's `futures` resolves to, so `TryStreamExt` does not reach
    // it. Reading it as an `AsyncBufRead` and framing that back into chunks is the
    // conversion that does not depend on which `futures` won, and it still streams --
    // nothing here buffers the object.
    let stream = tokio_util::io::ReaderStream::new(object.body.into_async_read())
        .map_err(anyhow::Error::from);

    Ok((object_size, Box::pin(stream)))
}

async fn _download_document(
    user: &CurrentUser,
    Path((collection_dataset, file_hash)): Path<(String, String)>,
) -> anyhow::Result<impl IntoResponse> {
    debug!("download requested: {collection_dataset}/{file_hash}");

    let document_identifier = DocumentIdentifier {
        collection_dataset: collection_dataset.clone(),
        file_hash,
    };
    permissions::assert_can_read(user, &collection_dataset).await?;
    let filename = get_blob_filename(user, document_identifier.clone()).await?;

    let (stream_size, stream) = get_document_content_stream(document_identifier.clone()).await?;

    let headers: [(String, String); 3] = [
        (
            "Content-Type".to_string(),
            "application/octet-stream".to_string(),
        ),
        (
            "Content-Disposition".to_string(),
            format!("attachment; filename=\"{}\"", filename),
        ),
        ("Content-Length".to_string(), format!("{}", stream_size)),
    ];

    let body = Body::from_stream(stream);
    Ok((headers, body).into_response())
}

pub async fn download_document(
    Extension(user): Extension<CurrentUser>,
    path: Path<(String, String)>,
) -> Response {
    match _download_document(&user, path).await {
        Ok(response) => response.into_response(),
        Err(e) => {
            if guard::is_forbidden(&e) {
                return (StatusCode::FORBIDDEN, Body::from(e.to_string())).into_response();
            }
            // A hash that is in no `vfs_files` row is a question with a complete answer,
            // not a failure: a stale bookmark, a purged dataset or a crawler guessing
            // hashes all land here. Answering 500 makes the site look like it is throwing
            // and (because `is_error` is derived from the status) counts every one of
            // them as breakage on the admin metrics page.
            if guard::is_not_found(&e) {
                return (StatusCode::NOT_FOUND, Body::from(e.to_string())).into_response();
            }
            tracing::error!("download_document: request failed: {:#?}", e);
            (StatusCode::INTERNAL_SERVER_ERROR, Body::from(e.to_string())).into_response()
        }
    }
}
