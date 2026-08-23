//! `chat_artifacts`: the index of what a chat's tools captured.
//!
//! An artifact is a blob a tool produced that is too big for the model's context but that
//! the *user* should see: the full before/after ordering of a web search, the archived
//! HTML and screenshot of a page the agent visited. The bytes live in the blob store under
//! `derived/chat-artifacts/<session>/<id>/`; this table is the sole index of their
//! existence.
//!
//! **An `artifact_id` is a lookup key, not a capability.** It arrives in a tool payload
//! written by an MCP server that an LLM drives, so it is never trusted: every read
//! resolves it back to a row and enforces owner-or-admin before a byte is served. That is
//! why `username` is denormalised onto the row. A read must not have to join
//! `chat_sessions` to prove ownership.

use crate::db_auth::{insert_row, now};
use crate::db_utils::clickhouse_utils::get_global_client;

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
pub struct ChatArtifactRow {
    pub artifact_id: String,
    pub session_id: String,
    pub username: String,
    pub kind: String,
    pub tool_name: String,
    #[serde(default)]
    pub url: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub thumb_key: String,
    #[serde(default)]
    pub body_key: String,
    #[serde(default)]
    pub body_bytes: u64,
    #[serde(default)]
    pub thumb_bytes: u64,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub detail: String,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub created_at: time::OffsetDateTime,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub updated_at: time::OffsetDateTime,
    #[serde(default)]
    pub is_deleted: u8,
}

/// Look an artifact up by id alone.
///
/// **No `username` filter here, on purpose.** The route needs the row's owner in order to
/// decide whether the caller may have it, and filtering by the caller's name would turn
/// "someone else's artifact" into "no such artifact". A 404 where a 403 belongs, which
/// hides a real permission failure behind an apparent missing row.
pub async fn get_artifact(artifact_id: &str) -> anyhow::Result<Option<ChatArtifactRow>> {
    let client = get_global_client();
    let rows = client
        .query(
            "SELECT artifact_id, session_id, username, kind, tool_name, url, title, \
             thumb_key, body_key, body_bytes, thumb_bytes, status, detail, \
             created_at, updated_at, is_deleted \
             FROM chat_artifacts FINAL WHERE artifact_id = ? AND is_deleted = 0 LIMIT 1",
        )
        .bind(artifact_id)
        .fetch_all::<ChatArtifactRow>()
        .await?;
    Ok(rows.into_iter().next())
}

/// Soft-delete every artifact belonging to one session.
///
/// Called when a chat is deleted, in the same operation. A ClickHouse TTL cannot remove
/// blob-store objects, so this only tombstones the rows. The Temporal sweeper deletes the
/// objects and then the rows. Doing it the other way round loses the only record of which
/// objects to remove.
pub async fn soft_delete_session_artifacts(username: &str, session_id: &str) -> anyhow::Result<()> {
    let client = get_global_client();
    let rows = client
        .query(
            "SELECT artifact_id, session_id, username, kind, tool_name, url, title, \
             thumb_key, body_key, body_bytes, thumb_bytes, status, detail, \
             created_at, updated_at, is_deleted \
             FROM chat_artifacts FINAL WHERE username = ? AND session_id = ? AND is_deleted = 0",
        )
        .bind(username)
        .bind(session_id)
        .fetch_all::<ChatArtifactRow>()
        .await?;

    for mut row in rows {
        row.is_deleted = 1;
        row.updated_at = now();
        insert_row("chat_artifacts", &row).await?;
    }
    Ok(())
}

/// Artifacts produced in one session, newest first. Used by the tool cards to resolve the
/// ids a tool payload carries without a round trip per card.
pub async fn list_session_artifacts(
    username: &str,
    session_id: &str,
) -> anyhow::Result<Vec<ChatArtifactRow>> {
    let client = get_global_client();
    Ok(client
        .query(
            "SELECT artifact_id, session_id, username, kind, tool_name, url, title, \
             thumb_key, body_key, body_bytes, thumb_bytes, status, detail, \
             created_at, updated_at, is_deleted \
             FROM chat_artifacts FINAL \
             WHERE username = ? AND session_id = ? AND is_deleted = 0 \
             ORDER BY created_at DESC LIMIT 500",
        )
        .bind(username)
        .bind(session_id)
        .fetch_all::<ChatArtifactRow>()
        .await?)
}
