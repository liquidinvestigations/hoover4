//! User table CRUD.

use crate::db_auth::{insert_row, now};
use crate::db_utils::clickhouse_utils::get_clickhouse_client;

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
pub struct UserRow {
    pub username: String,
    pub fullname: String,
    pub email: String,
    pub is_admin: bool,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub created_at: time::OffsetDateTime,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub updated_at: time::OffsetDateTime,
    pub is_deleted: u8,
}

pub async fn get_user(username: &str) -> anyhow::Result<Option<UserRow>> {
    let client = get_clickhouse_client();
    let mut rows = client
        .query("SELECT username, fullname, email, is_admin, created_at, updated_at, is_deleted FROM users FINAL WHERE username = ? AND is_deleted = 0")
        .bind(username)
        .fetch_all::<UserRow>()
        .await?;
    Ok(rows.pop())
}

pub async fn list_users() -> anyhow::Result<Vec<UserRow>> {
    let client = get_clickhouse_client();
    client
        .query("SELECT username, fullname, email, is_admin, created_at, updated_at, is_deleted FROM users FINAL WHERE is_deleted = 0 ORDER BY username")
        .fetch_all::<UserRow>()
        .await
        .map_err(Into::into)
}

pub async fn upsert_user(mut row: UserRow) -> anyhow::Result<()> {
    let existing = get_user(&row.username).await?;
    if let Some(existing) = existing {
        row.created_at = existing.created_at;
    } else {
        row.created_at = now();
    }
    row.updated_at = now();
    row.is_deleted = 0;
    insert_row("users", &row).await
}

pub async fn soft_delete_user(username: &str) -> anyhow::Result<()> {
    let Some(mut row) = get_user(username).await? else {
        return Ok(());
    };
    row.updated_at = now();
    row.is_deleted = 1;
    insert_row("users", &row).await
}
