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
}
