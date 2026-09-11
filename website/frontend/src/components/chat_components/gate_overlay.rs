//! Non-dismissible overlay over the composer when a new chat turn cannot start.

use common::chat_gate::ChatGateClosed;
use dioxus::prelude::*;

#[component]
pub fn ChatGateOverlay(reason: ChatGateClosed) -> Element {
    let lead = reason.overlay_lead();
    let action = reason.overlay_action();
    rsx! {
        div {
            class: "x-chat-gate-overlay",
            role: "status",
            style: "position: absolute; inset: 0; z-index: 4; \
                    background: rgba(255, 251, 235, 0.97); \
                    border: 1px solid #F59E0B; border-radius: 16px; \
                    padding: 28px 24px; \
                    display: flex; flex-direction: column; justify-content: center; \
                    gap: 10px; color: #92400E; pointer-events: auto;",
            p {
                style: "margin: 0; font-size: 18px; font-weight: 600; line-height: 1.4;",
                "{lead}"
            }
            p {
                style: "margin: 0; font-size: 14px; line-height: 1.5;",
                "{action}"
            }
        }
    }
}
