//! Authentication server functions.

use common::current_user::CurrentUser;
use dioxus::prelude::*;

#[server]
pub async fn whoami() -> Result<CurrentUser, ServerFnError> {
    crate::api::server_auth::extract_user().await
}
