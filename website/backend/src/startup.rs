//! Startup readiness checks.

use std::time::Duration;

/// Verify ClickHouse is reachable before serving traffic.
///
/// Retries briefly so a database that is still coming up doesn't cause a
/// spurious failure, then returns an error. The website bootstrap turns that
/// error into a hard, logged exit. The server must not start up looking healthy
/// while every DB-backed route silently fails.
pub async fn ensure_clickhouse_reachable() -> anyhow::Result<()> {
    const ATTEMPTS: usize = 10;
    const DELAY: Duration = Duration::from_secs(2);

    for attempt in 1..=ATTEMPTS {
        match crate::db_utils::clickhouse_utils::check_clickhouse_health().await {
            Ok(()) => return Ok(()),
            Err(e) => {
                tracing::error!("ClickHouse not reachable (attempt {attempt}/{ATTEMPTS}): {e}");
                if attempt < ATTEMPTS {
                    tokio::time::sleep(DELAY).await;
                }
            }
        }
    }

    anyhow::bail!(
        "ClickHouse still unreachable at {} after {ATTEMPTS} attempts, so it refuses to start",
        crate::db_utils::clickhouse_utils::clickhouse_url()
    )
}

