//! The upload routes other than tus: `GET /_upload/limits`, `POST /_upload/begin`,
//! `POST /_upload/{batch_id}/commit`, `POST /_upload/{batch_id}/abort` and
//! `GET /_upload/{batch_id}/prefix/{file_no}`.
//!
//! The session middleware resolves the user. `begin`, `commit` and `abort` accept
//! `Content-Type: application/json` only, so a request from another origin needs a CORS
//! preflight, which the site does not answer. The receiver work runs on the blocking
//! thread pool ([`run_blocking`]), outside the Dioxus server-function runtime.

use axum::{
    body::Body,
    extract::{Extension, Path},
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
use common::current_user::CurrentUser;
use common::uploads::{
    BeginRequest, LimitsResponse, UploadTargetInfo, MANIFEST_MAX_BYTES, MANIFEST_TOO_LARGE_MESSAGE,
};

use crate::uploads::{self, UploadError, UploadResult};

/// Run receiver work on the blocking thread pool.
pub async fn run_blocking<T: Send + 'static>(
    work: impl FnOnce() -> UploadResult<T> + Send + 'static,
) -> UploadResult<T> {
    match tokio::task::spawn_blocking(work).await {
        Ok(result) => result,
        Err(e) => Err(UploadError::new(500, format!("the upload task failed: {e}"))),
    }
}

/// The JSON response of a refusal or a failure. A failure is logged without file names.
pub fn error_response(err: UploadError) -> Response {
    let status = StatusCode::from_u16(err.status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
    if status.is_server_error() {
        tracing::error!("upload route failed: {}", err.message);
    }
    match err.refusal {
        Some(refusal) => (status, Json(refusal)).into_response(),
        None => (status, Json(serde_json::json!({ "message": err.message }))).into_response(),
    }
}

fn is_json(headers: &HeaderMap) -> bool {
    headers
        .get(axum::http::header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.split(';').next())
        .is_some_and(|v| v.trim().eq_ignore_ascii_case("application/json"))
}

fn not_json() -> Response {
    error_response(UploadError::new(415, "The request must have Content-Type: application/json."))
}

/// Read a JSON body of at most `limit` bytes. A larger body gives `None`.
async fn read_body(headers: &HeaderMap, body: Body, limit: usize) -> Result<Option<bytes::Bytes>, UploadError> {
    let declared = headers
        .get(axum::http::header::CONTENT_LENGTH)
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.parse::<u64>().ok());
    if declared.is_some_and(|n| n > limit as u64) {
        return Ok(None);
    }
    match axum::body::to_bytes(body, limit).await {
        Ok(bytes) => Ok(Some(bytes)),
        Err(e) => {
            let text = format!("{e:#}");
            if text.contains("length limit") {
                Ok(None)
            } else {
                Err(UploadError::new(400, format!("The request body could not be read: {text}")))
            }
        }
    }
}

/// `GET /_upload/limits`: the limits and the upload targets of the user.
pub async fn limits(Extension(user): Extension<CurrentUser>) -> Response {
    let limits = match uploads::service() {
        Ok(service) => service.limits.clone(),
        Err(e) => return error_response(e),
    };
    match crate::db_auth::uploads::upload_targets(&user.username).await {
        Ok(found) => Json(LimitsResponse {
            limits,
            targets: found
                .targets
                .into_iter()
                .map(|t| UploadTargetInfo { collection: t.collectionname, dataset: t.collection_dataset })
                .collect(),
            conflicts: found.conflicts.into_iter().map(|c| c.collectionname).collect(),
        })
        .into_response(),
        Err(e) => error_response(e.into()),
    }
}

/// `POST /_upload/begin`.
pub async fn begin(Extension(user): Extension<CurrentUser>, headers: HeaderMap, body: Body) -> Response {
    if !is_json(&headers) {
        return not_json();
    }
    let bytes = match read_body(&headers, body, MANIFEST_MAX_BYTES).await {
        Ok(Some(bytes)) => bytes,
        Ok(None) => return error_response(UploadError::new(413, MANIFEST_TOO_LARGE_MESSAGE)),
        Err(e) => return error_response(e),
    };
    let request: BeginRequest = match serde_json::from_slice(&bytes) {
        Ok(request) => request,
        Err(e) => return error_response(UploadError::new(400, format!("The upload list is not valid: {e}"))),
    };
    let service = match uploads::service() {
        Ok(service) => service,
        Err(e) => return error_response(e),
    };
    match run_blocking(move || service.begin(&user.username, &request)).await {
        Ok(response) => (StatusCode::CREATED, Json(response)).into_response(),
        Err(e) => error_response(e),
    }
}

/// `POST /_upload/{batch_id}/commit`. The answer comes after `committing` is durable.
/// Placement and the queue notification continue in the background, and startup
/// recovery and the sweep repeat them after a restart.
pub async fn commit(
    Extension(user): Extension<CurrentUser>,
    Path(batch_id): Path<String>,
    headers: HeaderMap,
    body: Body,
) -> Response {
    if !is_json(&headers) {
        return not_json();
    }
    if let Err(e) = read_body(&headers, body, 4096).await {
        return error_response(e);
    }
    let service = match uploads::service() {
        Ok(service) => service,
        Err(e) => return error_response(e),
    };
    let worker = service.clone();
    let id = batch_id.clone();
    match run_blocking(move || worker.commit(&user.username, &id)).await {
        Ok(response) => {
            tokio::task::spawn_blocking(move || {
                if let Err(e) = service.finish(&batch_id) {
                    tracing::error!("upload batch {batch_id}: the commit continues at the next sweep: {e:#}");
                }
            });
            Json(response).into_response()
        }
        Err(e) => error_response(e),
    }
}

/// `POST /_upload/{batch_id}/abort`. The answer comes after the placed files left the
/// dataset folder and the upload space of the batch is deleted.
pub async fn abort(
    Extension(user): Extension<CurrentUser>,
    Path(batch_id): Path<String>,
    headers: HeaderMap,
    body: Body,
) -> Response {
    if !is_json(&headers) {
        return not_json();
    }
    if let Err(e) = read_body(&headers, body, 4096).await {
        return error_response(e);
    }
    let service = match uploads::service() {
        Ok(service) => service,
        Err(e) => return error_response(e),
    };
    match run_blocking(move || service.abort(&user.username, &batch_id)).await {
        Ok(()) => StatusCode::NO_CONTENT.into_response(),
        Err(e) => error_response(e),
    }
}

/// `GET /_upload/{batch_id}/prefix/{file_no}`: the SHA-256 of the acknowledged prefix,
/// for the owner.
pub async fn prefix(
    Extension(user): Extension<CurrentUser>,
    Path((batch_id, file_no)): Path<(String, u32)>,
) -> Response {
    let service = match uploads::service() {
        Ok(service) => service,
        Err(e) => return error_response(e),
    };
    match run_blocking(move || service.prefix_digest(&user.username, &batch_id, file_no)).await {
        Ok(digest) => {
            let mut response = Json(digest).into_response();
            response
                .headers_mut()
                .insert(axum::http::header::CACHE_CONTROL, axum::http::HeaderValue::from_static("no-store"));
            response
        }
        Err(e) => error_response(e),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn headers(length: Option<usize>) -> HeaderMap {
        let mut headers = HeaderMap::new();
        if let Some(n) = length {
            headers.insert(axum::http::header::CONTENT_LENGTH, n.to_string().parse().unwrap());
        }
        headers
    }

    #[tokio::test]
    async fn a_body_of_the_limit_is_read_and_one_byte_more_is_refused() {
        for declared in [true, false] {
            let at_limit = vec![b' '; 64];
            let got = read_body(&headers(declared.then_some(64)), Body::from(at_limit), 64).await.unwrap();
            assert_eq!(got.map(|b| b.len()), Some(64));
            let over = vec![b' '; 65];
            let got = read_body(&headers(declared.then_some(65)), Body::from(over), 64).await.unwrap();
            assert!(got.is_none(), "declared={declared}");
        }
    }

    #[test]
    fn only_json_is_accepted() {
        let mut map = HeaderMap::new();
        assert!(!is_json(&map));
        map.insert(axum::http::header::CONTENT_TYPE, "text/plain".parse().unwrap());
        assert!(!is_json(&map));
        map.insert(axum::http::header::CONTENT_TYPE, "application/json; charset=utf-8".parse().unwrap());
        assert!(is_json(&map));
    }
}
