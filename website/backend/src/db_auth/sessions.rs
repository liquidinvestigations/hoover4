//! Web session CRUD.

use rand::RngCore;

use crate::db_auth::{insert_row, now};
use crate::db_utils::clickhouse_utils::get_clickhouse_client;

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
pub struct SessionRow {
    pub session_id: String,
    pub username: String,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub created_at: time::OffsetDateTime,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub expires_at: time::OffsetDateTime,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub updated_at: time::OffsetDateTime,
    pub is_deleted: u8,
}

fn generate_session_id() -> String {
    let mut bytes = [0u8; 32];
    rand::rng().fill_bytes(&mut bytes);
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

pub async fn get_session(session_id: &str) -> anyhow::Result<Option<SessionRow>> {
    let client = get_clickhouse_client();
    let mut rows = client
        .query("SELECT session_id, username, created_at, expires_at, updated_at, is_deleted FROM web_sessions FINAL WHERE session_id = ? AND is_deleted = 0")
        .bind(session_id)
        .fetch_all::<SessionRow>()
        .await?;
    let row = rows.pop();
    if let Some(ref session) = row {
        if session.expires_at <= now() {
            return Ok(None);
        }
    }
    Ok(row)
}

pub async fn create_session(
    username: &str,
    expires_at: time::OffsetDateTime,
) -> anyhow::Result<SessionRow> {
    let row = SessionRow {
        session_id: generate_session_id(),
        username: username.to_string(),
        created_at: now(),
        expires_at,
        updated_at: now(),
        is_deleted: 0,
    };
    insert_row("web_sessions", &row).await?;
    Ok(row)
}

pub async fn delete_session(session_id: &str) -> anyhow::Result<()> {
    let client = get_clickhouse_client();
    let mut rows = client
        .query("SELECT session_id, username, created_at, expires_at, updated_at, is_deleted FROM web_sessions FINAL WHERE session_id = ? AND is_deleted = 0")
        .bind(session_id)
        .fetch_all::<SessionRow>()
        .await?;
    let Some(mut row) = rows.pop() else {
        return Ok(());
    };
    row.updated_at = now();
    row.is_deleted = 1;
    insert_row("web_sessions", &row).await
}

pub async fn delete_sessions_for_user(username: &str) -> anyhow::Result<()> {
    let client = get_clickhouse_client();
    let rows = client
        .query("SELECT session_id, username, created_at, expires_at, updated_at, is_deleted FROM web_sessions FINAL WHERE username = ? AND is_deleted = 0")
        .bind(username)
        .fetch_all::<SessionRow>()
        .await?;
    for mut row in rows {
        row.updated_at = now();
        row.is_deleted = 1;
        insert_row("web_sessions", &row).await?;
    }
    Ok(())
}
