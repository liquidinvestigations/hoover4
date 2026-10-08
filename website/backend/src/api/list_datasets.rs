//! Endpoint for listing datasets.

use std::collections::HashMap;

use common::current_user::CurrentUser;
use common::storage_tree::{
    CollectionAggregates, CollectionNode, CollectionOverview, DatasetAggregates, DatasetSummary,
};
use common::vfs::dataset_root_key;

use crate::auth::permissions::{self, PermissionSet};
use crate::db_utils::clickhouse_utils::{collection_db_name, get_global_client};
use crate::db_utils::manticore_utils::manticore_search_sql_uncached;

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
            has_folder_children: false,
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
    let mut tree = group_by_collection(list_permitted_datasets(user).await?);
    for collection in &mut tree {
        let table = format!("{}_vfs", collection.collectionname);
        let response = manticore_search_sql_uncached::<FolderPresenceRow>(format!(
            "SELECT collection_dataset FROM {table} WHERE parent_key IN ({}) AND kind != 1 GROUP BY collection_dataset LIMIT {} {} ;",
            collection.datasets.iter().map(|dataset| format_sql_query::QuotedData(&dataset_root_key(&dataset.collection_dataset)).to_string()).collect::<Vec<_>>().join(", "),
            collection.datasets.len(),
            crate::api::search::search_sql::sql_options_clause(crate::api::search::search_sql::QueryTable::Structure, collection.datasets.len() as u64),
        ))
        .await;
        let rows: Vec<FolderPresenceRow> = match response {
            Ok(response) => response.hits.hits.into_iter().map(|hit| hit._source).collect(),
            Err(error) if error.to_string().contains(&format!("unknown local table(s) '{table}'")) => {
                tracing::debug!(collection = %collection.collectionname, "storage index is not available");
                Vec::new()
            }
            Err(error) => return Err(error),
        };
        for dataset in &mut collection.datasets {
            dataset.has_folder_children = rows.iter().any(|row| row.collection_dataset == dataset.collection_dataset);
        }
    }
    Ok(tree)
}

#[derive(Debug, Clone, serde::Deserialize)]
struct FolderPresenceRow {
    collection_dataset: String,
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

/// One collection's datasets with their cached statistics: what the collection landing
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

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct StoredStatsRow {
    collection_dataset: String,
    document_count: u64,
    total_size_bytes: u64,
    indexed_count: u64,
    error_count: u64,
    state: String,
}

/// The cached statistics of every registered dataset, or of one collection's datasets.
///
/// One read of the global `dataset_stats` table, which the pipeline writes during and
/// after processing. The join with the registry hides the rows of deleted datasets. A
/// dataset with no statistics row is absent from the result.
pub async fn stored_dataset_aggregates(
    collectionname: Option<&str>,
) -> anyhow::Result<Vec<DatasetAggregates>> {
    let filter = if collectionname.is_some() { "AND d.collectionname = ?" } else { "" };
    let sql = format!(
        "SELECT s.collection_dataset AS collection_dataset, s.document_count AS document_count, \
         s.total_size_bytes AS total_size_bytes, s.indexed_count AS indexed_count, \
         s.error_count AS error_count, s.state AS state \
         FROM dataset_stats AS s FINAL \
         INNER JOIN (SELECT collection_dataset, collectionname FROM dataset FINAL WHERE is_deleted = 0) AS d \
         ON d.collection_dataset = s.collection_dataset \
         WHERE 1 {filter}"
    );
    let mut query = get_global_client().query(&sql);
    if let Some(name) = collectionname {
        query = query.bind(name);
    }
    let rows: Vec<StoredStatsRow> = query.fetch_all().await?;
    Ok(rows
        .into_iter()
        .map(|row| DatasetAggregates {
            collection_dataset: row.collection_dataset,
            document_count: row.document_count,
            total_size_bytes: row.total_size_bytes,
            indexed_count: row.indexed_count,
            error_count: row.error_count,
            processing: row.state == "processing",
        })
        .collect())
}

async fn dataset_aggregates(collectionname: &str) -> anyhow::Result<Vec<DatasetAggregates>> {
    stored_dataset_aggregates(Some(collectionname)).await
}

/// The summed statistics of each collection the user may read, for the storage root.
pub async fn collections_overview(user: &CurrentUser) -> anyhow::Result<Vec<CollectionAggregates>> {
    let tree = group_by_collection(list_permitted_datasets(user).await?);
    let stored: HashMap<String, DatasetAggregates> = stored_dataset_aggregates(None)
        .await?
        .into_iter()
        .map(|a| (a.collection_dataset.clone(), a))
        .collect();
    Ok(tree
        .iter()
        .map(|collection| {
            let counted: Vec<&DatasetAggregates> = collection
                .datasets
                .iter()
                .filter_map(|d| stored.get(&d.collection_dataset))
                .collect();
            CollectionAggregates::sum(&collection.collectionname, collection.datasets.len() as u64, &counted)
        })
        .collect())
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
            has_folder_children: false,
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
