CREATE TABLE IF NOT EXISTS collection_datasets
(
    collection_dataset LowCardinality(String) COMMENT 'FK dataset.collection_dataset; sole ORDER BY key so a dataset lives in exactly one collection',
    collectionname LowCardinality(String) COMMENT 'FK collections.collectionname',
    created_at DateTime DEFAULT now(),
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree',
    is_deleted UInt8 DEFAULT 0 COMMENT 'Soft-delete tombstone (= dataset unassigned)'
)
ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (collection_dataset)
COMMENT '1:N collection to dataset assignment. Re-inserting with a new collectionname MOVES the dataset.';
