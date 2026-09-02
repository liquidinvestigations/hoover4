//! The one place the browser reads its own identity, shared with the rest of the tree.
//!
//! The reverse proxy in front of the website asserts an identity on every request it
//! forwards, so the backend never reaches a page render with no session: every path but
//! `/favicon.ico` requires one. This runs `/api/whoami` once and hands the answer down
//! as context, so a component that needs the identity reads it from here instead of
//! calling `/api/whoami` again for itself.

use common::current_user::CurrentUser;
use dioxus::prelude::*;

use crate::api::auth_api::whoami;

/// The one `whoami` the app runs, shared with everything under [`SessionProvider`].
#[derive(Clone, Copy)]
pub struct SessionResource(pub Resource<Result<CurrentUser, ServerFnError>>);

/// The signed-in user, or `None` while the identity call is still in flight.
pub fn use_session_user() -> Option<CurrentUser> {
    let session = try_consume_context::<SessionResource>()?;
    let value = session.0.read();
    value.as_ref().and_then(|r| r.as_ref().ok()).cloned()
}

/// Runs `whoami` once and hands the result down as context.
///
/// Children render immediately; they do not wait for the identity to resolve, because
/// the backend has already refused the request if it carried none.
#[component]
pub fn SessionProvider(children: Element) -> Element {
    let session = use_resource(whoami);
    use_context_provider(|| SessionResource(session));
    rsx! { {children} }
}
