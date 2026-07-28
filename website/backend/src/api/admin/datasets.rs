//! Admin dataset management API.

use common::admin_types::{AdminDatasetDetail, AdminDatasetItem, AdminDatasetStats};
use common::current_user::CurrentUser;
use time::format_description::well_known::Rfc3339;

use crate::api::admin::temporal_trigger;
use crate::auth::guard;
use crate::db_utils::clickhouse_utils::{collection_db_name, get_collection_client, get_global_client};

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
struct DatasetRow {
    pub collection_dataset: String,
    pub collectionname: String,
    pub dataset_name: String,
    pub dataset_display_name: String,
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
    let client = get_global_client();
    let mut rows = client
        .query("SELECT collection_dataset, collectionname, dataset_name, dataset_display_name, dataset_type, dataset_path, dataset_access_json, user_id, date_created, date_modified, is_deleted FROM dataset FINAL WHERE collection_dataset = ? AND is_deleted = 0")
        .bind(collection_dataset)
        .fetch_all::<DatasetRow>()
        .await?;
    Ok(rows.pop())
}

/// Per-collection stats. `blobs`, `vfs_files`, the plan tables and `processing_errors`
/// all live in the collection's own database, so the collection must be known — it is
/// read off the global registry row by the caller.
async fn fetch_stats(collection_dataset: &str, collectionname: &str) -> anyhow::Result<AdminDatasetStats> {
    let client = get_collection_client(collectionname);
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
    // Validates the slug (a database name is built from it below) and rejects legacy
    // rows with an empty collectionname.
    collection_db_name(&row.collectionname)?;
    let stats = fetch_stats(&collection_dataset, &row.collectionname).await?;
    Ok(AdminDatasetDetail {
        dataset: AdminDatasetItem {
            collection_dataset: row.collection_dataset,
            dataset_name: row.dataset_name,
            dataset_display_name: row.dataset_display_name,
            dataset_type: row.dataset_type,
            dataset_path: row.dataset_path,
            date_created: format_datetime(row.date_created),
        },
        collectionname: row.collectionname,
        stats,
    })
}

/// Edit a dataset's display name. That is the only mutable field: the collection is
/// fixed at creation (D1) and the short name is part of the composed, globally unique
/// `collection_dataset` id.
pub async fn admin_update_dataset(
    user: &CurrentUser,
    collection_dataset: String,
    dataset_display_name: String,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    let Some(mut row) = get_dataset_row(&collection_dataset).await? else {
        anyhow::bail!("dataset not found");
    };
    row.dataset_display_name = dataset_display_name;
    row.date_modified = time::OffsetDateTime::now_utc();
    let client = get_global_client();
    let mut insert = client.insert::<DatasetRow>("dataset").await?;
    insert.write(&row).await?;
    insert.end().await?;
    Ok(())
}

pub async fn admin_delete_dataset(
    user: &CurrentUser,
    collection_dataset: String,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    let client = get_global_client();
    let mut rows = client
        .query("SELECT collection_dataset, collectionname, dataset_name, dataset_display_name, dataset_type, dataset_path, dataset_access_json, user_id, date_created, date_modified, is_deleted FROM dataset FINAL WHERE collection_dataset = ?")
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
    // Purge the dataset's rows from the collection database and its Manticore
    // shards, then recompute the shard ledger (part 6). The workflow is
    // idempotent, so a failed trigger can be retried by deleting again.
    temporal_trigger::trigger_workflow(&collection_dataset, "purge_dataset").await?;
    Ok(())
}

pub async fn admin_trigger_workflow(
    user: &CurrentUser,
    collection_dataset: String,
    kind: String,
) -> anyhow::Result<String> {
    guard::require_admin(user)?;
    temporal_trigger::trigger_workflow(&collection_dataset, &kind).await
}
