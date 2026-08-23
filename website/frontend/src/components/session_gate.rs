//! The one place the browser acquires a session, wrapped around every page's rsx.
//!
//! `whoami` is the only endpoint the backend lets an unidentified caller reach, and the
//! only one that writes a `set-cookie`. Every other server function and every custom byte
//! route answers `401` without a session. So the app must establish one *before* it
//! renders anything that calls the API, which is what this wrapper is: it sits between
//! the router and the rest of the tree, and children do not exist until the resource
//! resolves.
//!
//! Blocking is not a nicety here. Rendering pages first and letting each of their
//! resources race the sign-in would give every one of them a 401 to display on first
//! paint, on every visit.
//!
//! **The refusal is a page, not an error.** With `HOOVER4_DEMO_MODE` off the backend
//! provisions nobody, so an unauthenticated visitor gets `Err` from `whoami`. The
//! intended outcome of an access-controlled deployment, and it has to read as one. It is
//! rendered as prose, not raised into the error boundary, because a boundary presents the
//! site as broken and offers a retry that cannot work.

use common::current_user::CurrentUser;
use dioxus::prelude::*;

use crate::api::auth_api::whoami;
use crate::api::error_util::user_facing_message;
use crate::components::suspend_boundary::LoadingIndicator;

/// The one `whoami` the app runs, shared with everything under the gate.
///
/// Handed down as a context rather than fetched again wherever the identity is needed.
/// `whoami` is the mint route (the only endpoint that writes a session), so a component
/// that calls it for itself puts another request on the one endpoint the whole app is
/// gated behind, once per page load, and the count becomes "how many identity-aware
/// components does this route mount" rather than one.
#[derive(Clone, Copy)]
pub struct SessionResource(pub Resource<Result<CurrentUser, ServerFnError>>);

/// The signed-in user, or `None` while the gate's `whoami` is still in flight.
///
/// `None` means "not known yet", never "guest": a component that defaults an unknown
/// identity to a concrete answer draws the wrong control on first paint and then takes it
/// away, which reads as a bug. There is no error case here. A refused sign-in never
/// renders children at all.
pub fn use_session_user() -> Option<CurrentUser> {
    let session = try_consume_context::<SessionResource>()?;
    let value = session.0.read();
    value.as_ref().and_then(|r| r.as_ref().ok()).cloned()
}

#[component]
pub fn SessionGate(children: Element) -> Element {
    // Server-side rendering of the app shell carries no identity, so this resolves to an
    // error there and the shell renders the waiting state. The browser re-runs it against
    // `/api/whoami`, which is the request that mints and sets the cookie.
    let session = use_resource(whoami);
    use_context_provider(|| SessionResource(session));

    rsx! {
        match &*session.read() {
            Some(Ok(_)) => rsx! { {children} },
            Some(Err(e)) => rsx! { SignInRefused { message: user_facing_message(e) } },
            None => rsx! {
                div {
                    id: "x-session-gate-loading",
                    style: "display: flex; width: 100%; height: 100%; align-items: center; justify-content: center;",
                    LoadingIndicator {}
                }
            },
        }
    }
}

/// What a visitor this deployment will not admit sees instead of the site.
#[component]
fn SignInRefused(message: String) -> Element {
    rsx! {
        div {
            id: "x-session-refused",
            style: "display: flex; width: 100%; height: 100%; align-items: center; justify-content: center; \
                    background: #1C212D; font-family: Roboto, sans-serif; padding: 24px; box-sizing: border-box;",
            div {
                style: "max-width: 520px; background: white; border-radius: 6px; padding: 28px 32px;",
                h1 {
                    style: "margin: 0 0 12px; font-size: 20px; font-weight: 500; color: #1C212D;",
                    "Sign-in required"
                }
                p {
                    style: "margin: 0 0 16px; font-size: 14px; line-height: 1.5; color: #333;",
                    "{message}"
                }
                p {
                    style: "margin: 0; font-size: 12px; color: #666;",
                    "Nothing was loaded. Reloading this page will not change the outcome until you have an account."
                }
            }
        }
    }
}
