DROP TABLE IF EXISTS text_content_new;
CREATE TABLE text_content_new
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, joins to files via file_hash',
    file_hash String COMMENT 'Hash of the source file that yielded this text',
    extracted_by String COMMENT 'Extractor that produced this text (e.g., pdfminer, tika)',
    page_id UInt32 COMMENT '1-based page number for paged formats (PDF, TIFF). For non-paged text, a 1-based ~256KB segment ordinal. Never 0.',
    text String COMMENT 'Text content for a page/part (<1M suggested)' CODEC(ZSTD(3)),
    text_bytes UInt64 DEFAULT 0 COMMENT 'Byte length of text, written at insert',
    version UInt64 COMMENT 'Writer version, see insert_text_pages'
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (collection_dataset, file_hash, extracted_by, page_id)
SETTINGS index_granularity = 1024, index_granularity_bytes = 1048576,
         max_bytes_to_merge_at_max_space_in_pool = 4294967296, merge_max_block_size = 1024;
INSERT INTO text_content_new (collection_dataset, file_hash, extracted_by, page_id, text, text_bytes, version)
    SELECT collection_dataset, file_hash, extracted_by, page_id, text, text_bytes, 0 FROM text_content FINAL;
EXCHANGE TABLES text_content_new AND text_content;
DROP TABLE text_content_new;

DROP TABLE IF EXISTS blob_values_new;
CREATE TABLE blob_values_new
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset owner, references dataset.collection_dataset',
    blob_hash String COMMENT 'Primary content hash matching blobs.blob_hash',
    blob_length UInt64 COMMENT 'Length of the blob in bytes',
    blob_value String COMMENT 'Raw blob bytes'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, blob_hash)
SETTINGS index_granularity = 1024, index_granularity_bytes = 1048576,
         max_bytes_to_merge_at_max_space_in_pool = 4294967296, merge_max_block_size = 512;
INSERT INTO blob_values_new (collection_dataset, blob_hash, blob_length, blob_value)
    SELECT collection_dataset, blob_hash, blob_length, blob_value FROM blob_values FINAL;
EXCHANGE TABLES blob_values_new AND blob_values;
DROP TABLE blob_values_new;

CREATE TABLE IF NOT EXISTS text_storage_ready (ok UInt8) ENGINE = TinyLog;
