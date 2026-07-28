CREATE TABLE IF NOT EXISTS tika_metadata
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, joins to artifacts via hash',
    hash String COMMENT 'Hash of the source artifact',
    tika_metadata_json String COMMENT 'Raw Tika metadata JSON as string',
    processed_at DateTime COMMENT 'ISO timestamp when Tika processed this item'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, hash)
COMMENT 'Apache Tika metadata captured during processing.';
