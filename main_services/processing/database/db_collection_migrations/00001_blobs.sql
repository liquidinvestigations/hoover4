CREATE TABLE IF NOT EXISTS blobs
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset owner, references dataset.collection_dataset',
    blob_hash String COMMENT 'Primary content hash (SHA3-256) for the blob',
    blob_size_bytes UInt64 COMMENT 'Size of the blob in bytes',
    md5 String COMMENT 'MD5 hash',
    sha1 String COMMENT 'SHA1 hash',
    sha256 String COMMENT 'SHA-256 hash',
    s3_path String COMMENT 'S3 object path if stored in S3, empty if in ClickHouse',
    stored_in_clickhouse UInt8 COMMENT '1 if blob value is stored in ClickHouse, else 0'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, blob_hash)
COMMENT 'Blob metadata: primary hash, size, auxiliary hashes, and storage location flags.';
