//! `/ai_chat/history`, the conversation history of the groups of the user.
//!
//! The page shows one page of chats at a time (`common::item_list`). The search matches a
//! part of the title or the summary and marks each match. The filters are the group, the
//! creator ("Chats started by me") and the explore chats of the boards, and the time order
//! is the last activity. The route query holds every value.
//!
//! A board chat is marked as such and has no delete button, because its board deletes it
//! when the board is dropped. Another chat has a delete button when the user created it or
//! is an administrator. A running chat shows a "Running" chip in place of the button.

use common::board_types::is_board_session;
use common::item_list::ItemListQuery;
use dioxus::prelude::*;

use crate::api::chat_api::{chat_delete_session, chat_page_sessions};
use crate::api::error_util::user_facing_message;
use crate::components::chat_components::{GroupName, Highlighted, ItemListBar, ItemPager, RunningChip};
use crate::routes::Route;
use crate::tr;

#[component]
pub fn AiChatHistoryPage(q: String, group: String, mine: String, boards: String, sort: String, page: String) -> Element {
    let query = use_memo(use_reactive!(|(q, group, mine, boards, sort, page)| {
        ItemListQuery::from_route(&q, &group, &mine, &boards, &sort, &page)
    }));
    let mut sessions_res = use_resource(move || {
        let query = query();
        async move { chat_page_sessions(query).await }
    });
    let open = move |next: ItemListQuery| {
        navigator().push(Route::ai_chat_history(&next));
    };
    let current = query();
    let groups = match &*sessions_res.read() {
        Some(Ok(page)) => page.groups.clone(),
        _ => Vec::new(),
    };

    rsx! {
        Title { {tr!("ai-chat-history-hoover-search-chat-history")} }
        div {
            style: "width: 100%; height: 100%; background: #F5F6F8; box-sizing: border-box; \
                    padding: 23px; overflow: auto;",
            div {
                style: "display: flex; align-items: center; gap: 15px; margin-bottom: 15px;",
                Link {
                    to: Route::AiChatPage {},
                    style: "color: var(--x-link); text-decoration: none; font-size: var(--x-text-md);",
                    {tr!("ai-chat-history-u-back")}
                }
                h1 {
                    style: "margin: 0; font-size: var(--x-text-page); line-height: var(--x-line-page); font-weight: 600; color: var(--x-ink-strong);",
                    {tr!("ai-chat-history-conversation-history")}
                }
            }
            ItemListBar { query: current.clone(), groups, show_chat_filters: true, on_change: open }
            match sessions_res.read().as_ref() {
                None => rsx! { div { style: "color: var(--x-ink-faint);", {tr!("ai-chat-history-loading-u")} } },
                Some(Err(e)) => rsx! {
                    div {
                        class: "x-error-display",
                        style: "color: var(--x-danger);",
                        {tr!("ai-chat-history-could-not-load-history", e: user_facing_message(e))}
                    }
                },
                Some(Ok(page)) if page.items.is_empty() => rsx! {
                    div { style: "color: var(--x-ink-faint);",
                        if current.search_text().is_empty() && current.group.is_empty() && !current.mine {
                            {tr!("ai-chat-history-no-conversations-yet")}
                        } else {
                            {tr!("item-list-no-chat-matches")}
                        }
                    }
                },
                Some(Ok(page)) => rsx! {
                    div {
                        style: "display: flex; flex-direction: column; gap: 10px; max-width: 860px;",
                        for s in page.items.clone() {
                            div {
                                key: "{s.session_id}",
                                class: "x-history-row",
                                style: "background: white; border: 1px solid; border-color: var(--x-border); border-radius: 12px; \
                                        padding: 14px 16px; display: flex; gap: 12px; align-items: flex-start;",
                                Link {
                                    to: Route::ai_chat_session(s.session_id.clone(), None, None),
                                    style: "flex: 1; min-width: 0; text-decoration: none; color: inherit;",
                                    div {
                                        style: "font-size: var(--x-text-md); font-weight: 600; color: var(--x-ink-strong);",
                                        if is_board_session(&s.session_id) {
                                            span {
                                                style: "font-size: var(--x-text-xs); font-weight: 500; color: var(--x-ink-muted); \
                                                        border: 1px solid; border-color: var(--x-border); border-radius: 6px; \
                                                        padding: 1px 6px; margin-right: 8px;",
                                                {tr!("ai-chat-history-board")}
                                            }
                                        }
                                        if s.title.is_empty() {
                                            {tr!("ai-chat-history-new-chat")}
                                        } else {
                                            Highlighted { text: s.title.clone(), needle: current.search_text() }
                                        }
                                    }
                                    div {
                                        style: "font-size: var(--x-text-sm); color: var(--x-ink-muted); margin-top: 4px; line-height: 1.45;",
                                        if s.summary.is_empty() {
                                            {tr!("ai-chat-history-messages", s_message_count: s.message_count)}
                                        } else {
                                            Highlighted { text: s.summary.clone(), needle: current.search_text() }
                                        }
                                    }
                                    div {
                                        style: "font-size: var(--x-text-xs); color: var(--x-ink-faint); margin-top: 6px; \
                                                display: flex; gap: 10px; align-items: center; flex-wrap: wrap;",
                                        span { {tr!("ai-chat-history-messages-updated", s_message_count: s.message_count, s_updated_at: s.updated_at.to_string())} }
                                        GroupName { name: s.owner_group.clone() }
                                    }
                                }
                                if s.running {
                                    RunningChip {}
                                } else if !is_board_session(&s.session_id) && s.can_delete {
                                    button {
                                        class: "x-history-delete",
                                        style: "background: none; border: 1px solid #FEE2E2; color: var(--x-danger); \
                                                border-radius: 8px; padding: 6px 10px; cursor: pointer; \
                                                font-size: var(--x-text-xs); flex-shrink: 0;",
                                        title: tr!("ai-chat-history-delete-conversation"),
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
                                        {tr!("ai-chat-history-delete")}
                                    }
                                }
                            }
                        }
                    }
                    ItemPager { query: current.clone(), total: page.total, on_change: open }
                },
            }
        }
    }
}
