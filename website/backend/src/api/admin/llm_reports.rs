//! The four reports of `/admin/llm`, read from `agent_step_events` and `agent_runs`.
//!
//! Each report runs only when an admin clicks its button, so a page load runs no query
//! here. Every figure is a count or a time of step attempts: one row of
//! `agent_step_events` is one attempt of a model call, a tool call or a title call.

use common::current_user::CurrentUser;
use common::llm_types::{ErrorCountRow, ErrorLogRow, ToolTableRow, TopUserRow};

use crate::auth::guard;
use crate::db_utils::clickhouse_utils::get_global_client;

/// The windows the top users report accepts, in days.
pub const TOP_USER_WINDOWS: [u16; 3] = [1, 7, 30];

/// The error counts. One row for each step and error class of the failed attempts,
/// and one row for each end class of the runs that failed or ended early. A run that
/// the step budget or the repeated call guard ended is `completed` with an
/// `end_reason`. It is not a failure, and it shows as its own class.
///
/// In ClickHouse an `ORDER BY` after `UNION ALL` applies to the last `SELECT` only, so
/// the union is a subquery and the order applies to the whole result.
const ERROR_COUNTS_SQL: &str = "\
SELECT source, class, d1, d7, d30 FROM ( \
    SELECT toString(step) AS source, toString(error_class) AS class, \
           countIf(event_time >= now() - INTERVAL 1 DAY) AS d1, \
           countIf(event_time >= now() - INTERVAL 7 DAY) AS d7, \
           count() AS d30 \
    FROM agent_step_events \
    WHERE ok = 0 AND event_time >= now() - INTERVAL 30 DAY \
    GROUP BY source, class \
    UNION ALL \
    SELECT 'run' AS source, if(end_reason != '', toString(end_reason), 'failed') AS class, \
           countIf(updated_at >= now() - INTERVAL 1 DAY) AS d1, \
           countIf(updated_at >= now() - INTERVAL 7 DAY) AS d7, \
           count() AS d30 \
    FROM agent_runs FINAL \
    WHERE (state = 'failed' OR end_reason != '') AND updated_at >= now() - INTERVAL 30 DAY \
    GROUP BY class \
) ORDER BY d30 DESC, source, class";

/// The newest 100 failed attempts of 7 days.
const ERROR_LOG_SQL: &str = "\
SELECT toUnixTimestamp64Milli(event_time) AS time_ms, toString(step) AS source, \
       toString(username) AS username, toString(name) AS name, \
       toString(error_class) AS class, substring(error, 1, 500) AS error \
FROM agent_step_events \
WHERE ok = 0 AND event_time >= now() - INTERVAL 7 DAY \
ORDER BY event_time DESC \
LIMIT 100";

/// One row for each tool, by calls in 30 days. An average over a window with no call
/// is NaN in ClickHouse, and JSON has no NaN, so `ifNotFinite` makes it 0.
const TOOL_TABLE_SQL: &str = "\
SELECT toString(name) AS tool, \
       countIf(event_time >= now() - INTERVAL 1 DAY) AS calls_24h, \
       ifNotFinite(round(100 * avgIf(ok = 0, event_time >= now() - INTERVAL 1 DAY), 1), 0) AS err_pct_24h, \
       ifNotFinite(round(avgIf(duration_ms, event_time >= now() - INTERVAL 1 DAY)), 0) AS avg_ms_24h, \
       countIf(event_time >= now() - INTERVAL 7 DAY) AS calls_7d, \
       ifNotFinite(round(100 * avgIf(ok = 0, event_time >= now() - INTERVAL 7 DAY), 1), 0) AS err_pct_7d, \
       ifNotFinite(round(avgIf(duration_ms, event_time >= now() - INTERVAL 7 DAY)), 0) AS avg_ms_7d, \
       count() AS calls_30d, \
       ifNotFinite(round(100 * avg(ok = 0), 1), 0) AS err_pct_30d, \
       ifNotFinite(round(avg(duration_ms)), 0) AS avg_ms_30d \
FROM agent_step_events \
WHERE step = 'tool' AND event_time >= now() - INTERVAL 30 DAY \
GROUP BY tool \
ORDER BY calls_30d DESC, tool";

/// The 30 users with the most model time in the window. Model time counts the model
/// and the title steps.
const TOP_USERS_SQL: &str = "\
SELECT toString(username) AS username, \
       countIf(step = 'tool') AS tool_calls, \
       toUInt64(sumIf(duration_ms, step = 'tool')) AS tool_ms, \
       countIf(step IN ('model', 'title')) AS model_calls, \
       toUInt64(sumIf(duration_ms, step IN ('model', 'title'))) AS model_ms, \
       toUInt64(sum(prompt_tokens)) AS tokens_in, \
       toUInt64(sum(completion_tokens)) AS tokens_out \
FROM agent_step_events \
WHERE event_time >= now() - toIntervalDay(?) \
GROUP BY username \
ORDER BY model_ms DESC, username \
LIMIT 30";

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct ErrorCountDbRow {
    source: String,
    class: String,
    d1: u64,
    d7: u64,
    d30: u64,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct ErrorLogDbRow {
    time_ms: i64,
    source: String,
    username: String,
    name: String,
    class: String,
    error: String,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct ToolTableDbRow {
    tool: String,
    calls_24h: u64,
    err_pct_24h: f64,
    avg_ms_24h: f64,
    calls_7d: u64,
    err_pct_7d: f64,
    avg_ms_7d: f64,
    calls_30d: u64,
    err_pct_30d: f64,
    avg_ms_30d: f64,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct TopUserDbRow {
    username: String,
    tool_calls: u64,
    tool_ms: u64,
    model_calls: u64,
    model_ms: u64,
    tokens_in: u64,
    tokens_out: u64,
}

/// The error counts report.
pub async fn admin_llm_error_counts(user: &CurrentUser) -> anyhow::Result<Vec<ErrorCountRow>> {
    guard::require_admin(user)?;
    let rows = get_global_client()
        .query(ERROR_COUNTS_SQL)
        .fetch_all::<ErrorCountDbRow>()
        .await?;
    Ok(rows
        .into_iter()
        .map(|r| ErrorCountRow {
            source: r.source,
            class: r.class,
            d1: r.d1,
            d7: r.d7,
            d30: r.d30,
        })
        .collect())
}

/// The recent error log report.
pub async fn admin_llm_error_log(user: &CurrentUser) -> anyhow::Result<Vec<ErrorLogRow>> {
    guard::require_admin(user)?;
    let rows = get_global_client()
        .query(ERROR_LOG_SQL)
        .fetch_all::<ErrorLogDbRow>()
        .await?;
    Ok(rows
        .into_iter()
        .map(|r| ErrorLogRow {
            time_ms: r.time_ms,
            source: r.source,
            username: r.username,
            name: r.name,
            class: r.class,
            error: r.error,
        })
        .collect())
}

/// The tool call report.
pub async fn admin_llm_tool_table(user: &CurrentUser) -> anyhow::Result<Vec<ToolTableRow>> {
    guard::require_admin(user)?;
    let rows = get_global_client()
        .query(TOOL_TABLE_SQL)
        .fetch_all::<ToolTableDbRow>()
        .await?;
    Ok(rows
        .into_iter()
        .map(|r| ToolTableRow {
            tool: r.tool,
            calls_24h: r.calls_24h,
            err_pct_24h: r.err_pct_24h,
            avg_ms_24h: r.avg_ms_24h,
            calls_7d: r.calls_7d,
            err_pct_7d: r.err_pct_7d,
            avg_ms_7d: r.avg_ms_7d,
            calls_30d: r.calls_30d,
            err_pct_30d: r.err_pct_30d,
            avg_ms_30d: r.avg_ms_30d,
        })
        .collect())
}

/// The top users report. `days` is 1, 7 or 30. Any other value is refused.
pub async fn admin_llm_top_users(
    user: &CurrentUser,
    days: u16,
) -> anyhow::Result<Vec<TopUserRow>> {
    guard::require_admin(user)?;
    if !TOP_USER_WINDOWS.contains(&days) {
        anyhow::bail!("the window must be 1, 7 or 30 days, not {days}");
    }
    let rows = get_global_client()
        .query(TOP_USERS_SQL)
        .bind(days)
        .fetch_all::<TopUserDbRow>()
        .await?;
    Ok(rows
        .into_iter()
        .map(|r| TopUserRow {
            username: r.username,
            tool_calls: r.tool_calls,
            tool_ms: r.tool_ms,
            model_calls: r.model_calls,
            model_ms: r.model_ms,
            tokens_in: r.tokens_in,
            tokens_out: r.tokens_out,
        })
        .collect())
}
