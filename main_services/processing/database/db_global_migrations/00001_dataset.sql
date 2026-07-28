CREATE TABLE IF NOT EXISTS dataset
(
    collection_dataset LowCardinality(String) COMMENT 'Globally unique dataset id, composed as <collectionname>_<dataset_name>',
    collectionname LowCardinality(String) COMMENT 'FK collections.collectionname - fixed at creation, never changes',
    dataset_name String COMMENT 'Short dataset name within the collection (slug)',
    dataset_display_name String COMMENT 'Human-readable dataset name',
    dataset_type String COMMENT 'Dataset type (disk, s3, webdav, etc.)',
    dataset_path String COMMENT 'Path to the dataset on the filesystem or in the cloud - points to root directory',
    dataset_access_json Nullable(String) COMMENT 'JSON Access information for the dataset (e.g. credentials, API keys)',
    user_id String COMMENT 'Owner/creator user id',
    date_created DateTime COMMENT 'ISO datetime when dataset was created',
    date_modified DateTime COMMENT 'ISO datetime when dataset was last modified',
    is_deleted UInt8 DEFAULT 0 COMMENT 'Soft-delete tombstone'
)
ENGINE = ReplacingMergeTree(date_modified, is_deleted)
ORDER BY (collection_dataset)
COMMENT 'Dataset registry. One row per dataset. collectionname is immutable and selects the collection database.';
