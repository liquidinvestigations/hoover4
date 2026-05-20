//! Virtual file system browsing endpoints.

use std::collections::BTreeSet;

use common::search_result::DocumentIdentifier;
use common::vfs::{PathDescriptor, VfsDirectoryEntry, VfsFileEntry, VfsListing};

use crate::db_utils::clickhouse_utils::get_clickhouse_client;

/// Look up the first VFS path for a given document identifier.
pub async fn get_first_vfs_path(
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<PathDescriptor> {
    let client = get_clickhouse_client();
    let sql = "
        SELECT path, container_hash
        FROM vfs_files
        WHERE collection_dataset = ?
          AND hash = ?
        ORDER BY path
        LIMIT 1
    ";
    let rows: Vec<(String, String)> = client
        .query(sql)
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash)
        .fetch_all()
        .await?;
    rows.into_iter()
        .next()
        .map(|(path, container_hash)| PathDescriptor {
            container_hash,
            path,
        })
        .ok_or_else(|| anyhow::anyhow!("No VFS path found for document"))
}

/// Fetch the immediate child directories and files for a given folder
/// inside a collection's virtual file system.
///
/// `path.path` is expected to be an absolute VFS path. The root is `"/"`;
/// an empty string is rejected so the caller is forced to use `"/"`.
/// `path.container_hash` selects the archive/email container that owns the
/// folder; empty string means top-level VFS.
pub async fn list_folder_children(
    collection_dataset: String,
    path: PathDescriptor,
) -> anyhow::Result<VfsListing> {
    if path.path.is_empty() {
        anyhow::bail!("path must not be empty; use \"/\" for the root folder");
    }

    let client = get_clickhouse_client();

    // Children of `path` are rows whose path begins with `prefix` (i.e. `path.path`
    // with a trailing slash) and whose remainder contains no further `/`.
    let prefix = if path.path.ends_with('/') {
        path.path.clone()
    } else {
        format!("{}/", path.path)
    };

    let dir_sql = "
        SELECT path
        FROM vfs_directories
        WHERE collection_dataset = ?
          AND container_hash = ?
          AND startsWith(path, ?)
          AND length(path) > length(?)
          AND position(substring(path, length(?) + 1), '/') = 0
        ORDER BY path
        LIMIT 5000
    ";
    let dir_paths: Vec<String> = client
        .query(dir_sql)
        .bind(&collection_dataset)
        .bind(&path.container_hash)
        .bind(&prefix)
        .bind(&prefix)
        .bind(&prefix)
        .fetch_all()
        .await?;

    let file_sql = "
        SELECT path, hash, file_size_bytes
        FROM vfs_files
        WHERE collection_dataset = ?
          AND container_hash = ?
          AND startsWith(path, ?)
          AND length(path) > length(?)
          AND position(substring(path, length(?) + 1), '/') = 0
        ORDER BY path
        LIMIT 5000
    ";
    let file_rows: Vec<(String, String, u64)> = client
        .query(file_sql)
        .bind(&collection_dataset)
        .bind(&path.container_hash)
        .bind(&prefix)
        .bind(&prefix)
        .bind(&prefix)
        .fetch_all()
        .await?;

    let directories = dir_paths
        .into_iter()
        .map(|full_path| {
            let name = full_path[prefix.len()..].to_string();
            VfsDirectoryEntry {
                name,
                path: PathDescriptor {
                    container_hash: path.container_hash.clone(),
                    path: full_path,
                },
            }
        })
        .collect();

    let file_hashes = BTreeSet::from_iter(file_rows.iter().map(|(_, hash, _)| hash.clone()));
    let container_hashes = _get_container_hashes(collection_dataset.clone(), file_hashes)
        .await
        .unwrap_or_default();

    let files = file_rows
        .into_iter()
        .map(|(full_path, hash, file_size_bytes)| {
            let name = full_path[prefix.len()..].to_string();
            VfsFileEntry {
                name,
                path: PathDescriptor {
                    container_hash: path.container_hash.clone(),
                    path: full_path,
                },
                hash: hash.clone(),
                file_size_bytes,
                is_container: container_hashes.contains(&hash),
            }
        })
        .collect();

    Ok(VfsListing {
        collection_dataset,
        path,
        directories,
        files,
    })
}

async fn _get_container_hashes(
    collection_dataset: String,
    file_hashes: BTreeSet<String>,
) -> anyhow::Result<BTreeSet<String>> {
    let client = get_clickhouse_client();
    let sql = "
        SELECT DISTINCT container_hash
        FROM vfs_files
        WHERE collection_dataset = ?
          AND container_hash IN (?)
    ";
    let rows: Vec<String> = client
        .query(sql)
        .bind(&collection_dataset)
        .bind(&file_hashes)
        .fetch_all()
        .await?;
    Ok(BTreeSet::from_iter(rows.into_iter()))
}
