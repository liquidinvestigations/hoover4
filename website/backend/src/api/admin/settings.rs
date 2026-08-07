//! Admin server settings API.

use common::admin_types::ServerSettingItem;
use common::current_user::CurrentUser;

use crate::auth::guard;
use crate::db_auth::settings;

pub async fn admin_list_settings(user: &CurrentUser) -> anyhow::Result<Vec<ServerSettingItem>> {
    guard::require_admin(user)?;
    let rows = settings::list_settings().await?;
    Ok(rows
        .into_iter()
        .map(|r| ServerSettingItem {
            key: r.key,
            value: r.value,
        })
        .collect())
}

pub async fn admin_set_setting(
    user: &CurrentUser,
    key: String,
    value: String,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    match key.as_str() {
        "session_expiration_seconds" => {
            let v: u64 = value.parse().map_err(|_| anyhow::anyhow!("must be a positive integer"))?;
            if v == 0 {
                anyhow::bail!("session_expiration_seconds must be > 0");
            }
        }
        "guest_permissions_mode" if value != "all" && value != "none" => {
            anyhow::bail!("guest_permissions_mode must be 'all' or 'none'");
        }
        "llm_default_chat_model" | "llm_summarization_model" => {
            if value.trim().is_empty() {
                anyhow::bail!("{key} must not be empty");
            }
            if value.chars().count() > 200 {
                anyhow::bail!("{key} is too long");
            }
        }
        "embeddings_serving_model" => {
            if value.trim().is_empty() {
                anyhow::bail!("embeddings_serving_model must not be empty");
            }
        }
        "embeddings_serving_dim" => {
            let v: u32 = value
                .parse()
                .map_err(|_| anyhow::anyhow!("embeddings_serving_dim must be a positive integer"))?;
            if v == 0 || v > 8192 {
                anyhow::bail!("embeddings_serving_dim must be between 1 and 8192");
            }
        }
        "chat_artifact_ttl_days" => {
            let v: u32 = value
                .parse()
                .map_err(|_| anyhow::anyhow!("chat_artifact_ttl_days must be a positive integer"))?;
            if v == 0 || v > 3650 {
                anyhow::bail!("chat_artifact_ttl_days must be between 1 and 3650");
            }
        }
        _ => {}
    }
    settings::set_setting(&key, &value).await
}
