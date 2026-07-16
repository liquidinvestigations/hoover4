//! Shared server function error mapping (server-only: references the backend crate).

#[cfg(feature = "server")]
pub fn to_server_fn_error(e: anyhow::Error) -> dioxus::prelude::ServerFnError {
    use dioxus::prelude::ServerFnError;
    if backend::auth::guard::is_forbidden(&e) {
        ServerFnError::ServerError {
            message: e.to_string(),
            code: 403,
            details: None,
        }
    } else {
        ServerFnError::ServerError {
            message: e.to_string(),
            code: 500,
            details: None,
        }
    }
}
