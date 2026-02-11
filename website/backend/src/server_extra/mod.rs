use axum::{body::Body, extract::Path, response::IntoResponse};
use tracing::info;

pub async fn download_document(Path((collection_dataset, file_hash)): Path<(String, String)>) -> impl IntoResponse{
    info!("Downloading document: {}/{}", collection_dataset, file_hash);


    let data = b"your data";
    // let stream = ReaderStream::new(&data[..]);
    let body = Body::from(&data[..]);
    let headers = [
        ("Content-Type", "text/toml; charset=utf-8"),
        (
           "Content-Disposition",
            "attachment; filename=\"YourFileName.txt\"",
        ),
    ];
    (headers, body).into_response()
}