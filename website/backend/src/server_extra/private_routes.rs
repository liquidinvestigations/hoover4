//! No blanket CORS on the routes that serve private bytes.
//!
//! `/_chat_artifact/…` and `/_download_document/…` return a user's captured page or an
//! investigation's document, behind an owner-or-admin check. An
//! `access-control-allow-origin: *` on either is a header saying "any origin may read
//! this" attached to a response whose whole job is deciding that not any origin may. A
//! browser will not hand a `*` response to a *credentialed* cross-origin read, so it was
//! never a live hole — it is a permission statement contradicting the code beneath it, on
//! the two routes where an audit of the headers must not be told the wrong thing. These
//! routes are same-origin only, so they say so.
//!
//! **Where the header actually came from, measured.** The application emits no CORS
//! headers at all: probed directly, the server binary answers `/_chat_artifact/…` with no
//! `access-control-*` and no `vary`. The `*` observed on port 12345 is added by the
//! `dx serve` dev proxy in front of it — the same dev-mode layer that injects the "Your
//! app is being rebuilt" toast, and it disappears with `dx serve`. This middleware is
//! therefore a guarantee about the application, not a fix for the dev server: it is
//! outermost in `main.rs` so that any CORS layer added inside the framework's router later
//! is stripped back off these two paths, and it costs one string compare per request.

use axum::{
    extract::Request,
    middleware::Next,
    response::Response,
};

/// Path prefixes that serve bytes behind a per-request permission check.
///
/// The same list the session middleware refuses without a session
/// ([`crate::auth::route_policy::CUSTOM_ROUTE_PREFIXES`]), read from there rather than
/// restated: a route that is private enough to need an ACL is private enough to need a
/// session, and two copies of the list would eventually disagree about one of them.
use crate::auth::route_policy::CUSTOM_ROUTE_PREFIXES as PRIVATE_PREFIXES;

pub fn is_private_path(path: &str) -> bool {
    PRIVATE_PREFIXES.iter().any(|p| path.starts_with(p))
}

pub async fn strip_cors_on_private_routes(request: Request, next: Next) -> Response {
    let private = is_private_path(request.uri().path());
    let mut response = next.run(request).await;
    if private {
        let headers = response.headers_mut();
        headers.remove("access-control-allow-origin");
        headers.remove("access-control-allow-credentials");
        headers.remove("access-control-expose-headers");
    }
    response
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_the_private_routes_are_affected() {
        assert!(is_private_path("/_chat_artifact/6f1a3c2e/page.html"));
        assert!(is_private_path("/_download_document/testdata_x/abc"));
        // The site itself, its assets and its server functions stay as the framework
        // serves them — narrowing CORS there is a different decision with a blast radius.
        assert!(!is_private_path("/"));
        assert!(!is_private_path("/wasm/frontend_bg.wasm"));
        assert!(!is_private_path("/api/search_for_results1234"));
        // Prefix, not `contains`: a path that merely mentions the route is not it.
        assert!(!is_private_path("/x/_chat_artifact/abc/page.html"));
    }
}
