//! `/ai_chat/history`, full conversation list with delete.

use dioxus::prelude::*;

use crate::api::chat_api::{chat_delete_session, chat_list_sessions};
use crate::routes::Route;

#[component]
pub fn AiChatHistoryPage() -> Element {
    let mut sessions_res = use_resource(chat_list_sessions);

    rsx! {
        Title { "Hoover Search - Chat history" }
        div {
            style: "width: 100%; height: 100%; background: #F5F6F8; box-sizing: border-box; \
                    padding: 23px; overflow: auto;",
            div {
                style: "display: flex; align-items: center; gap: 15px; margin-bottom: 15px;",
                Link {
                    to: Route::AiChatPage {},
                    style: "color: var(--x-link); text-decoration: none; font-size: var(--x-text-md);",
                    "\u{2190} Back"
                }
                h1 {
                    style: "margin: 0; font-size: var(--x-text-page); line-height: var(--x-line-page); font-weight: 600; color: var(--x-ink-strong);",
                    "Conversation history"
                }
            }
            match sessions_res.read().as_ref() {
                None => rsx! { div { style: "color: var(--x-ink-faint);", "Loading\u{2026}" } },
                Some(Err(e)) => rsx! {
                    div {
                        class: "x-error-display",
                        style: "color: var(--x-danger);",
                        "Could not load history: {e}"
                    }
                },
                Some(Ok(list)) if list.is_empty() => rsx! {
                    div { style: "color: var(--x-ink-faint);", "No conversations yet." }
                },
                Some(Ok(list)) => rsx! {
                    div {
                        style: "display: flex; flex-direction: column; gap: 10px; max-width: 860px;",
                        for s in list.clone() {
                            div {
                                key: "{s.session_id}",
                                style: "background: white; border: 1px solid; border-color: var(--x-border); border-radius: 12px; \
                                        padding: 14px 16px; display: flex; gap: 12px; align-items: flex-start;",
                                Link {
                                    to: Route::ai_chat_session(s.session_id.clone(), None, None),
                                    style: "flex: 1; min-width: 0; text-decoration: none; color: inherit;",
                                    div {
                                        style: "font-size: var(--x-text-md); font-weight: 600; color: var(--x-ink-strong);",
                                        if s.title.is_empty() { "New chat" } else { "{s.title}" }
                                    }
                                    div {
                                        style: "font-size: var(--x-text-sm); color: var(--x-ink-muted); margin-top: 4px; line-height: 1.45;",
                                        if s.summary.is_empty() {
                                            "{s.message_count} messages"
                                        } else {
                                            "{s.summary}"
                                        }
                                    }
                                    div {
                                        style: "font-size: var(--x-text-xs); color: var(--x-ink-faint); margin-top: 6px;",
                                        "{s.message_count} messages · updated {s.updated_at}"
                                    }
                                }
                                button {
                                    style: "background: none; border: 1px solid #FEE2E2; color: var(--x-danger); \
                                            border-radius: 8px; padding: 6px 10px; cursor: pointer; \
                                            font-size: var(--x-text-xs); flex-shrink: 0;",
                                    title: "Delete conversation",
                                    onclick: {
                                        let id = s.session_id.clone();
                                        move |_| {
                                            let id = id.clone();
                                            spawn(async move {
                                                if chat_delete_session(id).await.is_ok() {
                                                    sessions_res.restart();
                                                }
                                            });
                                        }
                                    },
                                    "Delete"
                                }
                            }
                        }
                    }
                },
            }
        }
    }
}
