CREATE TABLE IF NOT EXISTS video_metadata
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, joins to artifacts via hash',
    hash String COMMENT 'Hash of the source video',
    video_metadata_json String COMMENT 'Raw ffprobe metadata JSON as string',
    processed_at DateTime COMMENT 'ISO timestamp when ffprobe processed this item'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, hash)
COMMENT 'FFprobe metadata captured during video processing.';
