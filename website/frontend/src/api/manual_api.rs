//! The manual pages (`/docs`, `/docs/admin`). The backend reads the manuals once at start
//! (`backend::api::manual`), and only an administrator gets the administration manual.

use common::manual::ManualPage;
use dioxus::prelude::*;

#[cfg(feature = "server")]
use crate::api::error_util::to_server_fn_error;

/// One manual. `admin` asks for the administration manual, which is "not found" for a user
/// who is not an administrator.
#[server]
pub async fn manual_page(admin: bool) -> Result<ManualPage, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::manual::manual_page(&user, admin).await.map_err(to_server_fn_error)
}
