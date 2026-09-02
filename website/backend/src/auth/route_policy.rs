//! Which HTTP paths require a session.
//!
//! **Every path requires an already-resolved session, except `/favicon.ico`.** The
//! reverse proxy in front of the website asserts an identity on every request it
//! forwards, so there is nothing left to load before an identity exists: the app shell,
//! the wasm bundle and `/assets/…` all require a session like every server function and
//! every custom byte-serving route.
//!
//! Nothing here decides *what* a resolved user may read. That is
//! [`crate::auth::permissions`]. This is only the question of whether anyone is asking.

/// Custom (non-server-function) routes mounted in `main.rs`.
///
/// Each serves bytes behind a per-request permission check, so each needs a caller to
/// check. Adding a route to `main.rs` without adding it here is the mistake this constant
/// exists to make visible: `every_custom_route_requires_a_session` in the tests below
/// enumerates it, and `server_extra::private_routes` reads the same list for its CORS
/// decision, so the two cannot drift.
pub const CUSTOM_ROUTE_PREFIXES: [&str; 3] = [
    "/_chat_artifact/",
    "/_download_document/",
    "/_download_ocr_pdf/",
];

/// The one path a caller with no identity may still reach.
const OPEN_PATH: &str = "/favicon.ico";

/// Must this request already carry a resolved identity?
///
/// True for every path except [`OPEN_PATH`].
pub fn requires_session(path: &str) -> bool {
    path != OPEN_PATH
}

/// The body of a refusal, written for whoever reads it in a network panel or a log.
pub const NO_SESSION_MESSAGE: &str =
    "no session: this endpoint requires a signed-in session. Authenticate through the \
     reverse proxy in front of this deployment.";

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_the_favicon_stays_open() {
        assert!(!requires_session("/favicon.ico"));
        assert!(requires_session("/"));
        assert!(requires_session("/assets/main.css"));
        assert!(requires_session("/wasm/frontend_bg.wasm"));
    }

    #[test]
    fn every_custom_route_requires_a_session() {
        // The literal paths mounted in `main.rs`, written out rather than derived, so a
        // route added there and forgotten here fails a test instead of shipping open.
        for path in [
            "/_download_document/testdata_testfiles/abc123",
            "/_download_ocr_pdf/testdata_testfiles/abc123/tesseract/eng",
            "/_chat_artifact/6f1a3c2e/page.html",
        ] {
            assert!(requires_session(path), "{path} must require a session");
        }
    }

    #[test]
    fn every_server_function_requires_a_session() {
        assert!(requires_session("/api/search_for_results16667617515180422573"));
        assert!(requires_session("/api/chat_send_message"));
        assert!(requires_session("/api/whoami933738303362312952"));
        // An unknown /api/ path is still an API path: the default is closed.
        assert!(requires_session("/api/something_new_nobody_listed"));
    }

    #[test]
    fn the_app_shell_now_requires_a_session() {
        // The browser has an identity before it ever loads the shell: the proxy in
        // front asserts one on every request, this one included.
        for path in [
            "/",
            "/search/o3Njb2xsZWN0aW9u/0/9g==/9g==",
            "/admin/metrics",
            "/assets/main.css",
            "/wasm/frontend_bg.wasm",
        ] {
            assert!(requires_session(path), "{path} must require a session");
        }
    }
}
