//! AI Chat server-function wrappers.
//!
//! Each of these resolves the current user server-side and hands it to the backend; the
//! browser never supplies an identity, and never supplies a permission list.

use common::chat_types::{
    ChatOptions, ChatPollResult, ChatSendResult, ChatSessionDetail, ChatSessionItem, LiveChatRun,
};
use dioxus::prelude::*;

#[cfg(feature = "server")]
use crate::api::error_util::to_server_fn_error;

#[server]
pub async fn chat_list_sessions() -> Result<Vec<ChatSessionItem>, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::chat::list_chat_sessions(&user)
        .await
        .map_err(to_server_fn_error)
}

#[server]
pub async fn chat_create_session(collections: Vec<String>) -> Result<String, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::chat::create_chat_session(&user, collections)
        .await
        .map_err(to_server_fn_error)
}

#[server]
pub async fn chat_get_session(session_id: String) -> Result<ChatSessionDetail, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::chat::get_chat_session(&user, session_id)
        .await
        .map_err(to_server_fn_error)
}

#[server]
pub async fn chat_delete_session(session_id: String) -> Result<(), ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::chat::delete_chat_session(&user, session_id)
        .await
        .map_err(to_server_fn_error)
}

#[server]
pub async fn chat_set_collections(
    session_id: String,
    collections: Vec<String>,
) -> Result<(), ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::chat::set_chat_collections(&user, session_id, collections)
        .await
        .map_err(to_server_fn_error)
}

/// Send a message and get the updated trajectory back.
///
/// This is a long call — the agent runs several LLM turns and searches before it
/// answers — so the UI must show a pending state while it is in flight.
///
/// `options.internet_tools` routes to the full research agent
/// (`HOOVER4_FULL_AGENT_URL`) instead of the internal search agent. The options are
/// honoured on the **first** turn only and frozen onto the session; later turns reuse
/// the frozen values whatever the client sends. When rate-limited,
/// `retry_after_seconds` is set and `messages` is empty (nothing was written).
#[server]
pub async fn chat_send_message(
    session_id: String,
    message: String,
    options: ChatOptions,
    model_id: Option<String>,
) -> Result<ChatSendResult, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::chat::send_message(&user, session_id, message, options, model_id)
        .await
        .map_err(to_server_fn_error)
}

/// Hand the question to the long-running Temporal research task instead of waiting.
///
/// Returns the Temporal run id on success. On rate-limit, returns an error string
/// containing `retry_after_seconds` so the composer can show "try again in N s".
#[server]
pub async fn chat_start_research(
    session_id: String,
    message: String,
    options: ChatOptions,
) -> Result<String, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    match backend::api::chat::start_research_task(&user, session_id, message, options)
        .await
        .map_err(to_server_fn_error)?
    {
        Ok(run_id) => Ok(run_id),
        Err(retry_after_seconds) => Err(ServerFnError::new(format!(
            "rate_limited:{retry_after_seconds}"
        ))),
    }
}

/// Agent runs the website is holding open right now. Admin only.
///
/// Inline chat turns only — deep research runs in a Temporal worker and is visible in
/// the Temporal UI, which the admin page links to rather than duplicating.
#[server]
pub async fn chat_admin_live_runs() -> Result<Vec<LiveChatRun>, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::chat::admin_list_live_runs(&user).map_err(to_server_fn_error)
}

/// Ask an in-flight run to stop. Admin only. `false` means it had already finished.
#[server]
pub async fn chat_admin_cancel_run(run_id: u64) -> Result<bool, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::chat::admin_cancel_live_run(&user, run_id).map_err(to_server_fn_error)
}

/// Long-poll the tail of a conversation: finished rows after `after_seq` (the last seq
/// the client already has; `None` means "send everything"), plus the in-flight turn.
/// Holds up to ~15 s when nothing changes; `sig` is the opaque change token from the
/// previous poll (empty on the first call).
#[server]
pub async fn chat_poll(
    session_id: String,
    after_seq: Option<u32>,
    sig: String,
) -> Result<ChatPollResult, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::chat::poll_chat(&user, session_id, after_seq, sig)
        .await
        .map_err(to_server_fn_error)
}

/// The composer's stop button: finalise the running turn's partial answer with a
/// truncation marker. `false` means the turn had already finished.
#[server]
pub async fn chat_stop(session_id: String) -> Result<bool, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::chat::stop_chat_turn(&user, session_id).map_err(to_server_fn_error)
}

/// Clear an interrupted turn's leftover stream rows once the user has seen the marker.
#[server]
pub async fn chat_dismiss_interrupted(session_id: String) -> Result<(), ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::chat::dismiss_interrupted_turn(&user, session_id)
        .await
        .map_err(to_server_fn_error)
}

/// The search-detail JSON behind a `web_search` card's popup.
///
/// Fetched lazily on first open — it holds both orderings of every candidate, which is
/// far more than the card needs collapsed and more than `TOOL_PAYLOAD_CHARS` could carry
/// in the tool result at all.
#[server]
pub async fn chat_artifact_detail(artifact_id: String) -> Result<String, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::chat::get_chat_artifact_detail(&user, artifact_id)
        .await
        .map_err(to_server_fn_error)
}
