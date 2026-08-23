//! Client API calls for the collections > datasets levels of the storage tree.
//!
//! The VFS calls in `vfs_api` are all scoped to one dataset, because the structure index
//! is. These are the two levels above it, which come from the dataset registry instead.

use common::storage_tree::{CollectionNode, CollectionOverview};
use dioxus::prelude::*;

#[cfg(feature = "server")]
use crate::api::error_util::to_server_fn_error;

/// Every collection the user may read, with its datasets. ONE call, on mount, for a
/// tree of any size. The folders below a dataset are fetched only when it is expanded.
#[server]
pub async fn list_storage_tree() -> Result<Vec<CollectionNode>, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::list_datasets::list_permitted_collection_tree(&user)
        .await
        .map_err(to_server_fn_error)
}

/// One collection's datasets with their cached aggregates: the landing page's cards.
#[server]
pub async fn collection_overview(
    collectionname: String,
) -> Result<CollectionOverview, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::list_datasets::collection_overview(&user, collectionname)
        .await
        .map_err(to_server_fn_error)
}

/// The `vfs_node` term ids of a whole selection, in one round trip per dataset.
///
/// The single-key [`crate::api::vfs_api::vfs_node_term_id`] is still what the storage
/// page's "Open in Search" link uses. It has exactly one key. The picker has as many
/// keys as the user has ticked, and ticking a collection row ticks all of its datasets
/// at once, so resolving them one at a time is a burst of requests per click.
///
/// The dataset of each key is read off the key itself (its first field); a key that
/// names no dataset, or one the user may not read, is skipped rather than failing the
/// batch. A stale selection must not make the pane unusable.
#[server]
pub async fn vfs_node_term_ids(node_keys: Vec<String>) -> Result<Vec<u64>, ServerFnError> {
    use common::vfs::dataset_of_node_key;
    use std::collections::HashMap;

    let user = crate::api::server_auth::extract_user().await?;
    let mut by_dataset: HashMap<String, Vec<String>> = HashMap::new();
    for key in node_keys {
        let Some(dataset) = dataset_of_node_key(&key) else {
            continue;
        };
        by_dataset.entry(dataset.to_string()).or_default().push(key);
    }
    let mut ids: Vec<u64> = Vec::new();
    for (dataset, keys) in by_dataset {
        if backend::auth::permissions::assert_can_read(&user, &dataset)
            .await
            .is_err()
        {
            continue;
        }
        let resolved = backend::api::vfs::tree::node_term_ids(&dataset, &keys)
            .await
            .map_err(to_server_fn_error)?;
        ids.extend(resolved.into_values());
    }
    ids.sort_unstable();
    ids.dedup();
    Ok(ids)
}
