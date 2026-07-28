CREATE TABLE IF NOT EXISTS vfs_files
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset that owns the file, joins to unique_uploads and file_types',
    container_hash String COMMENT 'Archive/email container hash if nested, references archives.archive_hash',
    path String COMMENT 'File path within the logical VFS (display + navigation)',
    hash String COMMENT 'Content hash for the file, references unique_uploads.hash',
    user_id String COMMENT 'Uploader or last modifier user id',
    file_size_bytes UInt64 COMMENT 'File size in bytes'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, path, hash)
COMMENT 'Virtual file system: files and directories. Logical VFS files (includes extracted files from archives/emails).';
