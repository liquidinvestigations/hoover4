//! Collections, dataset links, and group permissions CRUD.

use crate::db_auth::{insert_row, now};
use crate::db_utils::clickhouse_utils::get_global_client;

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
pub struct CollectionRow {
    pub collectionname: String,
    pub fullname: String,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub created_at: time::OffsetDateTime,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub updated_at: time::OffsetDateTime,
    pub is_deleted: u8,
    /// 0 = restricted (readable only through a group grant), 1 = public (readable by
    /// every authenticated user). Declared in `00005_collections.sql` — it was its own
    /// `ALTER` migration until the Part 2 Phase 0 re-collapse folded it in.
    pub is_public: u8,
}

/// Column list for `collections`, used by every SELECT in this module so the
/// `clickhouse::Row` field order can never drift from the query.
const COLLECTION_SELECT: &str =
    "SELECT collectionname, fullname, created_at, updated_at, is_deleted, is_public \
     FROM collections FINAL";

/// A dataset's collection membership.
///
/// Since the database split there is no `collection_datasets` table: the mapping is a
/// column on `dataset` (decision D1 — a dataset belongs to exactly one collection, fixed
/// at creation), so this is a projection of the registry row.
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

const DATASET_COLLECTION_SELECT: &str = "SELECT collection_dataset, collectionname, \
     date_created AS created_at, date_modified AS updated_at, is_deleted FROM dataset FINAL";

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
    let client = get_global_client();
    client
        .query(&format!(
            "{COLLECTION_SELECT} WHERE is_deleted = 0 ORDER BY collectionname"
        ))
        .fetch_all::<CollectionRow>()
        .await
        .map_err(Into::into)
}

pub async fn get_collection(collectionname: &str) -> anyhow::Result<Option<CollectionRow>> {
    let client = get_global_client();
    let mut rows = client
        .query(&format!(
            "{COLLECTION_SELECT} WHERE collectionname = ? AND is_deleted = 0"
        ))
        .bind(collectionname)
        .fetch_all::<CollectionRow>()
        .await?;
    Ok(rows.pop())
}

/// Collectionnames that are readable by every authenticated user.
///
/// The other half of the permission union next to [`permitted_collections`]; kept as
/// its own query so a caller can never accidentally resolve public access through the
/// group join and drop it when a user has no groups at all.
pub async fn public_collections() -> anyhow::Result<Vec<String>> {
    let client = get_global_client();
    let mut result = client
        .query(
            "SELECT collectionname FROM collections FINAL \
             WHERE is_deleted = 0 AND is_public = 1",
        )
        .fetch_all::<String>()
        .await?;
    result.sort();
    Ok(result)
}

/// Flip a collection between restricted (`false`) and public (`true`).
pub async fn set_collection_public(collectionname: &str, is_public: bool) -> anyhow::Result<()> {
    let Some(mut row) = get_collection(collectionname).await? else {
        anyhow::bail!("collection not found");
    };
    row.is_public = u8::from(is_public);
    upsert_collection(row).await
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
    let client = get_global_client();
    client
        .query(&format!(
            "{DATASET_COLLECTION_SELECT} WHERE collectionname = ? AND is_deleted = 0 ORDER BY collection_dataset"
        ))
        .bind(collectionname)
        .fetch_all::<CollectionDatasetRow>()
        .await
        .map_err(Into::into)
}

pub async fn get_dataset_collection(
    collection_dataset: &str,
) -> anyhow::Result<Option<CollectionDatasetRow>> {
    let client = get_global_client();
    let mut rows = client
        .query(&format!(
            "{DATASET_COLLECTION_SELECT} WHERE collection_dataset = ? AND is_deleted = 0 AND collectionname != ''"
        ))
        .bind(collection_dataset)
        .fetch_all::<CollectionDatasetRow>()
        .await?;
    Ok(rows.pop())
}

/// Table created by the last collection migration. Used as the readiness sentinel:
/// `EnsureCollectionDatabase` creates the database first and only then applies the
/// migrations in filename order, so the database existing proves nothing — this table
/// existing proves every migration before it ran too.
///
/// The canonical value lives in
/// `main_services/processing/database/db_collection_migrations/READINESS_SENTINEL`
/// (asserted there against the last migration file by the Python test suite). This is
/// a checked-in copy — the website build cannot include files outside `website/` —
/// kept in sync by the unit test below. Update BOTH when a migration is added after
/// it in `main_services/processing/database/db_collection_migrations/`.
const LAST_COLLECTION_MIGRATION_TABLE: &str = include_str!("READINESS_SENTINEL");

/// Whether this collection's ClickHouse database has finished provisioning.
///
/// Creating a collection starts an `EnsureCollectionDatabase` workflow and returns
/// immediately, so between those two points the collection exists but its schema does
/// not. The admin UI shows that as a "provisioning" state.
pub async fn collection_db_ready(collectionname: &str) -> anyhow::Result<bool> {
    if !crate::api::admin::collections::collectionname_valid(collectionname) {
        return Ok(false);
    }
    let client = get_global_client();
    let count: u64 = client
        .query("SELECT count() FROM system.tables WHERE database = ? AND name = ?")
        .bind(format!("Hoover4_Collection_{collectionname}"))
        .bind(LAST_COLLECTION_MIGRATION_TABLE.trim())
        .fetch_one()
        .await?;
    Ok(count > 0)
}

async fn get_permission(groupname: &str, collectionname: &str) -> anyhow::Result<Option<PermissionRow>> {
    let client = get_global_client();
    let mut rows = client
        .query("SELECT groupname, collectionname, created_at, updated_at, is_deleted FROM collection_group_permissions FINAL WHERE groupname = ? AND collectionname = ? AND is_deleted = 0")
        .bind(groupname)
        .bind(collectionname)
        .fetch_all::<PermissionRow>()
        .await?;
    Ok(rows.pop())
}

pub async fn list_permissions_for_group(groupname: &str) -> anyhow::Result<Vec<PermissionRow>> {
    let client = get_global_client();
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
    let client = get_global_client();
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

/// Datasets the user may read: those in a collection granted to one of their groups,
/// UNION those in any collection marked public.
pub async fn permitted_collection_datasets(username: &str) -> anyhow::Result<Vec<String>> {
    let client = get_global_client();
    let mut result = client
        .query(
            "SELECT DISTINCT collection_dataset FROM (
                 SELECT d.collection_dataset AS collection_dataset
                 FROM user_group_membership AS m FINAL
                 INNER JOIN collection_group_permissions AS p FINAL ON p.groupname = m.groupname
                 INNER JOIN collections AS c FINAL ON c.collectionname = p.collectionname
                 INNER JOIN dataset AS d FINAL ON d.collectionname = p.collectionname
                 WHERE m.username = ? AND m.is_deleted = 0 AND p.is_deleted = 0
                   AND c.is_deleted = 0 AND d.is_deleted = 0
                 UNION DISTINCT
                 SELECT d.collection_dataset AS collection_dataset
                 FROM collections AS c FINAL
                 INNER JOIN dataset AS d FINAL ON d.collectionname = c.collectionname
                 WHERE c.is_deleted = 0 AND c.is_public = 1 AND d.is_deleted = 0
             )",
        )
        .bind(username)
        .fetch_all::<String>()
        .await?;
    result.sort();
    Ok(result)
}

/// Sibling of [`permitted_collection_datasets`] at collection granularity — the search
/// fan-out and the DB routing need permitted collections, not just permitted datasets.
pub async fn permitted_collections(username: &str) -> anyhow::Result<Vec<String>> {
    let client = get_global_client();
    let mut result = client
        .query(
            "SELECT DISTINCT collectionname FROM (
                 SELECT p.collectionname AS collectionname
                 FROM user_group_membership AS m FINAL
                 INNER JOIN collection_group_permissions AS p FINAL ON p.groupname = m.groupname
                 INNER JOIN collections AS c FINAL ON c.collectionname = p.collectionname
                 WHERE m.username = ? AND m.is_deleted = 0 AND p.is_deleted = 0
                   AND c.is_deleted = 0
                 UNION DISTINCT
                 SELECT c.collectionname AS collectionname
                 FROM collections AS c FINAL
                 WHERE c.is_deleted = 0 AND c.is_public = 1
             )",
        )
        .bind(username)
        .fetch_all::<String>()
        .await?;
    result.sort();
    Ok(result)
}


#[cfg(test)]
mod tests {
    /// Keep the checked-in sentinel copy in sync with the canonical file next to
    /// the collection migrations (which the Python test suite asserts against the
    /// last migration file). Runs on a dev checkout; skips where main_services is
    /// not mounted (website container).
    #[test]
    fn readiness_sentinel_copy_matches_canonical() {
        let canonical = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../main_services/processing/database/db_collection_migrations/READINESS_SENTINEL");
        if !canonical.exists() {
            eprintln!("skipping: main_services not reachable from the cargo workspace");
            return;
        }
        let canonical = std::fs::read_to_string(canonical).unwrap();
        assert_eq!(
            canonical.trim(),
            super::LAST_COLLECTION_MIGRATION_TABLE.trim(),
            "READINESS_SENTINEL copies drifted — update both (see the const's doc comment)"
        );
    }
}
