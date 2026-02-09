//! Endpoint for retrieving raw document metadata.

use clickhouse::sql;
use common::{document_metadata::DocumentMetadataTableInfo, search_result::DocumentIdentifier};
use tokio::io::AsyncBufReadExt;

use crate::db_utils::clickhouse_utils::get_clickhouse_client;

pub async fn get_raw_metadata(
    document_identifier: DocumentIdentifier,
    table_info: DocumentMetadataTableInfo)
    -> anyhow::Result<Vec<serde_json::Value>> {
    let client = get_clickhouse_client();

    let query =
        "SELECT * FROM ? WHERE ? = ? AND collection_dataset = ? LIMIT 11";
    let query = client.query(query)
    .bind(sql::Identifier(&table_info.table_name))
    .bind(sql::Identifier(&table_info.hash_column_name))
    .bind(&document_identifier.file_hash)
    .bind(&document_identifier.collection_dataset);


    let mut result_lines = query.fetch_bytes("JSONEachRow")?.lines();

    let mut result = Vec::new();
    while let Some(line) = result_lines.next_line().await? {
        let item = serde_json::from_str::<serde_json::Value>(&line)?;
        let serde_json::Value::Object(mut obj) = item else {
            anyhow::bail!("Invalid JSON object: {}", line);
        };
        obj.remove("collection_dataset");
        obj.remove(&table_info.hash_column_name);
        for json_column in &table_info.json_columns {
            if let Some(serde_json::Value::String(json_value)) = obj.remove(json_column) {
                let json_value = serde_json::from_str::<serde_json::Value>(&json_value)?;
                obj.insert(json_column.clone(), json_value);
            }
        }
        result.push(obj.into());
    }
    Ok(result)
}