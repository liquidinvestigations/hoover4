//! `/ai_chat`, the AI Chat homepage. The left column is the chat: "What are you
//! researching?", the newest conversations of the groups of the user, the group of the new
//! chat and the composer. A new chat searches every collection that the user and its group
//! can both read. Without a group to choose, the composer does not send. The right column is
//! the board overview of the groups of the user: a card per board with its title, group,
//! counts and a thumbnail of its graph, and a link to the create page. The boards need the
//! chat models, so the column shows only while the chat gate is open.

use common::chat_gate::ChatGate;
use common::chat_types::ChatOptions;
use dioxus::prelude::*;

use crate::api::admin_api::chat_llm_configured;
use crate::api::board_api::list_boards;
use crate::api::error_util::user_facing_message;
use crate::api::chat_api::{
    chat_create_session, chat_delete_session, chat_list_sessions, chat_send_message,
};
use crate::components::chat_components::{
    BoardCard, ChatComposer, ChatGateOverlay, ChatSessionCard, GroupPicker,
};
use common::item_groups::GroupChoice;
use crate::routes::Route;
use crate::tr;

const HOMEPAGE_CARD_LIMIT: usize = 6;

#[component]
pub fn AiChatPage() -> Element {
    let sessions_res = use_resource(|| chat_list_sessions(false));
    let configured_res = use_resource(chat_llm_configured);
    let mut draft = use_signal(common::links::RichText::default);
    let mut options = use_signal(ChatOptions::default);
    let mut sending = use_signal(|| false);
    let mut error = use_signal(|| None::<String>);
    let mut retry_after = use_signal(|| None::<u64>);
    let group = use_signal(String::new);
    let group_choices = use_signal(|| None::<Vec<GroupChoice>>);
    let nav = navigator();

    let gate = match configured_res.read().as_ref() {
        None => None,
        Some(Ok(g)) => Some(*g),
        Some(Err(_)) => Some(ChatGate::from_server_result::<()>(Err(()))),
    };
    let gate_open = gate == Some(ChatGate::Open);

    let on_submit = move |_| {
        let text = draft.read().trimmed();
        if text.is_blank() || *sending.read() {
            return;
        }
        let live_gate = match configured_res.read().as_ref() {
            Some(Ok(g)) => *g,
            Some(Err(_)) => ChatGate::from_server_result::<()>(Err(())),
            None => ChatGate::Open,
        };
        if !live_gate.is_open() {
            return;
        }
        let chosen_group = group.read().clone();
        if chosen_group.is_empty() {
            return;
        }
        let opts = *options.read();
        draft.set(common::links::RichText::default());
        sending.set(true);
        error.set(None);
        retry_after.set(None);
        spawn(async move {
            match chat_create_session(chosen_group, Vec::new()).await {
                Ok(id) => {
                    // The session exists before the first message can be refused. When
                    // that message never lands, the empty "New chat" it left behind is
                    // pure litter, and rate limiting is exactly the case that produces
                    // one per press. So the failure paths take it back out.
                    let sent = {
                        match chat_send_message(id.clone(), text, opts).await {
                            Ok(result) => match result.retry_after_seconds {
                                Some(secs) => {
                                    retry_after.set(Some(secs));
                                    false
                                }
                                None => true,
                            },
                            Err(e) => {
                                error.set(Some(e.to_string()));
                                false
                            }
                        }
                    };
                    if sent {
                        nav.push(Route::ai_chat_session(id, None, None));
                    } else {
                        // Best effort: a conversation that failed to start is worth less
                        // than the error message already on screen, so a failure to clean
                        // it up must not replace that message with a second one.
                        let _ = chat_delete_session(id).await;
                    }
                }
                Err(e) => error.set(Some(e.to_string())),
            }
            sending.set(false);
        });
    };

    let sessions = sessions_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned()
        .unwrap_or_default();
    let cards: Vec<_> = sessions.into_iter().take(HOMEPAGE_CARD_LIMIT).collect();

    rsx! {
        Title { {tr!("ai-chat-homepage-hoover-search-ai-chat")} }
        div {
            style: "width: 100%; height: 100%; background: #F5F6F8; box-sizing: border-box; \
                    display: flex; gap: 23px; padding: 23px; overflow: auto;",
        div {
            class: "x-ai-chat-column",
            style: "flex: 1 1 60%; min-width: 0; display: flex; flex-direction: column; align-items: center;",
            h1 {
                style: "margin: 0 0 23px; font-size: var(--x-text-page); line-height: var(--x-line-page); font-weight: 600; color: var(--x-ink-strong); \
                        text-align: center;",
                {tr!("ai-chat-homepage-what-are-you-researching")}
            }

            if !cards.is_empty() {
                div {
                    style: "display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); \
                            gap: 11px; width: 100%; max-width: 920px; margin-bottom: 23px;",
                    for s in cards {
                        ChatSessionCard { key: "{s.session_id}", session: s }
                    }
                }
                div {
                    style: "margin-bottom: 15px;",
                    Link {
                        to: Route::AiChatHistoryPage {},
                        style: "font-size: var(--x-text-sm); color: var(--x-link); text-decoration: none;",
                        {tr!("ai-chat-homepage-view-all-conversations")}
                    }
                }
            }

            div { style: "width: 100%; max-width: 720px; margin-bottom: 8px;",
                GroupPicker { selected: group, choices: group_choices, hint: tr!("ai-chat-homepage-members-of-the-group-can-read") }
            }
            div { style: "width: 100%; max-width: 720px; position: relative;",
                ChatComposer {
                    draft,
                    options,
                    sending,
                    retry_after_seconds: retry_after,
                    on_submit,
                    blocked: !gate_open || group.read().is_empty(),
                }
                if let Some(ChatGate::Closed(reason)) = gate {
                    ChatGateOverlay { reason }
                }
            }

            if let Some(e) = error.read().clone() {
                div {
                    class: "x-error-display",
                    style: "margin-top: 12px; color: var(--x-danger); font-size: var(--x-text-sm);",
                    "{e}"
                }
            }
            if *sending.read() {
                div { style: "margin-top: 12px; color: var(--x-ink-muted); font-size: var(--x-text-sm);",
                    {tr!("ai-chat-homepage-starting-conversation-u")}
                }
            }
        }
        if gate_open {
            BoardsOverview {}
        }
        }
    }
}

/// The right column: a card per board of the groups of the user, newest first.
#[component]
fn BoardsOverview() -> Element {
    let boards_res = use_resource(list_boards);
    rsx! {
        div {
            class: "x-boards-overview",
            style: "flex: 0 1 400px; min-width: 300px; display: flex; flex-direction: column; gap: 11px;",
            div { style: "display: flex; align-items: center; justify-content: space-between;",
                h2 { style: "margin: 0; font-size: var(--x-text-section); font-weight: 600; color: var(--x-ink-strong);", {tr!("ai-chat-homepage-investigation-boards")} }
                Link {
                    class: "x-board-new",
                    to: Route::AiBoardCreatePage {},
                    style: "font-size: var(--x-text-sm); color: var(--x-link); text-decoration: none; font-weight: 500;",
                    {tr!("ai-chat-homepage-new-board")}
                }
            }
            match &*boards_res.read() {
                None => rsx! { div { style: "color: var(--x-ink-faint); font-size: var(--x-text-sm);", {tr!("ai-chat-homepage-loading-boards-u")} } },
                Some(Err(e)) => rsx! {
                    div { class: "x-error-display", style: "color: var(--x-danger); font-size: var(--x-text-sm);",
                        {tr!("ai-chat-homepage-could-not-load-the-boards", user_facing_message_e: (user_facing_message(e)).to_string())}
                    }
                },
                Some(Ok(list)) if list.is_empty() => rsx! {
                    div { style: "color: var(--x-ink-muted); font-size: var(--x-text-sm);",
                        {tr!("ai-chat-homepage-you-have-no-board-a")}
                    }
                },
                Some(Ok(list)) => rsx! {
                    for board in list.clone() {
                        BoardCard { key: "{board.board_id}", board }
                    }
                },
            }
        }
    }
}


