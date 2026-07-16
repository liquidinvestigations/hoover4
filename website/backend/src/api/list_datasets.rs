//! Endpoint for listing datasets.

use common::current_user::CurrentUser;

use crate::auth::permissions::{self, PermissionSet};
use crate::db_utils::clickhouse_utils::get_clickhouse_client;

pub async fn list_dataset_ids() -> anyhow::Result<Vec<String>> {
    let client = get_clickhouse_client();
    let mut result = client
        .query("SELECT DISTINCT collection_dataset FROM dataset FINAL WHERE is_deleted = 0")
        .fetch_all()
        .await?;
    result.sort();
    Ok(result)
}

pub async fn list_permitted_dataset_ids(user: &CurrentUser) -> anyhow::Result<Vec<String>> {
    let perms = permissions::resolve_permissions(user).await?;
    let all = list_dataset_ids().await?;
    match perms {
        PermissionSet::All => Ok(all),
        PermissionSet::Some(set) => Ok(all.into_iter().filter(|d| set.contains(d)).collect()),
    }
}
