//! Endpoint for listing datasets.

use std::collections::HashMap;
use std::sync::{LazyLock, Mutex};
use std::time::{Duration, Instant};

use common::current_user::CurrentUser;
use common::storage_tree::{CollectionNode, CollectionOverview, DatasetAggregates, DatasetSummary};

use crate::auth::permissions::{self, PermissionSet};
use crate::db_utils::clickhouse_utils::{
    collection_db_name, get_collection_client, get_global_client,
};

pub async fn list_dataset_ids() -> anyhow::Result<Vec<String>> {
    let client = get_global_client();
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

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
struct DatasetSummaryRow {
    collection_dataset: String,
    collectionname: String,
    dataset_name: String,
    dataset_display_name: String,
}

async fn list_permitted_datasets(user: &CurrentUser) -> anyhow::Result<Vec<DatasetSummary>> {
    let perms = permissions::resolve_permissions(user).await?;
    let rows: Vec<DatasetSummaryRow> = get_global_client()
        .query(
            "SELECT collection_dataset, collectionname, dataset_name, dataset_display_name \
             FROM dataset FINAL WHERE is_deleted = 0 ORDER BY collectionname, dataset_name",
        )
        .fetch_all()
        .await?;
    Ok(rows
        .into_iter()
        .filter(|row| match &perms {
            PermissionSet::All => true,
            PermissionSet::Some(set) => set.contains(&row.collection_dataset),
        })
        // A registry row whose collectionname is empty or invalid names no database, so
        // nothing under it could ever be browsed; it is dropped rather than rendered as
        // a row that errors on expand.
        .filter(|row| collection_db_name(&row.collectionname).is_ok())
        .map(|row| DatasetSummary {
            collection_dataset: row.collection_dataset,
            collectionname: row.collectionname,
            dataset_name: row.dataset_name,
            dataset_display_name: row.dataset_display_name,
        })
        .collect())
}

/// The whole collections > datasets skeleton the storage tree renders, in ONE query.
///
/// The tree is lazy below this point: a dataset's folders are fetched when its row is
/// expanded, never on mount. This call must therefore stay a single round trip however
/// many collections and datasets exist. The tree is on every storage surface and in the
/// filter modal, and one call per row was the shape of the viewer defect that wedged
/// ClickHouse with 41 queries per page load.
pub async fn list_permitted_collection_tree(
    user: &CurrentUser,
) -> anyhow::Result<Vec<CollectionNode>> {
    Ok(group_by_collection(list_permitted_datasets(user).await?))
}

/// Group an already-sorted dataset list into collection nodes, preserving order.
fn group_by_collection(datasets: Vec<DatasetSummary>) -> Vec<CollectionNode> {
    let mut nodes: Vec<CollectionNode> = Vec::new();
    for dataset in datasets {
        match nodes.last_mut() {
            Some(node) if node.collectionname == dataset.collectionname => {
                node.datasets.push(dataset)
            }
            _ => nodes.push(CollectionNode {
                collectionname: dataset.collectionname.clone(),
                datasets: vec![dataset],
            }),
        }
    }
    nodes
}

/// One collection's datasets with their cached aggregates: what the collection landing
/// page's cards show.
pub async fn collection_overview(
    user: &CurrentUser,
    collectionname: String,
) -> anyhow::Result<CollectionOverview> {
    let datasets: Vec<DatasetSummary> = list_permitted_datasets(user)
        .await?
        .into_iter()
        .filter(|d| d.collectionname == collectionname)
        .collect();
    if datasets.is_empty() {
        // Either the collection does not exist or the user may read nothing in it. The
        // two are deliberately not distinguished: the second answer leaks the first.
        anyhow::bail!("no readable datasets in collection {collectionname:?}");
    }
    let aggregates = dataset_aggregates(&collectionname).await?;
    let permitted: Vec<DatasetAggregates> = aggregates
        .into_iter()
        .filter(|a| {
            datasets
                .iter()
                .any(|d| d.collection_dataset == a.collection_dataset)
        })
        .collect();
    Ok(CollectionOverview {
        collectionname,
        datasets,
        aggregates: permitted,
    })
}

/// How long a collection's aggregates are cached in-process.
///
/// The same TTL the shard ledger uses (`clickhouse_utils::SHARD_STATE_TTL`): these are
/// three grouped scans of a collection's largest tables, they move only while an ingest
/// runs, and the page they back is a landing page people bounce off.
const AGGREGATE_TTL: Duration = Duration::from_secs(30);

static AGGREGATE_CACHE: LazyLock<Mutex<HashMap<String, (Instant, Vec<DatasetAggregates>)>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

/// Per-dataset document count, total size, indexed count and error count for every
/// dataset in one collection.
///
/// Three grouped queries for the whole collection rather than five per dataset (which is
/// what `admin::datasets::fetch_stats` does for its single-dataset page): the landing
/// page shows every dataset at once, so the per-dataset shape would be N x 5 round trips
/// on one load.
async fn dataset_aggregates(collectionname: &str) -> anyhow::Result<Vec<DatasetAggregates>> {
    {
        let cache = AGGREGATE_CACHE.lock().unwrap();
        if let Some((fetched, values)) = cache.get(collectionname)
            && fetched.elapsed() < AGGREGATE_TTL
        {
            return Ok(values.clone());
        }
    }
    // Validated first, with the fallible call: `get_collection_client` panics on a bad
    // slug and this is reachable from a request handler with whatever the registry holds.
    collection_db_name(collectionname)?;
    let client = get_collection_client(collectionname);

    // `blobs` is a ReplacingMergeTree, so an un-merged duplicate row would double both
    // the count and the size. Collapsing per hash first is what the ETA collector does
    // (`P_admin/eta_collector.py`) and is the only form that is stable between merges.
    let sizes: Vec<(String, u64, u64)> = client
        .query(
            "SELECT collection_dataset, count() AS documents, sum(sz) AS bytes FROM ( \
               SELECT collection_dataset, blob_hash, any(blob_size_bytes) AS sz \
               FROM blobs GROUP BY collection_dataset, blob_hash \
             ) GROUP BY collection_dataset",
        )
        .fetch_all()
        .await?;
    let indexed: Vec<(String, u64)> = client
        .query(
            "SELECT collection_dataset, uniqExact(file_hash) AS value \
             FROM index_state GROUP BY collection_dataset",
        )
        .fetch_all()
        .await?;
    let errors: Vec<(String, u64)> = client
        .query(
            "SELECT collection_dataset, count() AS value \
             FROM processing_errors GROUP BY collection_dataset",
        )
        .fetch_all()
        .await?;

    let indexed: HashMap<String, u64> = indexed.into_iter().collect();
    let errors: HashMap<String, u64> = errors.into_iter().collect();
    let values: Vec<DatasetAggregates> = sizes
        .into_iter()
        .map(|(collection_dataset, document_count, total_size_bytes)| DatasetAggregates {
            indexed_count: indexed.get(&collection_dataset).copied().unwrap_or(0),
            error_count: errors.get(&collection_dataset).copied().unwrap_or(0),
            collection_dataset,
            document_count,
            total_size_bytes,
        })
        .collect();

    AGGREGATE_CACHE
        .lock()
        .unwrap()
        .insert(collectionname.to_string(), (Instant::now(), values.clone()));
    Ok(values)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dataset(collection: &str, name: &str) -> DatasetSummary {
        DatasetSummary {
            collection_dataset: format!("{collection}_{name}"),
            collectionname: collection.to_string(),
            dataset_name: name.to_string(),
            dataset_display_name: String::new(),
        }
    }

    #[test]
    fn datasets_group_into_their_collections_in_order() {
        let nodes = group_by_collection(vec![
            dataset("other", "emails"),
            dataset("testdata", "shapes"),
            dataset("testdata", "testfiles"),
            dataset("testdata", "zips"),
        ]);
        let names: Vec<&str> = nodes.iter().map(|n| n.collectionname.as_str()).collect();
        assert_eq!(names, ["other", "testdata"]);
        assert_eq!(nodes[1].dataset_ids().len(), 3);
        assert_eq!(nodes[1].dataset_ids()[0], "testdata_shapes");
    }

    #[test]
    fn an_empty_registry_is_an_empty_tree_not_an_empty_collection() {
        assert!(group_by_collection(Vec::new()).is_empty());
    }
}
