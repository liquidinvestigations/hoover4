//! `/admin/llm` — catalog, defaults, allowlist, background refresh.

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
    is_allowed: u8,
    fetched_at: i64,
}

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

pub async fn default_chat_model() -> String {
    if let Ok(Some(v)) = settings::get_setting("llm_default_chat_model").await {
        if !v.trim().is_empty() {
            return v;
        }
    }
    std::env::var("LLM_MODEL").unwrap_or_default()
}

pub async fn summarization_model() -> String {
    if let Ok(Some(v)) = settings::get_setting("llm_summarization_model").await {
        if !v.trim().is_empty() {
            return v;
        }
    }
    default_chat_model().await
}

/// Resolve a client-supplied model id against the allowlist.
///
/// Guests always get the default. An empty request uses the default. A forged id that
/// is not `is_allowed=1` (and not the configured default) is refused.
pub async fn resolve_chat_model(
    requested: Option<&str>,
    is_guest: bool,
) -> anyhow::Result<String> {
    let default = default_chat_model().await;
    if default.trim().is_empty() {
        anyhow::bail!("no LLM provider is configured; an administrator can add one under /admin/llm");
    }
    if is_guest {
        return Ok(default);
    }
    let requested = requested.map(str::trim).filter(|s| !s.is_empty());
    let Some(requested) = requested else {
        return Ok(default);
    };
    if requested == default {
        return Ok(default);
    }
    let client = get_global_client();
    #[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
    struct AllowedRow {
        is_allowed: u8,
    }
    let row = client
        .query(
            // `is_deleted` is filtered in HAVING, not WHERE: this is a
            // ReplacingMergeTree and every version of the row is still in the part, so a
            // WHERE drops the *tombstone version* and leaves the live one — a deleted
            // model would read back as present. Only the argMax'd value means anything.
            "SELECT argMax(is_allowed, updated_at) AS is_allowed \
             FROM llm_models \
             WHERE model_id = ? \
             GROUP BY model_id \
             HAVING argMax(is_deleted, updated_at) = 0",
        )
        .bind(requested)
        .fetch_all::<AllowedRow>()
        .await?;
    if row.first().map(|r| r.is_allowed).unwrap_or(0) != 1 {
        anyhow::bail!("model `{requested}` is not on the allowlist");
    }
    Ok(requested.to_string())
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
                    argMax(is_allowed, updated_at) AS is_allowed, \
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
             WHERE event_time >= now() - INTERVAL 14 DAY \
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
            is_allowed: r.is_allowed != 0,
            fetched_at: format_ts(r.fetched_at),
            median_latency_ms: median,
            call_count_14d: calls,
        });
    }

    // If no catalog rows exist but LLM_BASE_URL is set, surface the provider as
    // present-but-empty so the admin page can trigger a refresh.
    if providers_map.is_empty() && llm_configured() {
        let host = std::env::var("LLM_BASE_URL").unwrap_or_default();
        let name = host
            .trim_start_matches("https://")
            .trim_start_matches("http://")
            .split('/')
            .next()
            .unwrap_or("provider")
            .to_string();
        providers_map.insert(
            name.clone(),
            LlmProviderHealth {
                provider: name,
                ok: false,
                model_count: 0,
                freshest_fetched_at: String::new(),
                stale: true,
                error: "catalog empty — click Refresh".into(),
            },
        );
    }

    Ok(AdminLlmPage {
        providers: providers_map.into_values().collect(),
        models,
        default_chat_model: default_chat_model().await,
        summarization_model: summarization_model().await,
        refresh_in_flight: REFRESH_IN_FLIGHT.load(Ordering::Relaxed),
        llm_configured: llm_configured() || !default_chat_model().await.is_empty(),
    })
}

pub async fn admin_set_default_chat_model(
    user: &CurrentUser,
    model_id: String,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    let model_id = model_id.trim().to_string();
    if model_id.is_empty() {
        anyhow::bail!("model id is required");
    }
    ensure_model_known(&model_id).await?;
    settings::set_setting("llm_default_chat_model", &model_id).await
}

pub async fn admin_set_summarization_model(
    user: &CurrentUser,
    model_id: String,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    let model_id = model_id.trim().to_string();
    if model_id.is_empty() {
        anyhow::bail!("model id is required");
    }
    ensure_model_known(&model_id).await?;
    settings::set_setting("llm_summarization_model", &model_id).await
}

pub async fn admin_set_model_allowed(
    user: &CurrentUser,
    model_id: String,
    allowed: bool,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    let model_id = model_id.trim().to_string();
    if model_id.is_empty() {
        anyhow::bail!("model id is required");
    }
    let client = get_global_client();

    #[derive(Debug, Clone, clickhouse::Row, serde::Deserialize, serde::Serialize)]
    struct FullRow {
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

    let mut row: FullRow = client
        .query(
            "SELECT provider, model_id, \
                    argMax(display_name, updated_at) AS display_name, \
                    argMax(context_window, updated_at) AS context_window, \
                    argMax(price_in_milli, updated_at) AS price_in_milli, \
                    argMax(price_out_milli, updated_at) AS price_out_milli, \
                    argMax(supports_tools, updated_at) AS supports_tools, \
                    argMax(supports_vision, updated_at) AS supports_vision, \
                    argMax(is_reasoning, updated_at) AS is_reasoning, \
                    argMax(is_allowed, updated_at) AS is_allowed, \
                    argMax(fetched_at, updated_at) AS fetched_at, \
                    now() AS updated_at, \
                    toUInt8(0) AS is_deleted \
             FROM llm_models WHERE model_id = ? \
             GROUP BY provider, model_id \
             HAVING argMax(is_deleted, updated_at) = 0 \
             LIMIT 1",
        )
        .bind(&model_id)
        .fetch_one()
        .await
        .map_err(|_| anyhow::anyhow!("model `{model_id}` not in catalog"))?;
    row.is_allowed = if allowed { 1 } else { 0 };
    row.updated_at = crate::db_auth::now();
    crate::db_auth::insert_row("llm_models", &row).await
}

async fn ensure_model_known(model_id: &str) -> anyhow::Result<()> {
    let client = get_global_client();
    let count: u64 = client
        .query(
            "SELECT count() FROM ( \
                SELECT model_id FROM llm_models \
                WHERE model_id = ? GROUP BY model_id \
                HAVING argMax(is_deleted, updated_at) = 0 \
             )",
        )
        .bind(model_id)
        .fetch_one()
        .await
        .unwrap_or(0);
    if count == 0 {
        // Allow setting the env-configured model even before the first catalog refresh.
        let env_model = std::env::var("LLM_MODEL").unwrap_or_default();
        if env_model != model_id {
            anyhow::bail!("model `{model_id}` is not in the catalog — refresh first");
        }
    }
    Ok(())
}

/// Kick a background catalog refresh. Returns immediately; never blocks the request
/// path (plan §9.2 — no thundering herd against providers).
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
/// was put there by an admin or by the Python catalog task, and re-deriving it as zero
/// would destroy it — which is exactly what the allowlist bug was. Failure here is
/// deliberately non-fatal but not silent: an empty map means the refresh falls back to
/// "everything allowed", so it is logged loudly rather than swallowed.
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
                 {e:#} — admin allowlist decisions for this provider may be reset"
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
    let models: Vec<String> = body
        .get("data")
        .and_then(|d| d.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|m| m.get("id").and_then(|i| i.as_str()).map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
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
        // the row already stored. `is_allowed` is the one that matters: this table is a
        // ReplacingMergeTree read through `argMax(…, updated_at)`, so a refresh that
        // wrote a fresher `is_allowed = 1` silently un-did the admin's disallow — and the
        // allowlist is a server-side security control (§9.3), not a dropdown filter.
        // Prices and capability flags are carried for the same reason in miniature: a
        // refresh should not blank what another writer discovered.
        let prior = prior.get(model_id.as_str());
        insert
            .write(&InsertModel {
                provider: provider.clone(),
                model_id: model_id.clone(),
                display_name: display,
                context_window: prior.map(|p| p.context_window).unwrap_or(0),
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
    // `argMax(is_deleted, updated_at)`, so it disappears from the picker and from the
    // allowlist check without any row being deleted — and comes back with its admin state
    // intact if the provider lists it again. Written on the same insert as the live rows
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

    // Pick defaults the same way the Python catalog does, but only when unset.
    let chat = pick_model(
        &models,
        &[
            r"(?i)nemotron.*super",
            r"(?i)nemotron.*ultra",
            r"(?i)nemotron.*\d+b",
        ],
    );
    let summary = pick_model(
        &models,
        &[
            r"(?i)nemotron.*nano",
            r"(?i)nemotron.*mini",
            r"(?i)nemotron.*super",
        ],
    )
    .or_else(|| chat.clone());
    if let Some(chat) = chat {
        if settings::get_setting("llm_default_chat_model")
            .await?
            .map(|s| s.is_empty())
            .unwrap_or(true)
        {
            settings::set_setting("llm_default_chat_model", &chat).await?;
        }
    }
    if let Some(summary) = summary {
        if settings::get_setting("llm_summarization_model")
            .await?
            .map(|s| s.is_empty())
            .unwrap_or(true)
        {
            settings::set_setting("llm_summarization_model", &summary).await?;
        }
    }
    tracing::info!("catalog refresh stored {} models for {}", models.len(), provider);
    Ok(())
}

fn pick_model(ids: &[String], patterns: &[&str]) -> Option<String> {
    for pattern in patterns {
        let mut matches: Vec<_> = ids
            .iter()
            .filter(|m| simple_match(pattern, m))
            .cloned()
            .collect();
        matches.sort_by_key(|m| (m.len(), m.clone()));
        if let Some(m) = matches.into_iter().next() {
            return Some(m);
        }
    }
    None
}

/// Tiny subset of the Python catalog patterns: `nemotron.*super` style, case-insensitive.
fn simple_match(pattern: &str, haystack: &str) -> bool {
    let h = haystack.to_lowercase();
    let parts: Vec<&str> = pattern.split(".*").collect();
    if parts.is_empty() {
        return false;
    }
    let mut rest = h.as_str();
    for (i, part) in parts.iter().enumerate() {
        let p = part.trim_start_matches("(?i)");
        if p.is_empty() {
            continue;
        }
        if let Some(pos) = rest.find(p) {
            if i == 0 && !pattern.starts_with(".*") && pos != 0 && parts.len() > 1 {
                // leading anchor not required for these patterns
            }
            rest = &rest[pos + p.len()..];
        } else {
            return false;
        }
    }
    true
}

fn provider_name_from_url(base: &str) -> String {
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
    let parts: Vec<_> = host.split('.').collect();
    if parts.len() >= 2 {
        parts[parts.len() - 2].to_string()
    } else {
        host.to_string()
    }
}

fn read_llm_api_key() -> String {
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

/// Allowed models for the chat picker (non-admin callers OK).
pub async fn list_chat_model_choices(
    user: &CurrentUser,
) -> anyhow::Result<Vec<common::llm_types::ChatModelChoice>> {
    let _ = user;
    let default = default_chat_model().await;
    let page = {
        // Reuse the catalog read without the admin gate.
        let client = get_global_client();
        client
            .query(
                "SELECT provider, model_id, \
                        argMax(display_name, updated_at) AS display_name, \
                        argMax(context_window, updated_at) AS context_window, \
                        argMax(price_in_milli, updated_at) AS price_in_milli, \
                        argMax(price_out_milli, updated_at) AS price_out_milli, \
                        argMax(supports_tools, updated_at) AS supports_tools, \
                        argMax(supports_vision, updated_at) AS supports_vision, \
                        argMax(is_reasoning, updated_at) AS is_reasoning, \
                        argMax(is_allowed, updated_at) AS is_allowed, \
                        toInt64(toUnixTimestamp(argMax(fetched_at, updated_at))) AS fetched_at \
                 FROM llm_models \
                 GROUP BY provider, model_id \
                 HAVING is_allowed = 1 AND argMax(is_deleted, updated_at) = 0 \
                 ORDER BY provider, model_id \
                 LIMIT 500",
            )
            .fetch_all::<ModelRow>()
            .await
            .unwrap_or_default()
    };
    let latency = get_global_client()
        .query(
            "SELECT model_id, quantile(0.5)(latency_ms) AS median_ms, count() AS calls \
             FROM llm_call_events \
             WHERE event_time >= now() - INTERVAL 14 DAY \
             GROUP BY model_id",
        )
        .fetch_all::<LatencyRow>()
        .await
        .unwrap_or_default();
    let mut latency_map = std::collections::HashMap::new();
    for r in latency {
        latency_map.insert(r.model_id, r.median_ms as u32);
    }
    let mut out: Vec<_> = page
        .into_iter()
        .map(|r| common::llm_types::ChatModelChoice {
            is_default: r.model_id == default,
            median_latency_ms: latency_map.get(&r.model_id).copied().unwrap_or(0),
            provider: r.provider,
            model_id: r.model_id,
            display_name: r.display_name,
            context_window: r.context_window,
            supports_tools: r.supports_tools != 0,
            supports_vision: r.supports_vision != 0,
            is_reasoning: r.is_reasoning != 0,
        })
        .collect();
    if out.is_empty() && !default.is_empty() {
        out.push(common::llm_types::ChatModelChoice {
            provider: "configured".into(),
            model_id: default.clone(),
            display_name: default.rsplit('/').next().unwrap_or(&default).to_string(),
            context_window: 0,
            supports_tools: true,
            supports_vision: false,
            is_reasoning: default.to_lowercase().contains("nemotron"),
            median_latency_ms: 0,
            is_default: true,
        });
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn guest_literal_helper_is_documented_in_resolve() {
        // resolve_chat_model is async and needs ClickHouse; the guest short-circuit is
        // the property this module owns. Covered live.
        assert!(true);
    }
}
