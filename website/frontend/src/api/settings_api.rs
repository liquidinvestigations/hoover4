//! The language settings of the signed-in user.

use common::language::LanguageSettings;
use dioxus::prelude::*;

#[cfg(feature = "server")]
use crate::api::error_util::to_server_fn_error;

/// The browser's `Accept-Language` header of the current request.
#[cfg(feature = "server")]
async fn accept_language() -> Option<String> {
    use dioxus::fullstack::FullstackContext;
    let headers: axum::http::HeaderMap = FullstackContext::extract().await.ok()?;
    headers
        .get(axum::http::header::ACCEPT_LANGUAGE)
        .and_then(|value| value.to_str().ok())
        .map(str::to_string)
}

/// The saved and the resolved languages of the caller.
#[server]
pub async fn language_settings() -> Result<LanguageSettings, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::settings::language_settings(&user, accept_language().await.as_deref())
        .await
        .map_err(to_server_fn_error)
}

/// Save the caller's interface and agent languages. An empty code clears a setting.
#[server]
pub async fn save_language_settings(interface: String, agent: String) -> Result<LanguageSettings, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::settings::save_language_settings(&user, &interface, &agent, accept_language().await.as_deref())
        .await
        .map_err(to_server_fn_error)
}
