//! `/admin/llm`: the catalog, the models that `hoover4.ini` sets, the thinking switch and the
//! background refresh.

use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use common::current_user::CurrentUser;
use common::llm_types::{AdminLlmPage, LlmModelItem, LlmProviderHealth};

use crate::auth::guard;
use crate::db_auth::settings;
use crate::db_utils::clickhouse_utils::get_global_client;

static REFRESH_IN_FLIGHT: AtomicBool = AtomicBool::new(false);

const CATALOG_STALE_SECONDS: i64 = 3 * 60 * 60;

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct ModelRow {
    provider: String,
    model_id: String,
    display_name: String,
    context_window: u32,
    price_in_milli: u32,
    price_out_milli: u32,
    supports_tools: u8,
    supports_vision: u8,
    is_reasoning: u8,
    fetched_at: i64,
}

/// The median latency and call count of one model over 14 days of `llm_call_events`.
/// Only `kind = 'chat'` rows count, so a title call does not move
/// the median of a chat model.
#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct LatencyRow {
    model_id: String,
    median_ms: f64,
    calls: u64,
}

fn format_ts(unix_seconds: i64) -> String {
    if unix_seconds <= 0 {
        return String::new();
    }
    time::OffsetDateTime::from_unix_timestamp(unix_seconds)
        .ok()
        .and_then(|dt| dt.format(&time::format_description::well_known::Rfc3339).ok())
        .unwrap_or_else(|| unix_seconds.to_string())
}

fn llm_configured() -> bool {
    std::env::var("LLM_BASE_URL")
        .ok()
        .map(|s| !s.trim().is_empty())
        .unwrap_or(false)
}

/// The model of agent turns: `LLM_QUALITY_MODEL` when it is set, else `LLM_MODEL`. Both come
/// from `[llm_provider.<name>]` of `hoover4.ini` through `deploy.py`, which renders the quality
/// model only together with its endpoint. No setting overrides it.
///
/// **Mirrored in `main_services/processing/tasks/llm_endpoints.py`** (`chat_model`).
pub fn agent_model() -> String {
    agent_model_from(
        &std::env::var("LLM_QUALITY_MODEL").unwrap_or_default(),
        &std::env::var("LLM_MODEL").unwrap_or_default(),
    )
}

fn agent_model_from(quality: &str, base: &str) -> String {
    let quality = quality.trim();
    if quality.is_empty() { base.trim().to_string() } else { quality.to_string() }
}

/// The model of short calls (titles, summaries, board labels and assessments): `LLM_MODEL`.
pub fn short_call_model() -> String {
    std::env::var("LLM_MODEL").unwrap_or_default().trim().to_string()
}

/// The model of a new chat turn, or an error when `hoover4.ini` configures none.
pub fn chat_turn_model() -> anyhow::Result<String> {
    let model = agent_model();
    if model.is_empty() {
        anyhow::bail!("no LLM provider is configured; set one in hoover4.ini");
    }
    Ok(model)
}

pub async fn admin_get_llm(user: &CurrentUser) -> anyhow::Result<AdminLlmPage> {
    guard::require_admin(user)?;
    let client = get_global_client();

    let rows = client
        .query(
            "SELECT provider, model_id, \
                    argMax(display_name, updated_at) AS display_name, \
                    argMax(context_window, updated_at) AS context_window, \
                    argMax(price_in_milli, updated_at) AS price_in_milli, \
                    argMax(price_out_milli, updated_at) AS price_out_milli, \
                    argMax(supports_tools, updated_at) AS supports_tools, \
                    argMax(supports_vision, updated_at) AS supports_vision, \
                    argMax(is_reasoning, updated_at) AS is_reasoning, \
                    toInt64(toUnixTimestamp(argMax(fetched_at, updated_at))) AS fetched_at \
             FROM llm_models \
             GROUP BY provider, model_id \
             HAVING argMax(is_deleted, updated_at) = 0 \
             ORDER BY provider, model_id \
             LIMIT 2000",
        )
        .fetch_all::<ModelRow>()
        .await
        .unwrap_or_default();

    let latency = client
        .query(
            "SELECT model_id, quantile(0.5)(latency_ms) AS median_ms, count() AS calls \
             FROM llm_call_events \
             WHERE event_time >= now() - INTERVAL 14 DAY AND kind = 'chat' \
             GROUP BY model_id",
        )
        .fetch_all::<LatencyRow>()
        .await
        .unwrap_or_default();
    let mut latency_map = std::collections::HashMap::new();
    for r in latency {
        latency_map.insert(r.model_id, (r.median_ms as u32, r.calls));
    }

    let now = time::OffsetDateTime::now_utc().unix_timestamp();
    let mut providers_map: std::collections::BTreeMap<String, LlmProviderHealth> =
        std::collections::BTreeMap::new();
    let mut models = Vec::with_capacity(rows.len());
    for r in rows {
        let (median, calls) = latency_map
            .get(&r.model_id)
            .copied()
            .unwrap_or((0, 0));
        let stale = r.fetched_at > 0 && (now - r.fetched_at) > CATALOG_STALE_SECONDS;
        let entry = providers_map.entry(r.provider.clone()).or_insert_with(|| {
            LlmProviderHealth {
                provider: r.provider.clone(),
                ok: true,
                model_count: 0,
                freshest_fetched_at: String::new(),
                stale: true,
                error: String::new(),
            }
        });
        entry.model_count += 1;
        if r.fetched_at > 0 {
            let ts = format_ts(r.fetched_at);
            if entry.freshest_fetched_at.is_empty() || ts > entry.freshest_fetched_at {
                entry.freshest_fetched_at = ts;
            }
            if !stale {
                entry.stale = false;
            }
        }
        models.push(LlmModelItem {
            provider: r.provider,
            model_id: r.model_id,
            display_name: r.display_name,
            context_window: r.context_window,
            price_in_milli: r.price_in_milli,
            price_out_milli: r.price_out_milli,
            supports_tools: r.supports_tools != 0,
            supports_vision: r.supports_vision != 0,
            is_reasoning: r.is_reasoning != 0,
            fetched_at: format_ts(r.fetched_at),
            median_latency_ms: median,
            call_count_14d: calls,
        });
    }

    // If no catalog rows exist but LLM_BASE_URL is set, report the provider as
    // present-but-empty so the admin page can trigger a refresh.
    if providers_map.is_empty() && llm_configured() {
        let name = provider_name_from_url(&std::env::var("LLM_BASE_URL").unwrap_or_default());
        providers_map.insert(
            name.clone(),
            LlmProviderHealth {
                provider: name,
                ok: false,
                model_count: 0,
                freshest_fetched_at: String::new(),
                stale: true,
                error: "The catalog is empty. Click Refresh.".into(),
            },
        );
    }

    Ok(AdminLlmPage {
        providers: providers_map.into_values().collect(),
        models,
        agent_model: agent_model(),
        short_call_model: short_call_model(),
        refresh_in_flight: REFRESH_IN_FLIGHT.load(Ordering::Relaxed),
        llm_configured: llm_configured() || !agent_model().is_empty(),
        thinking: llm_thinking().await,
    })
}

/// The `server_settings` key of the thinking switch. The worker reads the same key
/// before each agent model call.
pub const LLM_THINKING_KEY: &str = "llm_thinking";

/// Parse a stored `llm_thinking` value. Only `off` turns thinking off. An absent row,
/// an empty value and every other value mean on.
pub fn thinking_from_setting(value: Option<&str>) -> bool {
    !matches!(value.map(str::trim), Some("off"))
}

/// The thinking switch as stored. A failed read returns on, as the worker does.
pub async fn llm_thinking() -> bool {
    match settings::get_setting(LLM_THINKING_KEY).await {
        Ok(v) => thinking_from_setting(v.as_deref()),
        Err(_) => true,
    }
}

/// Turn the thinking of agent model calls on or off. The next model call of every run
/// reads the new value.
pub async fn admin_set_llm_thinking(user: &CurrentUser, on: bool) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    settings::set_setting(LLM_THINKING_KEY, if on { "on" } else { "off" }).await
}

/// Kick a background catalog refresh. Returns immediately; never blocks the request
/// path: N concurrent readers refreshing on demand is a thundering herd against every
/// provider.
pub async fn admin_refresh_catalog(user: &CurrentUser) -> anyhow::Result<bool> {
    guard::require_admin(user)?;
    if REFRESH_IN_FLIGHT
        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .is_err()
    {
        return Ok(false);
    }
    let handle = tokio::runtime::Handle::current();
    handle.spawn(async {
        if let Err(e) = refresh_catalog_now().await {
            tracing::warn!("catalog refresh failed: {e:#}");
        }
        REFRESH_IN_FLIGHT.store(false, Ordering::SeqCst);
    });
    Ok(true)
}

/// One provider's catalog as it stands *before* a refresh, keyed by model id.
///
/// A refresh knows nothing but the ids `/models` returned. Everything else in the table
/// was put there by an earlier writer or by the Python catalog task, and re-deriving it as
/// zero would destroy it. Failure here is
/// deliberately non-fatal but not silent: an empty map means the refresh writes default
/// values, so it is logged loudly rather than swallowed.
#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct PriorModel {
    model_id: String,
    display_name: String,
    context_window: u32,
    price_in_milli: u32,
    price_out_milli: u32,
    supports_tools: u8,
    supports_vision: u8,
    is_reasoning: u8,
    is_allowed: u8,
    #[serde(with = "clickhouse::serde::time::datetime")]
    fetched_at: time::OffsetDateTime,
    is_deleted: u8,
}

async fn prior_catalog(provider: &str) -> std::collections::HashMap<String, PriorModel> {
    let rows = get_global_client()
        .query(
            "SELECT model_id, \
                    argMax(display_name, updated_at) AS display_name, \
                    argMax(context_window, updated_at) AS context_window, \
                    argMax(price_in_milli, updated_at) AS price_in_milli, \
                    argMax(price_out_milli, updated_at) AS price_out_milli, \
                    argMax(supports_tools, updated_at) AS supports_tools, \
                    argMax(supports_vision, updated_at) AS supports_vision, \
                    argMax(is_reasoning, updated_at) AS is_reasoning, \
                    argMax(is_allowed, updated_at) AS is_allowed, \
                    argMax(fetched_at, updated_at) AS fetched_at, \
                    argMax(is_deleted, updated_at) AS is_deleted \
             FROM llm_models WHERE provider = ? GROUP BY model_id LIMIT 5000",
        )
        .bind(provider)
        .fetch_all::<PriorModel>()
        .await;
    match rows {
        Ok(rows) => rows
            .into_iter()
            .map(|r| (r.model_id.clone(), r))
            .collect(),
        Err(e) => {
            tracing::warn!(
                "catalog refresh could not read the current state of provider {provider}: \
                 {e:#}. Stored catalog columns for this provider may be reset"
            );
            std::collections::HashMap::new()
        }
    }
}

async fn refresh_catalog_now() -> anyhow::Result<()> {
    let base = std::env::var("LLM_BASE_URL")
        .map_err(|_| anyhow::anyhow!("LLM_BASE_URL unset"))?
        .trim_end_matches('/')
        .to_string();
    if base.is_empty() {
        anyhow::bail!("LLM_BASE_URL empty");
    }
    let api_key = read_llm_api_key();
    let provider = provider_name_from_url(&base);
    let client = reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(3))
        .timeout(Duration::from_secs(5))
        .build()?;
    let mut req = client.get(format!("{base}/models"));
    if !api_key.is_empty() {
        req = req.bearer_auth(&api_key);
    }
    let resp = req.send().await?;
    if !resp.status().is_success() {
        anyhow::bail!("provider returned {}", resp.status());
    }
    let body: serde_json::Value = resp.json().await?;
    let entries: Vec<&serde_json::Value> = body
        .get("data")
        .and_then(|d| d.as_array())
        .map(|arr| arr.iter().collect())
        .unwrap_or_default();
    let models: Vec<String> = entries
        .iter()
        .filter_map(|m| m.get("id").and_then(|i| i.as_str()).map(str::to_string))
        .collect();
    // The window the listing stated, for the models that stated one. A model missing
    // from this map is one the provider said nothing about, and the stored value is
    // carried forward rather than blanked or guessed.
    let windows: std::collections::HashMap<String, u32> = entries
        .iter()
        .filter_map(|m| {
            let id = m.get("id").and_then(|i| i.as_str())?;
            let window = context_window_from_entry(m)?;
            Some((id.to_string(), window))
        })
        .collect();
    if models.is_empty() {
        anyhow::bail!("provider returned zero models");
    }

    #[derive(Debug, Clone, clickhouse::Row, serde::Serialize)]
    struct InsertModel {
        provider: String,
        model_id: String,
        display_name: String,
        context_window: u32,
        price_in_milli: u32,
        price_out_milli: u32,
        supports_tools: u8,
        supports_vision: u8,
        is_reasoning: u8,
        is_allowed: u8,
        #[serde(with = "clickhouse::serde::time::datetime")]
        fetched_at: time::OffsetDateTime,
        #[serde(with = "clickhouse::serde::time::datetime")]
        updated_at: time::OffsetDateTime,
        is_deleted: u8,
    }

    let now = crate::db_auth::now();
    let client = get_global_client();
    let prior = prior_catalog(&provider).await;

    let mut insert = client.insert::<InsertModel>("llm_models").await?;
    for model_id in &models {
        let display = model_id.rsplit('/').next().unwrap_or(model_id).to_string();
        let is_reasoning = if model_id.to_lowercase().contains("nemotron")
            || model_id.to_lowercase().contains("reason")
            || model_id.to_lowercase().contains("thinking")
        {
            1
        } else {
            0
        };
        // Everything the provider's `/models` does not tell us is carried forward from
        // the row already stored, because this table is a ReplacingMergeTree read through
        // `argMax(…, updated_at)` and a fresher row replaces every column. `is_allowed` is
        // carried with the rest. No code reads it since the models come from `hoover4.ini`.
        // Prices and capability flags are carried so that a refresh does not blank what
        // another writer discovered.
        let prior = prior.get(model_id.as_str());
        insert
            .write(&InsertModel {
                provider: provider.clone(),
                model_id: model_id.clone(),
                display_name: display,
                // What the provider just said, else what was stored, else 0 for
                // unknown. Never a default: a percentage of an invented window reads
                // as a measurement, and the compaction trigger trusts it.
                context_window: windows
                    .get(model_id.as_str())
                    .copied()
                    .or_else(|| prior.map(|p| p.context_window))
                    .unwrap_or(0),
                price_in_milli: prior.map(|p| p.price_in_milli).unwrap_or(0),
                price_out_milli: prior.map(|p| p.price_out_milli).unwrap_or(0),
                supports_tools: prior.map(|p| p.supports_tools).unwrap_or(0),
                supports_vision: prior.map(|p| p.supports_vision).unwrap_or(0),
                is_reasoning,
                // Never seen before → allowed. Seen before → whatever the admin left it
                // at, including on a model the provider dropped and has now re-listed.
                is_allowed: prior.map(|p| p.is_allowed).unwrap_or(1),
                fetched_at: now,
                updated_at: now,
                is_deleted: 0,
            })
            .await?;
    }

    // The tombstone the migration comment promises. A model the provider has stopped
    // listing gets one `is_deleted = 1` version; every reader filters on
    // `argMax(is_deleted, updated_at)`, so it disappears from the catalog list without any
    // row being deleted, and comes back with its stored columns intact if the provider lists
    // it again. Written on the same insert as the live rows
    // so a refresh is one atomic-enough batch rather than two.
    let listed: std::collections::HashSet<&str> = models.iter().map(String::as_str).collect();
    let mut tombstoned = 0usize;
    for (model_id, p) in prior.iter() {
        if p.is_deleted != 0 || listed.contains(model_id.as_str()) {
            continue;
        }
        insert
            .write(&InsertModel {
                provider: provider.clone(),
                model_id: model_id.clone(),
                display_name: p.display_name.clone(),
                context_window: p.context_window,
                price_in_milli: p.price_in_milli,
                price_out_milli: p.price_out_milli,
                supports_tools: p.supports_tools,
                supports_vision: p.supports_vision,
                is_reasoning: p.is_reasoning,
                is_allowed: p.is_allowed,
                // Not `now`: this is the last time the provider actually confirmed it.
                fetched_at: p.fetched_at,
                updated_at: now,
                is_deleted: 1,
            })
            .await?;
        tombstoned += 1;
    }
    insert.end().await?;
    if tombstoned > 0 {
        tracing::info!(
            "catalog refresh: provider {provider} no longer lists {tombstoned} model(s); \
             tombstoned"
        );
    }

    tracing::info!("catalog refresh stored {} models for {}", models.len(), provider);
    Ok(())
}

/// A short, stable name for the endpoint a base URL points at.
///
/// A registrable domain is named by its second-to-last label: `api.moonshot.ai` is
/// `moonshot`. An address literal has no such label, and taking one anyway names the
/// provider after an octet of its IP (`192.0.2.10:21960` becomes `2`), so the host and
/// its port are kept whole. Every place that names a provider goes through this,
/// including the placeholder row for a configured endpoint whose catalog is still empty:
/// two spellings of one endpoint render as two providers, one of them permanently empty.
pub(crate) fn provider_name_from_url(base: &str) -> String {
    if let Ok(name) = std::env::var("LLM_PROVIDER_NAME") {
        if !name.trim().is_empty() {
            return name;
        }
    }
    let host = base
        .trim_start_matches("https://")
        .trim_start_matches("http://")
        .split('/')
        .next()
        .unwrap_or("provider");
    if host.starts_with('[') {
        return host.to_string();
    }
    let bare = if host.matches(':').count() == 1 {
        host.rsplit_once(':').map(|(h, _)| h).unwrap_or(host)
    } else {
        host
    };
    if !bare.is_empty() && bare.chars().all(|c| c.is_ascii_digit() || c == '.') {
        return host.to_string();
    }
    let parts: Vec<_> = bare.split('.').collect();
    if parts.len() >= 2 {
        parts[parts.len() - 2].to_string()
    } else {
        bare.to_string()
    }
}

/// Where a provider states a model's context length, in the order to try.
///
/// `max_model_len` is vLLM's; `context_length` is what most OpenAI-compatible gateways
/// use; `context_window` is the name the table itself uses and some providers echo it.
///
/// Mirrors `_CONTEXT_WINDOW_KEYS` in `main_services/processing/tasks/llm_catalog.py`, and
/// so does the `meta.n_ctx` lookup of `context_window_from_entry`.
/// The two writers of `llm_models` must read the same keys or a refresh from one blanks
/// what the other discovered.
const CONTEXT_WINDOW_KEYS: [&str; 3] = ["max_model_len", "context_length", "context_window"];

/// The context window one `/models` entry states, or `None` when it states none.
///
/// There is deliberately no fallback guess. A wrong denominator is worse than an absent
/// one, because everything computed from it looks calculated.
fn context_window_from_entry(entry: &serde_json::Value) -> Option<u32> {
    // llama.cpp states the window inside `meta` as `n_ctx`, after the top-level keys.
    let candidates = CONTEXT_WINDOW_KEYS
        .iter()
        .map(|key| entry.get(*key))
        .chain(std::iter::once(entry.get("meta").and_then(|meta| meta.get("n_ctx"))));
    for raw in candidates {
        let Some(raw) = raw else {
            continue;
        };
        // A gateway that renders the number as a string is common enough to cost an
        // afternoon when it silently parses as nothing.
        let value = raw
            .as_u64()
            .or_else(|| raw.as_str().and_then(|s| s.trim().parse::<u64>().ok()));
        if let Some(value) = value {
            if value > 0 {
                return Some(value.min(u32::MAX as u64) as u32);
            }
        }
    }
    None
}

pub(crate) fn read_llm_api_key() -> String {
    if let Ok(key) = std::env::var("LLM_API_KEY") {
        if !key.trim().is_empty() {
            return key;
        }
    }
    if let Ok(path) = std::env::var("LLM_API_KEY_FILE") {
        if let Ok(key) = std::fs::read_to_string(&path) {
            return key.trim().to_string();
        }
    }
    String::new()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Thinking is on by default. Only the stored value `off` turns it off.
    #[test]
    fn thinking_is_on_unless_the_setting_says_off() {
        assert!(thinking_from_setting(None));
        assert!(thinking_from_setting(Some("")));
        assert!(thinking_from_setting(Some("on")));
        assert!(!thinking_from_setting(Some("off")));
        assert!(!thinking_from_setting(Some(" off ")));
    }

    /// An endpoint reached by IP must not be named after one of its octets, and the
    /// placeholder row for an empty catalog must spell the provider the same way the
    /// refresh will, otherwise one endpoint renders as two providers.
    #[test]
    fn a_provider_name_survives_an_address_literal() {
        let configured = std::env::var("LLM_PROVIDER_NAME").ok().filter(|name| !name.trim().is_empty());
        for (base, expected) in [
            ("https://api.moonshot.ai/v1", "moonshot"),
            ("https://integrate.api.nvidia.com/v1", "nvidia"),
            ("http://192.0.2.10:21960/v1", "192.0.2.10:21960"),
            ("http://127.0.0.1/v1", "127.0.0.1"),
            ("http://[fd00::1]:8000/v1", "[fd00::1]:8000"),
            ("http://localhost:8000/v1", "localhost"),
        ] {
            assert_eq!(provider_name_from_url(base), configured.as_deref().unwrap_or(expected), "{base}");
        }
    }

    /// The catalog is the only denominator anything has for "% of context used", so a
    /// listing that states a window must be trusted and one that states nothing must
    /// stay absent. A guess here is worse than a gap: the compaction trigger downstream
    /// fires on a percentage, and a plausible wrong window makes it fire wrongly.
    #[test]
    fn a_stated_context_window_is_read_and_an_unstated_one_stays_absent() {
        let cases: [(serde_json::Value, Option<u32>); 8] = [
            (serde_json::json!({"max_model_len": 262144}), Some(262144)),
            (serde_json::json!({"context_length": 128000}), Some(128000)),
            (serde_json::json!({"context_window": 8192}), Some(8192)),
            // Gateways that render the number as a string are common enough that
            // silently parsing one as nothing costs an afternoon.
            (serde_json::json!({"max_model_len": "262144"}), Some(262144)),
            // vLLM's key wins over a gateway's when both are present.
            (
                serde_json::json!({"max_model_len": 262144, "context_length": 4096}),
                Some(262144),
            ),
            (serde_json::json!({"id": "no-window-here"}), None),
            (serde_json::json!({"max_model_len": 0}), None),
            // llama.cpp states it inside `meta`.
            (serde_json::json!({"id": "m", "meta": {"n_ctx": 262144}}), Some(262144)),
        ];
        for (entry, expected) in cases {
            assert_eq!(context_window_from_entry(&entry), expected, "{entry}");
        }
    }

    /// The agent model is the quality model when `hoover4.ini` names one, and the provider
    /// model when it does not.
    #[test]
    fn the_agent_model_is_the_quality_model_when_one_is_set() {
        assert_eq!(agent_model_from("ornith", "dgemma"), "ornith");
        assert_eq!(agent_model_from(" ", "dgemma"), "dgemma");
        assert_eq!(agent_model_from("", ""), "");
    }
}
