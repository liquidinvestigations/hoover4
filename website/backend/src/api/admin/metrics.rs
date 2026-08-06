//! Admin metrics API: the `/admin/metrics` aggregates and per-user LLM usage.
//!
//! Reads the rolling 24h `usage_events` / `api_events` tables written by
//! [`crate::api::telemetry`], and the chat tables for the per-user LLM view.
//! Every entry point is admin-gated.
//!
//! The TTL on both tables is applied by background merges, so rows can outlive
//! 24 h briefly — every query here filters `event_ts >= now() - INTERVAL 24
//! HOUR` itself rather than trusting the TTL.

use common::current_user::CurrentUser;
use common::metrics_types::*;

use crate::api::rate_limit::{self, RateLimitKind};
use crate::auth::guard;
use crate::db_utils::clickhouse_utils::get_global_client;

const LAST_24H: &str = "event_ts >= now() - INTERVAL 24 HOUR";

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct EventTypeCountRow {
    event_type: String,
    count: u64,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct UserCountRow {
    username: String,
    count: u64,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct SeriesRow {
    bucket: i64,
    count: u64,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct ApiStatsRow {
    function_name: String,
    calls: u64,
    errors: u64,
    p50_ms: f64,
    p95_ms: f64,
    max_ms: u32,
    bytes_in: u64,
    bytes_out: u64,
}

fn format_ts(unix_seconds: i64) -> String {
    time::OffsetDateTime::from_unix_timestamp(unix_seconds)
        .ok()
        .and_then(|dt| dt.format(&time::format_description::well_known::Rfc3339).ok())
        .unwrap_or_else(|| unix_seconds.to_string())
}

/// Aggregates for `/admin/metrics`: the usage counters and the per-function
/// API stats, both over the last 24 h.
pub async fn admin_get_metrics(user: &CurrentUser) -> anyhow::Result<AdminMetrics> {
    guard::require_admin(user)?;
    let client = get_global_client();

    let per_event_type = client
        .query(&format!(
            "SELECT event_type, count() AS count FROM usage_events \
             WHERE {LAST_24H} GROUP BY event_type ORDER BY count DESC"
        ))
        .fetch_all::<EventTypeCountRow>()
        .await?
        .into_iter()
        .map(|r| UsageEventCount {
            event_type: r.event_type,
            count: r.count,
        })
        .collect();

    let per_user = client
        .query(&format!(
            "SELECT username, count() AS count FROM usage_events \
             WHERE {LAST_24H} GROUP BY username ORDER BY count DESC LIMIT 20"
        ))
        .fetch_all::<UserCountRow>()
        .await?
        .into_iter()
        .map(|r| UserEventCount {
            username: r.username,
            count: r.count,
        })
        .collect();

    let series = client
        .query(&format!(
            "SELECT toInt64(toUnixTimestamp(toStartOfHour(event_ts))) AS bucket, count() AS count \
             FROM usage_events WHERE {LAST_24H} GROUP BY bucket ORDER BY bucket"
        ))
        .fetch_all::<SeriesRow>()
        .await?
        .into_iter()
        .map(|r| UsageTimePoint {
            bucket: format_ts(r.bucket),
            count: r.count,
        })
        .collect();

    let api = client
        .query(&format!(
            "SELECT function_name, count() AS calls, sum(is_error) AS errors, \
                    quantile(0.5)(duration_ms) AS p50_ms, quantile(0.95)(duration_ms) AS p95_ms, \
                    max(duration_ms) AS max_ms, sum(bytes_in) AS bytes_in, sum(bytes_out) AS bytes_out \
             FROM api_events WHERE {LAST_24H} GROUP BY function_name ORDER BY calls DESC"
        ))
        .fetch_all::<ApiStatsRow>()
        .await?
        .into_iter()
        .map(|r| ApiFunctionStats {
            error_rate: if r.calls == 0 {
                0.0
            } else {
                r.errors as f64 / r.calls as f64
            },
            function_name: r.function_name,
            calls: r.calls,
            errors: r.errors,
            p50_ms: r.p50_ms as u32,
            p95_ms: r.p95_ms as u32,
            max_ms: r.max_ms,
            bytes_in: r.bytes_in,
            bytes_out: r.bytes_out,
        })
        .collect();

    Ok(AdminMetrics {
        usage: UsageMetrics {
            per_event_type,
            per_user,
            series,
        },
        api,
    })
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct SessionRow {
    session_id: String,
    title: String,
    created: i64,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct SessionStatsRow {
    session_id: String,
    message_count: u64,
    tool_calls: u64,
    agent_duration_ms: u64,
}

/// Per-user LLM usage for `/admin/users/:username/llm`: chat sessions, message
/// and tool-call counts, summed agent time, and current rate-limit usage.
///
/// Reads `chat_messages` / `chat_sessions` only — they are owned by the chat
/// feature and are never modified here.
pub async fn admin_get_user_llm(
    user: &CurrentUser,
    username: String,
) -> anyhow::Result<AdminUserLlmMetrics> {
    guard::require_admin(user)?;
    let client = get_global_client();

    let sessions = client
        .query(
            "SELECT session_id, any(title) AS title, toInt64(toUnixTimestamp(max(created_at))) AS created \
             FROM chat_sessions FINAL WHERE username = ? AND is_deleted = 0 \
             GROUP BY session_id ORDER BY created DESC LIMIT 50",
        )
        .bind(&username)
        .fetch_all::<SessionRow>()
        .await?;

    let stats = client
        .query(
            "SELECT session_id, count() AS message_count, countIf(role = 'tool') AS tool_calls, \
                    sum(agent_duration_ms) AS agent_duration_ms \
             FROM chat_messages FINAL WHERE username = ? GROUP BY session_id",
        )
        .bind(&username)
        .fetch_all::<SessionStatsRow>()
        .await?;

    let mut session_list: Vec<UserLlmSession> = Vec::with_capacity(sessions.len());
    for s in sessions {
        let st = stats.iter().find(|st| st.session_id == s.session_id);
        session_list.push(UserLlmSession {
            session_id: s.session_id,
            title: s.title,
            created_at: format_ts(s.created),
            message_count: st.map(|s| s.message_count).unwrap_or(0),
            tool_calls: st.map(|s| s.tool_calls).unwrap_or(0),
            agent_duration_ms: st.map(|s| s.agent_duration_ms).unwrap_or(0),
        });
    }

    let chat_messages = session_list.iter().map(|s| s.message_count).sum();
    let tool_calls = session_list.iter().map(|s| s.tool_calls).sum();
    let agent_duration_ms_total = session_list.iter().map(|s| s.agent_duration_ms).sum();

    let chat_limit = rate_limit::window_usage(&username, RateLimitKind::ChatMessage)
        .into_iter()
        .map(|(window, used, budget)| RateWindowUsage {
            window: window.to_string(),
            used,
            budget,
        })
        .collect();
    let api_limit = rate_limit::window_usage(&username, RateLimitKind::ApiCall)
        .into_iter()
        .map(|(window, used, budget)| RateWindowUsage {
            window: window.to_string(),
            used,
            budget,
        })
        .collect();

    Ok(AdminUserLlmMetrics {
        username,
        chat_messages,
        tool_calls,
        agent_duration_ms_total,
        sessions: session_list,
        chat_limit,
        api_limit,
        chat_per_minute: rate_limit::per_minute_limit(RateLimitKind::ChatMessage),
        api_per_minute: rate_limit::per_minute_limit(RateLimitKind::ApiCall),
    })
}
