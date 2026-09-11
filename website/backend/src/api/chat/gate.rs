//! Whether a new chat turn may start.
//!
//! Shared by `chat_llm_configured` (the frontend hint) and the send/research entry
//! points (the actual gate). Reads configuration and the runtime switch. It never
//! calls the provider.

use common::chat_gate::{
    chat_enabled_from_stored, evaluate_chat_gate, ChatGate, ChatGateClosed, ChatGateInputs,
    CHAT_ENABLED_SETTING,
};

use crate::api::admin::llm::{default_chat_model, provider_name_from_url, read_llm_api_key};
use crate::db_auth::settings;

/// Evaluate the live process: env, the key file, and `server_settings`.
pub async fn evaluate_live_chat_gate() -> ChatGate {
    let stored = match settings::get_setting(CHAT_ENABLED_SETTING).await {
        Ok(value) => value,
        Err(_) => return ChatGate::Closed(ChatGateClosed::Unevaluable),
    };
    let chat_enabled = match chat_enabled_from_stored(stored.as_deref()) {
        Ok(enabled) => Ok(enabled),
        Err(()) => return ChatGate::Closed(ChatGateClosed::Unevaluable),
    };
    let base_url = std::env::var("LLM_BASE_URL").unwrap_or_default();
    let env_model = std::env::var("LLM_MODEL").unwrap_or_default();
    let default_model = default_chat_model().await;
    let provider_name = provider_name_from_url(&base_url);
    let api_key = read_llm_api_key();
    evaluate_chat_gate(ChatGateInputs {
        base_url: &base_url,
        env_model: &env_model,
        default_chat_model: &default_model,
        provider_name: &provider_name,
        api_key: &api_key,
        chat_enabled,
    })
}

/// Refuse a new turn when the gate is closed. An in-flight turn is not cancelled.
pub async fn require_chat_open() -> anyhow::Result<()> {
    match evaluate_live_chat_gate().await {
        ChatGate::Open => Ok(()),
        ChatGate::Closed(reason) => anyhow::bail!("{}", reason.refusal_message()),
    }
}
