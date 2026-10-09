-- OCR targets that a stage decided to skip, such as an image under the size floor or an
-- empty input. The row settles the target of its engine and languages, so a later OCR run
-- sends no request for it. A later row of the same key replaces the earlier one.
CREATE TABLE IF NOT EXISTS ocr_skips
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset of the file',
    file_hash String COMMENT 'Content hash of the file',
    stage LowCardinality(String) COMMENT 'image or pdf',
    engine LowCardinality(String) COMMENT 'tesseract or easyocr',
    languages LowCardinality(String) COMMENT 'Language pass, +-joined',
    reason LowCardinality(String) COMMENT 'The skip outcome, such as ocr_skipped_too_small',
    op_id String DEFAULT '' COMMENT 'Operation that wrote the row, empty during ingestion',
    updated_at DateTime64(6) DEFAULT now64(6) COMMENT 'Write time, the ReplacingMergeTree version'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (collection_dataset, file_hash, stage, engine, languages)
COMMENT 'Decided OCR skips. A row settles its OCR target.';

-- The OCR targets that one rerun_ocr operation found open. Progress counts these rows. A
-- settled target gets a second row with done = 1, which replaces the first by updated_at,
-- so a reader takes the FINAL state. An index target can open again when new OCR text
-- needs indexing. since is the version of the language setting that the target was
-- computed from, and an OCR error newer than it settles the target. since_is_precise is
-- 0 when that version was copied from a whole-second time.
CREATE TABLE IF NOT EXISTS ocr_run_targets
(
    op_id String COMMENT 'The rerun_ocr operation',
    collection_dataset LowCardinality(String) COMMENT 'Dataset of the file',
    plan_hash String COMMENT 'Plan that holds the file',
    file_hash String COMMENT 'Content hash of the file',
    stage LowCardinality(String) COMMENT 'image, pdf or index',
    engine LowCardinality(String) COMMENT 'tesseract or easyocr, empty for index',
    languages LowCardinality(String) COMMENT 'Language pass, empty for index',
    since DateTime64(6) COMMENT 'Version of the language setting, the epoch when none exists',
    since_is_precise UInt8 DEFAULT 1 COMMENT '0 for a version copied from a whole-second time',
    done UInt8 DEFAULT 0 COMMENT '1 when the target settled during the operation',
    updated_at DateTime64(6) DEFAULT now64(6) COMMENT 'Write time, the ReplacingMergeTree version'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (op_id, collection_dataset, file_hash, stage, engine, languages)
TTL toDateTime(updated_at) + INTERVAL 180 DAY
COMMENT 'Open OCR targets of each rerun_ocr operation and whether each one settled.';

-- One receipt for each OCR text segment that a successful text-page writer read and
-- indexed, with the text version it read. An index target is complete only when every
-- current OCR segment of the file has a receipt of its current version. A later receipt
-- of the same segment replaces the earlier one by receipt_version.
CREATE TABLE IF NOT EXISTS ocr_indexed_text
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset of the file',
    file_hash String COMMENT 'Content hash of the file',
    extracted_by String COMMENT 'OCR variant of the segment',
    page_id UInt32 COMMENT 'Segment of the variant, 1-based',
    text_version UInt64 COMMENT 'text_content.version that the writer read, in nanoseconds',
    receipt_version UInt64 DEFAULT toUInt64(toUnixTimestamp64Micro(now64(6))) COMMENT 'Write time in microseconds, the ReplacingMergeTree version'
)
ENGINE = ReplacingMergeTree(receipt_version)
ORDER BY (collection_dataset, file_hash, extracted_by, page_id)
COMMENT 'Committed index receipts of exact OCR segment versions.';

-- The readiness sentinel. The website reports a collection ready once this table exists.
CREATE TABLE IF NOT EXISTS ocr_run_targets_ready (ok UInt8) ENGINE = TinyLog
