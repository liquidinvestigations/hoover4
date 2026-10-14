//! Read-only display of the internet tools switch, once a conversation has frozen it.
//!
//! Sits at the right end of the chat title row, taking over from the composer's checkbox once
//! the first message is sent. It is a `disabled` checkbox rather than text or an icon: a
//! checkbox is what the user ticked, so a checkbox shows their choice back to them, greyed
//! out, in the position they left it. Its tooltip says how to change it.

use dioxus::prelude::*;

/// The tooltip of the frozen switch.
pub const LOCKED_TOOLTIP: &str = "Start a new chat to change this setting.";

#[component]
pub fn LockedInternetFlag(on: bool) -> Element {
    // Off is stated, not merely absent: "Internet tools" greyed and unticked reads as
    // "this chat had no web access", which is exactly the question a user asks when an
    // answer says it could not reach the internet.
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
