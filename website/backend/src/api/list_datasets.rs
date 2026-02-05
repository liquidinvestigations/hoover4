use crate::db_utils::clickhouse_utils::get_clickhouse_client;

pub async fn list_dataset_ids() -> anyhow::Result<Vec<String>> {
    let client = get_clickhouse_client();
    let result = client
        .query("SELECT DISTINCT collection_dataset FROM dataset")
        .fetch_all()
        .await?;
    Ok(result)
}
