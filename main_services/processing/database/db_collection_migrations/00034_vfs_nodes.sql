-- The materialised VFS tree: one row per node, where a node is a directory, a plain
-- file, or a container (an archive or an email that has children of its own). Built by
-- P6's `build_vfs_nodes` from vfs_files / vfs_directories / archives / emails, and read
-- by two consumers: the `<collectionname>_vfs` Manticore structure index (the tree
-- sidebar and in-folder search), and the `file_paths` ancestor closure the metadata
-- indexer writes so that filtering on a folder finds everything below it.
--
-- `node_key` is the canonical identity and is what the closure term ids hash:
--
--     node_key := "{collection_dataset}\x1f{container_hash}\x1f{normalised_path}"
--
-- The unit separator cannot occur in a dataset id or in a path we accept (paths with
-- control characters are rejected and logged). `normalised_path` is absolute, `/`-rooted,
-- with no trailing slash except for the root itself. The per-dataset pseudo-root is
-- "{collection_dataset}\x1f\x1f/", and it is what the tree's dataset row filters on.
--
-- Scoping the key by dataset AND container is the whole point: the bare path `/data` is
-- the same string in every dataset and inside every archive, so a term id hashed from
-- the path alone silently unions unrelated corpora.
--
-- `parent_key` crosses container boundaries: the parent of the root inside `a.zip` is
-- the node of `a.zip` itself, in ITS container. That is what makes a `.docx` nested
-- three archives deep reachable from the folder on disk that holds the outermost one.
CREATE TABLE IF NOT EXISTS vfs_nodes
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset that owns the node',
    container_hash String COMMENT 'Archive/email container this node lives inside, empty at the top level',
    path String COMMENT 'Normalised absolute path of the node within its container',
    node_key String COMMENT 'Canonical identity: collection_dataset, container_hash and path joined by the unit separator',
    parent_key String COMMENT 'node_key of the parent, crossing container boundaries. Empty for the dataset pseudo-root',
    kind Enum8('dir' = 0, 'file' = 1, 'container' = 2) COMMENT 'Directory, plain file, or a file that is itself a container',
    file_hash String COMMENT 'Content hash for file and container nodes, empty for directories',
    file_size_bytes Int64 COMMENT 'Size in bytes for file and container nodes, -1 when unknown or not a file',
    depth UInt16 COMMENT 'Distance from the dataset pseudo-root, counting container hops',
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (collection_dataset, node_key)
COMMENT 'Materialised VFS tree, one row per node. Source for the per-collection Manticore structure index and for the file_paths ancestor closure. This is also the readiness sentinel (see READINESS_SENTINEL) and must stay the last table-creating migration.';
