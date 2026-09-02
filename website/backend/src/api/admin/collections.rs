//! Admin collection management API.

use common::admin_types::{AdminCollectionDetail, AdminCollectionItem, AdminDatasetItem};
use common::current_user::CurrentUser;
use time::format_description::well_known::Rfc3339;

use crate::api::admin::operations;
use crate::auth::guard;
use crate::db_auth::collections::{self, CollectionRow};

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
struct DatasetListRow {
    pub collection_dataset: String,
    pub dataset_name: String,
    pub dataset_display_name: String,
    pub dataset_type: String,
    pub dataset_path: String,
    #[serde(with = "clickhouse::serde::time::datetime")]
    pub date_created: time::OffsetDateTime,
}

/// Maximum length of a collectionname. Kept short because it is a prefix of a
/// ClickHouse database name and of every Manticore shard table name.
pub const MAX_COLLECTIONNAME_LENGTH: usize = 48;

/// Validate a collectionname.
///
/// Mirrors `validate_collectionname` in
/// `main_services/processing/database/clickhouse.py`. Duplicated deliberately: the two
/// runtimes must independently refuse a bad name, because the name is interpolated into
/// a ClickHouse database name and into Manticore table names, neither of which can be
/// bound as a parameter.
pub fn collectionname_valid(s: &str) -> bool {
    if s.is_empty() || s.len() > MAX_COLLECTIONNAME_LENGTH {
        return false;
    }
    // No '-': every Manticore identifier (<name>_<n>_pages|_meta) is interpolated
    // UNQUOTED into SQL in both runtimes, and a dashed table name does not parse.
    if !s
        .chars()
        .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')
    {
        return false;
    }
    // `<name>_<digits>` would collide with a Manticore shard name (e.g. `testdata_1`).
    if let Some((_, tail)) = s.rsplit_once('_')
        && !tail.is_empty()
        && tail.chars().all(|c| c.is_ascii_digit())
    {
        return false;
    }
    // Reserved Manticore table suffixes.
    if s.ends_with("_pages") || s.ends_with("_meta") {
        return false;
    }
    // Would produce a confusing database name next to `Hoover4_Processing`.
    if s == "processing" {
        return false;
    }
    true
}

fn format_datetime(dt: time::OffsetDateTime) -> String {
    dt.format(&Rfc3339).unwrap_or_else(|_| dt.to_string())
}

pub async fn admin_list_collections(user: &CurrentUser) -> anyhow::Result<Vec<AdminCollectionItem>> {
    guard::require_admin(user)?;
    let cols = collections::list_collections().await?;
    let mut result = Vec::with_capacity(cols.len());
    for c in cols {
        let datasets = collections::list_collection_datasets(&c.collectionname).await?;
        let perms = collections::list_permissions_for_collection(&c.collectionname).await?;
        let db_ready = collections::collection_db_ready(&c.collectionname).await?;
        result.push(AdminCollectionItem {
            collectionname: c.collectionname,
            fullname: c.fullname,
            dataset_count: datasets.len() as u32,
            group_count: perms.len() as u32,
            db_ready,
            is_public: c.is_public == 1,
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
    let client = crate::db_utils::clickhouse_utils::get_global_client();
    let mut datasets = Vec::new();
    for link in &dataset_links {
        let rows = client
            .query("SELECT collection_dataset, dataset_name, dataset_display_name, dataset_type, dataset_path, date_created FROM dataset FINAL WHERE collection_dataset = ? AND is_deleted = 0")
            .bind(&link.collection_dataset)
            .fetch_all::<DatasetListRow>()
            .await?;
        if let Some(row) = rows.into_iter().next() {
            datasets.push(AdminDatasetItem {
                collection_dataset: row.collection_dataset,
                dataset_name: row.dataset_name,
                dataset_display_name: row.dataset_display_name,
                dataset_type: row.dataset_type,
                dataset_path: row.dataset_path,
                date_created: format_datetime(row.date_created),
            });
        }
    }
    let db_ready = collections::collection_db_ready(&c.collectionname).await?;
    Ok(AdminCollectionDetail {
        collection: AdminCollectionItem {
            collectionname: c.collectionname,
            fullname: c.fullname,
            dataset_count: datasets.len() as u32,
            group_count: perms.len() as u32,
            db_ready,
            is_public: c.is_public == 1,
        },
        datasets,
        groups_with_access: perms.into_iter().map(|p| p.groupname).collect(),
    })
}

pub async fn admin_create_collection(
    user: &CurrentUser,
    collectionname: String,
    fullname: String,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    if !collectionname_valid(&collectionname) {
        anyhow::bail!(
            "invalid collectionname: use 1-{MAX_COLLECTIONNAME_LENGTH} characters of [a-z0-9_], \
             not ending in _<digits>, _pages or _meta"
        );
    }
    if collections::get_collection(&collectionname).await?.is_some() {
        anyhow::bail!("collection already exists");
    }
    collections::upsert_collection(CollectionRow {
        collectionname: collectionname.clone(),
        fullname,
        created_at: time::OffsetDateTime::now_utc(),
        updated_at: time::OffsetDateTime::now_utc(),
        is_deleted: 0,
        // New collections start restricted. Opening one up is a deliberate admin
        // action, never a default.
        is_public: 0,
    })
    .await?;

    // Provision the collection's ClickHouse database. The schema lives in Python, so we
    // dispatch the operation and do not wait for it: the collection page shows a
    // "provisioning" state until `collection_db_ready` returns true. It is an operation
    // rather than a bare workflow so that provisioning has a row saying whether it ever
    // finished: without one, a collection stuck in "provisioning" is a state with no
    // record behind it to explain why.
    //
    // If the operation cannot even be dispatched, undo the row. Leaving it would strand
    // the collection: it can never be provisioned (there is no re-provision action) and
    // it can never be re-created either, because the existence check above would reject
    // it.
    if let Err(e) =
        operations::dispatch_operation("ensure_collection", &collectionname, "", &user.username, "", "")
            .await
    {
        collections::soft_delete_collection(&collectionname).await.ok();
        anyhow::bail!("database provisioning failed to start, collection not created: {e}");
    }
    Ok(())
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
    collections::soft_delete_collection(&collectionname).await?;

    // Destructive: drops Hoover4_Collection_<name> entirely. Gated above on the
    // collection having no datasets, and in the UI on typing the collection name.
    // Dispatched as an operation, so a drop that fails half way is a row that can be
    // re-run rather than a database nobody knows is still there.
    operations::dispatch_operation(
        "drop_collection_database",
        &collectionname,
        "",
        &user.username,
        "",
        "",
    )
    .await?;
    Ok(())
}

/// Flip a collection between `restricted` (group grants only) and `public` (readable
/// by every authenticated user, in addition to their group grants).
///
/// Existing group grants are left untouched: making a collection public is additive,
/// so making it restricted again restores exactly the previous access.
pub async fn admin_set_collection_public(
    user: &CurrentUser,
    collectionname: String,
    is_public: bool,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    collections::set_collection_public(&collectionname, is_public).await?;
    // The permission cache keys on username and holds resolved collection sets for up
    // to 60s, so without this a just-published collection stays invisible for a minute.
    crate::auth::permissions::invalidate_permission_cache();
    Ok(())
}

pub async fn admin_grant_permission(
    user: &CurrentUser,
    groupname: String,
    collectionname: String,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    collections::grant_permission(&groupname, &collectionname).await?;
    crate::auth::permissions::invalidate_permission_cache();
    Ok(())
}

pub async fn admin_revoke_permission(
    user: &CurrentUser,
    groupname: String,
    collectionname: String,
) -> anyhow::Result<()> {
    guard::require_admin(user)?;
    collections::revoke_permission(&groupname, &collectionname).await?;
    crate::auth::permissions::invalidate_permission_cache();
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{collectionname_valid, MAX_COLLECTIONNAME_LENGTH};

    /// The validation matrix is shared with the Python package
    /// (`database.clickhouse.validate_collectionname`): both runtimes validate
    /// independently, so both suites load the one canonical list,
    /// `main_services/processing/database/collectionname_validation_cases.json`.
    /// Reachable from the cargo workspace on a dev checkout; skipped where
    /// main_services is not mounted (website container).
    fn shared_cases() -> Option<serde_json::Value> {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../main_services/processing/database/collectionname_validation_cases.json");
        let text = std::fs::read_to_string(path).ok()?;
        serde_json::from_str(&text).ok()
    }

    fn case_names(cases: &serde_json::Value, key: &str) -> Vec<String> {
        cases[key]
            .as_array()
            .unwrap_or_else(|| panic!("shared validation cases: missing {key:?} array"))
            .iter()
            .map(|v| v.as_str().expect("case names must be strings").to_string())
            .collect()
    }

    #[test]
    fn accepts_valid_slugs() {
        let Some(cases) = shared_cases() else {
            eprintln!("skipping: main_services validation cases not reachable");
            return;
        };
        for name in case_names(&cases, "valid") {
            assert!(collectionname_valid(&name), "should accept {name:?}");
        }
    }

    #[test]
    fn rejects_invalid_slugs() {
        let Some(cases) = shared_cases() else {
            eprintln!("skipping: main_services validation cases not reachable");
            return;
        };
        for name in case_names(&cases, "invalid") {
            assert!(!collectionname_valid(&name), "should reject {name:?}");
        }
    }

    /// Length boundary pinned locally (the shared list covers it too, but only
    /// where main_services is mounted).
    #[test]
    fn length_boundary() {
        assert!(collectionname_valid(&"x".repeat(MAX_COLLECTIONNAME_LENGTH)));
        assert!(!collectionname_valid(&"x".repeat(MAX_COLLECTIONNAME_LENGTH + 1)));
    }
}
