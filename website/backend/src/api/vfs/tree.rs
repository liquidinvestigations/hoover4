//! Tree navigation and in-folder search over the `<collectionname>_vfs` structure index.
//!
//! Why these do not read `vfs_files` directly
//! ------------------------------------------
//! The old listing walks `vfs_directories`/`vfs_files` with a `startsWith(path, prefix)`
//! predicate per level. That works for "show me this folder" and cannot answer the two
//! questions this module exists for: "what is under this node INCLUDING through the
//! containers below it" and "which names under this node match `*report*`". Both are
//! one predicate against the materialised tree — `ancestor_keys` for the first, an infix
//! `MATCH` on `name` for the second.
//!
//! Why they are uncached
//! ---------------------
//! Every query here goes through `manticore_search_sql_uncached`. The tree changes while
//! ingestion runs, watching a folder fill up is the normal case, and a stale tree is
//! worse than a slow one. These queries are cheap: one small attribute table, no text.

use common::current_user::CurrentUser;
use common::vfs::{VfsNodeKind, VfsTreeChildren, VfsTreeNode};
use serde::{Deserialize, Serialize};

use crate::api::admin::collections::collectionname_valid;
use crate::api::search::search_sql::sql_options_clause;
use crate::auth::permissions;
use crate::db_utils::clickhouse_utils;
use crate::db_utils::manticore_match::quoted_manticore_string;
use crate::db_utils::manticore_utils::manticore_search_sql_uncached;

/// Children returned per expansion before the tree shows a "N more…" row. A folder with
/// 40 000 entries is a real thing in these corpora (`many-children`), and rendering all
/// of them freezes the browser long before it helps anyone.
pub const MAX_CHILDREN_PER_NODE: u64 = 500;

/// Ancestors walked before `vfs_tree_path_to` gives up. The tree can contain cycles
/// (`eml-7-recursive` is an email containing itself), so this is a termination
/// condition, not a tuning knob.
pub const MAX_PATH_DEPTH: usize = 64;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
struct NodeRow {
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
    Ok(format!("{collectionname}_vfs"))
}

/// One page of a node's immediate children, folders first then files, each group by name.
///
/// `node_key` is the full `{dataset}\x1f{container}\x1f{path}` key. It is bound as a
/// quoted string rather than reconstructed here so the caller cannot end up with a key
/// the indexer never wrote.
pub async fn vfs_tree_children(
    user: &CurrentUser,
    collection_dataset: String,
    node_key: String,
    limit: u64,
    offset: u64,
) -> anyhow::Result<VfsTreeChildren> {
    let table = structure_table(user, &collection_dataset).await?;
    let limit = limit.clamp(1, MAX_CHILDREN_PER_NODE);
    let options_clause = sql_options_clause((limit + offset).max(1000));
    let sql = format!(
        "
        SELECT collection_dataset, node_key, parent_key, container_hash, path, name,
               kind, file_hash, file_size_bytes, depth
        FROM {table}
        WHERE collection_dataset = {}
          AND parent_key = {}
        ORDER BY kind ASC, path ASC
        LIMIT {limit} OFFSET {offset}
        {options_clause}
        ;",
        format_sql_query::QuotedData(&collection_dataset),
        format_sql_query::QuotedData(&node_key),
    );
    let response = manticore_search_sql_uncached::<NodeRow>(sql).await?;
    Ok(VfsTreeChildren {
        parent_key: node_key,
        total: response.hits.total,
        nodes: response.hits.hits.into_iter().map(|h| h._source.into()).collect(),
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
    let table = structure_table(user, &collection_dataset).await?;
    let mut chain: Vec<VfsTreeNode> = Vec::new();
    let mut seen = std::collections::BTreeSet::new();
    let mut cursor = node_key;

    while !cursor.is_empty() && chain.len() < MAX_PATH_DEPTH {
        if !seen.insert(cursor.clone()) {
            tracing::warn!("vfs_tree_path_to: cycle at {cursor:?}; truncating the breadcrumb");
            break;
        }
        let sql = format!(
            "
            SELECT collection_dataset, node_key, parent_key, container_hash, path, name,
                   kind, file_hash, file_size_bytes, depth
            FROM {table}
            WHERE collection_dataset = {} AND node_key = {}
            LIMIT 1
            {}
            ;",
            format_sql_query::QuotedData(&collection_dataset),
            format_sql_query::QuotedData(&cursor),
            sql_options_clause(1),
        );
        let response = manticore_search_sql_uncached::<NodeRow>(sql).await?;
        let Some(hit) = response.hits.hits.into_iter().next() else {
            break;
        };
        let node: VfsTreeNode = hit._source.into();
        cursor = node.parent_key.clone();
        chain.push(node);
    }
    chain.reverse();
    Ok(chain)
}

/// Names matching `pattern` anywhere under `node_key`, folders and files alike.
///
/// "Under" means the full ancestor closure, so a match three archives deep still comes
/// back — that is what makes this different from filtering the current listing. The
/// pattern is wrapped in stars for infix matching (`min_infix_len='3'` on the table) and
/// quoted; Manticore's own query-syntax metacharacters are stripped rather than escaped,
/// because a folder search box is not a place to expose query syntax.
pub async fn vfs_search_in_folder(
    user: &CurrentUser,
    collection_dataset: String,
    node_key: String,
    pattern: String,
    limit: u64,
) -> anyhow::Result<VfsTreeChildren> {
    let table = structure_table(user, &collection_dataset).await?;
    let cleaned = sanitize_folder_search(&pattern);
    if cleaned.is_empty() {
        return Ok(VfsTreeChildren { parent_key: node_key, nodes: Vec::new(), total: 0 });
    }
    let limit = limit.clamp(1, MAX_CHILDREN_PER_NODE);
    let options_clause = sql_options_clause(limit.max(1000));
    let Some(ancestor_id) = node_term_id(&collection_dataset, &node_key).await? else {
        // The node has never been an ancestor of anything, so nothing is under it.
        return Ok(VfsTreeChildren { parent_key: node_key, nodes: Vec::new(), total: 0 });
    };
    let sql = format!(
        "
        SELECT collection_dataset, node_key, parent_key, container_hash, path, name,
               kind, file_hash, file_size_bytes, depth
        FROM {table}
        WHERE collection_dataset = {}
          AND ancestor_keys = {ancestor_id}
          AND MATCH({})
        ORDER BY kind ASC, depth ASC, path ASC
        LIMIT {limit}
        {options_clause}
        ;",
        format_sql_query::QuotedData(&collection_dataset),
        quoted_manticore_string(&format!("*{cleaned}*")),
    );
    let response = manticore_search_sql_uncached::<NodeRow>(sql).await?;
    Ok(VfsTreeChildren {
        parent_key: node_key,
        total: response.hits.total,
        nodes: response.hits.hits.into_iter().map(|h| h._source.into()).collect(),
    })
}

/// The `vfs_node` term id of a node key, looked up rather than recomputed.
///
/// The id is `blake2b(key)` truncated to 63 bits, minted by the Python indexer into
/// `string_term_text_to_id`. Reimplementing that hash here would give two definitions of
/// document identity that can drift silently — the ids would simply stop matching and
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
/// collection row selects every dataset under it — one round trip per key made that a
/// burst of N requests for a single click. One `IN` per dataset instead.
///
/// Keys the dictionary does not know are simply absent from the map, exactly as
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
/// literal string, not "a NOT b". Stars are stripped too — the query already wraps the
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

    #[test]
    fn sanitize_can_empty_the_pattern() {
        // A box holding only operators must search for nothing, not for everything.
        assert_eq!(sanitize_folder_search("***"), "");
        assert_eq!(sanitize_folder_search("   "), "");
        assert_eq!(sanitize_folder_search(""), "");
    }
}
