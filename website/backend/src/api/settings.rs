//! The language settings of the signed-in user.

use anyhow::bail;
use common::current_user::CurrentUser;
use common::language::{supported_code, LanguageSettings, AGENT_LANGUAGE_KEY, UI_LANGUAGE_KEY};

use crate::db_auth::user_settings::{set_user_setting, user_settings};

/// The saved and the resolved languages of `user`. The browser header decides the
/// interface language when none is saved.
pub async fn language_settings(user: &CurrentUser, accept_language: Option<&str>) -> anyhow::Result<LanguageSettings> {
    let saved = user_settings(&user.username).await?;
    let get = |key: &str| saved.get(key).map(String::as_str).unwrap_or_default();
    Ok(LanguageSettings::resolve(get(UI_LANGUAGE_KEY), get(AGENT_LANGUAGE_KEY), accept_language))
}

/// Save both language settings of `user`. An empty value clears a setting: the interface
/// then follows the browser, and the agent follows the interface.
pub async fn save_language_settings(
    user: &CurrentUser,
    interface: &str,
    agent: &str,
    accept_language: Option<&str>,
) -> anyhow::Result<LanguageSettings> {
    for value in [interface, agent] {
        if !value.is_empty() && supported_code(value) != Some(value) {
            bail!("unsupported language code {value:?}");
        }
    }
    set_user_setting(&user.username, UI_LANGUAGE_KEY, interface).await?;
    set_user_setting(&user.username, AGENT_LANGUAGE_KEY, agent).await?;
    language_settings(user, accept_language).await
}
