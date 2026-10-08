//! Admin access guard, shows 403 for non-admins.

use dioxus::prelude::*;

use crate::components::admin_components::{C_DANGER, FONT, HELP_TEXT, PAGE_TITLE};
use crate::components::session_context::use_session_user;
use crate::components::suspend_boundary::LoadingIndicator;

#[component]
pub fn AdminGuard(children: Element) -> Element {
    // The gate's identity, not another `whoami`: this component sits under it, and a
    // second call to the mint route per page load is the one request that writes sessions.
    let user = use_session_user();
    rsx! {
        match &user {
            Some(u) if u.is_admin => rsx! { {children} },
            Some(u) => rsx! {
                div {
                    style: "display: flex; flex-direction: column; width: 100%; height: 100%; background: white; {FONT}",
                    div {
                        style: "padding: 24px 40px;",
                        h1 { style: "{PAGE_TITLE} color: {C_DANGER};", "Administration access required" }
                        p { style: "font-size: var(--x-text-md); margin: 0 0 8px;", "Signed in as {u.username}." }
                        p { style: "{HELP_TEXT} margin: 0;", "Ask an administrator for access to this section." }
                    }
                }
            },
            None => rsx! {
                div { style: "padding: 40px; display: flex; justify-content: center;", LoadingIndicator {} }
            },
        }
    }
}
