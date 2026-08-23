//! Which HTTP paths require a session, and the single path allowed to create one.
//!
//! The rule this file exists to make checkable: **exactly one route may mint a session.**
//! A fresh `set-cookie` on every response lets any client that does not store cookies (a
//! crawler, a `curl` loop, a link checker) create a `guest-<hex>` user and a `user_login`
//! event per request, so the user table and the metrics page grow without bound and stop
//! being readable.
//!
//! The shape is:
//!
//! * `/api/<whoami…>` is the **mint route**. It is the only place a session is created, a
//!   `guest-*` user is provisioned, or a `set-cookie` is written. The frontend blocks the
//!   whole app on it (`components::session_gate`), so it always runs first.
//! * every other server function and every custom byte-serving route **requires** an
//!   already-resolved session and answers `401` without one.
//! * the app shell (page routes, `/assets/…`, the wasm bundle) stays open, because the
//!   browser has to be able to load the code that calls the mint route. The shell contains
//!   no collection data; everything it renders arrives through a route that is checked.
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

/// Dioxus mounts every server function under this prefix.
const SERVER_FN_PREFIX: &str = "/api/";

/// Is this the one route that may create a session and write a `set-cookie`?
///
/// Matched through the telemetry allowlist rather than by string prefix, because Dioxus
/// mounts a server function at `/api/<name><decimal hash>` and the hash changes with the
/// function's signature. `whoami_evil` and `/x/api/whoami` are therefore not it.
pub fn is_session_mint_route(path: &str) -> bool {
    crate::api::telemetry::api_function_name(path) == Some("whoami")
}

/// Must this request already carry a resolved identity?
///
/// True for every server function except the mint route, and for every custom route.
pub fn requires_session(path: &str) -> bool {
    if is_session_mint_route(path) {
        return false;
    }
    path.starts_with(SERVER_FN_PREFIX)
        || CUSTOM_ROUTE_PREFIXES.iter().any(|p| path.starts_with(p))
}

/// The body of a refusal, written for whoever reads it in a network panel or a log.
pub const NO_SESSION_MESSAGE: &str =
    "no session: this endpoint requires a signed-in session. Load the site first, which \
     establishes one through /api/whoami, or authenticate through the reverse proxy.";

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_whoami_may_mint() {
        assert!(is_session_mint_route("/api/whoami"));
        assert!(is_session_mint_route("/api/whoami933738303362312952"));
        assert!(!is_session_mint_route("/api/whoami_evil"));
        assert!(!is_session_mint_route("/x/api/whoami"));
        assert!(!is_session_mint_route("/api/search_for_results"));
        assert!(!is_session_mint_route("/"));
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
    fn every_server_function_except_the_mint_route_requires_a_session() {
        assert!(requires_session("/api/search_for_results16667617515180422573"));
        assert!(requires_session("/api/chat_send_message"));
        // An unknown /api/ path is still an API path: the default is closed.
        assert!(requires_session("/api/something_new_nobody_listed"));
        assert!(!requires_session("/api/whoami933738303362312952"));
    }

    #[test]
    fn the_app_shell_stays_open() {
        // The browser must be able to load the code that calls the mint route. None of
        // these carry collection data.
        for path in [
            "/",
            "/search/o3Njb2xsZWN0aW9u/0/9g==/9g==",
            "/admin/metrics",
            "/assets/main.css",
            "/wasm/frontend_bg.wasm",
            "/favicon.ico",
        ] {
            assert!(!requires_session(path), "{path} must stay open");
        }
    }
}
