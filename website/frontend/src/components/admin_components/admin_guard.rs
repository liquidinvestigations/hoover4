//! Admin access guard, shows 403 for non-admins.

use dioxus::prelude::*;

use crate::components::admin_components::{C_DANGER, C_HEADER, C_YELLOW, FONT};
use crate::components::session_gate::use_session_user;
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
                    header {
                        style: "background: {C_HEADER}; padding: 12px 40px;",
                        span { style: "color: {C_YELLOW}; font-size: 22px;", "Hoover4 administration" }
                    }
                    div {
                        style: "padding: 40px;",
                        div {
                            style: "max-width: 520px; border: 1px solid #eee; padding: 24px;",
                            h1 { style: "margin: 0 0 12px; color: {C_DANGER}; font-size: 20px; font-weight: 400;", "403: admin access required" }
                            p { style: "color: #333; font-size: 13px; margin: 0 0 8px;", "Signed in as: {u.username}" }
                            p { style: "color: #666; font-size: 13px; margin: 0;", "Contact an administrator if you need access to this section." }
                        }
                    }
                }
            },
            None => rsx! {
                div { style: "padding: 40px; display: flex; justify-content: center;", LoadingIndicator {} }
            },
        }
    }
}
