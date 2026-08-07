//! Startup readiness checks.

use std::time::Duration;

/// Verify ClickHouse is reachable before serving traffic.
///
/// Retries briefly so a database that is still coming up doesn't cause a
/// spurious failure, then returns an error. The website bootstrap turns that
/// error into a hard, logged exit — the server must not start up looking healthy
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
        "ClickHouse still unreachable at {} after {ATTEMPTS} attempts — refusing to start",
        crate::db_utils::clickhouse_utils::clickhouse_url()
    )
}

/// The **multi-threaded** tokio runtime the server was built on.
///
/// Dioxus **server functions** do not run on it: they execute in a context where
/// `tokio::task::block_in_place` panics with *"can call blocking only when running on the
/// multi-threaded runtime"*, and `tokio::spawn` from inside one inherits that same
/// context rather than escaping it. Anything reaching a library that blocks internally —
/// the MinIO SDK does, under `to_segmented_bytes` — has to be handed to this handle
/// explicitly.
///
/// Set once from `main.rs`, where the runtime flavour is already asserted.
static MULTI_THREAD_RUNTIME: std::sync::OnceLock<tokio::runtime::Handle> =
    std::sync::OnceLock::new();

pub fn set_multi_thread_runtime(handle: tokio::runtime::Handle) {
    let _ = MULTI_THREAD_RUNTIME.set(handle);
}

/// Run `future` on the multi-threaded runtime, wherever the caller happens to be.
///
/// Falls back to awaiting inline when the handle was never registered (a unit test, or a
/// binary that did not call [`set_multi_thread_runtime`]) — that path is correct
/// everywhere except inside a server function, which is exactly where the handle exists.
pub async fn on_multi_thread_runtime<F, T>(future: F) -> anyhow::Result<T>
where
    F: std::future::Future<Output = anyhow::Result<T>> + Send + 'static,
    T: Send + 'static,
{
    match MULTI_THREAD_RUNTIME.get() {
        Some(handle) => handle
            .spawn(future)
            .await
            .map_err(|e| anyhow::anyhow!("task failed: {e}"))?,
        None => future.await,
    }
}
