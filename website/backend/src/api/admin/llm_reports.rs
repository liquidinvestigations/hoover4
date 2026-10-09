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

const SYSTEMONE_SQL: &str = "\
SELECT toString(hook) AS hook, toString(rule_id) AS rule_id, \
       countIf(event_time >= now() - INTERVAL 1 DAY) AS requests_24h, \
       countIf(event_time >= now() - INTERVAL 7 DAY) AS requests_7d, \
       count() AS requests_30d, toUInt64(sum(length(question_ids))) AS questions, \
       quantile(0.5)(latency_ms) AS median_ms, quantile(0.95)(latency_ms) AS p95_ms, \
       ifNotFinite(100 * avg(outcome != 'ok'), 0) AS error_pct, \
       ifNotFinite(100 * sum(positive_answers) / sum(scored_answers), 0) AS positive_pct, \
       toUInt64(sum(actions)) AS actions \
FROM (SELECT * FROM systemone_call_events \
      WHERE event_time >= now() - INTERVAL 30 DAY \
      ORDER BY event_time DESC LIMIT 1 BY request_id) \
GROUP BY hook, rule_id ORDER BY hook, rule_id";

const SYSTEMONE_FAILURES_SQL: &str = "\
SELECT toUnixTimestamp64Milli(event_time) AS time_ms, toString(hook) AS hook, \
       toString(rule_id) AS rule_id, toString(outcome) AS outcome \
FROM (SELECT * FROM systemone_call_events \
      WHERE event_time >= now() - INTERVAL 30 DAY \
      ORDER BY event_time DESC LIMIT 1 BY request_id) \
WHERE outcome != 'ok' ORDER BY event_time DESC LIMIT 100";

#[derive(Debug, clickhouse::Row, serde::Deserialize)]
struct SystemOneDbRow {
    hook: String, rule_id: String,
    requests_24h: u64, requests_7d: u64, requests_30d: u64, questions: u64,
    median_ms: f64, p95_ms: f64, error_pct: f64, positive_pct: f64, actions: u64,
}

#[derive(Debug, clickhouse::Row, serde::Deserialize)]
struct SystemOneFailureDbRow {
    time_ms: i64, hook: String, rule_id: String, outcome: String,
}

/// Read classifier counts and recent failures only when the administrator runs the report.
pub async fn admin_llm_systemone(user: &CurrentUser) -> anyhow::Result<common::llm_types::SystemOneReport> {
    guard::require_admin(user)?;
    let client = get_global_client();
    let (rows, failures) = tokio::try_join!(
        client.query(SYSTEMONE_SQL).fetch_all::<SystemOneDbRow>(),
        client.query(SYSTEMONE_FAILURES_SQL).fetch_all::<SystemOneFailureDbRow>(),
    )?;
    Ok(common::llm_types::SystemOneReport {
        rows: rows.into_iter().map(|r| common::llm_types::SystemOneRow {
            hook: r.hook, rule_id: r.rule_id, requests_24h: r.requests_24h,
            requests_7d: r.requests_7d, requests_30d: r.requests_30d,
            questions: r.questions, median_ms: r.median_ms, p95_ms: r.p95_ms,
            error_pct: r.error_pct, positive_pct: r.positive_pct, actions: r.actions,
        }).collect(),
        failures: failures.into_iter().map(|r| common::llm_types::SystemOneFailure {
            time_ms: r.time_ms, hook: r.hook, rule_id: r.rule_id, outcome: r.outcome,
        }).collect(),
    })
}
