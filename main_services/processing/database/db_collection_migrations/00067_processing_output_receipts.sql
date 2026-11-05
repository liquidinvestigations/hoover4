CREATE TABLE IF NOT EXISTS processing_output_receipts
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset of the output',
    file_hash String COMMENT 'Source content hash',
    output_kind LowCardinality(String) COMMENT 'Published output contract',
    output_identity String COMMENT 'Published output identity',
    fingerprint String COMMENT 'Versioned update contract',
    stage LowCardinality(String) COMMENT 'Completed dependent stage',
    op_id String COMMENT 'Operation that completed the stage',
    receipt_version UInt64 DEFAULT toUInt64(toUnixTimestamp64Micro(now64(6))) COMMENT 'Receipt write version'
)
ENGINE = ReplacingMergeTree(receipt_version)
ORDER BY (collection_dataset, file_hash, output_kind, output_identity, fingerprint, stage)
COMMENT 'Completion receipts for a published output and its dependent stages.'
