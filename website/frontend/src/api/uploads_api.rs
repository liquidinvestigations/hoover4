//! Upload page server function wrappers. The backend checks access in
//! `backend::api::uploads_api` with the rules of `backend::db_auth::uploads`.

use common::upload_pages::{ResumeFile, UploadBatchCursor, UploadBatchDetail, UploadBatchPage};
use common::uploads::LimitsResponse;
use dioxus::prelude::*;

#[cfg(feature = "server")]
use crate::api::error_util::to_server_fn_error;

/// The limits and the current upload targets of the caller.
#[server]
pub async fn upload_page_info() -> Result<LimitsResponse, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::uploads_api::upload_page_info(&user).await.map_err(to_server_fn_error)
}

/// One page of the batch list. An empty `collection` lists every readable collection.
#[server]
pub async fn list_upload_batches(
    collection: String,
    before: Option<UploadBatchCursor>,
) -> Result<UploadBatchPage, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::uploads_api::list_upload_batches(&user, collection, before)
        .await
        .map_err(to_server_fn_error)
}

/// The detail page of one batch, with one page of its file table.
#[server]
pub async fn upload_batch_detail(
    collection: String,
    batch_id: String,
    page: u32,
) -> Result<UploadBatchDetail, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::uploads_api::upload_batch_detail(&user, collection, batch_id, page)
        .await
        .map_err(to_server_fn_error)
}

/// The manifest of an `uploading` batch of the caller, for "Continue upload".
#[server]
pub async fn upload_batch_resume_files(
    collection: String,
    batch_id: String,
) -> Result<Vec<ResumeFile>, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::uploads_api::upload_batch_resume_files(&user, collection, batch_id)
        .await
        .map_err(to_server_fn_error)
}
