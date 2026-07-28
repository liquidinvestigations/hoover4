//! ClickHouse data-access layer for auth tables.

pub mod collections;
pub mod groups;
pub mod sessions;
pub mod settings;
pub mod users;

use crate::db_utils::clickhouse_utils::get_global_client;
use time::OffsetDateTime;

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
