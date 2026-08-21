//! Serve a derived searchable PDF, ACL'd exactly like the original document.
//!
//! Separate from `download_document` because the two resolve the object completely
//! differently. A document is a `blobs` row (sometimes with its bytes in ClickHouse); a
//! derived PDF has **no** `blobs` row at all — `pdf_ocr_results` is the sole index of its
//! existence, by design, because a `blobs` row under `derived/` is what would let the
//! ingest walker find the object and start the re-derive loop.
//!
//! What the two do share is the permission check, and that is deliberate: an OCR'd PDF is
//! a rendering of the source document, so being allowed to read one is exactly being
//! allowed to read the other. The check is on the *source* document's dataset, before any
//! lookup.

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

async fn _download_ocr_pdf(
    user: &CurrentUser,
    Path((collection_dataset, pdf_hash, engine, languages)): Path<(String, String, String, String)>,
) -> anyhow::Result<impl IntoResponse> {
    permissions::assert_can_read(user, &collection_dataset).await?;

    let (blob_key, size_bytes) =
        lookup_blob_key(&collection_dataset, &pdf_hash, &engine, &languages).await?;

    // The derived object is in the collection's own bucket, beside the source PDF it was
    // built from — not in a single shared one, which would make one collection's derived
    // material reachable while reading another's.
    let collectionname = crate::db_utils::collectionname_of_dataset(&collection_dataset).await?;
    let bucket = crate::db_utils::collection_bucket(&collectionname);
    let client = crate::db_utils::s3_client().await?;
    let object = client
        .get_object()
        .bucket(&bucket)
        .key(&blob_key)
        .send()
        .await
        .with_context(|| format!("Failed to get {blob_key}"))?;
    let object_size = object.content_length().unwrap_or_default() as usize;
    // `ByteStream` has a `Stream` impl only through a `futures-core` version that is not
    // the one this workspace's `futures` resolves to, so `TryStreamExt` does not reach
    // it. Reading it as an `AsyncBufRead` and framing that back into chunks is the
    // conversion that does not depend on which `futures` won, and it still streams --
    // nothing here buffers the object.
    let stream = tokio_util::io::ReaderStream::new(object.body.into_async_read())
        .map_err(anyhow::Error::from);


    // `inline`, not `attachment`: this is the source the PDF viewer swaps to, so it has to
    // render in place rather than start a download.
    let headers: [(String, String); 3] = [
        ("Content-Type".to_string(), "application/pdf".to_string()),
        (
            "Content-Disposition".to_string(),
            format!("inline; filename=\"{pdf_hash}.{engine}.{languages}.pdf\""),
        ),
        (
            "Content-Length".to_string(),
            format!("{}", if object_size > 0 { object_size } else { size_bytes as usize }),
        ),
    ];
    Ok((headers, Body::from_stream(stream)).into_response())
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
            // why this asks `guard::is_not_found` rather than matching one message —
            // matching one message leaves every unknown dataset 500ing on this route.
            let message = e.to_string();
            if guard::is_not_found(&e) {
                return (StatusCode::NOT_FOUND, Body::from(message)).into_response();
            }
            tracing::error!("download_ocr_pdf: request failed: {:#?}", e);
            (StatusCode::INTERNAL_SERVER_ERROR, Body::from(message)).into_response()
        }
    }
}
