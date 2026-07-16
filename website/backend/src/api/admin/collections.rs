//! Admin collection management API.

use common::admin_types::{AdminCollectionDetail, AdminCollectionItem, AdminDatasetItem};
use common::current_user::CurrentUser;
use time::format_description::well_known::Rfc3339;

use crate::api::list_datasets;
use crate::auth::guard;
use crate::db_auth::collections::{self, CollectionRow};

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
struct DatasetListRow {
    pub collection_dataset: String,
    pub dataset_name: String,
    pub dataset_type: String,
    pub dataset_path: String,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub date_created: time::OffsetDateTime,
}

fn slug_valid(s: &str) -> bool {
    !s.is_empty()
        && s.chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '-')
}

fn format_datetime(dt: time::OffsetDateTime) -> String {
    dt.format(&Rfc3339).unwrap_or_else(|_| dt.to_string())
}

async fn unassigned_datasets() -> anyhow::Result<Vec<String>> {
    let all = list_datasets::list_dataset_ids().await?;
    let mut unassigned = Vec::new();
    for cd in all {
        if collections::get_dataset_collection(&cd).await?.is_none() {
            unassigned.push(cd);
        }
    }
    Ok(unassigned)
}

pub async fn admin_list_unassigned_datasets(user: &CurrentUser) -> anyhow::Result<Vec<String>> {
    guard::require_admin(user)?;
    unassigned_datasets().await
}

pub async fn admin_list_collections(user: &CurrentUser) -> anyhow::Result<Vec<AdminCollectionItem>> {
    guard::require_admin(user)?;
    let cols = collections::list_collections().await?;
    let mut result = Vec::with_capacity(cols.len());
    for c in cols {
        let datasets = collections::list_collection_datasets(&c.collectionname).await?;
        let perms = collections::list_permissions_for_collection(&c.collectionname).await?;
        result.push(AdminCollectionItem {
            collectionname: c.collectionname,
            fullname: c.fullname,
            dataset_count: datasets.len() as u32,
            group_count: perms.len() as u32,
        });
    }
    Ok(result)
}

pub async fn admin_get_collection(
    user: &CurrentUser,
    collectionname: String,
) -> anyhow::Result<AdminCollectionDetail> {
    guard::require_admin(user)?;
    let c = collections::get_collection(&collectionname)
        .await?
        .ok_or_else(|| anyhow::anyhow!("collection not found"))?;
    let dataset_links = collections::list_collection_datasets(&collectionname).await?;
    let perms = collections::list_permissions_for_collection(&collectionname).await?;
    let client = crate::db_utils::clickhouse_utils::get_clickhouse_client();
    let mut datasets = Vec::new();
    for link in &dataset_links {
        let rows = client
            .query("SELECT collection_dataset, dataset_name, dataset_type, dataset_path, date_created FROM dataset FINAL WHERE collection_dataset = ? AND is_deleted = 0")
            .bind(&link.collection_dataset)
            .fetch_all::<DatasetListRow>()
            .await?;
        if let Some(row) = rows.into_iter().next() {
            datasets.push(AdminDatasetItem {
                collection_dataset: row.collection_dataset,
                dataset_name: row.dataset_name,
                dataset_type: row.dataset_type,
                dataset_path: row.dataset_path,
                date_created: format_datetime(row.date_created),
            });
        }
    }
    Ok(AdminCollectionDetail {
        collection: AdminCollectionItem {
            collectionname: c.collectionname,
            fullname: c.fullname,
            dataset_count: datasets.len() as u32,
            group_count: perms.len() as u32,
        },
        datasets,
        groups_with_access: perms.into_iter().map(|p| p.groupname).collect(),
        unassigned_datasets: unassigned_datasets().await?,
    })
}

pub async fn admin_create_collection(
    user: &CurrentUser,
    collectionname: String,
    fullname: String,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    if !slug_valid(&collectionname) {
        anyhow::bail!("invalid collectionname slug");
    }
    if collections::get_collection(&collectionname).await?.is_some() {
        anyhow::bail!("collection already exists");
    }
    collections::upsert_collection(CollectionRow {
        collectionname,
        fullname,
        created_at: time::OffsetDateTime::now_utc(),
        updated_at: time::OffsetDateTime::now_utc(),
        is_deleted: 0,
    })
    .await
}

pub async fn admin_update_collection(
    user: &CurrentUser,
    collectionname: String,
    fullname: String,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    let Some(mut row) = collections::get_collection(&collectionname).await? else {
        anyhow::bail!("collection not found");
    };
    row.fullname = fullname;
    collections::upsert_collection(row).await
}

pub async fn admin_delete_collection(
    user: &CurrentUser,
    collectionname: String,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    let datasets = collections::list_collection_datasets(&collectionname).await?;
    if !datasets.is_empty() {
        anyhow::bail!("collection still has datasets assigned");
    }
    let perms = collections::list_permissions_for_collection(&collectionname).await?;
    for p in perms {
        collections::revoke_permission(&p.groupname, &collectionname).await?;
    }
    collections::soft_delete_collection(&collectionname).await
}

pub async fn admin_assign_dataset(
    user: &CurrentUser,
    collectionname: String,
    collection_dataset: String,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    if collections::get_collection(&collectionname).await?.is_none() {
        anyhow::bail!("collection not found");
    }
    collections::assign_dataset(&collectionname, &collection_dataset).await
}

pub async fn admin_unassign_dataset(
    user: &CurrentUser,
    collection_dataset: String,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    collections::unassign_dataset(&collection_dataset).await
}

pub async fn admin_grant_permission(
    user: &CurrentUser,
    groupname: String,
    collectionname: String,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    collections::grant_permission(&groupname, &collectionname).await
}

pub async fn admin_revoke_permission(
    user: &CurrentUser,
    groupname: String,
    collectionname: String,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    collections::revoke_permission(&groupname, &collectionname).await
}
