//! AI Chat API: sessions, trajectories, and asking the agent a question.
//!
//! The security property this module exists to hold: **an agent answering for a user
//! can only read collections that user could read in the search UI.** That is enforced
//! in one place — [`send_message`] resolves the live permission set and passes it to the
//! agent, which passes it to the MCP servers. The collection selection stored on a
//! session is a *preference*; it is intersected with live permissions on every message,
//! so a permission revoked after a chat started takes effect on the next message.

pub mod agent_client;
pub mod live_runs;
pub mod summarize;

use std::time::Instant;

use common::chat_types::{
    extract_doc_refs, title_from_message, truncate_payload, ChatOptions, ChatRole,
    ChatSendResult, ChatSessionDetail, ChatSessionItem, MAX_MESSAGE_CHARS, TOOL_PAYLOAD_CHARS,
};
use common::current_user::CurrentUser;

use crate::api::rate_limit::{check_and_record, RateLimitKind};
use crate::api::telemetry::{self, EVENT_LLM_CHAT_MESSAGE, EVENT_LLM_MCP_TOOL_CALL};
use crate::db_chat::{self, AppendMessageExtras};
use crate::db_utils::clickhouse_utils::list_permitted_collections;

/// Cap on sessions returned to the history sidebar / homepage.
const SESSION_LIST_LIMIT: u32 = 100;

/// How much of a tool call's payload is stored in the short `content` summary column.
const TOOL_SUMMARY_CHARS: usize = 400;

/// Reject anonymous use. Guests are allowed only when demo mode is on
/// (`HOOVER4_DEMO_MODE`), keyed by their `guest-*` username like any other user.
///
/// Revisit whether guests should have LLM access at all — see `website/Readme.md`.
fn require_named_user(user: &CurrentUser) -> anyhow::Result<&str> {
    require_named_user_inner(user, crate::auth::session_middleware::demo_mode())
}

fn require_named_user_inner(user: &CurrentUser, demo: bool) -> anyhow::Result<&str> {
    if user.username.is_empty() {
        anyhow::bail!("no user in session");
    }
    if user.is_guest && !demo {
        anyhow::bail!("AI Chat requires a signed-in user; guest sessions have no chat history outside demo mode");
    }
    Ok(&user.username)
}

pub async fn list_chat_sessions(user: &CurrentUser) -> anyhow::Result<Vec<ChatSessionItem>> {
    let username = require_named_user(user)?;
    db_chat::list_sessions(username, SESSION_LIST_LIMIT).await
}

/// Start a new conversation.
///
/// The requested collections are intersected with what the user may actually read, so a
/// crafted request cannot seed a session with a collection the user has no access to.
pub async fn create_chat_session(
    user: &CurrentUser,
    collections: Vec<String>,
) -> anyhow::Result<String> {
    let username = require_named_user(user)?;
    let permitted = list_permitted_collections(user).await?;
    let selected = intersect_collections(&collections, &permitted);
    db_chat::create_session(username, "New chat", &selected).await
}

pub async fn get_chat_session(
    user: &CurrentUser,
    session_id: String,
) -> anyhow::Result<ChatSessionDetail> {
    let username = require_named_user(user)?;
    let row = db_chat::get_session(username, &session_id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("chat session not found"))?;
    let messages = db_chat::list_messages(username, &session_id).await?;
    let available_collections = list_permitted_collections(user).await?;

    let options = row.options();
    Ok(ChatSessionDetail {
        session: ChatSessionItem {
            session_id: row.session_id,
            title: row.title,
            summary: row.summary,
            collections: row.collections,
            created_at: String::new(),
            updated_at: String::new(),
            message_count: messages.len() as u32,
            options,
        },
        messages,
        available_collections,
    })
}

pub async fn delete_chat_session(user: &CurrentUser, session_id: String) -> anyhow::Result<()> {
    let username = require_named_user(user)?;
    db_chat::delete_session(username, &session_id).await
}

/// Change which collections a conversation searches.
pub async fn set_chat_collections(
    user: &CurrentUser,
    session_id: String,
    collections: Vec<String>,
) -> anyhow::Result<()> {
    let username = require_named_user(user)?;
    let permitted = list_permitted_collections(user).await?;
    let selected = intersect_collections(&collections, &permitted);
    db_chat::touch_session(username, &session_id, None, Some(&selected)).await
}

/// Serialise the failed-attempt list for the `retry_errors` column. Empty stays empty
/// rather than becoming `"[]"`, so "no retries" costs no bytes on the overwhelmingly
/// common row.
fn encode_errors(errors: &[String]) -> String {
    if errors.is_empty() {
        return String::new();
    }
    serde_json::to_string(errors).unwrap_or_default()
}

/// Keep only requested collections the user may actually read.
///
/// An empty request means "everything I am allowed to see" — that is the useful default
/// for a chat, and it stays correct as permissions change because it is re-resolved on
/// every message rather than frozen into the session.
pub fn intersect_collections(requested: &[String], permitted: &[String]) -> Vec<String> {
    if requested.is_empty() {
        return permitted.to_vec();
    }
    let allowed: std::collections::HashSet<&String> = permitted.iter().collect();
    let mut out: Vec<String> = requested
        .iter()
        .filter(|c| allowed.contains(c))
        .cloned()
        .collect();
    out.sort();
    out.dedup();
    out
}

/// Send one user message and record the agent's whole trajectory.
///
/// Returns the updated trajectory so the caller can render it without a second round
/// trip. Every step — the user turn, each tool call, the answer, and any failure — is
/// persisted as it happens, so an agent that dies mid-run leaves a transcript showing
/// how far it got rather than nothing at all.
///
/// When the rate limiter refuses, nothing is written and `retry_after_seconds` is set.
///
/// `requested_options` only has effect on the **first** turn of a conversation; after
/// that the frozen values on the session win, so a client that forgets to send them —
/// or forges them — cannot change which agent a thread is talking to mid-way.
pub async fn send_message(
    user: &CurrentUser,
    session_id: String,
    message: String,
    requested_options: ChatOptions,
) -> anyhow::Result<ChatSendResult> {
    let username = require_named_user(user)?;

    if let Err(e) = check_and_record(username, RateLimitKind::ChatMessage) {
        return Ok(ChatSendResult {
            messages: Vec::new(),
            retry_after_seconds: Some(e.retry_after_seconds),
        });
    }

    let message = message.trim().to_string();
    if message.is_empty() {
        anyhow::bail!("message is empty");
    }
    if message.chars().count() > MAX_MESSAGE_CHARS {
        anyhow::bail!("message is too long (max {MAX_MESSAGE_CHARS} characters)");
    }

    let session = db_chat::get_session(username, &session_id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("chat session not found"))?;

    // Live permissions win over whatever the session was created with.
    let permitted = list_permitted_collections(user).await?;
    let allowed = intersect_collections(&session.collections, &permitted);

    let history = db_chat::list_messages(username, &session_id).await?;
    let agent_history: Vec<agent_client::AgentChatMessage> = history
        .iter()
        .filter(|m| m.role.is_conversational())
        .map(|m| agent_client::AgentChatMessage {
            r#type: match m.role {
                ChatRole::User => "human".to_string(),
                _ => "ai".to_string(),
            },
            content: m.content.clone(),
        })
        .collect();

    // Freeze the agent switches onto the conversation on the first turn; afterwards
    // this returns what was frozen and ignores what the client asked for.
    let options = db_chat::lock_session_options(username, &session_id, requested_options).await?;

    let mut seq = db_chat::next_seq(username, &session_id).await?;
    db_chat::append_message(
        username,
        &session_id,
        seq,
        ChatRole::User,
        &message,
        AppendMessageExtras::default(),
    )
    .await?;
    seq += 1;

    // Provisional title from the first user turn; LLM title/summary replaces it below.
    let is_first_turn = history.is_empty();
    let provisional_title = title_from_message(&message);
    if is_first_turn {
        db_chat::touch_session(username, &session_id, Some(&provisional_title), None).await?;
    } else {
        db_chat::touch_session(username, &session_id, None, None).await?;
    }

    let message_id = format!("{session_id}-{seq}");
    let started = Instant::now();
    let run = live_runs::register(
        username,
        &session_id,
        &provisional_title,
        &message,
        options,
    );
    let call = agent_client::ask_agent_with_retries(
        username,
        &session_id,
        &message_id,
        &message,
        &agent_history,
        &allowed,
        options.internet_tools,
        |attempt| run.set_attempt(attempt),
        || run.is_cancelled(),
    )
    .await;
    let agent_duration_ms = started.elapsed().as_millis().min(u128::from(u32::MAX)) as u32;
    let attempt_errors = call.attempt_errors;
    let result = call.result;
    drop(run);

    let mut assistant_answer_for_summary: Option<String> = None;

    match result {
        Ok(result) => {
            let paired = agent_client::pair_tool_calls(&result.tool_calls, TOOL_SUMMARY_CHARS);
            for call in &paired {
                let tool_input = truncate_payload(&call.tool_input, TOOL_PAYLOAD_CHARS);
                let tool_output = truncate_payload(&call.tool_output, TOOL_PAYLOAD_CHARS);
                let refs = extract_doc_refs(&call.tool_name, &call.tool_output);
                let doc_refs = if refs.is_empty() {
                    String::new()
                } else {
                    serde_json::to_string(&refs).unwrap_or_default()
                };
                db_chat::append_message(
                    username,
                    &session_id,
                    seq,
                    ChatRole::Tool,
                    &call.summary,
                    AppendMessageExtras {
                        tool_name: call.tool_name.clone(),
                        tool_input,
                        tool_output,
                        doc_refs,
                        agent_duration_ms: 0,
                        retry_errors: String::new(),
                        // A tool row is the tool's output, not the model's: leaving
                        // these empty is what makes "which model wrote this" a question
                        // only the assistant rows answer.
                        model: String::new(),
                        reasoning: String::new(),
                    },
                )
                .await?;
                telemetry::record_event(username, EVENT_LLM_MCP_TOOL_CALL, &call.tool_name);
                seq += 1;
            }

            let result_reasoning = result.reasoning.clone();
            let answer = if result.answer.trim().is_empty() {
                "(the assistant returned an empty answer)".to_string()
            } else {
                result.answer
            };
            assistant_answer_for_summary = Some(answer.clone());
            db_chat::append_message(
                username,
                &session_id,
                seq,
                ChatRole::Assistant,
                &answer,
                AppendMessageExtras {
                    agent_duration_ms,
                    // Kept on a *successful* row too: a turn that only worked on the
                    // third try is worth surfacing, and it is the only trace that the
                    // agent tier was flapping.
                    retry_errors: encode_errors(&attempt_errors),
                    // The model narrates its plan on the same channel as its answer.
                    // The agent separates the two; storing the narration here is what
                    // keeps it out of the answer body while still making it readable
                    // behind the disclosure.
                    reasoning: result_reasoning,
                    model: std::env::var("LLM_MODEL").unwrap_or_default(),
                    ..Default::default()
                },
            )
            .await?;
            telemetry::record_event(username, EVENT_LLM_CHAT_MESSAGE, "chat");
        }
        Err(e) => {
            // A failed agent call belongs in the transcript: the user asked something
            // and deserves to see what went wrong in place, not a toast that vanishes.
            db_chat::append_message(
                username,
                &session_id,
                seq,
                ChatRole::Error,
                &format!("The assistant could not answer: {e}"),
                AppendMessageExtras {
                    agent_duration_ms,
                    retry_errors: encode_errors(&attempt_errors),
                    ..Default::default()
                },
            )
            .await?;
        }
    }

    // Title/summary from the LLM after the first turn — never blocks / fails the turn.
    if is_first_turn {
        if let Some(answer) = assistant_answer_for_summary {
            let username_owned = username.to_string();
            let session_owned = session_id.clone();
            let user_msg = message.clone();
            tokio::spawn(async move {
                if let Some(ts) = summarize::generate_title_and_summary(&user_msg, &answer).await {
                    let _ = db_chat::set_session_title_summary(
                        &username_owned,
                        &session_owned,
                        Some(&ts.title),
                        Some(&ts.summary),
                    )
                    .await;
                }
            });
        }
    }

    let messages = db_chat::list_messages(username, &session_id).await?;
    Ok(ChatSendResult {
        messages,
        retry_after_seconds: None,
    })
}

/// Hand a question to the long-running research workflow instead of answering it inline.
///
/// The synchronous path in [`send_message`] holds an HTTP request open for the whole
/// agent run, which is fine for a chat turn and wrong for an exhaustive research run.
/// This variant records the user's turn, reserves the transcript position, and starts a
/// Temporal `ResearchTask` that writes the answer back when it finishes — so the user
/// can close the tab.
///
/// Returns the Temporal run id, or a rate-limit refusal via the same `ChatSendResult`
/// shape used by [`send_message`] when limited (here encoded as an error string with
/// retry seconds — research returns only a run id on success).
pub async fn start_research_task(
    user: &CurrentUser,
    session_id: String,
    message: String,
    requested_options: ChatOptions,
) -> anyhow::Result<Result<String, u64>> {
    let username = require_named_user(user)?;

    if let Err(e) = check_and_record(username, RateLimitKind::ChatMessage) {
        // Nothing written — consistent with send_message's rate-limit path.
        return Ok(Err(e.retry_after_seconds));
    }

    let message = message.trim().to_string();
    if message.is_empty() {
        anyhow::bail!("message is empty");
    }
    if message.chars().count() > MAX_MESSAGE_CHARS {
        anyhow::bail!("message is too long (max {MAX_MESSAGE_CHARS} characters)");
    }

    let session = db_chat::get_session(username, &session_id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("chat session not found"))?;
    let permitted = list_permitted_collections(user).await?;
    let allowed = intersect_collections(&session.collections, &permitted);

    // Deep research is one of the two frozen switches; a thread that started as a
    // research thread stays one.
    db_chat::lock_session_options(
        username,
        &session_id,
        ChatOptions {
            deep_research: true,
            ..requested_options
        },
    )
    .await?;

    let history = db_chat::list_messages(username, &session_id).await?;
    let mut seq = db_chat::next_seq(username, &session_id).await?;
    db_chat::append_message(
        username,
        &session_id,
        seq,
        ChatRole::User,
        &message,
        AppendMessageExtras::default(),
    )
    .await?;
    seq += 1;

    if history.is_empty() {
        db_chat::touch_session(username, &session_id, Some(&title_from_message(&message)), None)
            .await?;
    } else {
        db_chat::touch_session(username, &session_id, None, None).await?;
    }

    // A placeholder so the transcript shows the task was accepted. The workflow writes
    // over this `seq` when it finishes — `chat_messages` is keyed on it, so the
    // placeholder is replaced rather than duplicated.
    db_chat::append_message(
        username,
        &session_id,
        seq,
        ChatRole::Assistant,
        "Research task started. The answer will appear here when it finishes; you can \
         close this page and come back.",
        AppendMessageExtras::default(),
    )
    .await?;

    let run_id = start_research_workflow(username, &session_id, &message, &allowed, seq).await?;
    Ok(Ok(run_id))
}

/// Every agent run this website process currently has in flight. Admin only.
///
/// Scope is honest about its limits: this is *this process's* inline chat turns. Deep
/// research runs in a Temporal worker and is visible in the Temporal UI instead — the
/// admin page links there rather than pretending to own that view.
pub fn admin_list_live_runs(user: &CurrentUser) -> anyhow::Result<Vec<common::chat_types::LiveChatRun>> {
    require_admin(user)?;
    Ok(live_runs::snapshot())
}

/// Ask an in-flight run to stop. Admin only.
///
/// Cooperative: the run notices between retry attempts and before it writes. It cannot
/// abort an HTTP call already in flight against the agent, so a kill during a slow
/// generation takes effect when that call returns.
pub fn admin_cancel_live_run(user: &CurrentUser, run_id: u64) -> anyhow::Result<bool> {
    require_admin(user)?;
    Ok(live_runs::request_cancel(run_id))
}

fn require_admin(user: &CurrentUser) -> anyhow::Result<()> {
    if !user.is_admin {
        anyhow::bail!("admin access required");
    }
    Ok(())
}

/// Start the `ResearchTask` workflow over Temporal's HTTP API.
///
/// The workflow id is session- and seq-keyed so a double submit is a no-op rather than
/// two agents racing to write the same transcript row.
async fn start_research_workflow(
    username: &str,
    session_id: &str,
    query: &str,
    allowed_collections: &[String],
    start_seq: u32,
) -> anyhow::Result<String> {
    let base_url = std::env::var("TEMPORAL_HTTP_URL")
        .unwrap_or_else(|_| "http://localhost:21908".to_string());
    let workflow_id = format!("research-{session_id}-{start_seq}");
    let url = format!("{base_url}/api/v1/namespaces/default/workflows/{workflow_id}");

    let body = serde_json::json!({
        "workflowType": { "name": "ResearchTask" },
        "taskQueue": { "name": "processing-common-queue" },
        "input": [{
            "username": username,
            "session_id": session_id,
            "query": query,
            "allowed_collections": allowed_collections,
            "start_seq": start_seq,
        }],
    });

    let response = reqwest::Client::new()
        .post(&url)
        .json(&body)
        .send()
        .await?;
    if !response.status().is_success() {
        let text = response.text().await.unwrap_or_default();
        anyhow::bail!("could not start research task: {text}");
    }
    let json: serde_json::Value = response.json().await?;
    Ok(json
        .get("runId")
        .and_then(|v| v.as_str())
        .unwrap_or("started")
        .to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn v(items: &[&str]) -> Vec<String> {
        items.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn empty_request_means_every_permitted_collection() {
        assert_eq!(intersect_collections(&[], &v(&["a", "b"])), v(&["a", "b"]));
    }

    #[test]
    fn request_is_narrowed_to_permitted() {
        assert_eq!(
            intersect_collections(&v(&["a", "secret"]), &v(&["a", "b"])),
            v(&["a"])
        );
    }

    #[test]
    fn request_entirely_outside_permissions_yields_nothing() {
        // Not "fall back to everything": a selection of only forbidden collections must
        // narrow to the empty set, never widen.
        assert!(intersect_collections(&v(&["secret"]), &v(&["a"])).is_empty());
    }

    #[test]
    fn a_user_with_no_permissions_gets_nothing() {
        assert!(intersect_collections(&[], &[]).is_empty());
        assert!(intersect_collections(&v(&["a"]), &[]).is_empty());
    }

    #[test]
    fn duplicates_are_collapsed() {
        assert_eq!(intersect_collections(&v(&["a", "a"]), &v(&["a"])), v(&["a"]));
    }

    fn user(username: &str, is_guest: bool) -> CurrentUser {
        CurrentUser {
            username: username.to_string(),
            fullname: String::new(),
            email: String::new(),
            is_admin: false,
            is_guest,
            groups: Vec::new(),
        }
    }

    #[test]
    fn guests_and_anonymous_users_are_refused() {
        // Outside demo mode guests are refused; inside demo mode they are keyed by
        // guest-* username like any other user. Anonymous always refuses.
        assert!(require_named_user_inner(&user("guest-1", true), false).is_err());
        assert_eq!(
            require_named_user_inner(&user("guest-1", true), true).unwrap(),
            "guest-1"
        );
        assert!(require_named_user_inner(&user("", false), false).is_err());
        assert!(require_named_user_inner(&user("", true), true).is_err());
        assert_eq!(require_named_user_inner(&user("ann", false), false).unwrap(), "ann");
    }
}
