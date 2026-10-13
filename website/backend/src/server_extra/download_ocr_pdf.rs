//! Serve complete searchable PDFs after dataset access verification.
//! Retained whole objects stream directly. Multipart overlays use temporary assembly.

use axum::{
    body::Body,
    extract::{Extension, Path},
    response::{IntoResponse, Response},
};
use common::{current_user::CurrentUser, document_sources::DocumentPdfSourceItem, search_result::DocumentIdentifier};
use reqwest::StatusCode;

use crate::{
    auth::{guard, permissions},
    db_utils::clickhouse_utils::get_client_for_dataset,
};

/// The prefix every derived object lives under. A stored `blob_key` that does not start
/// with it is not served: the row is the only thing naming the object, so a row that has
/// been made to point somewhere else would otherwise turn this route into a reader for
/// any key in the bucket.
const DERIVED_PREFIX: &str = "derived/";

async fn lookup_blob_key(
    collection_dataset: &str,
    pdf_hash: &str,
    engine: &str,
    languages: &str,
) -> anyhow::Result<(String, u64)> {
    let client = get_client_for_dataset(collection_dataset).await?;
    let rows = client
        .query(
            "SELECT argMax(blob_key, updated_at), argMax(size_bytes, updated_at) \
             FROM pdf_ocr_results \
             WHERE collection_dataset = ? AND pdf_hash = ? AND engine = ? AND languages = ? \
             GROUP BY collection_dataset, pdf_hash, engine, languages \
             HAVING argMax(is_deleted, updated_at) = 0",
        )
        .bind(collection_dataset)
        .bind(pdf_hash)
        .bind(engine)
        .bind(languages)
        .fetch_all::<(String, u64)>()
        .await?;

    let (key, size) = rows
        .into_iter()
        .next()
        .ok_or_else(|| {
            anyhow::anyhow!("no OCR'd PDF for {pdf_hash} ({engine}+{languages}): not found")
        })?;
    if !key.starts_with(DERIVED_PREFIX) {
        anyhow::bail!("refusing to serve {key:?}: it is not under {DERIVED_PREFIX}");
    }
    Ok((key, size))
}

pub async fn read_ocr_pdf_bytes(
    user: &CurrentUser,
    document_identifier: &DocumentIdentifier,
    source: &DocumentPdfSourceItem,
    max_bytes: u64,
) -> anyhow::Result<Vec<u8>> {
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    anyhow::ensure!(source.is_ocr(), "an OCR source is required");
    let (blob_key, size_bytes) = lookup_blob_key(
        &document_identifier.collection_dataset,
        &document_identifier.file_hash,
        &source.engine,
        &source.languages,
    )
    .await?;
    anyhow::ensure!(size_bytes <= max_bytes, "OCR PDF is over the search byte limit");
    let collectionname = crate::db_utils::collectionname_of_dataset(&document_identifier.collection_dataset).await?;
    let bucket = crate::db_utils::collection_bucket(&collectionname);
    let client = crate::db_utils::s3_client().await?;
    let object = client.get_object().bucket(bucket).key(blob_key).send().await?;
    read_limited_body(object.body.into_async_read(), max_bytes).await
}

async fn read_limited_body(
    reader: impl tokio::io::AsyncRead + Unpin,
    max_bytes: u64,
) -> anyhow::Result<Vec<u8>> {
    use tokio::io::AsyncReadExt;

    let mut bytes = Vec::new();
    reader.take(max_bytes.saturating_add(1)).read_to_end(&mut bytes).await?;
    anyhow::ensure!(bytes.len() as u64 <= max_bytes, "OCR PDF is over the search byte limit");
    Ok(bytes)
}

#[cfg(test)]
mod search_body_tests {
    use super::read_limited_body;

    #[tokio::test]
    async fn received_body_over_limit_is_rejected() {
        let result = read_limited_body(&b"more bytes than recorded"[..], 4).await;
        assert!(result.unwrap_err().to_string().contains("over the search byte limit"));
    }

    #[tokio::test]
    async fn received_body_at_limit_is_complete() {
        assert_eq!(read_limited_body(&b"pdf bytes"[..], 9).await.unwrap(), b"pdf bytes");
    }
}

async fn _download_ocr_pdf(
    user: &CurrentUser,
    Path((collection_dataset, pdf_hash, engine, languages)): Path<(String, String, String, String)>,
) -> anyhow::Result<impl IntoResponse> {
    permissions::assert_can_read(user, &collection_dataset).await?;

    let id = DocumentIdentifier { collection_dataset, file_hash: pdf_hash };
    let sources = crate::api::documents::get_document_sources::get_pdf_sources(user,id.clone()).await?;
    let source = sources.into_iter().find(|source|source.engine == engine && source.languages == languages)
        .ok_or_else(||anyhow::anyhow!("PDF source not found"))?;
    crate::server_extra::pdf_parts::complete_response(user,&id,&source).await

}

pub async fn download_ocr_pdf(
    Extension(user): Extension<CurrentUser>,
    path: Path<(String, String, String, String)>,
) -> Response {
    match _download_ocr_pdf(&user, path).await {
        Ok(response) => response.into_response(),
        Err(e) => {
            if guard::is_forbidden(&e) {
                return (StatusCode::FORBIDDEN, Body::from(e.to_string())).into_response();
            }
            // A missing variant is a 404, not a 500: the selector offers what
            // `pdf_ocr_results` said existed, and a purge between the page load and the
            // click is a normal race rather than a broken server. An unknown dataset is
            // the same answer and reaches here from `get_client_for_dataset`, which is
            // why this asks `guard::is_not_found` rather than matching one message.
            // Matching one message leaves every unknown dataset 500ing on this route.
            let message = e.to_string();
            if guard::is_not_found(&e) {
                return (StatusCode::NOT_FOUND, Body::from(message)).into_response();
            }
            tracing::error!("download_ocr_pdf: request failed: {:#?}", e);
            (StatusCode::INTERNAL_SERVER_ERROR, Body::from(message)).into_response()
        }
    }
}
