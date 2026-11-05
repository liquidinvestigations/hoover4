//! Timeout parity with a controlled HTTP response and the isolated result cache.

#[tokio::test]
#[ignore = "requires the controlled timeout server and isolated cache"]
async fn cached_and_uncached_partial_responses_keep_the_same_timeout_type() -> anyhow::Result<()> {
    anyhow::ensure!(std::env::var("HOOVER4_TIMEOUT_FIXTURE").as_deref() == Ok("1"), "The timeout response fixture is required.");
    let sql = "SELECT controlled_timeout".to_string();
    let uncached = backend::db_utils::manticore_utils::manticore_search_sql_uncached::<serde_json::Value>(sql.clone()).await.unwrap_err();
    assert!(backend::db_utils::manticore_utils::is_search_timeout(&uncached));
    let run = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)?.as_nanos();
    let salt = format!("timeout-{run}");
    let body = r#"{"hits":{"hits":[],"total":7,"total_relation":"eq"},"timed_out":true,"took":30,"aggregations":null}"#;
    backend::db_utils::clickhouse_utils::get_global_client().query(
        "INSERT INTO search_manticore_cache (query_hash,query_string,result_json,duration_ms) VALUES (?,?,?,30)"
    ).bind(sha256::digest(format!("{salt}\n{sql}"))).bind(&sql).bind(body).execute().await?;
    let cached = backend::db_utils::manticore_utils::manticore_search_sql::<serde_json::Value>(sql, &salt).await.unwrap_err();
    assert!(backend::db_utils::manticore_utils::is_search_timeout(&cached));
    let requests: serde_json::Value = reqwest::get(format!("{}/count", std::env::var("MANTICORE_URL")?)).await?.json().await?;
    assert_eq!(requests["requests"], 1, "The cached timeout must not issue another service request.");
    Ok(())
}
