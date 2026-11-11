//! Tree navigation and in-folder search over the `<collectionname>_vfs` structure index.
//!
//! Why these do not read `vfs_files` directly
//! ------------------------------------------
//! The old listing walks `vfs_directories`/`vfs_files` with a `startsWith(path, prefix)`
//! predicate per level. That works for "show me this folder" and cannot answer the two
//! questions this module exists for: "what is under this node INCLUDING through the
//! containers below it" and "which names under this node match `*report*`". Both are
//! one predicate against the materialised tree: `ancestor_keys` for the first, an infix
//! `MATCH` on `name` for the second.
//!
//! Why they are uncached
//! ---------------------
//! Every query here goes through `manticore_search_sql_uncached`. The tree changes while
//! ingestion runs, watching a folder fill up is the normal case, and a stale tree is
//! worse than a slow one. These queries are cheap: one small attribute table, no text.

use common::current_user::CurrentUser;
use common::vfs::{
    VFS_SEARCH_REACHABLE, VfsDatasetSearch, VfsNodeKind, VfsTreeChildren, VfsTreeNode, VfsTreePath,
};
use serde::{Deserialize, Serialize};

use crate::api::admin::collections::collectionname_valid;
use crate::api::list_datasets::list_permitted_datasets;
use crate::api::search::fanout::{FanoutTarget, fan_out};
use crate::api::search::search_sql::sql_options_clause;
use crate::auth::permissions;
use crate::db_utils::clickhouse_utils;
use crate::db_utils::manticore_match::quoted_manticore_string;
use crate::db_utils::manticore_utils::manticore_search_sql_uncached;

/// The biggest page this module will hand back in one call.
///
/// A PAGE SIZE cap, not a per-node cap: the caller pages with `offset`, so a folder with
/// 40 000 entries is reachable a page at a time. It must stay ABOVE the number the tree
/// asks for (500): set equal, a caller trying to widen its request is clamped back to
/// what it already had, and the "N more…" row can never resolve.
pub const MAX_CHILDREN_PER_PAGE: u64 = 2000;

/// Ancestors walked before `vfs_tree_path_to` gives up. The tree can contain cycles
/// (`eml-7-recursive` is an email containing itself), so this is a termination
/// condition, not a tuning knob.
pub const MAX_PATH_DEPTH: usize = 64;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
struct NodeRow {
    /// SQL aliases the index identity so it remains in the JSON source row.
    #[serde(default, rename = "search_id")]
    id: u64,
    collection_dataset: String,
    node_key: String,
    parent_key: String,
    container_hash: String,
    path: String,
    name: String,
    kind: i64,
    file_hash: String,
    file_size_bytes: i64,
    depth: i64,
    subfolder_count: u32,
}

impl From<NodeRow> for VfsTreeNode {
    fn from(row: NodeRow) -> Self {
        VfsTreeNode {
            collection_dataset: row.collection_dataset,
            node_key: row.node_key,
            parent_key: row.parent_key,
            container_hash: row.container_hash,
            path: row.path,
            name: row.name,
            kind: VfsNodeKind::from_int(row.kind),
            file_hash: row.file_hash,
            file_size_bytes: row.file_size_bytes,
            depth: row.depth,
            subfolder_count: row.subfolder_count,
        }
    }
}

/// The `<collectionname>_vfs` table of the collection that owns a dataset, after
/// checking the caller may read it.
///
/// Returns the validated table name. The collection name is interpolated into SQL, so it
/// is re-validated here even though it comes from the registry rather than from input.
async fn structure_table(user: &CurrentUser, collection_dataset: &str) -> anyhow::Result<String> {
    permissions::assert_can_read(user, collection_dataset).await?;
    let collectionname = clickhouse_utils::resolve_collection(collection_dataset).await?;
    if !collectionname_valid(&collectionname) {
        anyhow::bail!("invalid collection name for dataset {collection_dataset:?}");
    }
    Ok(crate::db_utils::manticore_utils::physical_table(&format!(
        "{collectionname}_vfs"
    )))
}

/// The SQL one page of children resolves to.
///
/// Split out of [`vfs_tree_children`] so the two things that are commonly got wrong here
/// (which rows `folders_only` excludes, and that `total` is counted over the same
/// predicate the page is drawn from) are assertable without a live Manticore.
///
/// `kind != 1` is "not a plain file": `Enum8('dir'=0,'file'=1,'container'=2)`, and a
/// container is folder-like. Excluding by inequality rather than listing `IN (0, 2)`
/// keeps a future kind on the folder side by default, which is the safer default for a
/// tree whose whole job is to show what can be opened.
fn children_sql(
    table: &str,
    collection_dataset: &str,
    node_key: &str,
    limit: u64,
    offset: u64,
    folders_only: bool,
    options_clause: &str,
) -> String {
    let kind_clause = if folders_only { "\n          AND kind != 1" } else { "" };
    format!(
        "
        SELECT collection_dataset, node_key, parent_key, container_hash, path, name,
               kind, file_hash, file_size_bytes, depth, subfolder_count
        FROM {table}
        WHERE collection_dataset = {}
          AND parent_key = {}{kind_clause}
        ORDER BY kind ASC, path ASC
        LIMIT {limit} OFFSET {offset}
        {options_clause}
        ;",
        quoted_manticore_string(collection_dataset),
        quoted_manticore_string(node_key),
    )
}

/// One page of a node's immediate children, folders first then files, each group by name.
///
/// `node_key` is the full `{dataset}\x1f{container}\x1f{path}` key. It is bound as a
/// quoted string rather than reconstructed here so the caller cannot end up with a key
/// the indexer never wrote.
///
/// `folders_only` drops plain files from both the page AND from `total`. The tree skins
/// set it; the file-browser content pane does not, because files belong in the pane. It
/// is one predicate and it fixes three things at once: the "N more…" row stops promising
/// rows the tree will never draw, `ORDER BY kind ASC` stops letting a folder's files fill
/// the first page and starve the containers behind them, and a folder holding nothing but
/// files reports `total = 0` and renders as the leaf it is.
///
/// Paging is by `offset`. The caller appends pages; it must not re-ask with a bigger
/// `limit`, which is what [`MAX_CHILDREN_PER_PAGE`] used to make impossible.
pub async fn vfs_tree_children(
    user: &CurrentUser,
    collection_dataset: String,
    node_key: String,
    limit: u64,
    offset: u64,
    folders_only: bool,
) -> anyhow::Result<VfsTreeChildren> {
    let table = structure_table(user, &collection_dataset).await?;
    let limit = limit.clamp(1, MAX_CHILDREN_PER_PAGE);
    let options_clause = sql_options_clause(crate::api::search::search_sql::QueryTable::Structure, (limit + offset).max(1000));
    let sql = children_sql(
        &table,
        &collection_dataset,
        &node_key,
        limit,
        offset,
        folders_only,
        &options_clause,
    );
    let started = std::time::Instant::now();
    let response = manticore_search_sql_uncached::<NodeRow>(sql).await?;
    Ok(VfsTreeChildren {
        parent_key: node_key,
        total: response.hits.total,
        nodes: response.hits.hits.into_iter().map(|h| h._source.into()).collect(),
        datastore_queries: 1,
        took_ms: started.elapsed().as_millis() as u64,
    })
}

/// One page of a node's immediate children that sort after `after_key`, in the order of
/// [`vfs_tree_children`], and the count of every child of the node.
///
/// A key position stays correct while rows are added before it, where an offset moves.
/// `after_key` must be a child of `node_key`. Another key returns an error, because a
/// page after a node of another folder does not exist. Plain files are included.
pub async fn vfs_tree_children_after(
    user: &CurrentUser,
    collection_dataset: String,
    node_key: String,
    after_key: String,
    limit: u64,
) -> anyhow::Result<VfsTreeChildren> {
    let table = structure_table(user, &collection_dataset).await?;
    let limit = limit.clamp(1, MAX_CHILDREN_PER_PAGE);
    let after_sql = format!(
        "SELECT collection_dataset, node_key, parent_key, container_hash, path, name, kind, file_hash, file_size_bytes, depth, subfolder_count FROM {table} WHERE collection_dataset = {} AND node_key = {} LIMIT 1 {} ;",
        quoted_manticore_string(&collection_dataset),
        quoted_manticore_string(&after_key),
        sql_options_clause(crate::api::search::search_sql::QueryTable::Structure, 1),
    );
    let Some(after) = manticore_search_sql_uncached::<NodeRow>(after_sql).await?.hits.hits.into_iter().next() else {
        return Err(crate::auth::guard::InvalidInput(format!("no node {after_key:?} in this dataset")).into());
    };
    let after = after._source;
    if after.parent_key != node_key {
        return Err(crate::auth::guard::InvalidInput(format!("{after_key:?} is not a child of {node_key:?}")).into());
    }
    let started = std::time::Instant::now();
    let total = manticore_search_sql_uncached::<NodeRow>(children_sql(
        &table, &collection_dataset, &node_key, 1, 0, false, &sql_options_clause(crate::api::search::search_sql::QueryTable::Structure, 1000),
    ))
    .await?
    .hits
    .total;
    // The same order as `children_sql`, `kind` then `path`, continued past one row.
    let sql = format!(
        "
        SELECT collection_dataset, node_key, parent_key, container_hash, path, name,
               kind, file_hash, file_size_bytes, depth, subfolder_count
        FROM {table}
        WHERE collection_dataset = {}
          AND parent_key = {}
          AND (kind > {kind} OR (kind = {kind} AND path > {}))
        ORDER BY kind ASC, path ASC
        LIMIT {limit}
        {}
        ;",
        quoted_manticore_string(&collection_dataset),
        quoted_manticore_string(&node_key),
        quoted_manticore_string(&after.path),
        sql_options_clause(crate::api::search::search_sql::QueryTable::Structure, limit.max(1000)),
        kind = after.kind,
    );
    let response = manticore_search_sql_uncached::<NodeRow>(sql).await?;
    Ok(VfsTreeChildren {
        parent_key: node_key,
        total,
        nodes: response.hits.hits.into_iter().map(|h| h._source.into()).collect(),
        datastore_queries: 3,
        took_ms: started.elapsed().as_millis() as u64,
    })
}

/// The chain of nodes from the dataset root down to `node_key`, root first.
///
/// Walks `parent_key` one hop at a time rather than reading `ancestor_keys`, because the
/// breadcrumb needs the ORDER and the closure is a set. The visited set is not optional:
/// `parent_key` can form a cycle when an email contains itself.
pub async fn vfs_tree_path_to(
    user: &CurrentUser,
    collection_dataset: String,
    node_key: String,
) -> anyhow::Result<Vec<VfsTreeNode>> {
    Ok(vfs_tree_path_with_stats(user, collection_dataset, node_key).await?.nodes)
}

/// The ancestor walk plus how many structure-index queries it issued.
///
/// One hop is one query. A browser request count cannot stand in for this figure.
pub async fn vfs_tree_path_with_stats(
    user: &CurrentUser,
    collection_dataset: String,
    node_key: String,
) -> anyhow::Result<VfsTreePath> {
    let table = structure_table(user, &collection_dataset).await?;
    let started = std::time::Instant::now();
    let mut chain: Vec<VfsTreeNode> = Vec::new();
    let mut seen = std::collections::BTreeSet::new();
    let mut cursor = node_key;
    let mut datastore_queries = 0;

    while !cursor.is_empty() && chain.len() < MAX_PATH_DEPTH {
        if !seen.insert(cursor.clone()) {
            tracing::warn!("vfs_tree_path_to: cycle at {cursor:?}; truncating the breadcrumb");
            break;
        }
        let sql = format!(
            "
            SELECT collection_dataset, node_key, parent_key, container_hash, path, name,
                   kind, file_hash, file_size_bytes, depth, subfolder_count
            FROM {table}
            WHERE collection_dataset = {} AND node_key = {}
            LIMIT 1
            {}
            ;",
            quoted_manticore_string(&collection_dataset),
            quoted_manticore_string(&cursor),
            sql_options_clause(crate::api::search::search_sql::QueryTable::Structure, 1),
        );
        datastore_queries += 1;
        let response = manticore_search_sql_uncached::<NodeRow>(sql).await?;
        let Some(hit) = response.hits.hits.into_iter().next() else {
            break;
        };
        let node: VfsTreeNode = hit._source.into();
        cursor = node.parent_key.clone();
        chain.push(node);
    }
    chain.reverse();
    Ok(VfsTreePath {
        nodes: chain,
        datastore_queries,
        took_ms: started.elapsed().as_millis() as u64,
    })
}

/// Resolve an archive or email container hash to the materialised row that enters it.
///
/// The root descriptor inside a container has no row key of its own. The container row
/// remains the active tree row while its root is open.
pub async fn vfs_tree_container_node(
    user: &CurrentUser,
    collection_dataset: String,
    container_hash: String,
) -> anyhow::Result<Option<VfsTreeNode>> {
    let table = structure_table(user, &collection_dataset).await?;
    let sql = format!(
        "SELECT collection_dataset, node_key, parent_key, container_hash, path, name, kind, file_hash, file_size_bytes, depth, subfolder_count FROM {table} WHERE collection_dataset = {} AND file_hash = {} AND kind = 2 ORDER BY container_hash ASC, path ASC LIMIT 1 {} ;",
        quoted_manticore_string(&collection_dataset),
        quoted_manticore_string(&container_hash),
        sql_options_clause(crate::api::search::search_sql::QueryTable::Structure, 1),
    );
    Ok(manticore_search_sql_uncached::<NodeRow>(sql)
        .await?
        .hits
        .hits
        .into_iter()
        .next()
        .map(|hit| hit._source.into()))
}

/// Names matching `pattern` anywhere under `node_key`, folders and files alike.
///
/// "Under" means the full ancestor closure, so a match three archives deep still comes
/// back. That is what makes this different from filtering the current listing. The
/// pattern is wrapped in stars for infix matching (`min_infix_len='3'` on the table) and
/// quoted; Manticore's own query-syntax metacharacters are stripped rather than escaped,
/// because a folder search box is not a place to expose query syntax.
///
/// `offset` skips that many matches in the same order. `offset + limit` stays at or
/// under [`MAX_CHILDREN_PER_PAGE`], the deepest match this function returns.
pub async fn vfs_search_in_folder(
    user: &CurrentUser,
    collection_dataset: String,
    node_key: String,
    pattern: String,
    limit: u64,
    offset: u64,
) -> anyhow::Result<VfsTreeChildren> {
    let table = structure_table(user, &collection_dataset).await?;
    let cleaned = sanitize_folder_search(&pattern);
    if cleaned.is_empty() {
        return Ok(VfsTreeChildren {
            parent_key: node_key,
            nodes: Vec::new(),
            total: 0,
            datastore_queries: 0,
            took_ms: 0,
        });
    }
    let offset = offset.min(MAX_CHILDREN_PER_PAGE);
    let limit = limit.clamp(1, MAX_CHILDREN_PER_PAGE).min((MAX_CHILDREN_PER_PAGE - offset).max(1));
    let options_clause = sql_options_clause(crate::api::search::search_sql::QueryTable::Structure, (offset + limit).max(1000));
    let Some(ancestor_id) = node_term_id(&collection_dataset, &node_key).await? else {
        // The node has never been an ancestor of anything, so nothing is under it.
        return Ok(VfsTreeChildren {
            parent_key: node_key,
            nodes: Vec::new(),
            total: 0,
            datastore_queries: 0,
            took_ms: 0,
        });
    };
    let sql = format!(
        "
        SELECT collection_dataset, node_key, parent_key, container_hash, path, name,
               kind, file_hash, file_size_bytes, depth, subfolder_count
        FROM {table}
        WHERE collection_dataset = {}
          AND ancestor_keys = {ancestor_id}
          AND MATCH({})
        ORDER BY kind ASC, depth ASC, path ASC
        LIMIT {limit} OFFSET {offset}
        {options_clause}
        ;",
        quoted_manticore_string(&collection_dataset),
        quoted_manticore_string(&format!("*{cleaned}*")),
    );
    let started = std::time::Instant::now();
    let response = manticore_search_sql_uncached::<NodeRow>(sql).await?;
    Ok(VfsTreeChildren {
        parent_key: node_key,
        total: response.hits.total,
        nodes: response.hits.hits.into_iter().map(|h| h._source.into()).collect(),
        datastore_queries: 1,
        took_ms: started.elapsed().as_millis() as u64,
    })
}

/// The largest page that [`vfs_search_datasets`] returns.
pub const MAX_DATASET_SEARCH_PAGE: u64 = 200;

/// The SQL that one collection runs for [`vfs_search_datasets`].
///
/// Every collection orders its rows by the same five keys that [`dataset_search_order`]
/// uses, and returns its first `fetch` rows. The merge cuts the global window from these rows.
/// The numeric index identity distinguishes case-only paths and paths in different containers.
fn datasets_search_sql(table: &str, datasets: &[String], cleaned: &str, fetch: u64, options_clause: &str) -> String {
    let dataset_list = datasets
        .iter()
        .map(|d| quoted_manticore_string(d))
        .collect::<Vec<_>>()
        .join(", ");
    format!(
        "
        SELECT id AS search_id, collection_dataset, node_key, parent_key, container_hash, path, name,
               kind, file_hash, file_size_bytes, depth, subfolder_count
        FROM {table}
        WHERE collection_dataset IN ({dataset_list})
          AND MATCH({})
        ORDER BY kind ASC, depth ASC, path ASC, collection_dataset ASC, id ASC
        LIMIT {fetch}
        {options_clause}
        ;",
        quoted_manticore_string(&format!("*{cleaned}*")),
    )
}

/// The order of the global merge, the same as the per-collection `ORDER BY`.
///
/// Manticore compares strings with the `libc_ci` collation, which is `strcasecmp`: ASCII
/// letters compare without case and other bytes compare as bytes. The merge compares the
/// same way. The numeric index identity resolves ties within each collection.
fn dataset_search_order(a: &NodeRow, b: &NodeRow) -> std::cmp::Ordering {
    fn ci(value: &str) -> impl Iterator<Item = u8> + '_ {
        value.bytes().map(|byte| byte.to_ascii_lowercase())
    }
    a.kind
        .cmp(&b.kind)
        .then_with(|| a.depth.cmp(&b.depth))
        .then_with(|| ci(&a.path).cmp(ci(&b.path)))
        .then_with(|| ci(&a.collection_dataset).cmp(ci(&b.collection_dataset)))
        .then_with(|| a.id.cmp(&b.id))
        .then_with(|| a.path.cmp(&b.path))
        .then_with(|| a.collection_dataset.cmp(&b.collection_dataset))
        .then_with(|| a.node_key.cmp(&b.node_key))
}

/// Merge the sorted prefixes of every collection and cut one global window.
fn merge_dataset_search(sources: Vec<Vec<NodeRow>>, offset: u64, limit: u64) -> Vec<NodeRow> {
    let mut rows: Vec<NodeRow> = sources.into_iter().flatten().collect();
    rows.sort_by(dataset_search_order);
    rows.into_iter().skip(offset as usize).take(limit as usize).collect()
}

/// Names that match `pattern` in every dataset that the caller can read, or in the
/// readable datasets of one collection.
///
/// The readable datasets are resolved here for every request. Each collection is one
/// fan-out target, so the search shares the process-wide query gate, the retries and the
/// rule that a failed target fails the whole request. Every collection returns its first
/// `offset + limit` matches in one order, and the merge cuts the global window from them.
/// A window after [`VFS_SEARCH_REACHABLE`] matches is empty, and `total` still counts
/// every match. The pattern is cleaned and wrapped in stars as in
/// [`vfs_search_in_folder`]: a term needs three characters for the infix index.
///
/// A named collection with no readable dataset is an error, as on the collection page.
pub async fn vfs_search_datasets(
    user: &CurrentUser,
    collection: Option<String>,
    pattern: String,
    limit: u64,
    offset: u64,
) -> anyhow::Result<VfsDatasetSearch> {
    let limit = limit.clamp(1, MAX_DATASET_SEARCH_PAGE);
    let cleaned = sanitize_folder_search(&pattern);
    let mut datasets = list_permitted_datasets(user).await?;
    if let Some(name) = collection.as_deref() {
        datasets.retain(|d| d.collectionname == name);
        if datasets.is_empty() {
            anyhow::bail!("no readable datasets in collection {name:?}");
        }
    }
    let empty = VfsDatasetSearch { offset, limit, ..Default::default() };
    if cleaned.is_empty() || datasets.is_empty() {
        return Ok(empty);
    }
    let mut by_collection: std::collections::BTreeMap<String, Vec<String>> = std::collections::BTreeMap::new();
    let mut labels = std::collections::BTreeMap::new();
    for dataset in &datasets {
        if !collectionname_valid(&dataset.collectionname) {
            continue;
        }
        labels.insert(dataset.collection_dataset.clone(), dataset.label().to_string());
        by_collection
            .entry(dataset.collectionname.clone())
            .or_default()
            .push(dataset.collection_dataset.clone());
    }
    // At least one row, so a window after the reachable range still reads the totals.
    let fetch = (offset.min(VFS_SEARCH_REACHABLE) + limit).min(VFS_SEARCH_REACHABLE).max(1);
    let options_clause = sql_options_clause(crate::api::search::search_sql::QueryTable::Structure, fetch.max(1000));
    let targets: Vec<FanoutTarget> = by_collection.keys().map(FanoutTarget::collection).collect();
    let by_collection = &by_collection;
    let cleaned = &cleaned;
    let options_clause = &options_clause;
    let results = fan_out(targets, |target| async move {
        let collectionname = target.collectionname();
        let datasets = by_collection.get(collectionname).cloned().unwrap_or_default();
        let table = crate::db_utils::manticore_utils::physical_table(&format!("{collectionname}_vfs"));
        let sql = datasets_search_sql(&table, &datasets, cleaned, fetch, options_clause);
        manticore_search_sql_uncached::<NodeRow>(sql).await
    })
    .await?;
    let mut total = 0;
    let mut total_exact = true;
    let mut sources = Vec::with_capacity(results.len());
    for (_, response) in results {
        total += response.hits.total;
        total_exact &= response.hits.total_relation.is_empty() || response.hits.total_relation == "eq";
        sources.push(response.hits.hits.into_iter().map(|hit| hit._source).collect());
    }
    let reachable = total.min(VFS_SEARCH_REACHABLE);
    let nodes: Vec<VfsTreeNode> = if offset >= reachable {
        Vec::new()
    } else {
        merge_dataset_search(sources, offset, limit.min(reachable - offset)).into_iter().map(Into::into).collect()
    };
    labels.retain(|dataset, _| nodes.iter().any(|node| &node.collection_dataset == dataset));
    Ok(VfsDatasetSearch { nodes, total, total_exact, reachable, offset, limit, dataset_labels: labels })
}

/// The `vfs_node` term id of a node key, looked up rather than recomputed.
///
/// The id is `blake2b(key)` truncated to 63 bits, minted by the Python indexer into
/// `string_term_text_to_id`. Reimplementing that hash here would give two definitions of
/// document identity that can drift silently. The ids would stop matching and
/// every folder filter would return nothing, with no error anywhere. One round trip
/// against the authoritative table is the cheaper kind of correct.
///
/// `None` means the key was never indexed as a term, which is a legitimate answer: an
/// empty folder is an ancestor of nothing.
pub async fn node_term_id(
    collection_dataset: &str,
    node_key: &str,
) -> anyhow::Result<Option<u64>> {
    let client = clickhouse_utils::get_client_for_dataset(collection_dataset).await?;
    let rows: Vec<u64> = client
        .query(
            "SELECT term_id FROM string_term_text_to_id FINAL
             WHERE collection_dataset = ? AND term_field = 'vfs_node' AND term_value = ?
             LIMIT 1",
        )
        .bind(collection_dataset)
        .bind(node_key)
        .fetch_all()
        .await?;
    Ok(rows.into_iter().next())
}

/// The `vfs_node` term ids of many node keys at once, keyed by node key.
///
/// The picker resolves its WHOLE selection every time a box is ticked, and a tick on a
/// collection row selects every dataset under it, one round trip per key made that a
/// burst of N requests for a single click. One `IN` per dataset instead.
///
/// Keys the dictionary does not know are absent from the map, exactly as
/// [`node_term_id`] returns `None`: an empty folder is an ancestor of nothing.
pub async fn node_term_ids(
    collection_dataset: &str,
    node_keys: &[String],
) -> anyhow::Result<std::collections::HashMap<String, u64>> {
    if node_keys.is_empty() {
        return Ok(std::collections::HashMap::new());
    }
    let client = clickhouse_utils::get_client_for_dataset(collection_dataset).await?;
    let rows: Vec<(String, u64)> = client
        .query(
            "SELECT term_value, term_id FROM string_term_text_to_id FINAL
             WHERE collection_dataset = ? AND term_field = 'vfs_node' AND term_value IN ?",
        )
        .bind(collection_dataset)
        .bind(node_keys)
        .fetch_all()
        .await?;
    Ok(rows.into_iter().collect())
}

/// Strip Manticore query-syntax metacharacters from a folder-search box.
///
/// Not escaping: this box is "type part of a name", and a user who types `a-b` means the
/// literal string, not "a NOT b". Stars are stripped too. The query already wraps the
/// pattern in them, and a user-supplied one produces `**foo**`, which matches nothing.
pub fn sanitize_folder_search(pattern: &str) -> String {
    pattern
        .chars()
        .filter(|c| !"@*()|!\"~/^$=<>\\".contains(*c))
        .collect::<String>()
        .trim()
        .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sanitize_strips_query_syntax_not_content() {
        assert_eq!(sanitize_folder_search("report"), "report");
        assert_eq!(sanitize_folder_search("  annual report  "), "annual report");
        assert_eq!(sanitize_folder_search("a-b_c.pdf"), "a-b_c.pdf");
        // Every one of these is a Manticore operator that would change what the query
        // means rather than what it matches.
        assert_eq!(sanitize_folder_search("@field foo"), "field foo");
        assert_eq!(sanitize_folder_search("a | b"), "a  b");
        assert_eq!(sanitize_folder_search("*wild*"), "wild");
        assert_eq!(sanitize_folder_search("\"exact\""), "exact");
        assert_eq!(sanitize_folder_search("a !b"), "a b");
    }

    fn snapshot(folders_only: bool) -> String {
        children_sql(
            "testcoll_vfs",
            "testdata_zips",
            "testdata_zips\u{1f}\u{1f}/location-1",
            500,
            1000,
            folders_only,
            "OPTION max_matches=1500",
        )
    }

    #[test]
    fn folders_only_excludes_plain_files_and_nothing_else() {
        let sql = snapshot(true);
        assert!(sql.contains("AND kind != 1"), "{sql}");
        // The predicate belongs to the WHERE clause, so `total` is counted over it too.
        // That is what makes the "N more…" row's arithmetic accurate.
        let where_clause = sql.split("ORDER BY").next().unwrap();
        assert!(where_clause.contains("AND kind != 1"), "{sql}");
        assert!(sql.contains("ORDER BY kind ASC, path ASC"), "{sql}");
        assert!(sql.contains("LIMIT 500 OFFSET 1000"), "{sql}");
        assert!(sql.contains("OPTION max_matches=1500"), "{sql}");
    }

    #[test]
    fn without_folders_only_the_page_is_every_child() {
        let sql = snapshot(false);
        assert!(!sql.contains("kind !="), "{sql}");
        // Everything else is identical: the flag adds one predicate and changes nothing
        // about the ordering or the paging.
        assert_eq!(sql, snapshot(true).replace("\n          AND kind != 1", ""));
    }

    #[test]
    fn the_node_key_is_quoted_not_interpolated() {
        // A key carries unit separators and arbitrary path text; it is data. Manticore
        // takes a backslash before a quote, and a doubled quote is a syntax error there.
        let sql = children_sql("t_vfs", "ds", "ds\u{1f}\u{1f}/it's", 10, 0, true, "");
        assert!(sql.contains("'ds\u{1f}\u{1f}/it\\'s'"), "{sql}");
    }

    fn row(collection_dataset: &str, kind: i64, depth: i64, path: &str, container: &str) -> NodeRow {
        NodeRow {
            collection_dataset: collection_dataset.to_string(),
            node_key: common::vfs::make_node_key(collection_dataset, container, path),
            container_hash: container.to_string(),
            path: path.to_string(),
            kind,
            depth,
            ..Default::default()
        }
    }

    #[test]
    fn dataset_search_sql_names_every_dataset_and_the_five_keys() {
        let sql = datasets_search_sql(
            "testdata_vfs",
            &["testdata_zips".to_string(), "testdata_it's".to_string()],
            "csv",
            75,
            "OPTION max_matches=1000",
        );
        assert!(sql.contains("FROM testdata_vfs"), "{sql}");
        assert!(sql.contains("collection_dataset IN ('testdata_zips', 'testdata_it\\'s')"), "{sql}");
        assert!(sql.contains("MATCH('*csv*')"), "{sql}");
        assert!(
            sql.contains("ORDER BY kind ASC, depth ASC, path ASC, collection_dataset ASC, id ASC"),
            "{sql}"
        );
        assert!(sql.contains("LIMIT 75\n"), "{sql}");
        assert!(!sql.contains("OFFSET"), "each collection returns its whole prefix: {sql}");
    }

    #[test]
    fn interleaved_collections_merge_into_one_order_without_gaps() {
        // Two collections whose matches alternate in the global order.
        let a = vec![row("a_one", 1, 1, "/a1.csv", ""), row("a_one", 1, 1, "/c1.csv", ""), row("a_one", 1, 2, "/x/e.csv", "")];
        let b = vec![row("b_two", 1, 1, "/B1.csv", ""), row("b_two", 1, 1, "/d1.csv", ""), row("b_two", 1, 2, "/x/f.csv", "")];
        let all = merge_dataset_search(vec![a.clone(), b.clone()], 0, 100);
        let paths: Vec<&str> = all.iter().map(|r| r.path.as_str()).collect();
        // `B1` sorts between `a1` and `c1`, as `strcasecmp` orders it.
        assert_eq!(paths, ["/a1.csv", "/B1.csv", "/c1.csv", "/d1.csv", "/x/e.csv", "/x/f.csv"]);
        let mut paged = Vec::new();
        for offset in (0..6).step_by(2) {
            paged.extend(merge_dataset_search(vec![a.clone(), b.clone()], offset, 2));
        }
        assert_eq!(paged, all, "pages of two rows give every row once");
    }

    #[test]
    fn equal_paths_in_two_containers_stay_two_rows_in_a_fixed_order() {
        let one = row("ds_zips", 1, 3, "/inner/same.txt", "aaa");
        let two = row("ds_zips", 1, 3, "/inner/same.txt", "bbb");
        let other = row("ds_copy", 1, 3, "/inner/same.txt", "aaa");
        let forward = merge_dataset_search(vec![vec![two.clone(), one.clone()], vec![other.clone()]], 0, 10);
        let backward = merge_dataset_search(vec![vec![other.clone()], vec![one.clone(), two.clone()]], 0, 10);
        assert_eq!(forward.len(), 3);
        assert_eq!(forward, backward, "the order does not depend on the order of the targets");
        assert_eq!(forward[0].collection_dataset, "ds_copy");
        assert_eq!(forward[1].container_hash, "aaa");
        assert_eq!(forward[2].container_hash, "bbb");
    }

    #[test]
    fn case_only_paths_use_index_identity_before_byte_order() {
        let mut lower = row("ds_one", 1, 1, "/a.csv", "");
        lower.id = 1;
        let mut upper = row("ds_one", 1, 1, "/A.csv", "");
        upper.id = 2;
        // A one-row SQL prefix must stay first when the prefix grows.
        let first = merge_dataset_search(vec![vec![lower.clone()]], 0, 1);
        let whole = merge_dataset_search(vec![vec![lower, upper.clone()]], 0, 2);
        assert_eq!(first[0], whole[0]);
        assert_eq!(whole[1], upper);
    }

    #[test]
    fn folders_sort_before_files_and_shallow_before_deep() {
        let file = row("x_y", 1, 1, "/a.csv", "");
        let folder = row("x_y", 0, 2, "/z/csv", "");
        let container = row("x_y", 2, 1, "/csv.zip", "");
        let merged = merge_dataset_search(vec![vec![file, container, folder]], 0, 10);
        let kinds: Vec<i64> = merged.iter().map(|r| r.kind).collect();
        assert_eq!(kinds, [0, 1, 2], "the integer order of `kind`, as in the SQL");
    }

    #[test]
    fn sanitize_can_empty_the_pattern() {
        // A box holding only operators must search for nothing, not for everything.
        assert_eq!(sanitize_folder_search("***"), "");
        assert_eq!(sanitize_folder_search("   "), "");
        assert_eq!(sanitize_folder_search(""), "");
    }

    #[test]
    fn missing_query_stats_deserialise_as_zero() {
        let children: VfsTreeChildren = serde_json::from_str(
            r#"{"parent_key":"p","nodes":[],"total":0}"#,
        )
        .unwrap();
        assert_eq!(children.datastore_queries, 0);
        assert_eq!(children.took_ms, 0);
        let path: VfsTreePath = serde_json::from_str(r#"{"nodes":[]}"#).unwrap();
        assert_eq!(path.datastore_queries, 0);
    }
}
