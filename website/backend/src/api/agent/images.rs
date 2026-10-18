//! The image routes of the agent serve the bytes of a document image and of a page
//! capture. The agent service sends them to the model after a tool result.
//!
//! The browser routes `/_image_preview` and `/_chat_artifact` read the same objects with a
//! browser session. These routes read them with the agent caller identity, so a model
//! request never carries a browser cookie.
//!
//! Each response carries an `etag` that names the source object. A request with a
//! matching `if-none-match` gets `304` after the access check, so a cached copy is used
//! only while the caller can still read the source.

use super::*;
use crate::api::documents::download_document::{get_blob_info, get_blob_value_from_clickhouse};
use crate::server_extra::{chat_artifact, image_preview};

/// The largest original image file that the route reads. A larger file has no stored
/// preview to send in its place, so the route refuses it.
pub(super) const MAX_ORIGINAL_IMAGE_BYTES: u64 = 32 * 1024 * 1024;

/// The bytes of one image, with the etag that names the source object.
fn image_response(etag: String, content_type: &str, bytes: Option<Vec<u8>>) -> Response {
    let quoted = format!("\"{etag}\"");
    let mut response = match bytes {
        None => StatusCode::NOT_MODIFIED.into_response(),
        Some(bytes) => {
            let mut response = bytes.into_response();
            if let Ok(value) = axum::http::HeaderValue::from_str(content_type) {
                response.headers_mut().insert(axum::http::header::CONTENT_TYPE, value);
            }
            response
        }
    };
    if let Ok(value) = axum::http::HeaderValue::from_str(&quoted) {
        response.headers_mut().insert(axum::http::header::ETAG, value);
    }
    response
}

/// True when the request names `etag` in `if-none-match`.
fn not_modified(headers: &HeaderMap, etag: &str) -> bool {
    headers
        .get(axum::http::header::IF_NONE_MATCH)
        .and_then(|value| value.to_str().ok())
        .is_some_and(|value| value.split(',').any(|tag| tag.trim().trim_matches('"') == etag))
}

async fn object_bytes(bucket: &str, key: &str) -> Result<Vec<u8>, AgentError> {
    let client = crate::db_utils::s3_client().await.map_err(AgentError::from_anyhow)?;
    let object = client
        .get_object()
        .bucket(bucket)
        .key(key)
        .send()
        .await
        .map_err(|error| AgentError::from_anyhow(anyhow::anyhow!("could not read {key}: {error}")))?;
    let bytes = object
        .body
        .collect()
        .await
        .map_err(|error| AgentError::from_anyhow(anyhow::anyhow!("could not read {key}: {error}")))?;
    Ok(bytes.to_vec())
}

/// `POST images/document`: the stored preview of an image or a video document, else the
/// original file of an image document.
pub(super) async fn images_document(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<DocumentImageRequest>,
) -> Result<Response, AgentError> {
    let identifier =
        document_identifier(&user, &headers, &body.collectionname, &body.file_hash, DatasetRow::Any).await?;
    let file_hash = identifier.file_hash.clone();
    let preview = image_preview::stored_preview(&identifier.collection_dataset, &file_hash)
        .await
        .map_err(AgentError::from_anyhow)?;
    if let Some(preview) = preview {
        let collectionname = crate::db_utils::collectionname_of_dataset(&identifier.collection_dataset)
            .await
            .map_err(AgentError::from_anyhow)?;
        if preview.bucket != crate::db_utils::collection_bucket(&collectionname) {
            return Err(AgentError::permission_denied("the preview is outside the collection bucket"));
        }
        let etag = format!("preview-{file_hash}");
        if not_modified(&headers, &etag) {
            return Ok(image_response(etag, "image/jpeg", None));
        }
        let bytes = object_bytes(&preview.bucket, &preview.key).await?;
        return Ok(image_response(etag, "image/jpeg", Some(bytes)));
    }
    let image = get_document_sources::get_image_sources(&user, identifier.clone())
        .await
        .map_err(AgentError::from_anyhow)?;
    if image.is_none() {
        return Err(AgentError::not_found("the document has no image and no stored preview"));
    }
    let etag = format!("original-{file_hash}");
    if not_modified(&headers, &etag) {
        return Ok(image_response(etag, "application/octet-stream", None));
    }
    let blob = get_blob_info(&identifier).await.map_err(AgentError::from_anyhow)?;
    if blob.blob_size_bytes > MAX_ORIGINAL_IMAGE_BYTES {
        return Err(AgentError::invalid_argument(format!(
            "the image file has {} bytes, above the limit of {MAX_ORIGINAL_IMAGE_BYTES} bytes",
            blob.blob_size_bytes
        )));
    }
    let bytes = if blob.stored_in_clickhouse {
        get_blob_value_from_clickhouse(&identifier).await.map_err(AgentError::from_anyhow)?.blob_value
    } else {
        let (bucket, key) = crate::db_utils::split_s3_path(&blob.s3_path)
            .ok_or_else(|| AgentError::from_anyhow(anyhow::anyhow!("blob s3_path is not an s3 url")))?;
        object_bytes(&bucket, &key).await?
    };
    Ok(image_response(etag, "application/octet-stream", Some(bytes)))
}

/// `POST images/capture`: the screenshot of a page capture. The caller must own the
/// capture or be an administrator.
pub(super) async fn images_capture(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<CaptureImageRequest>,
) -> Result<Response, AgentError> {
    validate_plain_text(&body.artifact_id)?;
    let row = crate::db_chat::artifacts::get_artifact(&body.artifact_id)
        .await
        .map_err(AgentError::from_anyhow)?
        .ok_or_else(|| AgentError::not_found("no such capture"))?;
    if !chat_artifact::may_read(&user.username, user.is_admin, &row.username) {
        return Err(AgentError::permission_denied("the capture belongs to another user"));
    }
    if row.thumb_key.is_empty() {
        return Err(AgentError::not_found("the capture has no screenshot"));
    }
    let etag = format!("capture-{}", row.artifact_id);
    if not_modified(&headers, &etag) {
        return Ok(image_response(etag, "image/webp", None));
    }
    let bytes = chat_artifact::fetch_artifact_object(&row.thumb_key).await.map_err(AgentError::from_anyhow)?;
    Ok(image_response(etag, "image/webp", Some(bytes)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_matching_etag_is_not_modified() {
        let mut headers = HeaderMap::new();
        assert!(!not_modified(&headers, "preview-h"));
        headers.insert(axum::http::header::IF_NONE_MATCH, "\"original-h\", \"preview-h\"".parse().unwrap());
        assert!(not_modified(&headers, "preview-h"));
        assert!(!not_modified(&headers, "capture-h"));
    }
}
