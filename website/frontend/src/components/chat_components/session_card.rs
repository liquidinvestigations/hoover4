//! Homepage / history card for one past conversation.

use common::chat_types::ChatSessionItem;
use dioxus::prelude::*;
use dioxus_free_icons::Icon;
use dioxus_free_icons::icons::md_communication_icons::MdChat;

use crate::routes::Route;

#[component]
pub fn ChatSessionCard(session: ChatSessionItem) -> Element {
    let title = if session.title.is_empty() {
        "New chat".to_string()
    } else {
        session.title.clone()
    };
    let summary = if session.summary.is_empty() {
        format!("{} messages", session.message_count)
    } else {
        session.summary.clone()
    };

    rsx! {
        Link {
            to: Route::ai_chat_session(session.session_id.clone(), None, None),
            style: "text-decoration: none; color: inherit; display: block;",
            div {
                style: "background: white; border: 1px solid; border-color: var(--x-border); border-radius: var(--x-radius); \
                        padding: 11px 15px; display: flex; gap: 11px; align-items: flex-start; \
                        min-height: 88px; box-sizing: border-box; transition: border-color 0.15s;",
                div {
                    style: "width: 40px; height: 40px; border-radius: 999px; background: #EEF2FF; \
                            color: var(--x-link); display: flex; align-items: center; justify-content: center; \
                            flex-shrink: 0; font-size: var(--x-text-xl);",
                    Icon { icon: MdChat, style: "width: 19px; height: 19px;" }
                }
                div { style: "min-width: 0; flex: 1;",
                    div {
                        style: "font-size: var(--x-text-body); line-height: var(--x-line-body); font-weight: 600; color: var(--x-ink-strong); \
                                white-space: nowrap; overflow: hidden; text-overflow: ellipsis;",
                        "{title}"
                    }
                    div {
                        style: "font-size: var(--x-text-detail); color: var(--x-ink-muted); margin-top: 4px; line-height: var(--x-line-detail); \
                                display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; \
                                overflow: hidden;",
                        "{summary}"
                    }
                }
            }
        }
    }
}
