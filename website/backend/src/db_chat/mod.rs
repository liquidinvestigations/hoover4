//! Storage for AI Chat sessions and their message trajectories.
//!
//! **Every function here takes a `username` and filters on it.** Ownership is not
//! checked once at the edge and then trusted: a transcript can quote documents from
//! restricted collections, so the owner is part of the primary key of every query. A
//! session id alone is never sufficient to read a conversation.

use common::chat_types::{ChatMessageItem, ChatRole, ChatSessionItem};
use time::format_description::well_known::Rfc3339;

use crate::db_auth::{insert_row, now};
use crate::db_utils::clickhouse_utils::get_global_client;

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
pub struct ChatSessionRow {
    pub session_id: String,
    pub username: String,
    pub title: String,
    #[serde(default)]
    pub summary: String,
    pub collections: Vec<String>,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub created_at: time::OffsetDateTime,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub updated_at: time::OffsetDateTime,
    pub is_deleted: u8,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
pub struct ChatMessageRow {
    pub session_id: String,
    pub username: String,
    pub seq: u32,
    pub role: String,
    pub content: String,
    pub tool_name: String,
    #[serde(default)]
    pub tool_input: String,
    #[serde(default)]
    pub tool_output: String,
    #[serde(default)]
    pub doc_refs: String,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub created_at: time::OffsetDateTime,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub updated_at: time::OffsetDateTime,
    #[serde(with = "clickhouse::serde::time::datetime64::millis")]
    pub created_ms: time::OffsetDateTime,
    #[serde(default)]
    pub agent_duration_ms: u32,
}

const SESSION_SELECT: &str = "SELECT session_id, username, title, summary, collections, created_at, \
     updated_at, is_deleted FROM chat_sessions FINAL";

const MESSAGE_SELECT: &str = "SELECT session_id, username, seq, role, content, tool_name, \
     tool_input, tool_output, doc_refs, created_at, updated_at, created_ms, agent_duration_ms \
     FROM chat_messages FINAL";

fn fmt(dt: time::OffsetDateTime) -> String {
    dt.format(&Rfc3339).unwrap_or_else(|_| dt.to_string())
}

/// Random id for a new chat. Reuses the web-session generator rather than adding a uuid
/// dependency — it is the same shape of value (opaque, unguessable, hex) and this
/// codebase already trusts it for auth cookies.
fn generate_chat_session_id() -> String {
    crate::db_auth::sessions::generate_session_id()
}

pub async fn create_session(
    username: &str,
    title: &str,
    collections: &[String],
) -> anyhow::Result<String> {
    let session_id = generate_chat_session_id();
    let row = ChatSessionRow {
        session_id: session_id.clone(),
        username: username.to_string(),
        title: title.to_string(),
        summary: String::new(),
        collections: collections.to_vec(),
        created_at: now(),
        updated_at: now(),
        is_deleted: 0,
    };
    insert_row("chat_sessions", &row).await?;
    Ok(session_id)
}

pub async fn get_session(
    username: &str,
    session_id: &str,
) -> anyhow::Result<Option<ChatSessionRow>> {
    let client = get_global_client();
    let mut rows = client
        .query(&format!(
            "{SESSION_SELECT} WHERE username = ? AND session_id = ? AND is_deleted = 0"
        ))
        .bind(username)
        .bind(session_id)
        .fetch_all::<ChatSessionRow>()
        .await?;
    Ok(rows.pop())
}

/// Sessions of one user, most recently active first.
pub async fn list_sessions(username: &str, limit: u32) -> anyhow::Result<Vec<ChatSessionItem>> {
    let client = get_global_client();
    let rows = client
        .query(&format!(
            "{SESSION_SELECT} WHERE username = ? AND is_deleted = 0 \
             ORDER BY updated_at DESC LIMIT ?"
        ))
        .bind(username)
        .bind(limit)
        .fetch_all::<ChatSessionRow>()
        .await?;

    // Message counts in one grouped query rather than one per session.
    let counts: Vec<(String, u64)> = client
        .query(
            "SELECT session_id, count() FROM chat_messages FINAL \
             WHERE username = ? GROUP BY session_id",
        )
        .bind(username)
        .fetch_all()
        .await?;
    let counts: std::collections::HashMap<String, u64> = counts.into_iter().collect();

    Ok(rows
        .into_iter()
        .map(|r| ChatSessionItem {
            message_count: counts.get(&r.session_id).copied().unwrap_or(0) as u32,
            session_id: r.session_id,
            title: r.title,
            summary: r.summary,
            collections: r.collections,
            created_at: fmt(r.created_at),
            updated_at: fmt(r.updated_at),
        })
        .collect())
}

pub async fn list_messages(
    username: &str,
    session_id: &str,
) -> anyhow::Result<Vec<ChatMessageItem>> {
    let client = get_global_client();
    let rows = client
        .query(&format!(
            "{MESSAGE_SELECT} WHERE username = ? AND session_id = ? ORDER BY seq"
        ))
        .bind(username)
        .bind(session_id)
        .fetch_all::<ChatMessageRow>()
        .await?;

    Ok(rows
        .into_iter()
        .map(|r| ChatMessageItem {
            seq: r.seq,
            role: ChatRole::from_str(&r.role),
            content: r.content,
            tool_name: r.tool_name,
            tool_input: r.tool_input,
            tool_output: r.tool_output,
            doc_refs: r.doc_refs,
            created_at: fmt(r.created_at),
            created_ms: fmt(r.created_ms),
            agent_duration_ms: r.agent_duration_ms,
        })
        .collect())
}

/// The next free `seq` in a session.
///
/// Not transactional — ClickHouse has no sequences and no row locks. Two messages sent
/// from two tabs at the same instant can collide on a `seq` and the ReplacingMergeTree
/// will keep one of them. Acceptable for a single-user chat UI; noted in the plan's
/// open questions rather than papered over with a lock this database cannot provide.
pub async fn next_seq(username: &str, session_id: &str) -> anyhow::Result<u32> {
    let client = get_global_client();
    let max: u32 = client
        .query(
            "SELECT ifNull(max(seq) + 1, 0) FROM chat_messages FINAL \
             WHERE username = ? AND session_id = ?",
        )
        .bind(username)
        .bind(session_id)
        .fetch_one()
        .await?;
    Ok(max)
}

/// Fields written for one trajectory row beyond the required role/content.
#[derive(Debug, Clone, Default)]
pub struct AppendMessageExtras {
    pub tool_name: String,
    pub tool_input: String,
    pub tool_output: String,
    pub doc_refs: String,
    pub agent_duration_ms: u32,
}

pub async fn append_message(
    username: &str,
    session_id: &str,
    seq: u32,
    role: ChatRole,
    content: &str,
    extras: AppendMessageExtras,
) -> anyhow::Result<()> {
    let ts = now();
    let row = ChatMessageRow {
        session_id: session_id.to_string(),
        username: username.to_string(),
        seq,
        role: role.as_str().to_string(),
        content: content.to_string(),
        tool_name: extras.tool_name,
        tool_input: extras.tool_input,
        tool_output: extras.tool_output,
        doc_refs: extras.doc_refs,
        created_at: ts,
        updated_at: ts,
        created_ms: ts,
        agent_duration_ms: extras.agent_duration_ms,
    };
    insert_row("chat_messages", &row).await
}

/// Update a session's title and/or collection selection, and bump `updated_at` so it
/// rises to the top of the history list.
pub async fn touch_session(
    username: &str,
    session_id: &str,
    title: Option<&str>,
    collections: Option<&[String]>,
) -> anyhow::Result<()> {
    let Some(mut row) = get_session(username, session_id).await? else {
        anyhow::bail!("chat session not found");
    };
    if let Some(t) = title {
        row.title = t.to_string();
    }
    if let Some(c) = collections {
        row.collections = c.to_vec();
    }
    row.updated_at = now();
    insert_row("chat_sessions", &row).await
}

/// Set title and/or summary without clearing the other.
pub async fn set_session_title_summary(
    username: &str,
    session_id: &str,
    title: Option<&str>,
    summary: Option<&str>,
) -> anyhow::Result<()> {
    let Some(mut row) = get_session(username, session_id).await? else {
        anyhow::bail!("chat session not found");
    };
    if let Some(t) = title {
        row.title = t.to_string();
    }
    if let Some(s) = summary {
        row.summary = s.to_string();
    }
    row.updated_at = now();
    insert_row("chat_sessions", &row).await
}

pub async fn delete_session(username: &str, session_id: &str) -> anyhow::Result<()> {
    let Some(mut row) = get_session(username, session_id).await? else {
        return Ok(());
    };
    row.is_deleted = 1;
    row.updated_at = now();
    insert_row("chat_sessions", &row).await
}
