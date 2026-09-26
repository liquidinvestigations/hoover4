//! Admin metrics API: the `/admin/metrics` aggregates and per-user LLM usage.
//!
//! Reads the rolling 24h `usage_events` / `api_events` tables written by
//! [`crate::api::telemetry`], and the chat tables for the per-user LLM view.
//! [`admin_get_manticore_load`] reads Manticore's own status for the load panel.
//! Every entry point is admin-gated.
//!
//! The TTL on both tables is applied by background merges, so rows can outlive
//! 24 h briefly, every query here filters `event_ts >= now() - INTERVAL 24
//! HOUR` itself rather than trusting the TTL.

use common::current_user::CurrentUser;
use common::metrics_types::*;

use crate::api::rate_limit::{self, RateLimitKind};
use crate::auth::guard;
use crate::db_utils::clickhouse_utils::get_global_client;
use crate::db_utils::manticore_utils::{manticore_raw_sql, ManticoreRawRow};

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
/// Reads `chat_messages` / `chat_sessions` only. They are owned by the chat
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

/// Status calls that one page load runs at once, one for each Manticore table.
const MANTICORE_STATUS_PARALLELISM: usize = 8;

/// Manticore's thread load, its work queue, and the memory and disk of its tables, for
/// `/admin/metrics`. It reads `SHOW STATUS`, `SHOW TABLES`, then `SHOW TABLE <t> STATUS`
/// for each table. A table whose status call fails counts as unread and the rest still
/// show. A failure of the first two calls fails the whole call.
pub async fn admin_get_manticore_load(user: &CurrentUser) -> anyhow::Result<ManticoreLoad> {
    use futures::StreamExt;

    guard::require_admin(user)?;
    let status = manticore_raw_sql("SHOW STATUS").await?;
    let tables = manticore_raw_sql("SHOW TABLES").await?;
    let names: Vec<String> = tables
        .iter()
        .filter_map(|row| row.get("Table").and_then(serde_json::Value::as_str))
        .map(str::to_string)
        .collect();
    let per_table: Vec<(String, anyhow::Result<Vec<ManticoreRawRow>>)> =
        futures::stream::iter(names)
            .map(|name| async move {
                // The name comes from SHOW TABLES and is interpolated into a statement,
                // so any name outside the table naming rule is refused, never sent.
                if !is_plain_table_name(&name) {
                    let refused = anyhow::anyhow!("table name {name:?} is not a plain name");
                    return (name, Err(refused));
                }
                let rows = manticore_raw_sql(&format!("SHOW TABLE {name} STATUS")).await;
                (name, rows)
            })
            .buffer_unordered(MANTICORE_STATUS_PARALLELISM)
            .collect()
            .await;
    let read_at = format_ts(time::OffsetDateTime::now_utc().unix_timestamp());
    Ok(manticore_load_from_rows(&status, per_table, read_at))
}

fn is_plain_table_name(name: &str) -> bool {
    !name.is_empty()
        && name
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
}

/// The value of one `Counter`/`Value` or `Variable_name`/`Value` row, by name.
fn status_value<'a>(rows: &'a [ManticoreRawRow], key_column: &str, name: &str) -> &'a str {
    rows.iter()
        .find(|row| row.get(key_column).and_then(serde_json::Value::as_str) == Some(name))
        .and_then(|row| row.get("Value").and_then(serde_json::Value::as_str))
        .unwrap_or("")
}

/// Three numbers of a `load` value, `"0.10 0.20 0.30"`. A value that does not parse is 0.
fn three_numbers(raw: &str) -> [f64; 3] {
    let mut out = [0.0; 3];
    for (slot, part) in out.iter_mut().zip(raw.split_whitespace()) {
        *slot = part.parse().unwrap_or(0.0);
    }
    out
}

/// Assemble the panel from the raw rows. Pure, so the parsing is tested without a server.
fn manticore_load_from_rows(
    status: &[ManticoreRawRow],
    per_table: Vec<(String, anyhow::Result<Vec<ManticoreRawRow>>)>,
    read_at: String,
) -> ManticoreLoad {
    let counter = |name: &str| status_value(status, "Counter", name);
    let table_count = per_table.len() as u32;
    let mut unread_tables = 0;
    let mut tables: Vec<ManticoreTableLoad> = Vec::new();
    for (table, rows) in per_table {
        let Ok(rows) = rows else {
            unread_tables += 1;
            continue;
        };
        let variable = |name: &str| status_value(&rows, "Variable_name", name);
        tables.push(ManticoreTableLoad {
            table,
            ram_bytes: variable("ram_bytes").parse().unwrap_or(0),
            disk_bytes: variable("disk_bytes").parse().unwrap_or(0),
            disk_chunks: variable("disk_chunks").parse().unwrap_or(0),
            optimizing: variable("optimizing").parse::<u32>().unwrap_or(0) > 0,
        });
    }
    let ram_bytes_total = tables.iter().map(|t| t.ram_bytes).sum();
    let disk_bytes_total = tables.iter().map(|t| t.disk_bytes).sum();
    let mut optimizing_tables: Vec<String> = tables
        .iter()
        .filter(|t| t.optimizing)
        .map(|t| t.table.clone())
        .collect();
    optimizing_tables.sort();
    tables.sort_by(|a, b| b.ram_bytes.cmp(&a.ram_bytes).then_with(|| a.table.cmp(&b.table)));
    tables.truncate(10);
    ManticoreLoad {
        read_at,
        uptime_seconds: counter("uptime").parse().unwrap_or(0),
        load: three_numbers(counter("load")),
        load_primary: three_numbers(counter("load_primary")),
        load_secondary: three_numbers(counter("load_secondary")),
        workers_total: counter("workers_total").parse().unwrap_or(0),
        workers_active: counter("workers_active").parse().unwrap_or(0),
        work_queue_length: counter("work_queue_length").parse().unwrap_or(0),
        table_count,
        unread_tables,
        ram_bytes_total,
        disk_bytes_total,
        optimizing_tables,
        largest_tables: tables,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::db_utils::manticore_utils::parse_raw_sql_response;

    fn rows(body: &str) -> Vec<ManticoreRawRow> {
        parse_raw_sql_response(body).unwrap()
    }

    #[test]
    fn the_panel_sums_the_tables_read_and_counts_the_rest() {
        let status = rows(
            r#"[{"data":[{"Counter":"uptime","Value":"41078"},
            {"Counter":"workers_total","Value":"16"},{"Counter":"workers_active","Value":"3"},
            {"Counter":"work_queue_length","Value":"17"},
            {"Counter":"load","Value":"0.10 0.20 0.30"},
            {"Counter":"load_primary","Value":"N/A 1.5 x"}],"error":""}]"#,
        );
        let table = |ram: u64, optimizing: u32| {
            Ok(rows(&format!(
                r#"[{{"data":[{{"Variable_name":"ram_bytes","Value":"{ram}"}},
                {{"Variable_name":"disk_bytes","Value":"100"}},
                {{"Variable_name":"disk_chunks","Value":"2"}},
                {{"Variable_name":"optimizing","Value":"{optimizing}"}}],"error":""}}]"#
            )))
        };
        let load = manticore_load_from_rows(
            &status,
            vec![
                ("a_pages".to_string(), table(10, 0)),
                ("b_pages".to_string(), table(30, 1)),
                ("c_vfs".to_string(), Err(anyhow::anyhow!("gone"))),
            ],
            "2026-01-01T00:00:00Z".to_string(),
        );
        assert_eq!(load.uptime_seconds, 41078);
        assert_eq!(load.load, [0.1, 0.2, 0.3]);
        assert_eq!(load.load_primary, [0.0, 1.5, 0.0]);
        assert_eq!(load.load_secondary, [0.0, 0.0, 0.0]);
        assert_eq!((load.workers_active, load.workers_total, load.work_queue_length), (3, 16, 17));
        assert_eq!((load.table_count, load.unread_tables), (3, 1));
        assert_eq!((load.ram_bytes_total, load.disk_bytes_total), (40, 200));
        assert_eq!(load.optimizing_tables, vec!["b_pages".to_string()]);
        assert_eq!(load.largest_tables[0].table, "b_pages");
        assert_eq!(load.largest_tables[0].disk_chunks, 2);
    }

    #[test]
    fn only_a_plain_table_name_is_sent() {
        assert!(is_plain_table_name("testdata_1_pages"));
        assert!(!is_plain_table_name(""));
        assert!(!is_plain_table_name("a; DROP TABLE b"));
        assert!(!is_plain_table_name("Upper"));
    }
}
