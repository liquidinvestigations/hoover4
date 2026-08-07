//! `/ai_chat` — "What are you researching?" homepage.

use common::chat_types::ChatOptions;
use dioxus::prelude::*;

use crate::api::admin_api::{chat_list_models, chat_llm_configured};
use crate::api::auth_api::whoami;
use crate::api::chat_api::{
    chat_create_session, chat_list_sessions, chat_send_message, chat_start_research,
};
use crate::components::chat_components::{ChatComposer, ChatSessionCard, ModelSelector};
use crate::routes::Route;

const HOMEPAGE_CARD_LIMIT: usize = 6;

#[component]
pub fn AiChatPage() -> Element {
    let sessions_res = use_resource(chat_list_sessions);
    let configured_res = use_resource(chat_llm_configured);
    let models_res = use_resource(chat_list_models);
    let whoami_res = use_resource(whoami);
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
    let is_guest = whoami_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .map(|u| u.is_guest)
        .unwrap_or(false);
    let choices = models_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned()
        .unwrap_or_default();
    if selected_model.read().is_empty() {
        if let Some(def) = choices.iter().find(|c| c.is_default) {
            selected_model.set(def.model_id.clone());
        } else if let Some(first) = choices.first() {
            selected_model.set(first.model_id.clone());
        }
    }

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
                    if opts.deep_research {
                        match chat_start_research(id.clone(), text, opts).await {
                            Ok(_) => {
                                nav.push(Route::ai_chat_session(id, None, None));
                            }
                            Err(e) => {
                                if let Some(secs) = parse_rate_limited(&e.to_string()) {
                                    retry_after.set(Some(secs));
                                } else {
                                    error.set(Some(e.to_string()));
                                }
                            }
                        }
                    } else {
                        let model_id = if model.is_empty() { None } else { Some(model) };
                        match chat_send_message(id.clone(), text, opts, model_id).await {
                            Ok(result) => {
                                if let Some(secs) = result.retry_after_seconds {
                                    retry_after.set(Some(secs));
                                } else {
                                    nav.push(Route::ai_chat_session(id, None, None));
                                }
                            }
                            Err(e) => error.set(Some(e.to_string())),
                        }
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
                    if !is_guest && !choices.is_empty() {
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
                div { style: "margin-top: 12px; color: #B91C1C; font-size: 13px;", "{e}" }
            }
            if *sending.read() {
                div { style: "margin-top: 12px; color: #64748B; font-size: 13px;",
                    "Starting conversation\u{2026}"
                }
            }
        }
    }
}

fn parse_rate_limited(msg: &str) -> Option<u64> {
    msg.strip_prefix("rate_limited:")
        .and_then(|s| s.trim().parse().ok())
}
