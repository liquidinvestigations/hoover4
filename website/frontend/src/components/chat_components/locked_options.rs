//! Show the locked internet setting beside the chat title when the deployment enables it.

use dioxus::prelude::*;
use crate::tr;

/// The tooltip of the frozen switch.
pub fn locked_tooltip() -> String {
    tr!("chat-locked-options-start-a-new-chat-to")
}

#[component]
pub fn LockedInternetFlag(on: bool) -> Element {
    let internet_tools_enabled = crate::api::chat_api::use_internet_tools_enabled();
    if !internet_tools_enabled {
        return rsx! {};
    }
    let color = if on { "var(--x-ink)" } else { "var(--x-ink-faint)" };
    let label = tr!("chat-locked-options-internet-tools");
    rsx! {
        label {
            class: "x-chat-locked-internet",
            style: "display: flex; align-items: center; gap: 6px; font-size: var(--x-text-sm); \
                    color: {color}; cursor: not-allowed; user-select: none; flex-shrink: 0; white-space: nowrap;",
            title: locked_tooltip(),
            input {
                r#type: "checkbox",
                checked: on,
                disabled: true,
                title: locked_tooltip(),
                style: "cursor: not-allowed;",
                // A disabled checkbox is skipped by keyboard navigation, so the state
                // needs saying out loud for anyone not looking at the tick.
                aria_label: if on { tr!("chat-locked-options-on", label: label.to_string()) } else { tr!("chat-locked-options-off", label: label.to_string()) },
            }
            "{label}"
        }
    }
}
