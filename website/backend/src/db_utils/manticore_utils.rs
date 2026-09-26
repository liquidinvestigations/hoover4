//! Utilities for Manticore query formatting and results.

use crate::db_utils::clickhouse_utils::get_global_client;
use serde::{Deserialize, Serialize, de::DeserializeOwned};
use std::collections::BTreeMap;
use std::time::Duration;

/// Seconds one shard query may take before it is a failure. Override with
/// [`SEARCH_TIMEOUT_ENV`] (clamped to 1..=600).
pub const SEARCH_TIMEOUT_SECONDS: u64 = 30;

pub const SEARCH_TIMEOUT_ENV: &str = "HOOVER4_SEARCH_TIMEOUT_SECONDS";

/// Extra seconds the client waits beyond the budget it asked Manticore for, so that a
/// query Manticore is about to cut off itself is reported as Manticore's timeout rather
/// than as the client's. The two are different failures and only one of them says the
/// daemon is unreachable.
const CLIENT_TIMEOUT_GRACE_SECONDS: u64 = 5;

/// Parse the timeout override: unset/unparseable falls back to the default, numbers are
/// clamped to 1..=600.
pub fn parse_search_timeout_seconds(raw: Option<&str>) -> u64 {
    raw.and_then(|s| s.trim().parse::<u64>().ok())
        .map(|n| n.clamp(1, 600))
        .unwrap_or(SEARCH_TIMEOUT_SECONDS)
}

/// The per-shard search budget in seconds.
///
/// **Per shard, not per request.** The fan-out runs shards concurrently, so the
/// request-level worst case is one budget plus the merge, while a single pathological
/// shard is cut loose instead of holding the page.
pub fn search_timeout_seconds() -> u64 {
    parse_search_timeout_seconds(std::env::var(SEARCH_TIMEOUT_ENV).ok().as_deref())
}

/// The same budget in milliseconds, for Manticore's `OPTION` clause.
pub fn search_timeout_ms() -> u64 {
    search_timeout_seconds() * 1000
}

/// A shard query that ran out of its budget, in either layer.
///
/// A distinct type because the two failure modes must be handled differently and the
/// difference is not visible in a message: a shard the fan-out could not REACH is
/// dropped with the amber partial-results notice, because a missing collection is
/// visible and truthful. A shard that TIMED OUT answered with truncated counts, and
/// Manticore says so only in a flag nobody sees. Displaying or caching that is serving
/// a wrong number as if it were right. So this fails the whole request instead.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SearchTimedOut(pub String);

impl std::fmt::Display for SearchTimedOut {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for SearchTimedOut {}

/// Whether an error is (or was caused by) a search timeout. Matched by TYPE, never by
/// message text. See `auth::guard::is_bad_request` for why.
pub fn is_search_timeout(err: &anyhow::Error) -> bool {
    err.chain().any(|cause| cause.is::<SearchTimedOut>())
}

/// Manticore answered and refused the statement, with an `error` in a JSON body.
///
/// A distinct type from a transport failure: a refused statement fails the same way on
/// every retry, while a daemon that did not answer can answer on the next attempt. The
/// message keeps the `Error: <status>: <body>` text that every caller logs today.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ManticoreRefused(pub String);

impl std::fmt::Display for ManticoreRefused {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for ManticoreRefused {}

/// Whether an error is (or was caused by) a statement Manticore refused.
pub fn is_manticore_refusal(err: &anyhow::Error) -> bool {
    err.chain().any(|cause| cause.is::<ManticoreRefused>())
}

#[derive(Debug, Serialize, Deserialize)]
pub struct RawSarchResult<T> {
    pub hits: RawSearchResultHits<T>,
    pub timed_out: bool,
    pub took: u64,
    pub aggregations: Option<BTreeMap<String, RawSearchResultAggregation>>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct RawSearchResultHits<T> {
    pub hits: Vec<RawSearchResultHit<T>>,
    pub total: u64,
    pub total_relation: String,
}

#[derive(Debug, Serialize, Deserialize, Default, Clone)]
pub struct RawSearchResultAggregation {
    pub buckets: Vec<RawSearchResultAggregationBucket>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct RawSearchResultAggregationBucket {
    pub key: serde_json::Value,
    #[serde(rename = "doc_count")]
    pub _duplicate_count: u64,
    #[serde(rename = "count(distinct file_hash)")]
    pub doc_count: u64,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct RawSearchResultHit<T> {
    pub _source: T,
    pub _score: u64,
}

/// Run one SQL statement against Manticore's `/sql` endpoint, with response caching.
///
/// This is the single-table primitive; the search fan-out (`api/search/fanout.rs`)
/// calls it once per shard. `cache_salt` is mixed into the cache key: the fan-out
/// passes the target collection's shard-ledger generation, so a shard change
/// invalidates that collection's cached searches without touching the others (and
/// each sub-query is cached separately, so adding a collection does not invalidate
/// existing cache entries).
///
/// **A timed-out response is an error and is never cached.** Manticore answers a query
/// that hit `max_query_time` with whatever it had found so far plus `timed_out: true`,
/// a count that is silently short, in a response shaped exactly like a correct one.
/// Caching it would freeze that wrong number in for the life of the shard generation.
pub async fn manticore_search_sql<T: DeserializeOwned + std::fmt::Debug>(
    sql: String,
    cache_salt: &str,
) -> anyhow::Result<RawSarchResult<T>> {
    let query_hash = sha256::digest(format!("{cache_salt}\n{sql}"));
    if let Ok(cached_response) = get_cached_response(&query_hash, &sql).await
        && let Ok(response) = serde_json::from_str::<RawSarchResult<T>>(&cached_response)
    {
        tracing::debug!("search cache HIT: {query_hash}");
        return Ok(response);
    }
    tracing::debug!("search cache MISS: {query_hash}");
    let t0 = std::time::Instant::now();
    let response_txt = manticore_post(sql.clone()).await?;
    tracing::debug!("search response: {} bytes", response_txt.len());
    let t1 = std::time::Instant::now();
    let dt_ms = t1.duration_since(t0).as_millis() as u32;
    let response: RawSarchResult<T> = serde_json::from_str(&response_txt)?;
    if response.timed_out {
        anyhow::bail!(SearchTimedOut(format!(
            "Manticore gave up on this query after {}s and returned partial counts",
            search_timeout_seconds()
        )));
    }
    if insert_cache(&query_hash, &sql, &response_txt, dt_ms)
        .await
        .is_ok()
    {
        tracing::debug!("search cache INSERTED: {query_hash} (searched in {dt_ms}ms)");
    } else {
        // Not an error path for the caller: the answer is already in hand and the next
        // identical query costs the same again.
        tracing::debug!("search cache insert failed: {query_hash}");
    }
    Ok(response)
}

/// POST one statement to Manticore's `/sql` endpoint and return its body.
///
/// The request carries the same budget as the `OPTION` clause plus a few seconds of
/// grace ([`CLIENT_TIMEOUT_GRACE_SECONDS`]). `max_query_time` is best-effort inside the
/// daemon and covers neither a connect stall nor a read stall, so without this a request
/// could outlive its budget indefinitely, which is what let the proxy return 504 while
/// the daemon kept working on the query behind it.
async fn manticore_post(sql: String) -> anyhow::Result<String> {
    let database_url =
        std::env::var("MANTICORE_URL").unwrap_or("http://127.0.0.1:21903".to_string());
    let database_url = format!("{}/sql", database_url);
    let client = reqwest::Client::new();
    let response = client
        .post(database_url)
        .timeout(Duration::from_secs(
            search_timeout_seconds() + CLIENT_TIMEOUT_GRACE_SECONDS,
        ))
        .body(sql)
        .send()
        .await
        .map_err(|e| {
            if e.is_timeout() {
                anyhow::Error::from(SearchTimedOut(format!(
                    "Manticore did not answer within {}s",
                    search_timeout_seconds() + CLIENT_TIMEOUT_GRACE_SECONDS
                )))
            } else {
                anyhow::Error::from(e)
            }
        })?;
    let status = response.status();
    let response_txt = response.text().await?;
    if status.is_client_error() || status.is_server_error() {
        let refused = serde_json::from_str::<serde_json::Value>(&response_txt)
            .ok()
            .is_some_and(|body| body.get("error").is_some_and(serde_json::Value::is_string));
        if refused {
            anyhow::bail!(ManticoreRefused(format!("Error: {}: {}", status, response_txt)));
        }
        anyhow::bail!("Error: {}: {}", status, response_txt);
    }
    Ok(response_txt)
}

/// Run one SQL statement against Manticore's `/sql` endpoint with NO caching at all.
///
/// Same wire call as [`manticore_search_sql`], minus the cache read and the cache
/// write. It exists for the VFS structure index: the tree changes as ingestion
/// proceeds, a user watching a folder fill up is the normal case, and a stale tree is
/// worse than a slow one. Structure queries are also cheap (one small attribute table,
/// no text bodies), so there is little to cache.
///
/// Do NOT route ordinary search through this. The result cache is what keeps repeated
/// facet fan-outs off Manticore.
pub async fn manticore_search_sql_uncached<T: DeserializeOwned + std::fmt::Debug>(
    sql: String,
) -> anyhow::Result<RawSarchResult<T>> {
    Ok(serde_json::from_str(&manticore_post(sql).await?)?)
}

/// One row of a raw-mode Manticore result: column name to value.
pub type ManticoreRawRow = serde_json::Map<String, serde_json::Value>;

/// The time that one status statement may take, connect included.
const RAW_SQL_TIMEOUT_SECONDS: u64 = 10;

/// Run one statement through Manticore's `/sql?mode=raw` endpoint and return the rows of
/// its first result.
///
/// The plain `/sql` endpoint of [`manticore_post`] takes `SELECT` only. Raw mode also takes
/// `SHOW STATUS`, `SHOW TABLES` and `SHOW TABLE <t> STATUS`, which the admin metrics page
/// reads. It bypasses the result cache, because a status value is only correct when it is
/// fresh.
pub async fn manticore_raw_sql(sql: &str) -> anyhow::Result<Vec<ManticoreRawRow>> {
    let base = std::env::var("MANTICORE_URL").unwrap_or("http://127.0.0.1:21903".to_string());
    let response = reqwest::Client::new()
        .post(format!("{base}/sql?mode=raw"))
        .timeout(Duration::from_secs(RAW_SQL_TIMEOUT_SECONDS))
        .form(&[("query", sql)])
        .send()
        .await?;
    let status = response.status();
    let body = response.text().await?;
    parse_raw_sql_response(&body)
        .map_err(|e| e.context(format!("Manticore answered {status} to {sql:?}")))
}

/// The rows of the first result of a raw-mode body, or its error.
///
/// Manticore answers a refused statement with one object, `{"error": "..."}`, and a
/// statement it ran with a list of results, each with an `error` field that is empty on
/// success.
pub fn parse_raw_sql_response(body: &str) -> anyhow::Result<Vec<ManticoreRawRow>> {
    let value: serde_json::Value = serde_json::from_str(body)
        .map_err(|e| anyhow::anyhow!("Manticore sent a body that is not JSON: {e}"))?;
    let first = match &value {
        serde_json::Value::Array(results) => results
            .first()
            .ok_or_else(|| anyhow::anyhow!("Manticore sent an empty result list"))?,
        other => other,
    };
    if let Some(error) = first.get("error").and_then(serde_json::Value::as_str) {
        if !error.is_empty() {
            anyhow::bail!(ManticoreRefused(error.to_string()));
        }
    }
    let rows = first
        .get("data")
        .and_then(serde_json::Value::as_array)
        .ok_or_else(|| anyhow::anyhow!("Manticore sent a result with no data rows"))?;
    Ok(rows
        .iter()
        .filter_map(|row| row.as_object().cloned())
        .collect())
}

async fn get_cached_response(query_hash: &String, query_string: &String) -> anyhow::Result<String> {
    let client = get_global_client();
    let sql = "
    SELECT result_json
    FROM search_manticore_cache
    WHERE query_hash = ?
      AND query_string = ?
    ORDER BY date_created DESC
    LIMIT 1
    ";
    let rows = client
        .query(sql)
        .bind(query_hash.clone())
        .bind(query_string.clone())
        .fetch_all::<String>()
        .await?;
    if let Some(result_json) = rows.into_iter().next() {
        Ok(result_json)
    } else {
        anyhow::bail!("Cache miss")
    }
}

async fn insert_cache(
    query_hash: &String,
    query_string: &String,
    response_txt: &String,
    dt_ms: u32,
) -> anyhow::Result<()> {
    let client = get_global_client();
    let sql = "
    INSERT INTO search_manticore_cache (query_hash, query_string, result_json, duration_ms)
    VALUES (?, ?, ?, ?)
    ";
    client
        .query(sql)
        .bind(query_hash.clone())
        .bind(query_string.clone())
        .bind(response_txt.clone())
        .bind(dt_ms)
        .execute()
        .await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_search_budget_defaults_and_clamps() {
        assert_eq!(parse_search_timeout_seconds(None), SEARCH_TIMEOUT_SECONDS);
        assert_eq!(parse_search_timeout_seconds(Some("10")), 10);
        assert_eq!(parse_search_timeout_seconds(Some(" 45 ")), 45);
        assert_eq!(parse_search_timeout_seconds(Some("0")), 1);
        assert_eq!(parse_search_timeout_seconds(Some("99999")), 600);
        for bad in ["", "abc", "-3", "30.5", "3e2"] {
            assert_eq!(
                parse_search_timeout_seconds(Some(bad)),
                SEARCH_TIMEOUT_SECONDS,
                "should fall back for {bad:?}"
            );
        }
    }

    /// The two failure modes are told apart by TYPE. A timeout that read as an ordinary
    /// shard failure would be dropped from the results with an amber notice, which is
    /// how a truncated count reaches the screen looking merely incomplete.
    #[test]
    fn a_timeout_is_recognisable_through_the_error_chain() {
        let error = anyhow::Error::from(SearchTimedOut("too slow".to_string()))
            .context("shard testdata_1");
        assert!(is_search_timeout(&error));
        assert!(!is_search_timeout(&anyhow::anyhow!("connection refused")));
    }

    #[test]
    fn a_raw_result_gives_its_rows() {
        let body = r#"[{"columns":[{"Counter":{"type":"string"}},{"Value":{"type":"string"}}],
            "data":[{"Counter":"uptime","Value":"41078"},{"Counter":"load","Value":"0.10 0.20 0.30"}],
            "total":2,"error":"","warning":""}]"#;
        let rows = parse_raw_sql_response(body).unwrap();
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[1]["Value"], "0.10 0.20 0.30");
    }

    #[test]
    fn a_raw_error_body_is_an_error_with_its_text() {
        let error =
            parse_raw_sql_response(r#"{"error":"SHOW TABLE STATUS requires an existing table"}"#)
                .unwrap_err();
        assert!(is_manticore_refusal(&error));
        assert!(error.to_string().contains("requires an existing table"));
        let error = parse_raw_sql_response(r#"[{"data":[],"error":"bad query"}]"#).unwrap_err();
        assert!(error.to_string().contains("bad query"));
        assert!(parse_raw_sql_response("<html>").is_err());
    }
}
