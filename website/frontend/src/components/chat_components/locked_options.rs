//! Show the locked internet setting beside the chat title when the deployment enables it.

use dioxus::prelude::*;

/// The tooltip of the frozen switch.
pub const LOCKED_TOOLTIP: &str = "Start a new chat to change this setting.";

#[component]
pub fn LockedInternetFlag(on: bool) -> Element {
    let internet_tools_enabled = crate::api::chat_api::use_internet_tools_enabled();
    if !internet_tools_enabled {
        return rsx! {};
    }
    let color = if on { "var(--x-ink)" } else { "var(--x-ink-faint)" };
    let label = "Internet tools";
    rsx! {
        label {
            class: "x-chat-locked-internet",
            style: "display: flex; align-items: center; gap: 6px; font-size: var(--x-text-sm); \
                    color: {color}; cursor: not-allowed; user-select: none; flex-shrink: 0; white-space: nowrap;",
            title: LOCKED_TOOLTIP,
            input {
                r#type: "checkbox",
                checked: on,
                disabled: true,
                title: LOCKED_TOOLTIP,
                style: "cursor: not-allowed;",
                // A disabled checkbox is skipped by keyboard navigation, so the state
                // needs saying out loud for anyone not looking at the tick.
                aria_label: if on { "{label}: on" } else { "{label}: off" },
            }
            "{label}"
        }
    }
}
