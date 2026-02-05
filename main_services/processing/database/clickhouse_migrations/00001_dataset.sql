CREATE TABLE IF NOT EXISTS dataset
(
    collection_dataset LowCardinality(String) COMMENT 'Logical dataset identifier, referenced by every table',
    dataset_name String COMMENT 'Human-readable dataset name',
    dataset_type String COMMENT 'Dataset type (disk, s3, webdav, etc.)',
    dataset_path String COMMENT 'Path to the dataset on the filesystem or in the cloud - points to root directory',
    dataset_access_json Nullable(String) COMMENT 'JSON Access information for the dataset (e.g. credentials, API keys)',
    user_id String COMMENT 'Owner/creator user id, referenced by VFS and labels',
    date_created DateTime COMMENT 'ISO datetime when dataset was created',
    date_modified DateTime COMMENT 'ISO datetime when dataset was last modified'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset)
COMMENT 'Datasets available for ingestion and search, parent for all tables.'
