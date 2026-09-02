//! Extract the current user in server functions.

/// The caller's identity, or a `401` if the request carried none.
///
/// The session middleware attaches a `CurrentUser` only when a cookie or a proxy-set
/// header resolved one, and it refuses every route except `/favicon.ico` outright when
/// it cannot, so a missing extension here means the request that reached this process
/// carried no identity the middleware could resolve.
///
/// The message is written for a reader, and the code is `401` rather than the default
/// `500`: nothing broke, the request proved nothing.
#[cfg(feature = "server")]
pub async fn extract_user() -> Result<common::current_user::CurrentUser, dioxus::prelude::ServerFnError> {
    use axum::Extension;
    use dioxus::fullstack::FullstackContext;
    use dioxus::prelude::ServerFnError;

    let extension: Result<Extension<common::current_user::CurrentUser>, _> =
        FullstackContext::extract().await;
    match extension {
        Ok(Extension(user)) => Ok(user),
        Err(_) => Err(ServerFnError::ServerError {
            message: NOT_SIGNED_IN.to_string(),
            code: 401,
            details: None,
        }),
    }
}

/// Shown to a visitor a deployment will not let in. Kept next to the code that produces
/// it so the wording cannot drift from the condition; the client renders whatever the
/// server sent rather than a second copy of this sentence.
#[cfg(feature = "server")]
pub const NOT_SIGNED_IN: &str =
    "Not signed in. This deployment requires an authenticated session and does not issue \
     anonymous ones. Sign in through your organisation's proxy, or ask an administrator \
     for access.";
