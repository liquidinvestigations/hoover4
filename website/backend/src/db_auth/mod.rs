//! ClickHouse data-access layer for auth tables.

pub mod collections;
pub mod groups;
pub mod sessions;
pub mod settings;
pub mod uploads;
pub mod users;

use std::collections::HashMap;
use std::sync::{Arc, LazyLock, Mutex};

use crate::db_utils::clickhouse_utils::get_global_client;
use time::OffsetDateTime;

/// Process-local locks, one for each key. A ClickHouse read followed by an insert enforces
/// nothing, so a writer that checks a stored row and then writes holds the lock of its key
/// across both steps.
///
/// The locks hold only inside one website process. The deployment runs one website
/// process, and no other program writes the rows that these locks protect.
pub(crate) type KeyedLocks = LazyLock<Mutex<HashMap<String, Arc<tokio::sync::Mutex<()>>>>>;

/// Wait for the lock of `key` in `locks` and return its guard. An entry that nobody holds
/// or waits for is removed on the way in, as `db_chat::turn_lock` does.
pub(crate) async fn lock_key(locks: &'static KeyedLocks, key: &str) -> tokio::sync::OwnedMutexGuard<()> {
    let lock = {
        let mut map = locks.lock().unwrap_or_else(|e| e.into_inner());
        map.retain(|k, lock| k == key || Arc::strong_count(lock) > 1);
        Arc::clone(map.entry(key.to_string()).or_default())
    };
    lock.lock_owned().await
}

pub(crate) fn now() -> OffsetDateTime {
    OffsetDateTime::now_utc()
}

pub(crate) async fn insert_row<T>(table: &str, row: &T) -> anyhow::Result<()>
where
    T: clickhouse::RowOwned + serde::Serialize,
{
    async fn inner<T>(table: &str, row: &T) -> anyhow::Result<()>
    where
        T: clickhouse::RowOwned + serde::Serialize,
    {
        let client = get_global_client();
        let mut insert = client.insert::<T>(table).await?;
        insert.write(row).await?;
        insert.end().await?;
        Ok(())
    }

    inner(table, row).await.inspect_err(|e| {
        tracing::error!("ClickHouse insert into `{table}` failed: {e}");
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    static TEST_LOCKS: KeyedLocks = LazyLock::new(Default::default);

    #[tokio::test]
    async fn two_holders_of_one_key_run_one_after_the_other() {
        let order = Arc::new(Mutex::new(Vec::new()));
        let first = lock_key(&TEST_LOCKS, "a").await;
        let waiter = {
            let order = Arc::clone(&order);
            tokio::spawn(async move {
                let _guard = lock_key(&TEST_LOCKS, "a").await;
                order.lock().unwrap().push("second");
            })
        };
        // Another key does not wait for the held one.
        drop(lock_key(&TEST_LOCKS, "b").await);
        tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        order.lock().unwrap().push("first");
        drop(first);
        waiter.await.unwrap();
        assert_eq!(*order.lock().unwrap(), vec!["first", "second"]);
    }
}
