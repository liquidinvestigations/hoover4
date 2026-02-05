use serde::{Deserialize, Serialize, de::DeserializeOwned};
use std::collections::BTreeMap;
use crate::db_utils::clickhouse_utils::get_clickhouse_client;

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

pub async fn manticore_search_sql<T: DeserializeOwned + std::fmt::Debug>(
    sql: String,
) -> anyhow::Result<RawSarchResult<T>> {
    let query_hash = sha256::digest(sql.clone());
    if let Ok(cached_response) = get_cached_response(&query_hash, &sql).await {
        if let Ok(response) = serde_json::from_str::<RawSarchResult<T>>(&cached_response) {
            println!("SEARCH CACHE HIT: {}", query_hash);
            return Ok(response);
        }
    }
    println!("SEARCH CACHE MISS: {}", query_hash);
    let t0 = std::time::Instant::now();
    let database_url = std::env::var("MANTICORE_URL").unwrap_or("http://127.0.0.1:9308".to_string());
    let database_url = format!("{}/sql", database_url);
    let client = reqwest::Client::new();

    let response = client.post(database_url).body(sql.clone()).send().await?;
    let status = response.status();
    let response_txt = response.text().await?;
    if status.is_client_error() || status.is_server_error() {
        anyhow::bail!("Error: {}: {}", status, response_txt);
    }
    println!("SEARCH RESPONSE: len = {}", response_txt.len());
    let t1 = std::time::Instant::now();
    let dt_ms = t1.duration_since(t0).as_millis() as u32;
    if insert_cache(&query_hash, &sql, &response_txt, dt_ms).await.is_ok() {
        println!("SEARCH CACHE INSERTED: {} (searched in {}ms)", query_hash, dt_ms);
    } else {
        println!("SEARCH CACHE INSERT FAILED: {}", query_hash);
    }
    // CACHE THE RESPONSE TEXT
    let response: RawSarchResult<T> = serde_json::from_str(&response_txt)?;
    Ok(response)
}


async fn get_cached_response(query_hash: &String, query_string: &String) -> anyhow::Result<String> {

    let client = get_clickhouse_client();
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


async fn insert_cache(query_hash: &String, query_string: &String, response_txt: &String, dt_ms: u32) -> anyhow::Result<()> {
    let client = get_clickhouse_client();
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