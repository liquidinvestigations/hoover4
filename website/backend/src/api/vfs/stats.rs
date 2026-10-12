//! The file count and byte count below VFS nodes, read from ClickHouse `vfs_nodes`.
//!
//! The pipeline writes `subtree_file_count` and `subtree_size_bytes` on every node in
//! `build_vfs_nodes` (`main_services/processing/tasks/P6_index_data/vfs_nodes.py`,
//! `compute_subtree_stats`). A read is one multi-get by node key that selects only those
//! columns. A key without values gets them from a read-time fallback:
//!
//! * tier A, for a row that exists and still reads -1 because it was written before the
//!   columns existed: prefix sums over `vfs_nodes`, with `kind` as the container test;
//! * tier B, for a key with no row, because a running batch added the folder after the
//!   last build: prefix sums over `vfs_files`, with the `build_node_rows` container test
//!   (an archive or an email that has members). It does not normalise paths and counts a
//!   path that the build rejects, so its values hold until the next build writes the row.
//!
//! Each tier runs one grouped query for the folder level and one query for each
//! container nesting level, and stops after [`MAX_FALLBACK_LEVELS`]. A result that hit
//! that limit is dropped, and the view shows nothing for that node.
//!
//! The container walk follows the Python cycle rule, and both must give the same numbers:
//! a walk never opens a container whose hash is already open on it, the container that
//! holds the start node starts open, and a container that is not opened still counts as
//! one file.
//!
//! The values are read uncached, the same as the rest of the tree: they change while
//! ingestion runs.

use std::collections::{BTreeMap, HashMap};

use common::current_user::CurrentUser;
use common::vfs::{NODE_KEY_SEPARATOR, SubtreeStats, VfsSubtreeStats, dataset_root_key, node_key_is_in_dataset};

use crate::auth::permissions;
use crate::db_utils::clickhouse_utils::get_client_for_dataset;

/// Container levels a fallback queries before it gives up. The pipeline's
/// `MAX_ANCESTOR_DEPTH` has the same value.
pub const MAX_FALLBACK_LEVELS: usize = 64;

/// The most node keys one request may ask about. A tree page is at most 2000 rows.
pub const MAX_KEYS_PER_REQUEST: usize = 5000;

/// One node to read values for.
#[derive(Debug, Clone, PartialEq)]
pub struct StatsTarget {
    pub node_key: String,
    pub container_hash: String,
    pub path: String,
    /// The file hash when the node is a container, whose members the walk opens.
    pub container_file_hash: Option<String>,
}

impl StatsTarget {
    /// A target from a node key, or `None` when the string is not a key of `collection_dataset`.
    pub fn from_key(collection_dataset: &str, node_key: &str, container_file_hash: &str) -> Option<Self> {
        if !node_key_is_in_dataset(node_key, collection_dataset) {
            return None;
        }
        let mut parts = node_key.splitn(3, NODE_KEY_SEPARATOR);
        let (_, container_hash, path) = (parts.next()?, parts.next()?, parts.next()?);
        Some(Self {
            node_key: node_key.to_string(),
            container_hash: container_hash.to_string(),
            path: path.to_string(),
            container_file_hash: (!container_file_hash.is_empty()).then(|| container_file_hash.to_string()),
        })
    }

    fn is_dataset_root(&self) -> bool {
        self.container_hash.is_empty() && self.path == "/"
    }

    /// The folder that lists this node, as `(container_hash, folder path)`.
    fn folder(&self) -> (String, String) {
        let parent = match self.path.rfind('/') {
            Some(0) | None => "/".to_string(),
            Some(index) => self.path[..index].to_string(),
        };
        (self.container_hash.clone(), parent)
    }

    fn name(&self) -> &str {
        self.path.rsplit('/').next().unwrap_or("")
    }
}

/// One container level: the files directly in it, their stored bytes, and the hashes
/// of the containers among them, one entry for each container node.
#[derive(Debug, Clone, Default, PartialEq)]
pub(crate) struct Level {
    pub files: u64,
    pub bytes: u64,
    pub inner: Vec<String>,
}

/// The member walk over fetched container levels.
#[derive(Debug, Default)]
pub(crate) struct Walker {
    pub levels: HashMap<String, Level>,
    /// Only results that no cycle cut. Such a result does not depend on what was open.
    memo: HashMap<String, u64>,
}

impl Walker {
    pub fn new(levels: HashMap<String, Level>) -> Self {
        Self { levels, memo: HashMap::new() }
    }

    /// Files inside container `hash`, with `open` already open. Returns the count and
    /// whether a cycle cut it.
    fn members(&mut self, hash: &str, open: &mut Vec<String>) -> (u64, bool) {
        if let Some(count) = self.memo.get(hash) {
            return (*count, false);
        }
        let level = self.levels.get(hash).cloned().unwrap_or_default();
        let mut total = level.files;
        let mut cut = false;
        for inner in &level.inner {
            if open.contains(inner) {
                cut = true;
                continue;
            }
            open.push(inner.clone());
            let (count, inner_cut) = self.members(inner, open);
            open.pop();
            total += count;
            cut |= inner_cut;
        }
        if !cut {
            self.memo.insert(hash.to_string(), total);
        }
        (total, cut)
    }

    /// Files inside the container `hash` that lives in container `holder`.
    pub fn container_files(&mut self, holder: &str, hash: &str) -> u64 {
        let mut open: Vec<String> = Vec::new();
        if !holder.is_empty() {
            open.push(holder.to_string());
        }
        if !open.iter().any(|o| o == hash) {
            open.push(hash.to_string());
        }
        self.members(hash, &mut open).0
    }

    /// The members of the containers `inner`, found at a level of container `holder`.
    /// Each container already counts as one file at that level.
    pub fn inner_files(&mut self, holder: &str, inner: &[String]) -> u64 {
        inner
            .iter()
            .filter(|hash| hash.as_str() != holder)
            .map(|hash| self.container_files(holder, hash))
            .sum()
    }
}

/// The values of one folder's children (or of the folder as a whole) from a fallback.
#[derive(Debug, Default)]
pub(crate) struct Fallback {
    pub holder: String,
    pub groups: HashMap<String, Level>,
    pub walker: Walker,
    pub incomplete: bool,
}

impl Fallback {
    /// A child folder, or the folder itself when the fallback is not per child (key "").
    pub fn folder(&mut self, name: &str) -> Option<SubtreeStats> {
        if self.incomplete {
            return None;
        }
        let level = self.groups.get(name).cloned().unwrap_or_default();
        let members = self.walker.inner_files(&self.holder, &level.inner);
        Some(SubtreeStats { file_count: level.files + members, size_bytes: level.bytes })
    }

    /// A child container file.
    pub fn container(&mut self, hash: &str) -> Option<SubtreeStats> {
        if self.incomplete {
            return None;
        }
        let file_count = self.walker.container_files(&self.holder, hash);
        let size_bytes = self.walker.levels.get(hash).map(|level| level.bytes).unwrap_or(0);
        Some(SubtreeStats { file_count, size_bytes })
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
enum Tier {
    /// `vfs_nodes`, for rows that exist and read -1.
    Nodes,
    /// `vfs_files`, for keys with no row.
    Files,
}

/// One grouped level query. `group` is the grouping expression and `filter` the row
/// filter after the dataset. Both are fixed text from this module.
fn level_sql(tier: Tier, group: &str, filter: &str) -> String {
    let (table, is_file, size, hash, is_container) = match tier {
        Tier::Nodes => (
            "vfs_nodes",
            "kind != 'dir'",
            "greatest(file_size_bytes, 0)",
            "file_hash",
            "kind = 'container'",
        ),
        Tier::Files => (
            "vfs_files",
            "1",
            "toInt64(file_size_bytes)",
            "hash",
            "hash IN (SELECT archive_hash FROM archives FINAL WHERE collection_dataset = {cd:String} \
                      UNION ALL SELECT email_hash FROM emails FINAL WHERE collection_dataset = {cd:String}) \
             AND hash IN (SELECT container_hash FROM vfs_files FINAL \
                          WHERE collection_dataset = {cd:String} AND container_hash != '')",
        ),
    };
    format!(
        "SELECT {group} AS g, toUInt64(countIf({is_file})) AS files, \
                toUInt64(greatest(sumIf({size}, {is_file}), 0)) AS bytes, \
                groupArrayIf({hash}, {is_container}) AS inner_hashes \
         FROM {table} FINAL \
         WHERE collection_dataset = {{cd:String}} AND {filter} \
         GROUP BY g"
    )
}

const CHILD_GROUP: &str = "splitByChar('/', substring(path, length({prefix:String}) + 1))[1]";
const FOLDER_FILTER: &str = "container_hash = {ch:String} AND startsWith(path, {prefix:String})";
const MEMBERS_FILTER: &str = "container_hash IN {hashes:Array(String)}";

/// One row of a level query. Bound by column name: `g`, `files`, `bytes`, `inner_hashes`.
#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct LevelRow {
    g: String,
    files: u64,
    bytes: u64,
    inner_hashes: Vec<String>,
}

/// The fallback for the children of folder `path` in container `container_hash`, or for
/// the folder as a whole when `per_child` is false. Returns the result and its query count.
async fn fallback(
    client: &clickhouse::Client,
    tier: Tier,
    collection_dataset: &str,
    container_hash: &str,
    path: &str,
    per_child: bool,
) -> anyhow::Result<(Fallback, u64)> {
    let prefix = if path == "/" { "/".to_string() } else { format!("{path}/") };
    let group = if per_child { CHILD_GROUP } else { "''" };
    let rows: Vec<LevelRow> = client
        .query(&level_sql(tier, group, FOLDER_FILTER))
        .param("cd", collection_dataset)
        .param("ch", container_hash)
        .param("prefix", &prefix)
        .fetch_all()
        .await?;
    let mut queries = 1;
    let groups: HashMap<String, Level> = rows
        .into_iter()
        .map(|row| (row.g, Level { files: row.files, bytes: row.bytes, inner: row.inner_hashes }))
        .collect();

    let mut levels: HashMap<String, Level> = HashMap::new();
    let mut frontier: Vec<String> = groups.values().flat_map(|l| l.inner.iter().cloned()).collect();
    frontier.sort();
    frontier.dedup();
    let mut depth = 0;
    while !frontier.is_empty() && depth < MAX_FALLBACK_LEVELS {
        let rows: Vec<LevelRow> = client
            .query(&level_sql(tier, "container_hash", MEMBERS_FILTER))
            .param("cd", collection_dataset)
            .param("hashes", &frontier)
            .fetch_all()
            .await?;
        queries += 1;
        depth += 1;
        for row in rows {
            levels.insert(row.g, Level { files: row.files, bytes: row.bytes, inner: row.inner_hashes });
        }
        for hash in &frontier {
            levels.entry(hash.clone()).or_default();
        }
        let mut next: Vec<String> = frontier
            .iter()
            .flat_map(|hash| levels[hash].inner.iter().cloned())
            .filter(|hash| !levels.contains_key(hash))
            .collect();
        next.sort();
        next.dedup();
        frontier = next;
    }
    Ok((
        Fallback {
            holder: container_hash.to_string(),
            groups,
            walker: Walker::new(levels),
            incomplete: !frontier.is_empty(),
        },
        queries,
    ))
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct StoredRow {
    node_key: String,
    subtree_file_count: i64,
    subtree_size_bytes: i64,
}

/// The values for `targets`, all in `collection_dataset`. A target without values is
/// absent from the map. Returns the map and the number of queries. The caller has
/// checked that the user may read the dataset.
pub async fn stats_for_targets(
    client: &clickhouse::Client,
    collection_dataset: &str,
    targets: &[StatsTarget],
) -> anyhow::Result<(BTreeMap<String, SubtreeStats>, u64)> {
    let mut out = BTreeMap::new();
    if targets.is_empty() {
        return Ok((out, 0));
    }
    let keys: Vec<&str> = targets.iter().map(|t| t.node_key.as_str()).collect();
    let stored: Vec<StoredRow> = client
        .query(
            "SELECT node_key, subtree_file_count, subtree_size_bytes FROM vfs_nodes FINAL \
             WHERE collection_dataset = {cd:String} AND node_key IN {keys:Array(String)}",
        )
        .param("cd", collection_dataset)
        .param("keys", &keys)
        .fetch_all()
        .await?;
    let mut queries = 1;
    let stored: HashMap<String, StoredRow> =
        stored.into_iter().map(|row| (row.node_key.clone(), row)).collect();

    // Targets without values, by tier and by the folder that lists them.
    let mut pending: BTreeMap<(bool, String, String), Vec<&StatsTarget>> = BTreeMap::new();
    for target in targets {
        match stored.get(&target.node_key) {
            Some(row) if row.subtree_file_count >= 0 && row.subtree_size_bytes >= 0 => {
                out.insert(
                    target.node_key.clone(),
                    SubtreeStats {
                        file_count: row.subtree_file_count as u64,
                        size_bytes: row.subtree_size_bytes as u64,
                    },
                );
            }
            row => {
                let (container_hash, folder) = if target.is_dataset_root() {
                    (String::new(), "/".to_string())
                } else {
                    target.folder()
                };
                pending.entry((row.is_some(), container_hash, folder)).or_default().push(target);
            }
        }
    }

    for ((has_row, container_hash, folder), group) in pending {
        let tier = if has_row { Tier::Nodes } else { Tier::Files };
        let root_only = group.iter().all(|t| t.is_dataset_root());
        let (mut result, count) =
            fallback(client, tier, collection_dataset, &container_hash, &folder, !root_only).await?;
        queries += count;
        if result.incomplete {
            tracing::warn!(
                "subtree fallback for {collection_dataset} {container_hash:?} {folder:?} stopped at \
                 {MAX_FALLBACK_LEVELS} container levels; its values are not shown"
            );
        }
        for target in group {
            let value = if target.is_dataset_root() {
                result.folder("")
            } else if let Some(hash) = &target.container_file_hash {
                result.container(hash)
            } else {
                result.folder(target.name())
            };
            if let Some(value) = value {
                out.insert(target.node_key.clone(), value);
            }
        }
    }
    Ok((out, queries))
}

/// The values for nodes of one dataset, for the file location picker.
///
/// `nodes` are `(node_key, container_file_hash)` pairs, where the hash is empty for a
/// folder. Keys of other datasets are ignored.
pub async fn vfs_subtree_stats(
    user: &CurrentUser,
    collection_dataset: String,
    nodes: Vec<(String, String)>,
) -> anyhow::Result<VfsSubtreeStats> {
    permissions::assert_can_read(user, &collection_dataset).await?;
    if nodes.len() > MAX_KEYS_PER_REQUEST {
        return Err(crate::auth::guard::InvalidInput(format!(
            "at most {MAX_KEYS_PER_REQUEST} nodes per request"
        ))
        .into());
    }
    let started = std::time::Instant::now();
    let targets: Vec<StatsTarget> = nodes
        .iter()
        .filter_map(|(key, hash)| StatsTarget::from_key(&collection_dataset, key, hash))
        .collect();
    let client = get_client_for_dataset(&collection_dataset).await?;
    let (stats, datastore_queries) = stats_for_targets(&client, &collection_dataset, &targets).await?;
    Ok(VfsSubtreeStats { stats, datastore_queries, took_ms: started.elapsed().as_millis() as u64 })
}

/// The values of the dataset roots, keyed by root node key, for the picker's dataset and
/// collection rows. A dataset the user may not read, or whose values fail, is absent.
pub async fn vfs_dataset_subtree_stats(
    user: &CurrentUser,
    datasets: Vec<String>,
) -> anyhow::Result<VfsSubtreeStats> {
    if datasets.len() > MAX_KEYS_PER_REQUEST {
        return Err(crate::auth::guard::InvalidInput(format!(
            "at most {MAX_KEYS_PER_REQUEST} datasets per request"
        ))
        .into());
    }
    let started = std::time::Instant::now();
    let mut result = VfsSubtreeStats::default();
    for collection_dataset in datasets {
        if permissions::assert_can_read(user, &collection_dataset).await.is_err() {
            continue;
        }
        let root = dataset_root_key(&collection_dataset);
        let Some(target) = StatsTarget::from_key(&collection_dataset, &root, "") else {
            continue;
        };
        let read = async {
            let client = get_client_for_dataset(&collection_dataset).await?;
            stats_for_targets(&client, &collection_dataset, &[target]).await
        };
        match read.await {
            Ok((stats, queries)) => {
                result.datastore_queries += queries;
                result.stats.extend(stats);
            }
            Err(error) => {
                tracing::warn!("subtree values for {collection_dataset} failed: {error:#}");
            }
        }
    }
    result.took_ms = started.elapsed().as_millis() as u64;
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// `(container_hash, path, kind, file_hash, size)`, the columns the tier A queries read.
    type Node = (&'static str, &'static str, &'static str, &'static str, u64);

    /// What the tier A queries return for these nodes, without ClickHouse.
    fn fake_fallback(nodes: &[Node], container_hash: &str, folder: &str, per_child: bool) -> Fallback {
        let prefix = if folder == "/" { "/".to_string() } else { format!("{folder}/") };
        let add = |level: &mut Level, node: &Node| {
            if node.2 != "dir" {
                level.files += 1;
                level.bytes += node.4;
            }
            if node.2 == "container" {
                level.inner.push(node.3.to_string());
            }
        };
        let mut groups: HashMap<String, Level> = HashMap::new();
        for node in nodes.iter().filter(|n| n.0 == container_hash && n.1.starts_with(&prefix)) {
            let name = if per_child { node.1[prefix.len()..].split('/').next().unwrap() } else { "" };
            add(groups.entry(name.to_string()).or_default(), node);
        }
        let mut levels: HashMap<String, Level> = HashMap::new();
        for node in nodes.iter().filter(|n| !n.0.is_empty()) {
            add(levels.entry(node.0.to_string()).or_default(), node);
        }
        Fallback { holder: container_hash.to_string(), groups, walker: Walker::new(levels), incomplete: false }
    }

    fn folder(nodes: &[Node], container_hash: &str, path: &str) -> (u64, u64) {
        let value = fake_fallback(nodes, container_hash, path, false).folder("").unwrap();
        (value.file_count, value.size_bytes)
    }

    fn container(nodes: &[Node], holder: &str, hash: &str) -> (u64, u64) {
        let value = fake_fallback(nodes, holder, "/", true).container(hash).unwrap();
        (value.file_count, value.size_bytes)
    }

    // The same four fixtures and values as `tests/unit/test_subtree_stats.py`.

    #[test]
    fn self_containing_email_is_not_opened_twice() {
        let nodes: &[Node] = &[
            ("", "/mail", "dir", "", 0),
            ("", "/mail/e.eml", "container", "E", 100),
            ("E", "/e.eml", "container", "E", 100),
            ("E", "/a.txt", "file", "T", 5),
        ];
        assert_eq!(folder(nodes, "", "/"), (3, 100));
        assert_eq!(folder(nodes, "", "/mail"), (3, 100));
        assert_eq!(container(nodes, "", "E"), (2, 105));
        assert_eq!(container(nodes, "E", "E"), (2, 105));
    }

    #[test]
    fn copy_of_the_holder_in_a_subfolder_is_one_file_there() {
        let nodes: &[Node] = &[
            ("", "/e.eml", "container", "E", 100),
            ("E", "/sub", "dir", "", 0),
            ("E", "/sub/e.eml", "container", "E", 100),
            ("E", "/a.txt", "file", "T", 5),
        ];
        assert_eq!(folder(nodes, "E", "/sub"), (1, 100));
        assert_eq!(container(nodes, "E", "E"), (2, 105));
        assert_eq!(container(nodes, "", "E"), (2, 105));
        assert_eq!(folder(nodes, "", "/"), (3, 100));
    }

    #[test]
    fn two_container_cycle_stops_at_the_open_container() {
        let nodes: &[Node] = &[
            ("", "/a.zip", "container", "A", 50),
            ("A", "/b.zip", "container", "B", 30),
            ("A", "/y.txt", "file", "Y", 3),
            ("B", "/a.zip", "container", "A", 50),
            ("B", "/x.txt", "file", "X", 2),
        ];
        assert_eq!(folder(nodes, "", "/"), (5, 50));
        assert_eq!(container(nodes, "", "A"), (4, 33));
        assert_eq!(container(nodes, "A", "B"), (2, 52));
        assert_eq!(container(nodes, "B", "A"), (2, 33));
    }

    #[test]
    fn container_at_two_paths_counts_under_both() {
        let nodes: &[Node] = &[
            ("", "/p", "dir", "", 0),
            ("", "/q", "dir", "", 0),
            ("", "/p/a.zip", "container", "A", 40),
            ("", "/q/a.zip", "container", "A", 40),
            ("A", "/b1.zip", "container", "B", 10),
            ("A", "/sub", "dir", "", 0),
            ("A", "/sub/b2.zip", "container", "B", 10),
            ("B", "/z.txt", "file", "Z", 1),
        ];
        assert_eq!(folder(nodes, "", "/"), (10, 80));
        assert_eq!(folder(nodes, "", "/p"), (5, 40));
        assert_eq!(container(nodes, "", "A"), (4, 20));
        assert_eq!(folder(nodes, "A", "/sub"), (2, 10));
        assert_eq!(container(nodes, "A", "B"), (1, 1));
    }

    #[test]
    fn per_child_groups_split_on_the_first_segment() {
        let nodes: &[Node] = &[
            ("", "/a", "dir", "", 0),
            ("", "/a/one.txt", "file", "1", 10),
            ("", "/a/b/two.txt", "file", "2", 20),
            ("", "/top.txt", "file", "3", 5),
        ];
        let mut result = fake_fallback(nodes, "", "/", true);
        assert_eq!(result.folder("a"), Some(SubtreeStats { file_count: 2, size_bytes: 30 }));
        assert_eq!(result.folder("missing"), Some(SubtreeStats::default()));
    }

    #[test]
    fn incomplete_fallback_shows_nothing() {
        let mut result = Fallback { incomplete: true, ..Default::default() };
        assert_eq!(result.folder(""), None);
        assert_eq!(result.container("A"), None);
    }

    #[test]
    fn target_parses_its_key_and_folder() {
        let key = format!("ds{NODE_KEY_SEPARATOR}C{NODE_KEY_SEPARATOR}/x/y.zip");
        let target = StatsTarget::from_key("ds", &key, "H").unwrap();
        assert_eq!(target.folder(), ("C".to_string(), "/x".to_string()));
        assert_eq!(target.name(), "y.zip");
        assert_eq!(target.container_file_hash.as_deref(), Some("H"));
        assert!(StatsTarget::from_key("other", &key, "").is_none());
        let root = StatsTarget::from_key("ds", &dataset_root_key("ds"), "").unwrap();
        assert!(root.is_dataset_root());
    }

    #[test]
    fn level_sql_selects_only_fixed_columns() {
        let sql = level_sql(Tier::Files, CHILD_GROUP, FOLDER_FILTER);
        assert!(sql.contains("FROM vfs_files FINAL"));
        assert!(sql.contains("archives FINAL") && sql.contains("emails FINAL"));
        let sql = level_sql(Tier::Nodes, "container_hash", MEMBERS_FILTER);
        assert!(sql.contains("FROM vfs_nodes FINAL"));
        assert!(sql.contains("kind = 'container'"));
    }
}
