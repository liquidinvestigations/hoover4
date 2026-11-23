//! `/ai_chat/boards`, the investigation boards of the groups of the user.
//!
//! The page shows one page of boards at a time (`common::item_list`). The search matches a
//! part of the title or the generated summary and marks each match. The group filter and the
//! time order (`created_at`) change the list. The route query holds every value.

use common::item_list::ItemListQuery;
use dioxus::prelude::*;

use crate::api::board_api::page_boards;
use crate::api::error_util::user_facing_message;
use crate::components::chat_components::{BoardCard, ItemListBar, ItemPager};
use crate::routes::Route;
use crate::tr;

#[component]
pub fn AiBoardListPage(q: String, group: String, sort: String, page: String) -> Element {
    let query = use_memo(use_reactive!(|(q, group, sort, page)| {
        ItemListQuery::from_route(&q, &group, "", "", &sort, &page)
    }));
    let boards_res = use_resource(move || {
        let query = query();
        async move { page_boards(query).await }
    });
    let open = move |next: ItemListQuery| {
        navigator().push(Route::ai_board_list(&next));
    };
    let current = query();
    let groups = match &*boards_res.read() {
        Some(Ok(page)) => page.groups.clone(),
        _ => Vec::new(),
    };

    rsx! {
        Title { {tr!("board-list-hoover-search-investigation-boards")} }
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
                    {tr!("ai-chat-homepage-investigation-boards")}
                }
                Link {
                    class: "x-board-new",
                    to: Route::AiBoardCreatePage {},
                    style: "font-size: var(--x-text-sm); color: var(--x-link); text-decoration: none; font-weight: 500;",
                    {tr!("ai-chat-homepage-new-board")}
                }
            }
            ItemListBar { query: current.clone(), groups, show_chat_filters: false, on_change: open }
            match &*boards_res.read() {
                None => rsx! { div { style: "color: var(--x-ink-faint);", {tr!("ai-chat-homepage-loading-boards-u")} } },
                Some(Err(e)) => rsx! {
                    div { class: "x-error-display", style: "color: var(--x-danger);",
                        {tr!("ai-chat-homepage-could-not-load-the-boards", user_facing_message_e: user_facing_message(e))}
                    }
                },
                Some(Ok(page)) if page.items.is_empty() => rsx! {
                    div { style: "color: var(--x-ink-faint);",
                        if current.search_text().is_empty() && current.group.is_empty() {
                            {tr!("ai-chat-homepage-you-have-no-board-a")}
                        } else {
                            {tr!("item-list-no-board-matches")}
                        }
                    }
                },
                Some(Ok(page)) => rsx! {
                    div {
                        class: "x-board-list",
                        style: "display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 11px;",
                        for board in page.items.clone() {
                            BoardCard { key: "{board.board_id}", board, highlight: current.search_text() }
                        }
                    }
                    ItemPager { query: current.clone(), total: page.total, on_change: open }
                },
            }
        }
    }
}
