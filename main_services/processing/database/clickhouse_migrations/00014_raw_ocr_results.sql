CREATE TABLE IF NOT EXISTS raw_ocr_results
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, joins to image.image_hash',
    image_hash String COMMENT 'Target image hash for OCR',
    run_time_ms UInt32 COMMENT 'OCR run time in milliseconds',
    result_hash String COMMENT 'Hash of raw OCR result stored in blob storage',
    raw_json String COMMENT 'Raw OCR result JSON string'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, image_hash)
COMMENT 'Raw OCR runs on images with link to results. Raw OCR outputs prior to interpretation.';
