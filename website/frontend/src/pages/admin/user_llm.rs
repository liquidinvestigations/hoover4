//! Stub for Plan 2 — `/admin/users/:username/llm`. Replace this body; keep the component name.

use dioxus::prelude::*;

#[component]
pub fn AdminUserLlmPage(username: String) -> Element {
    rsx! {
        Title { "Admin — LLM use — {username}" }
        div {
            style: "padding: 24px; color: #6B7280;",
            "Per-user LLM usage for {username} — Plan 2 implements this."
        }
    }
}
