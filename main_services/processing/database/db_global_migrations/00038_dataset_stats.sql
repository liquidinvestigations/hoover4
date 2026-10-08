-- Cached statistics and processing state for each dataset.
--
-- The storage landing pages, the admin collection list and the admin Datasets section
-- read this table instead of scanning each collection database per request.
-- database/dataset_stats.py writes it when an operation is admitted, when an operation
-- reaches a terminal state, and from the ETA collector pass while a collection has a
-- live operation. Readers join the dataset registry, so a deleted dataset has no
-- visible row.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS dataset_stats
(
    collectionname LowCardinality(String) COMMENT 'Collection of the dataset',
    collection_dataset String COMMENT 'Dataset identity, dataset.collection_dataset',
    document_count UInt64 COMMENT 'Distinct blob hashes, extracted files included',
    total_size_bytes UInt64 COMMENT 'One size for each distinct blob hash, summed',
    indexed_count UInt64 COMMENT 'Distinct file hashes in index_state',
    error_count UInt64 COMMENT 'Rows in processing_errors FINAL',
    state LowCardinality(String) COMMENT 'processing while a live operation holds the dataset, done otherwise',
    computed_at DateTime64(3) COMMENT 'When the row was computed, UTC, and the version column'
)
ENGINE = ReplacingMergeTree(computed_at)
ORDER BY (collectionname, collection_dataset)
COMMENT 'Newest statistics and processing state of each dataset. Read with FINAL.';
