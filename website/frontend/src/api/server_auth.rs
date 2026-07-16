//! Extract the current user in server functions.

#[cfg(feature = "server")]
pub async fn extract_user() -> Result<common::current_user::CurrentUser, dioxus::prelude::ServerFnError> {
    use axum::Extension;
    use dioxus::fullstack::FullstackContext;
    let Extension(user): Extension<common::current_user::CurrentUser> =
        FullstackContext::extract().await?;
    Ok(user)
}
