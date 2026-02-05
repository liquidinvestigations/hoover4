CREATE TABLE IF NOT EXISTS vfs_directories
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset that owns the directory tree',
    container_hash String COMMENT 'Archive/email container hash if nested, references archives.archive_hash',
    path String COMMENT 'Directory path within the logical VFS',
    user_id String COMMENT 'Creator or last modifier user id'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, container_hash, path)
COMMENT 'Virtual file system: files and directories. Directories shown in the directory tree viewer.';
