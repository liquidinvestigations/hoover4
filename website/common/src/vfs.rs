//! Shared types for browsing the virtual file system.

use serde::{Deserialize, Serialize};

/// Identifies a folder or file location inside the VFS.
///
/// `path` is an absolute path within the logical VFS (root is `"/"`).
/// `container_hash` identifies the archive/email container that owns the
/// path (empty string means top-level VFS, no container).
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct PathDescriptor {
    pub container_hash: String,
    pub path: String,
}

impl PathDescriptor {
    pub fn root() -> Self {
        Self {
            container_hash: String::new(),
            path: "/".to_string(),
        }
    }

    /// Returns a descriptor for the parent folder, keeping the container.
    /// The root folder's parent is itself.
    pub fn parent(&self) -> Self {
        let trimmed = self.path.trim_end_matches('/');
        let parent_path = if trimmed.is_empty() {
            "/".to_string()
        } else {
            match trimmed.rfind('/') {
                Some(0) | None => "/".to_string(),
                Some(idx) => trimmed[..idx].to_string(),
            }
        };
        Self {
            container_hash: self.container_hash.clone(),
            path: parent_path,
        }
    }
}

impl Default for PathDescriptor {
    fn default() -> Self {
        Self::root()
    }
}

impl std::fmt::Display for PathDescriptor {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        if self.container_hash.is_empty() {
            write!(f, "{}", self.path)
        } else {
            write!(f, "[{}]{}", self.container_hash, self.path)
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct VfsDirectoryEntry {
    pub name: String,
    pub path: PathDescriptor,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct VfsFileEntry {
    pub name: String,
    pub path: PathDescriptor,
    pub hash: String,
    pub file_size_bytes: u64,
    pub is_container: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct VfsListing {
    pub collection_dataset: String,
    pub path: PathDescriptor,
    pub directories: Vec<VfsDirectoryEntry>,
    pub files: Vec<VfsFileEntry>,
}

/// The unit separator that scopes a VFS node key by dataset and container.
///
/// `node_key := "{collection_dataset}\x1f{container_hash}\x1f{path}"`. It cannot occur
/// in a dataset id or in a path the ingest accepts, which is what makes the key
/// unambiguous — the bare path `/data` is the same string in every dataset and inside
/// every archive. The Python side builds the same key in
/// `tasks/P6_index_data/vfs_nodes.py`.
pub const NODE_KEY_SEPARATOR: char = '\u{1f}';

/// What a node is. The wire form is an integer because Manticore has no enum type.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum VfsNodeKind {
    #[default]
    Dir,
    File,
    /// A file that is also a folder: an archive or an email with attachments.
    Container,
}

impl VfsNodeKind {
    pub fn from_int(value: i64) -> Self {
        match value {
            1 => Self::File,
            2 => Self::Container,
            _ => Self::Dir,
        }
    }
    pub fn is_folder_like(&self) -> bool {
        matches!(self, Self::Dir | Self::Container)
    }
}

/// One node of the materialised tree, as the structure index stores it.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct VfsTreeNode {
    pub collection_dataset: String,
    pub node_key: String,
    pub parent_key: String,
    pub container_hash: String,
    pub path: String,
    pub name: String,
    pub kind: VfsNodeKind,
    pub file_hash: String,
    pub file_size_bytes: i64,
    pub depth: i64,
}

impl VfsTreeNode {
    /// The label to show. The root of a container has an empty basename, so it borrows
    /// the container's own name at render time; here it degrades to `/`.
    pub fn display_name(&self) -> &str {
        if self.name.is_empty() { "/" } else { &self.name }
    }

    /// Where clicking this node navigates to in the storage browser.
    pub fn descriptor(&self) -> PathDescriptor {
        match self.kind {
            // Entering a container means switching to ITS container hash at its root.
            VfsNodeKind::Container => PathDescriptor {
                container_hash: self.file_hash.clone(),
                path: "/".to_string(),
            },
            _ => PathDescriptor {
                container_hash: self.container_hash.clone(),
                path: self.path.clone(),
            },
        }
    }
}

/// One page of a node's children, with the "there are more" flag the tree needs to
/// render its "N more…" row rather than silently truncating.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct VfsTreeChildren {
    pub parent_key: String,
    pub nodes: Vec<VfsTreeNode>,
    pub total: u64,
}

/// One place a file hash appears, with the chain that leads to it.
///
/// A hash is content, not a location: the same bytes can sit at any number of paths, in
/// any number of containers. `chain` is the resolved ancestry (root first, the file node
/// last) so the reader gets a breadcrumb rather than a bare string; it is empty when the
/// structure index does not know the node, and `path` is then all there is to show.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct VfsFileLocation {
    pub collection_dataset: String,
    pub container_hash: String,
    pub path: String,
    pub chain: Vec<VfsTreeNode>,
}

impl VfsFileLocation {
    /// The folder that holds this file — where the storage browser opens to show it.
    ///
    /// From the chain's second-to-last node when there is one, because that hop already
    /// knows whether the parent is a plain folder or a container the browser has to step
    /// into. Without a chain it is the file's own descriptor walked up one level.
    pub fn parent_descriptor(&self) -> PathDescriptor {
        if self.chain.len() >= 2 {
            return self.chain[self.chain.len() - 2].descriptor();
        }
        PathDescriptor {
            container_hash: self.container_hash.clone(),
            path: self.path.clone(),
        }
        .parent()
    }

    /// The basename, for the last crumb.
    pub fn file_name(&self) -> &str {
        match self.chain.last() {
            Some(node) if !node.name.is_empty() => &node.name,
            _ => self
                .path
                .rsplit('/')
                .next()
                .filter(|name| !name.is_empty())
                .unwrap_or(&self.path),
        }
    }
}

/// Every location of one file hash inside one dataset, capped.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct VfsFileLocations {
    pub locations: Vec<VfsFileLocation>,
    /// Locations the hash really has. Larger than `locations.len()` when the cap bit.
    pub total: u64,
}

/// Build a node key without needing the indexer. Kept next to the separator so the two
/// cannot drift.
pub fn make_node_key(collection_dataset: &str, container_hash: &str, path: &str) -> String {
    format!("{collection_dataset}{NODE_KEY_SEPARATOR}{container_hash}{NODE_KEY_SEPARATOR}{path}")
}

/// The per-dataset pseudo-root, which every document's ancestor closure contains.
pub fn dataset_root_key(collection_dataset: &str) -> String {
    make_node_key(collection_dataset, "", "/")
}

/// The dataset a node key belongs to, or `None` when the string is not a node key.
///
/// The dataset is the first field of the key by construction, so a caller holding a
/// selection of keys from several datasets can route each one to its own dataset without
/// carrying a parallel list — which is what the unified tree's picker does.
pub fn dataset_of_node_key(node_key: &str) -> Option<&str> {
    node_key.split(NODE_KEY_SEPARATOR).next().filter(|d| !d.is_empty())
}

/// Whether `node_key` names something inside `collection_dataset`.
///
/// A prefix test on the PATH cannot answer this for the dataset root: its key ends in
/// `/`, and no child key starts with `…//`. It is also blind to containers, whose keys
/// carry a different second field entirely. Scoping by the dataset field answers both.
pub fn node_key_is_in_dataset(node_key: &str, collection_dataset: &str) -> bool {
    dataset_of_node_key(node_key) == Some(collection_dataset)
}

/// A node key as a person reads it: the path, or the dataset id for a dataset root.
///
/// A key is machine text — two unit separators and a container hash — and it reaches the
/// UI whenever a `vfs_node` term id is resolved back, which is how a `file_paths` filter
/// says what it is filtering on. The root's path is `/` and says nothing, so it renders
/// as its dataset instead. The container hash is dropped: a key inside an archive carries
/// the path RELATIVE to the archive, so `/child.txt` is all there is to show without a
/// second lookup for the archive's own path.
///
/// Anything that is not a node key comes back unchanged rather than blank — a stale id
/// or a value from another term field is still better shown than swallowed.
pub fn node_key_display_path(node_key: &str) -> &str {
    let mut fields = node_key.split(NODE_KEY_SEPARATOR);
    match (fields.next(), fields.next(), fields.next()) {
        (Some(dataset), Some(_), Some(path)) if !dataset.is_empty() => {
            if path == "/" { dataset } else { path }
        }
        _ => node_key,
    }
}

/// The last segment of [`node_key_display_path`] — the folder's own name, for the places
/// that have room for a word and not for a path.
pub fn node_key_display_name(node_key: &str) -> &str {
    let path = node_key_display_path(node_key);
    match path.trim_end_matches('/').rsplit('/').next() {
        Some(name) if !name.is_empty() => name,
        _ => path,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn node_keys_are_scoped_by_dataset_and_container() {
        // The whole point: the same path in two datasets, or inside two containers, is
        // three different nodes.
        let a = make_node_key("testdata_testfiles", "", "/data");
        let b = make_node_key("other_emails", "", "/data");
        let c = make_node_key("testdata_testfiles", "abc123", "/data");
        assert_ne!(a, b);
        assert_ne!(a, c);
        assert_eq!(dataset_root_key("testdata_testfiles"), "testdata_testfiles\u{1f}\u{1f}/");
    }

    #[test]
    fn a_key_names_the_dataset_it_belongs_to() {
        let root = dataset_root_key("testdata_zips");
        let folder = make_node_key("testdata_zips", "", "/location-1");
        let in_container = make_node_key("testdata_zips", "ziphash", "/child.txt");
        for key in [&root, &folder, &in_container] {
            assert_eq!(dataset_of_node_key(key), Some("testdata_zips"));
            assert!(node_key_is_in_dataset(key, "testdata_zips"));
        }
        // The path prefix test the tri-state used to rely on says none of these are
        // under the dataset root: the root ends in `/`, and a container key does not
        // share the root's second field at all.
        assert!(!folder.starts_with(&format!("{root}/")));
        assert!(!in_container.starts_with(&root));

        // A dataset whose id is a prefix of another one is a different dataset.
        assert!(!node_key_is_in_dataset(&folder, "testdata_zip"));
        assert_eq!(dataset_of_node_key(""), None);
    }

    #[test]
    fn a_node_key_renders_as_a_path_and_a_name() {
        let folder = make_node_key("testdata_testfiles", "", "/disk-files/enron");
        assert_eq!(node_key_display_path(&folder), "/disk-files/enron");
        assert_eq!(node_key_display_name(&folder), "enron");

        // A dataset root's path is `/`, which names nothing — the dataset does.
        let root = dataset_root_key("other_emails");
        assert_eq!(node_key_display_path(&root), "other_emails");
        assert_eq!(node_key_display_name(&root), "other_emails");

        // Inside a container the path is relative to it, and that is what shows.
        let inside = make_node_key("testdata_zips", "ziphash", "/child.txt");
        assert_eq!(node_key_display_path(&inside), "/child.txt");
        assert_eq!(node_key_display_name(&inside), "child.txt");

        // A trailing slash is a folder, not an empty name.
        let trailing = make_node_key("testdata_shapes", "", "/a/b/");
        assert_eq!(node_key_display_name(&trailing), "b");

        // Not a node key at all: shown as it stands rather than blanked.
        assert_eq!(node_key_display_path("application/pdf"), "application/pdf");
        assert_eq!(node_key_display_name("application/pdf"), "pdf");
        assert_eq!(node_key_display_path(""), "");
        assert_eq!(node_key_display_name(""), "");
    }

    #[test]
    fn container_nodes_navigate_into_themselves() {
        let container = VfsTreeNode {
            container_hash: "outer".to_string(),
            path: "/inner.zip".to_string(),
            kind: VfsNodeKind::Container,
            file_hash: "innerhash".to_string(),
            ..Default::default()
        };
        assert_eq!(
            container.descriptor(),
            PathDescriptor { container_hash: "innerhash".to_string(), path: "/".to_string() }
        );
        let plain = VfsTreeNode { kind: VfsNodeKind::File, ..container.clone() };
        assert_eq!(
            plain.descriptor(),
            PathDescriptor { container_hash: "outer".to_string(), path: "/inner.zip".to_string() }
        );
    }

    #[test]
    fn a_location_without_a_chain_still_names_its_file_and_folder() {
        // The fallback path: the structure index has not caught up (or the walk failed),
        // and the raw `vfs_files` row is all there is.
        let location = VfsFileLocation {
            collection_dataset: "testdata_zips".to_string(),
            container_hash: "ziphash".to_string(),
            path: "/inner/child.txt".to_string(),
            chain: Vec::new(),
        };
        assert_eq!(location.file_name(), "child.txt");
        assert_eq!(
            location.parent_descriptor(),
            PathDescriptor { container_hash: "ziphash".to_string(), path: "/inner".to_string() }
        );
    }

    #[test]
    fn a_location_inside_a_container_points_at_the_containers_root() {
        // The parent hop is the archive itself, and the folder that holds the file is the
        // archive's own root — the descriptor the browser needs, not the archive's path.
        let zip = VfsTreeNode {
            container_hash: String::new(),
            path: "/location-1/parent.zip".to_string(),
            name: "parent.zip".to_string(),
            kind: VfsNodeKind::Container,
            file_hash: "ziphash".to_string(),
            ..Default::default()
        };
        let child = VfsTreeNode {
            container_hash: "ziphash".to_string(),
            path: "/child.txt".to_string(),
            name: "child.txt".to_string(),
            kind: VfsNodeKind::File,
            file_hash: "childhash".to_string(),
            ..Default::default()
        };
        let location = VfsFileLocation {
            collection_dataset: "testdata_zips".to_string(),
            container_hash: "ziphash".to_string(),
            path: "/child.txt".to_string(),
            chain: vec![VfsTreeNode::default(), zip, child],
        };
        assert_eq!(location.file_name(), "child.txt");
        assert_eq!(
            location.parent_descriptor(),
            PathDescriptor { container_hash: "ziphash".to_string(), path: "/".to_string() }
        );
    }

    #[test]
    fn kind_from_int_defaults_to_dir() {
        assert_eq!(VfsNodeKind::from_int(0), VfsNodeKind::Dir);
        assert_eq!(VfsNodeKind::from_int(1), VfsNodeKind::File);
        assert_eq!(VfsNodeKind::from_int(2), VfsNodeKind::Container);
        assert_eq!(VfsNodeKind::from_int(99), VfsNodeKind::Dir);
    }
}
