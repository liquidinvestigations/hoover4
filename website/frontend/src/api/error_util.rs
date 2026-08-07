//! Shared server function error mapping (server-only: references the backend crate).

#[cfg(feature = "server")]
pub fn to_server_fn_error(e: anyhow::Error) -> dioxus::prelude::ServerFnError {
    use dioxus::prelude::ServerFnError;
    // 404 before 403: `is_not_found` is the narrower test, and a chat session that is not
    // the caller's answers "not found" on purpose rather than confirming it exists.
    let code = if backend::auth::guard::is_not_found(&e) {
        404
    } else if backend::auth::guard::is_forbidden(&e) {
        403
    } else {
        500
    };
    ServerFnError::ServerError {
        message: e.to_string(),
        code,
        details: None,
    }
}
