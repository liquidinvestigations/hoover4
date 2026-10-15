//! Admin server settings API.

use common::admin_types::ServerSettingItem;
use common::current_user::CurrentUser;

use crate::auth::guard;
use crate::db_auth::settings;

/// Settings this build understands, with the value that applies when no row exists.
///
/// The page used to list `server_settings` and nothing else, so a setting nobody had ever
/// written was **invisible and therefore unreachable**. A setting that has validation here
/// and a reader in the worker, and no way for an admin to set it, is worse than one that does
/// not exist, because everything about it reads as working.
///
/// The default shown must be the one the reader actually falls back to. Where these
/// disagree the page misrepresents the current behaviour, so keep them together:
/// * `session_expiration_seconds`, `auth::session` (one week)
/// * `chat_enabled`: default `true`. Read at request time by `api::chat::gate`
const KNOWN_SETTINGS: &[(&str, &str)] = &[
    ("session_expiration_seconds", "604800"),
    (common::chat_gate::CHAT_ENABLED_SETTING, "true"),
    // Read by `tasks/P_board/activities.py::_cap`: the board model work of all boards
    // together, explores and reasons. Default 1.
    ("board_max_parallel_explores", "1"),
];

/// Settings that this build no longer reads, with the reason that the setter gives. A stored
/// row of one of them stays in the table. The page does not list it, and the setter refuses
/// it, so no control on the page does nothing. An empty reason names `hoover4.ini`, which sets
/// the models. Chat content has no age limit, so no setting can remove it by age.
const RETIRED_SETTINGS: [(&str, &str); 5] = [
    ("llm_default_chat_model", ""),
    ("llm_summarization_model", ""),
    ("llm_model_internal_search", ""),
    ("llm_model_full_research", ""),
    ("chat_artifact_ttl_days", "Chat content is kept permanently. This setting no longer exists."),
];

fn retired(key: &str) -> Option<&'static str> {
    RETIRED_SETTINGS.iter().find(|(k, _)| *k == key).map(|(_, why)| *why)
}

/// Settings that a deployment step writes. The page does not list them and the setter
/// refuses them. `board_node_identity_version` selects the id format of new board nodes, and
/// `main.py activate-board-node-ids` sets it once the compatible services run. A lower value
/// would give new nodes ids that the stored nodes can already have.
const INTERNAL_SETTINGS: [&str; 1] = ["board_node_identity_version"];

/// Deployment configuration the page shows but cannot change: these come from
/// `hoover4.ini` through the container's environment, so a form field for them would be a
/// control that silently does nothing. They are listed because the alternative (a key
/// that decides what the dataset-creation form can reach, visible nowhere in the UI) is
/// how a setting becomes unreachable.
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
        .filter(|r| retired(&r.key).is_none() && !INTERNAL_SETTINGS.contains(&r.key.as_str()))
        .map(|r| ServerSettingItem {
            key: r.key,
            value: r.value,
        })
        .collect();
    // Known-but-unset settings are appended at their default, so they can be edited into
    // existence. A stored row always wins. This only fills gaps.
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
        k if INTERNAL_SETTINGS.contains(&k) => {
            anyhow::bail!("{key} is set by the deployment, not on this page")
        }
        k if retired(k).is_some() => {
            match retired(k).unwrap_or_default() {
                "" => anyhow::bail!("{key} is set in hoover4.ini, not on this page"),
                why => anyhow::bail!("{why}"),
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
        s if s == common::chat_gate::CHAT_ENABLED_SETTING => {
            match value.trim().to_ascii_lowercase().as_str() {
                "true" | "false" => {}
                _ => anyhow::bail!("chat_enabled must be true or false"),
            }
        }
        _ => {}
    }
    settings::set_setting(&key, &value).await
}
