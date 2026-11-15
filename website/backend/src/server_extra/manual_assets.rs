//! Serve the images of the manuals (`img/` and `crops/` of the manual folder).
//!
//! The manual page (`/docs`) and the administration manual page use them. The images hold
//! screenshots of the product and no data of a collection, so every signed-in person reads
//! them. `api::manual::asset_path` refuses every path outside the two image folders.

use axum::{
    body::Body,
    extract::Path,
    http::{header, StatusCode},
    response::{IntoResponse, Response},
};

use crate::api::manual;

/// The content type of an image file name.
fn content_type(path: &str) -> &'static str {
    match path.rsplit('.').next().map(str::to_ascii_lowercase).as_deref() {
        Some("png") => "image/png",
        Some("jpg" | "jpeg") => "image/jpeg",
        Some("webp") => "image/webp",
        Some("gif") => "image/gif",
        Some("svg") => "image/svg+xml",
        _ => "application/octet-stream",
    }
}

pub async fn manual_asset(Path(path): Path<String>) -> Response {
    let Some(file) = manual::asset_path(&manual::load().dir, &path) else {
        return (StatusCode::NOT_FOUND, "not found").into_response();
    };
    match tokio::fs::read(&file).await {
        Ok(bytes) => (
            [
                (header::CONTENT_TYPE, content_type(&path)),
                (header::CACHE_CONTROL, "private, max-age=3600"),
            ],
            Body::from(bytes),
        )
            .into_response(),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            (StatusCode::NOT_FOUND, "not found").into_response()
        }
        Err(error) => {
            tracing::error!("manual_asset: cannot read {}: {error}", file.display());
            (StatusCode::INTERNAL_SERVER_ERROR, "the image cannot be read").into_response()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::content_type;

    #[test]
    fn image_types_follow_the_extension() {
        assert_eq!(content_type("img/a.PNG"), "image/png");
        assert_eq!(content_type("crops/b.jpeg"), "image/jpeg");
        assert_eq!(content_type("img/c"), "application/octet-stream");
    }
}
