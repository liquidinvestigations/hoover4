//! Read-only display of the two agent switches, once a conversation has frozen them.
//!
//! Sits at the top of the transcript, where the composer's checkboxes used to be before
//! the first message. Both are rendered as genuinely `disabled` inputs rather than as
//! text or icons: a checkbox is what the user ticked, so a checkbox is what should show
//! their choice back to them — greyed out, in the position they left it.

use common::chat_types::ChatOptions;
use dioxus::prelude::*;

#[component]
pub fn LockedOptionsBar(options: ChatOptions) -> Element {
    rsx! {
        div {
            style: "display: flex; align-items: center; gap: 16px; flex-wrap: wrap; \
                    padding: 8px 14px; background: #F8FAFC; border-bottom: 1px solid #E5E7EB; \
                    flex-shrink: 0;",
            LockedFlag { label: "Deep Research", on: options.deep_research }
            LockedFlag { label: "Internet tools", on: options.internet_tools }
            div { style: "flex: 1;" }
            span {
                style: "font-size: 12px; color: #94A3B8;",
                title: "These decide which agent answers, so they are fixed once the \
                        conversation starts. Start a new chat to change them.",
                "\u{1f512} locked for this conversation"
            }
        }
    }
}

#[component]
fn LockedFlag(label: &'static str, on: bool) -> Element {
    // Off is stated, not merely absent: "Internet tools" greyed and unticked reads as
    // "this chat had no web access", which is exactly the question a user asks when an
    // answer says it could not reach the internet.
    let color = if on { "#334155" } else { "#94A3B8" };
    rsx! {
        label {
            style: "display: flex; align-items: center; gap: 6px; font-size: 13px; \
                    color: {color}; cursor: not-allowed; user-select: none;",
            input {
                r#type: "checkbox",
                checked: on,
                disabled: true,
                // A disabled checkbox is skipped by keyboard navigation, so the state
                // needs saying out loud for anyone not looking at the tick.
                aria_label: if on { "{label}: on" } else { "{label}: off" },
            }
            "{label}"
        }
    }
}
