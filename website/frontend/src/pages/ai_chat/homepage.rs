//! `/ai_chat` — "What are you researching?" homepage.

use common::chat_types::{rate_limited_seconds, ChatOptions};
use dioxus::prelude::*;

use crate::api::admin_api::{chat_list_models, chat_llm_configured};
use crate::api::chat_api::{
    chat_create_session, chat_delete_session, chat_list_sessions, chat_send_message,
    chat_start_research,
};
use crate::components::session_gate::use_session_user;
use crate::components::chat_components::{ChatComposer, ChatSessionCard, ModelSelector};
use crate::routes::Route;

const HOMEPAGE_CARD_LIMIT: usize = 6;

#[component]
pub fn AiChatPage() -> Element {
    let sessions_res = use_resource(chat_list_sessions);
    let configured_res = use_resource(chat_llm_configured);
    let models_res = use_resource(chat_list_models);
    let mut draft = use_signal(String::new);
    let mut options = use_signal(ChatOptions::default);
    let mut selected_model = use_signal(String::new);
    let mut sending = use_signal(|| false);
    let mut error = use_signal(|| None::<String>);
    let mut retry_after = use_signal(|| None::<u64>);
    let nav = navigator();

    let configured = configured_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .copied()
        .unwrap_or(true);
    // `None` while the session gate's `whoami` is in flight, not `false`. Defaulting to
    // "not a guest" drew the model picker for a moment on every guest's first paint, then
    // took it away — a control that appears and vanishes reads as a bug.
    let is_guest = use_session_user().map(|u| u.is_guest);
    let choices = models_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned()
        .unwrap_or_default();
    let show_models = is_guest == Some(false) && !choices.is_empty();
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
                    // pure litter — and rate limiting is exactly the case that produces
                    // one per press. So the failure paths take it back out.
                    let sent = if opts.deep_research {
                        match chat_start_research(id.clone(), text, opts).await {
                            Ok(_) => true,
                            Err(e) => {
                                if let Some(secs) = rate_limited_seconds(&e.to_string()) {
                                    retry_after.set(Some(secs));
                                } else {
                                    error.set(Some(e.to_string()));
                                }
                                false
                            }
                        }
                    } else {
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
                    display: flex; flex-direction: column; align-items: center; \
                    padding: 48px 24px 32px; overflow: auto;",
            h1 {
                style: "margin: 0 0 28px; font-size: 32px; font-weight: 600; color: #0F172A; \
                        text-align: center;",
                "What are you researching?"
            }

            if !cards.is_empty() {
                div {
                    style: "display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); \
                            gap: 14px; width: 100%; max-width: 920px; margin-bottom: 28px;",
                    for s in cards {
                        ChatSessionCard { key: "{s.session_id}", session: s }
                    }
                }
                div {
                    style: "margin-bottom: 20px;",
                    Link {
                        to: Route::AiChatHistoryPage {},
                        style: "font-size: 13px; color: #4F46E5; text-decoration: none;",
                        "View all conversations"
                    }
                }
            }

            div { style: "width: 100%; max-width: 720px;",
                if !configured {
                    div {
                        style: "background: #FEF3C7; border: 1px solid #F59E0B; border-radius: 12px; \
                                padding: 16px 18px; color: #92400E; font-size: 14px; line-height: 1.5;",
                        "No LLM provider is configured. An administrator can add one under "
                        Link {
                            to: Route::AdminLlmPage {},
                            style: "color: #92400E; font-weight: 600;",
                            "/admin/llm"
                        }
                        "."
                    }
                } else {
                    if show_models {
                        div { style: "margin-bottom: 10px;",
                            ModelSelector {
                                choices: choices.clone(),
                                selected: selected_model,
                                disabled: *sending.read(),
                            }
                        }
                    }
                    ChatComposer {
                        draft,
                        options,
                        sending,
                        retry_after_seconds: retry_after,
                        on_submit,
                    }
                }
            }

            if let Some(e) = error.read().clone() {
                div {
                    class: "x-error-display",
                    style: "margin-top: 12px; color: #B91C1C; font-size: 13px;",
                    "{e}"
                }
            }
            if *sending.read() {
                div { style: "margin-top: 12px; color: #64748B; font-size: 13px;",
                    "Starting conversation\u{2026}"
                }
            }
        }
    }
}

