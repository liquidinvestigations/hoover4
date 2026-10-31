//! The per-user settings in `user_settings`.

use std::collections::BTreeMap;

use crate::db_auth::{insert_row, now};
use crate::db_utils::clickhouse_utils::get_global_client;

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
pub struct UserSettingRow {
    pub username: String,
    pub key: String,
    pub value: String,
    #[serde(with = "clickhouse::serde::time::datetime64::millis")]
    pub updated_at: time::OffsetDateTime,
    pub is_deleted: u8,
}

/// The live settings of one user, by key.
pub async fn user_settings(username: &str) -> anyhow::Result<BTreeMap<String, String>> {
    let rows = get_global_client()
        .query("SELECT username, key, value, updated_at, is_deleted FROM user_settings FINAL WHERE username = ? AND is_deleted = 0")
        .bind(username)
        .fetch_all::<UserSettingRow>()
        .await?;
    Ok(rows.into_iter().map(|row| (row.key, row.value)).collect())
}

/// Store one setting. An empty value clears it.
pub async fn set_user_setting(username: &str, key: &str, value: &str) -> anyhow::Result<()> {
    let row = UserSettingRow {
        username: username.to_string(),
        key: key.to_string(),
        value: value.to_string(),
        updated_at: now(),
        is_deleted: u8::from(value.is_empty()),
    };
    insert_row("user_settings", &row).await
}
