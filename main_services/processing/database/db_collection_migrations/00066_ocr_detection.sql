-- One row for each image, and for each detected PDF page, from the OCR detection stage.
-- The rows describe a file. They select no OCR language and no OCR pass.
-- source_kind is image, original or preview. page_id is 1 for an image.
-- script is empty and language is und when the stage found no decision.
-- A row with has_text = 0 is a decision too, so the update step does not select the file again.
CREATE TABLE IF NOT EXISTS ocr_detection
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset whose processing wrote the row',
    hash String COMMENT 'Content hash of the file',
    source_kind LowCardinality(String) COMMENT 'image, original or preview',
    page_id UInt32 COMMENT '1-based page of a PDF source, 1 for an image',
    detector_version UInt16 COMMENT 'Output version of the stage',
    has_text UInt8 COMMENT '1 when the detector found text',
    box_count UInt32 COMMENT 'Text boxes that the detector kept',
    script LowCardinality(String) COMMENT 'Detected script, or empty',
    language LowCardinality(String) DEFAULT 'und' COMMENT 'Detected language code, or und',
    run_time_ms UInt32 COMMENT 'Service time for the page',
    updated_at DateTime64(6) DEFAULT now64(6) COMMENT 'Write time, UTC'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (collection_dataset, hash, source_kind, page_id)
SETTINGS index_granularity = 1024;
