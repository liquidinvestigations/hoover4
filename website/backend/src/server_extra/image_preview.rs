//! Serve the JPEG preview of an image or a video, with the access check of the document.
//!
//! The worker writes a preview for each image format that the browser cannot show, and
//! the first frame of each video. `image_previews` is the only record of the object, as
//! `pdf_ocr_results` is for a searchable PDF. A document without a row has no preview,
//! and the viewer then shows the original file.

use anyhow::Context;
use axum::{
    body::Body,
    extract::{Extension, Path},
    response::{IntoResponse, Response},
};
use common::current_user::CurrentUser;
use futures::TryStreamExt;
use reqwest::StatusCode;

use crate::{
    auth::{guard, permissions},
    db_utils::clickhouse_utils::get_client_for_dataset,
};

/// Every preview key starts with this prefix. A row that names another key is not
/// served, so a changed row cannot turn this route into a reader for the whole bucket.
const PREVIEW_PREFIX: &str = "derived/image-preview/";

#[derive(Debug, Clone, PartialEq)]
pub struct StoredPreview {
    pub bucket: String,
    pub key: String,
    pub width: u32,
    pub height: u32,
}

/// `(bucket, key)` of a stored preview path, or `None` for any other path.
fn split_preview_path(s3_path: &str) -> Option<(String, String)> {
    let (bucket, key) = s3_path.strip_prefix("s3://")?.split_once('/')?;
    if bucket.is_empty() || !key.starts_with(PREVIEW_PREFIX) || key.contains("..") {
        return None;
    }
    Some((bucket.to_string(), key.to_string()))
}

/// The preview of one document, or `None` when it has none.
///
/// The caller checks read access to the dataset first.
pub async fn stored_preview(
    collection_dataset: &str,
    file_hash: &str,
) -> anyhow::Result<Option<StoredPreview>> {
    let client = get_client_for_dataset(collection_dataset).await?;
    let rows = client
        .query(
            "SELECT argMax(s3_path, updated_at), argMax(width, updated_at), \
             argMax(height, updated_at) FROM image_previews \
             WHERE collection_dataset = ? AND hash = ? GROUP BY collection_dataset, hash",
        )
        .bind(collection_dataset)
        .bind(file_hash)
        .fetch_all::<(String, u32, u32)>()
        .await?;
    Ok(rows.into_iter().next().and_then(|(path, width, height)| {
        split_preview_path(&path).map(|(bucket, key)| StoredPreview { bucket, key, width, height })
    }))
}

async fn _image_preview(
    user: &CurrentUser,
    Path((collection_dataset, file_hash)): Path<(String, String)>,
) -> anyhow::Result<impl IntoResponse> {
    permissions::assert_can_read(user, &collection_dataset).await?;
    let preview = stored_preview(&collection_dataset, &file_hash)
        .await?
        .ok_or_else(|| anyhow::anyhow!("no image preview for {file_hash}: not found"))?;
    // The preview must be in the bucket of the document's own collection.
    let collectionname = crate::db_utils::collectionname_of_dataset(&collection_dataset).await?;
    anyhow::ensure!(
        preview.bucket == crate::db_utils::collection_bucket(&collectionname),
        "refusing to serve a preview outside the collection bucket"
    );
    let client = crate::db_utils::s3_client().await?;
    let object = client
        .get_object()
        .bucket(&preview.bucket)
        .key(&preview.key)
        .send()
        .await
        .with_context(|| format!("Failed to get {}", preview.key))?;
    let object_size = object.content_length().unwrap_or_default();
    // See `download_ocr_pdf` for why the body is read as an `AsyncRead`.
    let stream = tokio_util::io::ReaderStream::new(object.body.into_async_read())
        .map_err(anyhow::Error::from);
    let mut headers = vec![
        ("Content-Type".to_string(), "image/jpeg".to_string()),
        ("Content-Disposition".to_string(), format!("inline; filename=\"{file_hash}.jpg\"")),
    ];
    if object_size > 0 {
        headers.push(("Content-Length".to_string(), object_size.to_string()));
    }
    let mut response = Body::from_stream(stream).into_response();
    for (name, value) in headers {
        response.headers_mut().insert(
            axum::http::HeaderName::from_bytes(name.as_bytes())?,
            axum::http::HeaderValue::from_str(&value)?,
        );
    }
    Ok(response)
}

pub async fn image_preview(
    Extension(user): Extension<CurrentUser>,
    path: Path<(String, String)>,
) -> Response {
    match _image_preview(&user, path).await {
        Ok(response) => response.into_response(),
        Err(e) => {
            if guard::is_forbidden(&e) {
                return (StatusCode::FORBIDDEN, Body::from(e.to_string())).into_response();
            }
            let message = e.to_string();
            if guard::is_not_found(&e) {
                return (StatusCode::NOT_FOUND, Body::from(message)).into_response();
            }
            tracing::error!("image_preview: request failed: {:#?}", e);
            (StatusCode::INTERNAL_SERVER_ERROR, Body::from(message)).into_response()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::split_preview_path;

    #[test]
    fn only_preview_keys_are_served() {
        assert_eq!(
            split_preview_path("s3://hoover4-c-x/derived/image-preview/h.jpg"),
            Some(("hoover4-c-x".to_string(), "derived/image-preview/h.jpg".to_string()))
        );
        assert_eq!(split_preview_path("s3://hoover4-c-x/blobs/h"), None);
        assert_eq!(split_preview_path("s3://hoover4-c-x/derived/image-preview/../h"), None);
        assert_eq!(split_preview_path("/etc/passwd"), None);
        assert_eq!(split_preview_path("s3:///derived/image-preview/h.jpg"), None);
    }
}
