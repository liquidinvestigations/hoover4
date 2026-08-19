//! Client API calls for the VFS structure index.
//!
//! These back the tree sidebar, the filter pane's folder picker, and in-folder search.
//! Every one of them is answered from the collection's `<name>_vfs` Manticore table
//! through the NON-caching primitive: the tree changes while ingestion runs, and a
//! stale tree is worse than a slow one.

use common::vfs::{VfsTreeChildren, VfsTreeNode};
use dioxus::prelude::*;

#[cfg(feature = "server")]
use crate::api::error_util::to_server_fn_error;

/// One page of a node's children.
///
/// `folders_only` is what the tree skins pass and the file-browser content pane does not:
/// the tree draws only what can be opened, so counting files into its `total` promised
/// rows it was never going to render. Paging is by `offset` — the caller appends pages
/// rather than re-asking with a bigger `limit`.
#[server]
pub async fn vfs_tree_children(
    collection_dataset: String,
    node_key: String,
    limit: u64,
    offset: u64,
    folders_only: bool,
) -> Result<VfsTreeChildren, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::vfs::vfs_tree_children(
        &user,
        collection_dataset,
        node_key,
        limit,
        offset,
        folders_only,
    )
    .await
    .map_err(to_server_fn_error)
}

/// The chain of nodes from the dataset root down to one node, root first. What the
/// breadcrumb renders, and what the sidebar expands to reveal a deep selection.
#[server]
pub async fn vfs_tree_path_to(
    collection_dataset: String,
    node_key: String,
) -> Result<Vec<VfsTreeNode>, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::vfs::vfs_tree_path_to(&user, collection_dataset, node_key)
        .await
        .map_err(to_server_fn_error)
}

/// Names matching a pattern anywhere under a node — through containers, not just in the
/// current listing.
#[server]
pub async fn vfs_search_in_folder(
    collection_dataset: String,
    node_key: String,
    pattern: String,
    limit: u64,
) -> Result<VfsTreeChildren, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::vfs::vfs_search_in_folder(&user, collection_dataset, node_key, pattern, limit)
        .await
        .map_err(to_server_fn_error)
}

/// The `vfs_node` term id of a node key.
///
/// The folder filter is `file_paths IN (<term id>)`, and the id is minted by the Python
/// indexer (`blake2b` truncated to 63 bits). The client asks rather than recomputing:
/// two implementations of one hash drift silently, and the symptom would be a folder
/// filter that returns nothing with no error anywhere.
#[server]
pub async fn vfs_node_term_id(
    collection_dataset: String,
    node_key: String,
) -> Result<Option<u64>, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::auth::permissions::assert_can_read(&user, &collection_dataset)
        .await
        .map_err(to_server_fn_error)?;
    backend::api::vfs::tree::node_term_id(&collection_dataset, &node_key)
        .await
        .map_err(to_server_fn_error)
}
