//! Server settings CRUD.

use crate::db_auth::{insert_row, now};
use crate::db_utils::clickhouse_utils::get_clickhouse_client;

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
pub struct SettingRow {
    pub key: String,
    pub value: String,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub updated_at: time::OffsetDateTime,
    pub is_deleted: u8,
}

pub async fn get_setting(key: &str) -> anyhow::Result<Option<String>> {
    let client = get_clickhouse_client();
    let mut rows = client
        .query("SELECT key, value, updated_at, is_deleted FROM server_settings FINAL WHERE key = ? AND is_deleted = 0")
        .bind(key)
        .fetch_all::<SettingRow>()
        .await?;
    Ok(rows.pop().map(|r| r.value))
}

pub async fn list_settings() -> anyhow::Result<Vec<SettingRow>> {
    let client = get_clickhouse_client();
    client
        .query("SELECT key, value, updated_at, is_deleted FROM server_settings FINAL WHERE is_deleted = 0 ORDER BY key")
        .fetch_all::<SettingRow>()
        .await
        .map_err(Into::into)
}

pub async fn set_setting(key: &str, value: &str) -> anyhow::Result<()> {
    let row = SettingRow {
        key: key.to_string(),
        value: value.to_string(),
        updated_at: now(),
        is_deleted: 0,
    };
    insert_row("server_settings", &row).await
}

pub async fn get_setting_u64(key: &str, default: u64) -> anyhow::Result<u64> {
    match get_setting(key).await? {
        Some(v) => Ok(v.parse().unwrap_or(default)),
        None => Ok(default),
    }
}
