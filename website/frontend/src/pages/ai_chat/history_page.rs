//! `/ai_chat/history` — full conversation list with delete.

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
                    padding: 32px 28px; overflow: auto;",
            div {
                style: "display: flex; align-items: center; gap: 16px; margin-bottom: 20px;",
                Link {
                    to: Route::AiChatPage {},
                    style: "color: #4F46E5; text-decoration: none; font-size: 14px;",
                    "\u{2190} Back"
                }
                h1 {
                    style: "margin: 0; font-size: 24px; font-weight: 600; color: #0F172A;",
                    "Conversation history"
                }
            }
            match sessions_res.read().as_ref() {
                None => rsx! { div { style: "color: #94A3B8;", "Loading\u{2026}" } },
                Some(Err(e)) => rsx! {
                    div { style: "color: #B91C1C;", "Could not load history: {e}" }
                },
                Some(Ok(list)) if list.is_empty() => rsx! {
                    div { style: "color: #94A3B8;", "No conversations yet." }
                },
                Some(Ok(list)) => rsx! {
                    div {
                        style: "display: flex; flex-direction: column; gap: 10px; max-width: 860px;",
                        for s in list.clone() {
                            div {
                                key: "{s.session_id}",
                                style: "background: white; border: 1px solid #E5E7EB; border-radius: 12px; \
                                        padding: 14px 16px; display: flex; gap: 12px; align-items: flex-start;",
                                Link {
                                    to: Route::ai_chat_session(s.session_id.clone(), None, None),
                                    style: "flex: 1; min-width: 0; text-decoration: none; color: inherit;",
                                    div {
                                        style: "font-size: 15px; font-weight: 600; color: #0F172A;",
                                        if s.title.is_empty() { "New chat" } else { "{s.title}" }
                                    }
                                    div {
                                        style: "font-size: 13px; color: #64748B; margin-top: 4px; line-height: 1.45;",
                                        if s.summary.is_empty() {
                                            "{s.message_count} messages"
                                        } else {
                                            "{s.summary}"
                                        }
                                    }
                                    div {
                                        style: "font-size: 11px; color: #94A3B8; margin-top: 6px;",
                                        "{s.message_count} messages · updated {s.updated_at}"
                                    }
                                }
                                button {
                                    style: "background: none; border: 1px solid #FEE2E2; color: #B91C1C; \
                                            border-radius: 8px; padding: 6px 10px; cursor: pointer; \
                                            font-size: 12px; flex-shrink: 0;",
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
