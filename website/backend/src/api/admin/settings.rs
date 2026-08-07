//! Admin server settings API.

use common::admin_types::ServerSettingItem;
use common::current_user::CurrentUser;

use crate::auth::guard;
use crate::db_auth::settings;

/// Settings this build understands, with the value that applies when no row exists.
///
/// The page used to list `server_settings` and nothing else, so a setting nobody had ever
/// written was **invisible and therefore unreachable**: `chat_artifact_ttl_days` had
/// validation here and a reader in the artifact sweeper, and no way for an admin to set
/// it. A knob that exists in three places and cannot be turned is worse than one that does
/// not exist, because everything about it reads as working.
///
/// The default shown must be the one the reader actually falls back to. Where these
/// disagree the page is lying about the current behaviour, so keep them together:
/// * `chat_artifact_ttl_days` — `tasks/P_admin/artifact_sweeper.py::DEFAULT_TTL_DAYS`
/// * `session_expiration_seconds` — `auth::session` (one week)
/// * `guest_permissions_mode` — `auth::guard`
const KNOWN_SETTINGS: &[(&str, &str)] = &[
    ("session_expiration_seconds", "604800"),
    ("guest_permissions_mode", "none"),
    ("chat_artifact_ttl_days", "30"),
];

/// Deployment configuration the page shows but cannot change: these come from
/// `hoover4.ini` through the container's environment, so a form field for them would be a
/// control that silently does nothing. They are listed because the alternative — a key
/// that decides what the dataset-creation form can reach, visible nowhere in the UI — is
/// how `chat_artifact_ttl_days` became unreachable in the first place.
const DEPLOYMENT_KEYS: [(&str, &str); 1] = [("datasets_mount_path", "DATASETS_MOUNT_PATH")];

/// `(key, value)` for every deployment key, read from the environment.
pub async fn admin_list_deployment_config(
    user: &CurrentUser,
) -> anyhow::Result<Vec<ServerSettingItem>> {
    guard::require_admin(user)?;
    Ok(DEPLOYMENT_KEYS
        .iter()
        .map(|(key, env)| ServerSettingItem {
            key: (*key).to_string(),
            value: std::env::var(env).unwrap_or_default(),
        })
        .collect())
}

pub async fn admin_list_settings(user: &CurrentUser) -> anyhow::Result<Vec<ServerSettingItem>> {
    guard::require_admin(user)?;
    let rows = settings::list_settings().await?;
    let mut items: Vec<ServerSettingItem> = rows
        .into_iter()
        .map(|r| ServerSettingItem {
            key: r.key,
            value: r.value,
        })
        .collect();
    // Known-but-unset settings are appended at their default, so they can be edited into
    // existence. A stored row always wins — this only fills gaps.
    for (key, default) in KNOWN_SETTINGS {
        if !items.iter().any(|i| i.key == *key) {
            items.push(ServerSettingItem {
                key: (*key).to_string(),
                value: (*default).to_string(),
            });
        }
    }
    items.sort_by(|a, b| a.key.cmp(&b.key));
    Ok(items)
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
