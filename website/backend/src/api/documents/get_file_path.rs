//! Endpoint for resolving document file paths.

use common::vfs::{VfsFileLocation, VfsFileLocations, make_node_key};
use common::{current_user::CurrentUser, search_result::DocumentIdentifier};

use crate::auth::permissions;
use crate::db_utils::clickhouse_utils::get_client_for_dataset;

/// The one path to call a document by, or `None` when the dataset has no such file.
///
/// "No such file" is `None`, not an error: a bookmarked or shared document URL outlives
/// the ingest that produced it, and the title bar's job when the identifier resolves to
/// nothing is to say so quietly. An `Err` here reached the user as
/// `error running server function: File path not found` on a page that was otherwise
/// fine. Genuine failures (permissions, an unreachable ClickHouse) are still errors.
pub async fn get_file_path(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<Option<String>> {
    crate::api::telemetry::record_event(&user.username, crate::api::telemetry::EVENT_USER_GET_DOCUMENT, "");
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;
    let query = "SELECT path FROM vfs_files WHERE hash = ? AND collection_dataset = ? LIMIT 1";
    let query = client
        .query(query)
        .bind(&document_identifier.file_hash)
        .bind(&document_identifier.collection_dataset);
    let result = query.fetch_all::<String>().await?;
    Ok(result.into_iter().next())
}

/// Locations resolved into breadcrumb chains in one request.
///
/// Each chain is its own walk up `parent_key`, so the cost of this endpoint is
/// `locations × depth` small queries. A hash at every path of a wide fixture is a real
/// thing (the shapes corpus has one at 668), and a panel is not a place to spend 2000
/// round trips. The rest are reported as a count.
pub const MAX_FILE_LOCATIONS: u64 = 25;

/// Every path a file hash sits at inside its dataset, each with its ancestor chain.
///
/// Not `get_file_path` with the `LIMIT 1` raised: that one answers "what do I call this
/// document" for the title bar and wants exactly one name. This one exists because the
/// answer is usually more than one, and because each answer is only useful with the
/// containers above it. A member of `parent.zip` is at `/location-1/parent.zip/child.txt`
/// and at `/location-2/parent.zip/child.txt`, and neither path string says so on its own.
pub async fn get_file_locations(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<VfsFileLocations> {
    crate::api::telemetry::record_event(&user.username, crate::api::telemetry::EVENT_USER_GET_DOCUMENT, "");
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    let dataset = document_identifier.collection_dataset.clone();
    let client = get_client_for_dataset(&dataset).await?;

    // FINAL because `vfs_files` is a ReplacingMergeTree: an unmerged part would show the
    // same location twice, which in this panel reads as "the file really is in two
    // places".
    let total: u64 = client
        .query("SELECT count() FROM vfs_files FINAL WHERE hash = ? AND collection_dataset = ?")
        .bind(&document_identifier.file_hash)
        .bind(&dataset)
        .fetch_all::<u64>()
        .await?
        .into_iter()
        .next()
        .unwrap_or(0);

    let rows = client
        .query(
            "SELECT container_hash, path FROM vfs_files FINAL \
             WHERE hash = ? AND collection_dataset = ? \
             ORDER BY container_hash, path LIMIT ?",
        )
        .bind(&document_identifier.file_hash)
        .bind(&dataset)
        .bind(MAX_FILE_LOCATIONS)
        .fetch_all::<(String, String)>()
        .await?;

    // Concurrent, not sequential: the walks are independent and each one is several
    // round trips deep.
    let chains = futures::future::join_all(rows.iter().map(|(container_hash, path)| {
        let dataset = dataset.clone();
        let node_key = make_node_key(&dataset, container_hash, path);
        async move {
            // A location the structure index has not caught up with still belongs in the
            // list, with its raw path instead of a chain.
            crate::api::vfs::vfs_tree_path_to(user, dataset, node_key)
                .await
                .unwrap_or_default()
        }
    }))
    .await;

    let locations = rows
        .into_iter()
        .zip(chains)
        .map(|((container_hash, path), chain)| VfsFileLocation {
            collection_dataset: dataset.clone(),
            container_hash,
            path,
            chain,
        })
        .collect();

    Ok(VfsFileLocations { locations, total })
}

/// The document's canonical file type, for the title bar's glyph.
///
/// `""` for a document `file_type_canonical` has no row for, such as a file indexed before
/// the type resolver ran, or one still being processed. The glyph draws that as the generic
/// file icon, which is what the title bar drew for everything before.
pub async fn get_canonical_file_type(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<String> {
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;
    let rows: Vec<String> = client
        .query(
            "SELECT file_type FROM file_type_canonical FINAL \
             WHERE collection_dataset = ? AND hash = ? LIMIT 1",
        )
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash)
        .fetch_all()
        .await
        .unwrap_or_default();
    Ok(rows.into_iter().next().unwrap_or_default())
}
