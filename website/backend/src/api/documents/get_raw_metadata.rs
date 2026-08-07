//! Endpoint for retrieving raw document metadata.

use clickhouse::sql;
use common::{
    current_user::CurrentUser,
    document_metadata::DocumentMetadataTableInfo,
    search_result::DocumentIdentifier,
};
use tokio::io::AsyncBufReadExt;

use crate::auth::permissions;
use crate::db_utils::clickhouse_utils::get_client_for_dataset;

pub async fn get_raw_metadata(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
    table_info: DocumentMetadataTableInfo,
) -> anyhow::Result<Vec<serde_json::Value>> {
    crate::api::telemetry::record_event(&user.username, crate::api::telemetry::EVENT_USER_GET_DOCUMENT, "");
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;
    fetch_table(&client, &document_identifier, &table_info).await
}

/// Every requested table for one document, in the order asked for.
///
/// The metadata panel wants a dozen tables at once. One request per table meant a dozen
/// permission checks, a dozen telemetry events and — the part that matters — a dozen
/// ClickHouse queries opened simultaneously per document view. Here they share the
/// preamble and run one after another, so a page view costs ClickHouse one query at a
/// time instead of a burst.
pub async fn get_raw_metadata_tables(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
    table_list: Vec<DocumentMetadataTableInfo>,
) -> anyhow::Result<Vec<Vec<serde_json::Value>>> {
    crate::api::telemetry::record_event(&user.username, crate::api::telemetry::EVENT_USER_GET_DOCUMENT, "");
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;

    let mut results = Vec::with_capacity(table_list.len());
    for table_info in &table_list {
        results.push(fetch_table(&client, &document_identifier, table_info).await?);
    }
    Ok(results)
}

async fn fetch_table(
    client: &clickhouse::Client,
    document_identifier: &DocumentIdentifier,
    table_info: &DocumentMetadataTableInfo,
) -> anyhow::Result<Vec<serde_json::Value>> {
    let query = "SELECT * FROM ? WHERE ? = ? AND collection_dataset = ? LIMIT 11";
    let query = client
        .query(query)
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
