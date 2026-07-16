//! Collections, dataset links, and group permissions CRUD.

use crate::db_auth::{insert_row, now};
use crate::db_utils::clickhouse_utils::get_clickhouse_client;

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
pub struct CollectionRow {
    pub collectionname: String,
    pub fullname: String,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub created_at: time::OffsetDateTime,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub updated_at: time::OffsetDateTime,
    pub is_deleted: u8,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
pub struct CollectionDatasetRow {
    pub collection_dataset: String,
    pub collectionname: String,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub created_at: time::OffsetDateTime,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub updated_at: time::OffsetDateTime,
    pub is_deleted: u8,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
pub struct PermissionRow {
    pub groupname: String,
    pub collectionname: String,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub created_at: time::OffsetDateTime,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub updated_at: time::OffsetDateTime,
    pub is_deleted: u8,
}

pub async fn list_collections() -> anyhow::Result<Vec<CollectionRow>> {
    let client = get_clickhouse_client();
    client
        .query("SELECT collectionname, fullname, created_at, updated_at, is_deleted FROM collections FINAL WHERE is_deleted = 0 ORDER BY collectionname")
        .fetch_all::<CollectionRow>()
        .await
        .map_err(Into::into)
}

pub async fn get_collection(collectionname: &str) -> anyhow::Result<Option<CollectionRow>> {
    let client = get_clickhouse_client();
    let mut rows = client
        .query("SELECT collectionname, fullname, created_at, updated_at, is_deleted FROM collections FINAL WHERE collectionname = ? AND is_deleted = 0")
        .bind(collectionname)
        .fetch_all::<CollectionRow>()
        .await?;
    Ok(rows.pop())
}

pub async fn upsert_collection(mut row: CollectionRow) -> anyhow::Result<()> {
    let existing = get_collection(&row.collectionname).await?;
    if let Some(existing) = existing {
        row.created_at = existing.created_at;
    } else {
        row.created_at = now();
    }
    row.updated_at = now();
    row.is_deleted = 0;
    insert_row("collections", &row).await
}

pub async fn soft_delete_collection(collectionname: &str) -> anyhow::Result<()> {
    let Some(mut row) = get_collection(collectionname).await? else {
        return Ok(());
    };
    row.updated_at = now();
    row.is_deleted = 1;
    insert_row("collections", &row).await
}

pub async fn list_collection_datasets(
    collectionname: &str,
) -> anyhow::Result<Vec<CollectionDatasetRow>> {
    let client = get_clickhouse_client();
    client
        .query("SELECT collection_dataset, collectionname, created_at, updated_at, is_deleted FROM collection_datasets FINAL WHERE collectionname = ? AND is_deleted = 0 ORDER BY collection_dataset")
        .bind(collectionname)
        .fetch_all::<CollectionDatasetRow>()
        .await
        .map_err(Into::into)
}

pub async fn get_dataset_collection(
    collection_dataset: &str,
) -> anyhow::Result<Option<CollectionDatasetRow>> {
    let client = get_clickhouse_client();
    let mut rows = client
        .query("SELECT collection_dataset, collectionname, created_at, updated_at, is_deleted FROM collection_datasets FINAL WHERE collection_dataset = ? AND is_deleted = 0")
        .bind(collection_dataset)
        .fetch_all::<CollectionDatasetRow>()
        .await?;
    Ok(rows.pop())
}

pub async fn assign_dataset(collectionname: &str, collection_dataset: &str) -> anyhow::Result<()> {
    let existing = get_dataset_collection(collection_dataset).await?;
    let created_at = existing
        .as_ref()
        .map(|r| r.created_at)
        .unwrap_or_else(now);
    let row = CollectionDatasetRow {
        collection_dataset: collection_dataset.to_string(),
        collectionname: collectionname.to_string(),
        created_at,
        updated_at: now(),
        is_deleted: 0,
    };
    insert_row("collection_datasets", &row).await
}

pub async fn unassign_dataset(collection_dataset: &str) -> anyhow::Result<()> {
    let Some(mut row) = get_dataset_collection(collection_dataset).await? else {
        return Ok(());
    };
    row.updated_at = now();
    row.is_deleted = 1;
    insert_row("collection_datasets", &row).await
}

async fn get_permission(groupname: &str, collectionname: &str) -> anyhow::Result<Option<PermissionRow>> {
    let client = get_clickhouse_client();
    let mut rows = client
        .query("SELECT groupname, collectionname, created_at, updated_at, is_deleted FROM collection_group_permissions FINAL WHERE groupname = ? AND collectionname = ? AND is_deleted = 0")
        .bind(groupname)
        .bind(collectionname)
        .fetch_all::<PermissionRow>()
        .await?;
    Ok(rows.pop())
}

pub async fn list_permissions_for_group(groupname: &str) -> anyhow::Result<Vec<PermissionRow>> {
    let client = get_clickhouse_client();
    client
        .query("SELECT groupname, collectionname, created_at, updated_at, is_deleted FROM collection_group_permissions FINAL WHERE groupname = ? AND is_deleted = 0 ORDER BY collectionname")
        .bind(groupname)
        .fetch_all::<PermissionRow>()
        .await
        .map_err(Into::into)
}

pub async fn list_permissions_for_collection(
    collectionname: &str,
) -> anyhow::Result<Vec<PermissionRow>> {
    let client = get_clickhouse_client();
    client
        .query("SELECT groupname, collectionname, created_at, updated_at, is_deleted FROM collection_group_permissions FINAL WHERE collectionname = ? AND is_deleted = 0 ORDER BY groupname")
        .bind(collectionname)
        .fetch_all::<PermissionRow>()
        .await
        .map_err(Into::into)
}

pub async fn grant_permission(groupname: &str, collectionname: &str) -> anyhow::Result<()> {
    let existing = get_permission(groupname, collectionname).await?;
    let created_at = existing
        .as_ref()
        .map(|r| r.created_at)
        .unwrap_or_else(now);
    let row = PermissionRow {
        groupname: groupname.to_string(),
        collectionname: collectionname.to_string(),
        created_at,
        updated_at: now(),
        is_deleted: 0,
    };
    insert_row("collection_group_permissions", &row).await
}

pub async fn revoke_permission(groupname: &str, collectionname: &str) -> anyhow::Result<()> {
    let Some(mut row) = get_permission(groupname, collectionname).await? else {
        return Ok(());
    };
    row.updated_at = now();
    row.is_deleted = 1;
    insert_row("collection_group_permissions", &row).await
}

pub async fn permitted_collection_datasets(username: &str) -> anyhow::Result<Vec<String>> {
    let client = get_clickhouse_client();
    let mut result = client
        .query(
            "SELECT DISTINCT cd.collection_dataset
             FROM user_group_membership FINAL AS m
             INNER JOIN collection_group_permissions FINAL AS p ON p.groupname = m.groupname
             INNER JOIN collections FINAL AS c ON c.collectionname = p.collectionname
             INNER JOIN collection_datasets FINAL AS cd ON cd.collectionname = p.collectionname
             WHERE m.username = ? AND m.is_deleted = 0 AND p.is_deleted = 0
               AND c.is_deleted = 0 AND cd.is_deleted = 0",
        )
        .bind(username)
        .fetch_all::<String>()
        .await?;
    result.sort();
    Ok(result)
}
