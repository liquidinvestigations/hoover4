//! The cards of the chats and boards that a chat answer cites (`[Cn]`, `[Bn]`).
//!
//! A chat citation shows the chat list card ([`ChatSessionCard`]). A board citation shows the
//! board overview card ([`BoardCard`]) with its graph thumbnail. Each card loads its item
//! with the read rule of the person who reads the transcript. An item that the reader cannot
//! read, or that was deleted, shows a line that says so.

use common::board_types::BoardListItem;
use common::chat_items::{ChatItemRef, KIND_BOARD};
use dioxus::prelude::*;

use crate::api::chat_api::chat_cited_item_cards;
use crate::components::board_graph::BoardThumbnail;
use crate::components::chat_components::{ChatSessionCard, GroupName, Highlighted};
use crate::pages::admin::llm_reports::format_utc_ms;
use crate::routes::Route;
use crate::tr;

/// The card of one cited chat or board, under its handle.
#[component]
pub fn ItemCitationCard(item: ChatItemRef) -> Element {
    let board = item.kind == KIND_BOARD;
    let id = item.id.clone();
    let cards = use_resource(use_reactive!(|id, board| async move {
        if board {
            chat_cited_item_cards(Vec::new(), vec![id]).await
        } else {
            chat_cited_item_cards(vec![id], Vec::new()).await
        }
    }));
    let body = match &*cards.read() {
        None => rsx! {
            div { class: "x-item-citation-state", {tr!("chat-item-citation-loading")} }
        },
        Some(Ok(found)) if board && !found.boards.is_empty() => rsx! {
            BoardCard { board: found.boards[0].clone() }
        },
        Some(Ok(found)) if !board && !found.chats.is_empty() => rsx! {
            ChatSessionCard { session: found.chats[0].clone() }
        },
        Some(Ok(_)) => rsx! {
            div { class: "x-item-citation-state",
                if board { {tr!("chat-item-citation-board-unavailable")} } else { {tr!("chat-item-citation-chat-unavailable")} }
            }
        },
        Some(Err(e)) => rsx! {
            div { class: "x-item-citation-state x-error-display", style: "color: var(--x-danger);",
                {crate::api::error_util::user_facing_message(e)}
            }
        },
    };
    rsx! {
        div {
            class: "x-item-citation",
            "data-citation-handle": "{item.handle}",
            "data-citation-kind": "{item.kind}",
            style: "display: flex; flex-direction: column; gap: 4px; margin: 4px 0 10px; max-width: 520px;",
            div { style: "font-size: var(--x-text-detail); color: var(--x-ink-muted);",
                span { style: "font-weight: 600; margin-right: 6px;", "{item.handle}" }
                if !item.why.is_empty() { "{item.why}" }
            }
            {body}
        }
    }
}

/// The overview card of one board: title, status, the graph thumbnail, the summary, the time of
/// the newest event and the group. The board list on `/ai_chat` and a board citation in a chat
/// answer show it.
#[component]
pub fn BoardCard(
    board: BoardListItem,
    /// A search text whose matches the title and the summary mark. Empty marks nothing.
    #[props(default)]
    highlight: String,
) -> Element {
    let status = match (board.status.as_str(), board.graph.not_answered.len()) {
        ("active", _) => tr!("ai-chat-homepage-active"),
        ("paused", _) => tr!("ai-chat-homepage-paused"),
        ("review", _) => tr!("ai-chat-homepage-waits-for-review"),
        ("completed", 0) => tr!("ai-chat-homepage-completed"),
        ("completed", 1) => "Completed, 1 goal not answered".to_string(),
        ("completed", n) => tr!("ai-chat-homepage-completed-goals-not-answered", n: n.to_string()),
        ("dropped", _) => tr!("ai-chat-homepage-dropped"),
        _ => tr!("ai-chat-homepage-unknown"),
    };
    // The generated summary of the board. Before its first label pass, the first goal.
    let summary = if board.summary.is_empty() {
        board.graph.facts.iter().find(|f| f.fact_id == "goal").map(|f| f.text.clone()).unwrap_or_default()
    } else {
        board.summary.clone()
    };
    rsx! {
        Link {
            class: "x-board-card",
            "data-board-id": "{board.board_id}",
            to: Route::ai_board(board.board_id.clone(), String::new()),
            style: "display: block; background: white; border: 1px solid; border-color: var(--x-border); border-radius: 12px; \
                    padding: 12px 14px; text-decoration: none; color: inherit;",
            div { style: "display: flex; justify-content: space-between; gap: 8px;",
                span { style: "font-size: var(--x-text-body); font-weight: 600; color: var(--x-ink-strong); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;",
                    Highlighted { text: board.title.clone(), needle: highlight.clone() }
                }
                span { style: "font-size: var(--x-text-detail); color: var(--x-ink-muted); white-space: nowrap;", "{status}" }
            }
            BoardThumbnail { input: board.graph.clone() }
            div {
                class: "x-board-card-summary",
                style: "font-size: var(--x-text-detail); line-height: var(--x-line-detail); color: var(--x-ink); \
                        display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;",
                Highlighted { text: summary.clone(), needle: highlight.clone() }
            }
            div { style: "display: flex; gap: 10px; align-items: center; justify-content: space-between; margin-top: 2px;",
                span { style: "font-size: var(--x-text-detail); color: var(--x-ink-faint);", {tr!("ai-chat-homepage-updated", format_utc_ms_board_updated_ms: (format_utc_ms(board.updated_ms)).to_string())} }
                GroupName { name: board.owner_group.clone() }
            }
        }
    }
}
