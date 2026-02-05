CREATE TABLE IF NOT EXISTS blob_values
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset owner, references dataset.collection_dataset',
    blob_hash String COMMENT 'Primary content hash matching blobs.blob_hash',
    blob_length UInt64 COMMENT 'Length of the blob in bytes',
    blob_value String COMMENT 'Raw blob bytes'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, blob_hash)
COMMENT 'Blob content storage: dataset + hash to raw value mapping.';
