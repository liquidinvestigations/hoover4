//! Virtual file system browsing endpoints.

use common::search_result::DocumentIdentifier;
use common::vfs::{VfsDirectoryEntry, VfsFileEntry, VfsListing};

use crate::db_utils::clickhouse_utils::get_clickhouse_client;

/// Look up the first VFS path for a given document identifier.
pub async fn get_first_vfs_path(
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<String> {
    let client = get_clickhouse_client();
    let sql = "
        SELECT path
        FROM vfs_files
        WHERE collection_dataset = ?
          AND hash = ?
        ORDER BY path
        LIMIT 1
    ";
    let rows: Vec<String> = client
        .query(sql)
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash)
        .fetch_all()
        .await?;
    rows.into_iter()
        .next()
        .ok_or_else(|| anyhow::anyhow!("No VFS path found for document"))
}

/// Fetch the immediate child directories and files for a given folder
/// inside a collection's top-level virtual file system (no archive container).
///
/// `path` is expected to be an absolute VFS path. The root is `"/"`; an empty
/// string is rejected so the caller is forced to use `"/"`.
pub async fn list_folder_children(
    collection_dataset: String,
    path: String,
) -> anyhow::Result<VfsListing> {
    if path.is_empty() {
        anyhow::bail!("path must not be empty; use \"/\" for the root folder");
    }

    let client = get_clickhouse_client();

    // Children of `path` are rows whose path begins with `prefix` (i.e. `path`
    // with a trailing slash) and whose remainder contains no further `/`.
    let prefix = if path.ends_with('/') {
        path.clone()
    } else {
        format!("{}/", path)
    };

    let dir_sql = "
        SELECT path
        FROM vfs_directories
        WHERE collection_dataset = ?
          AND container_hash = ''
          AND startsWith(path, ?)
          AND length(path) > length(?)
          AND position(substring(path, length(?) + 1), '/') = 0
        ORDER BY path
        LIMIT 100
    ";
    let dir_paths: Vec<String> = client
        .query(dir_sql)
        .bind(&collection_dataset)
        .bind(&prefix)
        .bind(&prefix)
        .bind(&prefix)
        .fetch_all()
        .await?;

    let file_sql = "
        SELECT path, hash, file_size_bytes
        FROM vfs_files
        WHERE collection_dataset = ?
          AND container_hash = ''
          AND startsWith(path, ?)
          AND length(path) > length(?)
          AND position(substring(path, length(?) + 1), '/') = 0
        ORDER BY path
        LIMIT 100
    ";
    let file_rows: Vec<(String, String, u64)> = client
        .query(file_sql)
        .bind(&collection_dataset)
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
                path: full_path,
            }
        })
        .collect();

    let files = file_rows
        .into_iter()
        .map(|(full_path, hash, file_size_bytes)| {
            let name = full_path[prefix.len()..].to_string();
            VfsFileEntry {
                name,
                path: full_path,
                hash,
                file_size_bytes,
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
