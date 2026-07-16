//! Admin dataset management API.

use common::admin_types::{AdminDatasetDetail, AdminDatasetItem, AdminDatasetStats};
use common::current_user::CurrentUser;
use time::format_description::well_known::Rfc3339;

use crate::api::admin::temporal_trigger;
use crate::auth::guard;
use crate::db_auth::collections;
use crate::db_utils::clickhouse_utils::get_clickhouse_client;

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
struct DatasetRow {
    pub collection_dataset: String,
    pub dataset_name: String,
    pub dataset_type: String,
    pub dataset_path: String,
    pub dataset_access_json: Option<String>,
    pub user_id: String,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub date_created: time::OffsetDateTime,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub date_modified: time::OffsetDateTime,
    pub is_deleted: u8,
}

fn format_datetime(dt: time::OffsetDateTime) -> String {
    dt.format(&Rfc3339).unwrap_or_else(|_| dt.to_string())
}

async fn get_dataset_row(collection_dataset: &str) -> anyhow::Result<Option<DatasetRow>> {
    let client = get_clickhouse_client();
    let mut rows = client
        .query("SELECT collection_dataset, dataset_name, dataset_type, dataset_path, dataset_access_json, user_id, date_created, date_modified, is_deleted FROM dataset FINAL WHERE collection_dataset = ? AND is_deleted = 0")
        .bind(collection_dataset)
        .fetch_all::<DatasetRow>()
        .await?;
    Ok(rows.pop())
}

async fn fetch_stats(collection_dataset: &str) -> anyhow::Result<AdminDatasetStats> {
    let client = get_clickhouse_client();
    let blob_count: u64 = client
        .query("SELECT count() FROM blobs WHERE collection_dataset = ?")
        .bind(collection_dataset)
        .fetch_one()
        .await?;
    let vfs_file_count: u64 = client
        .query("SELECT count() FROM vfs_files WHERE collection_dataset = ?")
        .bind(collection_dataset)
        .fetch_one()
        .await?;
    let plans_total: u64 = client
        .query("SELECT count() FROM processing_plans WHERE collection_dataset = ?")
        .bind(collection_dataset)
        .fetch_one()
        .await?;
    let plans_finished: u64 = client
        .query("SELECT count() FROM processing_plan_finished WHERE collection_dataset = ?")
        .bind(collection_dataset)
        .fetch_one()
        .await?;
    let error_count: u64 = client
        .query("SELECT count() FROM processing_errors WHERE collection_dataset = ?")
        .bind(collection_dataset)
        .fetch_one()
        .await?;
    Ok(AdminDatasetStats {
        blob_count,
        vfs_file_count,
        plans_total,
        plans_finished,
        error_count,
    })
}

pub async fn admin_get_dataset(
    user: &CurrentUser,
    collection_dataset: String,
) -> anyhow::Result<AdminDatasetDetail> {
    guard::require_admin(user)?;
    let row = get_dataset_row(&collection_dataset)
        .await?
        .ok_or_else(|| anyhow::anyhow!("dataset not found"))?;
    let collectionname = collections::get_dataset_collection(&collection_dataset)
        .await?
        .map(|r| r.collectionname);
    let stats = fetch_stats(&collection_dataset).await?;
    Ok(AdminDatasetDetail {
        dataset: AdminDatasetItem {
            collection_dataset: row.collection_dataset,
            dataset_name: row.dataset_name,
            dataset_type: row.dataset_type,
            dataset_path: row.dataset_path,
            date_created: format_datetime(row.date_created),
        },
        collectionname,
        stats,
    })
}

pub async fn admin_update_dataset(
    user: &CurrentUser,
    collection_dataset: String,
    dataset_name: String,
    collectionname: Option<String>,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    let Some(mut row) = get_dataset_row(&collection_dataset).await? else {
        anyhow::bail!("dataset not found");
    };
    row.dataset_name = dataset_name;
    row.date_modified = time::OffsetDateTime::now_utc();
    let client = get_clickhouse_client();
    let mut insert = client.insert::<DatasetRow>("dataset").await?;
    insert.write(&row).await?;
    insert.end().await?;

    if let Some(ref cn) = collectionname {
        collections::assign_dataset(cn, &collection_dataset).await?;
    } else {
        collections::unassign_dataset(&collection_dataset).await?;
    }
    Ok(())
}

pub async fn admin_delete_dataset(
    user: &CurrentUser,
    collection_dataset: String,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    let client = get_clickhouse_client();
    let mut rows = client
        .query("SELECT collection_dataset, dataset_name, dataset_type, dataset_path, dataset_access_json, user_id, date_created, date_modified, is_deleted FROM dataset FINAL WHERE collection_dataset = ?")
        .bind(&collection_dataset)
        .fetch_all::<DatasetRow>()
        .await?;
    let Some(mut row) = rows.pop() else {
        anyhow::bail!("dataset not found");
    };
    row.is_deleted = 1;
    row.date_modified = time::OffsetDateTime::now_utc();
    let mut insert = client.insert::<DatasetRow>("dataset").await?;
    insert.write(&row).await?;
    insert.end().await?;
    collections::unassign_dataset(&collection_dataset).await
}

pub async fn admin_trigger_workflow(
    user: &CurrentUser,
    collection_dataset: String,
    kind: String,
) -> anyhow::Result<String> {
    guard::require_admin(user)?;
    temporal_trigger::trigger_workflow(&collection_dataset, &kind).await
}
