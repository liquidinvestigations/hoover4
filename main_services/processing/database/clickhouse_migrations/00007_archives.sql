CREATE TABLE IF NOT EXISTS archives
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, relates to vfs_files and archive_children',
    archive_hash String COMMENT 'Hash of the archive container (zip/rar/etc.)',
    archive_type String COMMENT 'Space-separated list of archive MIME types (zip, rar, 7z, etc.)'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, archive_hash)
COMMENT 'Archive tracking and extracted children. Archive containers detected during ingestion.';
