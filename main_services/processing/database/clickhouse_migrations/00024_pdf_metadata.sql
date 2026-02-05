CREATE TABLE IF NOT EXISTS pdf_metadata
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, joins to artifacts via hash',
    hash String COMMENT 'Hash of the source PDF',
    pdf_metadata_json String COMMENT 'Raw qpdf metadata JSON as string',
    processed_at DateTime COMMENT 'ISO timestamp when qpdf processed this item'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, hash)
COMMENT 'QPDF metadata captured during processing.';
