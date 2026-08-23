//! Shared server function error mapping, in both directions: an `anyhow::Error` on its
//! way out to a status code, and a `ServerFnError` on its way to a reader.

use dioxus::prelude::ServerFnError;

/// The one sentence to put in front of a reader when a server call failed.
///
/// Neither of the derived renderings is usable on a page. `Debug` prints the whole
/// struct: `ServerError { message: "…", code: 500, details: None }`, and `Display`
/// still wraps the message in *error running server function: … (details: …)*. The
/// backend already writes `message` for a person; everything around it is machinery.
///
/// **Every error surface goes through here.** Formatting the error at each call site is
/// how a Rust struct ends up printed across the pagination of a search page.
pub fn user_facing_message(error: &ServerFnError) -> String {
    match error {
        ServerFnError::ServerError { message, .. } => message.clone(),
        // The client could not reach the server at all, so the server's wording for it
        // does not exist and the transport detail helps nobody.
        ServerFnError::Request(_) => {
            "Could not reach the server. Check your connection and try again.".to_string()
        }
        other => other.to_string(),
    }
}

/// Did the caller ask for something impossible, rather than the server break?
///
/// A rejected search query is the live case: the message is advice for the person who
/// typed it, and presenting it the way a crash is presented tells them the site is
/// broken when the next keystroke would fix it.
pub fn is_user_input_error(error: &ServerFnError) -> bool {
    matches!(error, ServerFnError::ServerError { code, .. } if (400..500).contains(code))
}

#[cfg(feature = "server")]
pub fn to_server_fn_error(e: anyhow::Error) -> dioxus::prelude::ServerFnError {
    use dioxus::prelude::ServerFnError;
    // 400 first: it is matched by error TYPE while the other two match message text, so
    // it cannot be shadowed by prose that happens to contain "not found".
    //
    // Then 404 before 403: `is_not_found` is the narrower test, and a chat session that
    // is not the caller's answers "not found" on purpose rather than confirming it exists.
    let code = if backend::auth::guard::is_bad_request(&e) {
        400
    } else if backend::auth::guard::is_not_found(&e) {
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
