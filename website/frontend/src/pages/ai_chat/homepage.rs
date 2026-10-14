//! `/ai_chat`, the AI Chat homepage. The left column is the chat: "What are you
//! researching?", the newest conversations and the composer. The right column is the board
//! overview of the signed-in user: a card per board with its title, counts and a thumbnail
//! of its graph, and a link to the create page. The boards need the chat models, so the
//! column shows only while the chat gate is open.

use common::chat_gate::ChatGate;
use common::chat_types::ChatOptions;
use dioxus::prelude::*;

use common::board_types::BoardListItem;

use crate::api::admin_api::{chat_list_models, chat_llm_configured};
use crate::api::board_api::list_boards;
use crate::api::error_util::user_facing_message;
use crate::components::board_graph::BoardThumbnail;
use crate::pages::admin::llm_reports::format_utc_ms;
use crate::api::chat_api::{
    chat_create_session, chat_delete_session, chat_list_sessions, chat_send_message,
};
use crate::components::chat_components::{
    ChatComposer, ChatGateOverlay, ChatSessionCard, ModelSelector,
};
use crate::routes::Route;

const HOMEPAGE_CARD_LIMIT: usize = 6;

#[component]
pub fn AiChatPage() -> Element {
    let sessions_res = use_resource(|| chat_list_sessions(false));
    let configured_res = use_resource(chat_llm_configured);
    let models_res = use_resource(chat_list_models);
    let mut draft = use_signal(String::new);
    let mut options = use_signal(ChatOptions::default);
    let mut selected_model = use_signal(String::new);
    let mut sending = use_signal(|| false);
    let mut error = use_signal(|| None::<String>);
    let mut retry_after = use_signal(|| None::<u64>);
    let nav = navigator();

    let gate = match configured_res.read().as_ref() {
        None => None,
        Some(Ok(g)) => Some(*g),
        Some(Err(_)) => Some(ChatGate::from_server_result::<()>(Err(()))),
    };
    let gate_open = gate == Some(ChatGate::Open);
    let choices = models_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned()
        .unwrap_or_default();
    let show_models = !choices.is_empty();
    // In an effect, not in the render body: a signal written during render schedules
    // another render from inside one, which Dioxus tolerates and nobody should rely on.
    use_effect(move || {
        let choices = models_res
            .read()
            .as_ref()
            .and_then(|r| r.as_ref().ok())
            .cloned()
            .unwrap_or_default();
        // Read, not peeked: this effect must re-run when the value is *cleared*, which
        // is how a conversation switch asks for a fresh default. The write below then
        // re-runs it once more and it returns immediately.
        if !selected_model.read().is_empty() {
            return;
        }
        if let Some(def) = choices.iter().find(|c| c.is_default) {
            selected_model.set(def.model_id.clone());
        } else if let Some(first) = choices.first() {
            selected_model.set(first.model_id.clone());
        }
    });

    let on_submit = move |_| {
        let text = draft.read().trim().to_string();
        if text.is_empty() || *sending.read() {
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
        let opts = *options.read();
        let model = selected_model.read().clone();
        draft.set(String::new());
        sending.set(true);
        error.set(None);
        retry_after.set(None);
        spawn(async move {
            match chat_create_session(Vec::new()).await {
                Ok(id) => {
                    // The session exists before the first message can be refused. When
                    // that message never lands, the empty "New chat" it left behind is
                    // pure litter, and rate limiting is exactly the case that produces
                    // one per press. So the failure paths take it back out.
                    let sent = {
                        let model_id = if model.is_empty() { None } else { Some(model) };
                        match chat_send_message(id.clone(), text, opts, model_id).await {
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
        Title { "Hoover Search - AI Chat" }
        div {
            style: "width: 100%; height: 100%; background: #F5F6F8; box-sizing: border-box; \
                    display: flex; gap: 23px; padding: 23px; overflow: auto;",
        div {
            class: "x-ai-chat-column",
            style: "flex: 1 1 60%; min-width: 0; display: flex; flex-direction: column; align-items: center;",
            h1 {
                style: "margin: 0 0 23px; font-size: var(--x-text-page); line-height: var(--x-line-page); font-weight: 600; color: var(--x-ink-strong); \
                        text-align: center;",
                "What are you researching?"
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
                        "View all conversations"
                    }
                }
            }

            div { style: "width: 100%; max-width: 720px; position: relative;",
                if show_models {
                    div { style: "margin-bottom: 10px;",
                        ModelSelector {
                            choices: choices.clone(),
                            selected: selected_model,
                            disabled: *sending.read() || !gate_open,
                        }
                    }
                }
                ChatComposer {
                    draft,
                    options,
                    sending,
                    retry_after_seconds: retry_after,
                    on_submit,
                    blocked: !gate_open,
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
                    "Starting conversation\u{2026}"
                }
            }
        }
        if gate_open {
            BoardsOverview {}
        }
        }
    }
}

/// The right column: a card per board of the user, newest first.
#[component]
fn BoardsOverview() -> Element {
    let boards_res = use_resource(list_boards);
    rsx! {
        div {
            class: "x-boards-overview",
            style: "flex: 0 1 400px; min-width: 300px; display: flex; flex-direction: column; gap: 11px;",
            div { style: "display: flex; align-items: center; justify-content: space-between;",
                h2 { style: "margin: 0; font-size: var(--x-text-section); font-weight: 600; color: var(--x-ink-strong);", "Investigation boards" }
                Link {
                    class: "x-board-new",
                    to: Route::AiBoardCreatePage {},
                    style: "font-size: var(--x-text-sm); color: var(--x-link); text-decoration: none; font-weight: 500;",
                    "New board"
                }
            }
            match &*boards_res.read() {
                None => rsx! { div { style: "color: var(--x-ink-faint); font-size: var(--x-text-sm);", "Loading boards\u{2026}" } },
                Some(Err(e)) => rsx! {
                    div { class: "x-error-display", style: "color: var(--x-danger); font-size: var(--x-text-sm);",
                        "Could not load the boards: {user_facing_message(e)}"
                    }
                },
                Some(Ok(list)) if list.is_empty() => rsx! {
                    div { style: "color: var(--x-ink-muted); font-size: var(--x-text-sm);",
                        "You have no board. A board runs a long investigation as a sequence of agent explores, and you review its answers."
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

#[component]
fn BoardCard(board: BoardListItem) -> Element {
    let status = match board.status.as_str() {
        "active" => "Active",
        "paused" => "Paused",
        "review" => "Waits for review",
        "completed" => "Completed",
        "dropped" => "Dropped",
        _ => "Unknown",
    };
    let goals = if board.goals == 1 { "1 goal".to_string() } else { format!("{} goals", board.goals) };
    rsx! {
        Link {
            class: "x-board-card",
            "data-board-id": "{board.board_id}",
            to: Route::AiBoardPage { board_id: board.board_id.clone(), selected: String::new() },
            style: "display: block; background: white; border: 1px solid; border-color: var(--x-border); border-radius: 12px; \
                    padding: 12px 14px; text-decoration: none; color: inherit;",
            div { style: "display: flex; justify-content: space-between; gap: 8px;",
                span { style: "font-size: var(--x-text-md); font-weight: 600; color: var(--x-ink-strong); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;", "{board.title}" }
                span { style: "font-size: var(--x-text-xs); color: var(--x-ink-muted); white-space: nowrap;", "{status}" }
            }
            BoardThumbnail { input: board.graph.clone() }
            div { style: "font-size: var(--x-text-xs); color: var(--x-ink-muted); line-height: 1.5;",
                "{goals}, {board.facts_sourced} sourced, {board.facts_inferred} inferred, {board.facts_not_found} not found. "
                "{board.explores_used} of {board.max_explores} explores, {board.running} running, {board.open} open."
            }
            div { style: "font-size: var(--x-text-xs); color: var(--x-ink-faint); margin-top: 2px;", "Updated {format_utc_ms(board.updated_ms)}" }
        }
    }
}

