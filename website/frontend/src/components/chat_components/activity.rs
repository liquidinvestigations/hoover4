//! The activity line of a chat turn in progress.

use dioxus::prelude::*;

/// The one line that says a turn is in progress: a rotating icon and the text
/// `The bot is working...`. The session page renders it while its turn is active and not
/// interrupted, from the request until the turn ends, so it also covers the time before
/// the first stream row. It names no operation, because the turn state does not say which
/// one runs. A queued turn adds the slot it waits for on a second line.
#[component]
pub fn ChatActivity(
    /// `model` or `tool` while a step of the turn waits for a free slot, else empty.
    #[props(default)]
    queued_for: String,
) -> Element {
    let waiting = match queued_for.as_str() {
        "model" => "The turn waits for a free model slot.",
        "tool" => "The turn waits for a free tool slot.",
        _ => "",
    };
    rsx! {
        div { class: "x-chat-activity", "data-chat-activity": "true",
            div { class: "x-chat-activity-line",
                span { class: "x-chat-activity-spinner", "aria-hidden": "true",
                    dioxus_free_icons::Icon { icon: dioxus_free_icons::icons::md_action_icons::MdAutorenew, width: 16, height: 16 }
                }
                span { role: "status", "The bot is working..." }
            }
            if !waiting.is_empty() {
                div { class: "x-chat-activity-detail", "{waiting}" }
            }
        }
    }
}
