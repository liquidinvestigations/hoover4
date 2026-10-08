//! The two feedback routes.
//!
//! * `POST /_feedback/submit` takes a [`FeedbackSubmission`] as JSON from any signed-in
//!   person and stores it for the account of the request.
//! * `GET /_feedback/{report_id}/{screenshot.png|dom.html}` returns one stored object to
//!   an administrator.
//!
//! The upload is a route and not a server function, because its body holds a page image
//! and a DOM copy of several megabytes. `main.rs` sets the body limit of the route to
//! [`UPLOAD_MAX_BYTES`].
//!
//! The DOM copy is HTML that the browser of the sender wrote, so a sender controls it.
//! It is served with a CSP sandbox, which gives it an opaque origin and no scripts, so
//! it cannot act in the session of the administrator who opens it.

use axum::{
    body::Body,
    extract::{Extension, Path},
    response::{IntoResponse, Response},
    Json,
};
use common::current_user::CurrentUser;
use common::feedback_types::FeedbackSubmission;
pub use common::feedback_types::UPLOAD_MAX_BYTES;
use reqwest::StatusCode;

use crate::api::feedback::{self, FeedbackAsset};
use crate::auth::guard;

const DOM_CSP: &str = "sandbox; default-src 'none'; style-src 'self' 'unsafe-inline'; \
                       img-src 'self' data:; font-src 'self' data:";

fn status_of(err: &anyhow::Error) -> StatusCode {
    if guard::is_bad_request(err) {
        StatusCode::BAD_REQUEST
    } else if guard::is_not_found(err) {
        StatusCode::NOT_FOUND
    } else if guard::is_forbidden(err) {
        StatusCode::FORBIDDEN
    } else {
        StatusCode::INTERNAL_SERVER_ERROR
    }
}

pub async fn submit_feedback(
    Extension(user): Extension<CurrentUser>,
    Json(submission): Json<FeedbackSubmission>,
) -> Response {
    match feedback::store_submission(&user, submission).await {
        Ok(report_id) => Json(serde_json::json!({ "report_id": report_id })).into_response(),
        Err(e) => {
            let status = status_of(&e);
            if status == StatusCode::INTERNAL_SERVER_ERROR {
                tracing::error!("feedback from {} was not stored: {e:#}", user.username);
            }
            (status, Body::from(e.to_string())).into_response()
        }
    }
}

pub async fn feedback_asset(
    Extension(user): Extension<CurrentUser>,
    Path((report_id, asset)): Path<(String, String)>,
) -> Response {
    let Some(asset) = FeedbackAsset::parse(&asset) else {
        return (StatusCode::NOT_FOUND, "unknown report object").into_response();
    };
    let bytes = match feedback::read_asset(&user, &report_id, asset).await {
        Ok(bytes) => bytes,
        Err(e) => {
            let status = status_of(&e);
            if status == StatusCode::INTERNAL_SERVER_ERROR {
                tracing::error!("feedback object {report_id}/{} failed: {e:#}", asset.file_name());
            }
            return (status, Body::from(e.to_string())).into_response();
        }
    };
    let mut headers = axum::http::HeaderMap::new();
    let mut set = |name: &'static str, value: &str| {
        if let Ok(v) = axum::http::HeaderValue::from_str(value) {
            headers.insert(name, v);
        }
    };
    set("content-type", asset.content_type());
    set("content-length", &bytes.len().to_string());
    set("x-content-type-options", "nosniff");
    set("cache-control", "private, max-age=3600");
    if asset == FeedbackAsset::Dom {
        set("content-security-policy", DOM_CSP);
    }
    (headers, Body::from(bytes)).into_response()
}
