-- The scan stage's watermark, mirroring nlp_processed. The stage left-anti-joins
-- text_content against this table for the rule set version the scanner currently
-- reports, so a version bump makes every segment eligible again, and nothing re-runs
-- until a rescan is asked for, which is what makes a bump a decision rather than an
-- accident.
--
-- A segment the variant filter skipped still gets a row. Without one, every scan would
-- reconsider every skipped segment for ever.
CREATE TABLE IF NOT EXISTS regex_scanned
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset within this collection',
    file_hash String COMMENT 'Source file hash',
    extracted_by String COMMENT 'Extractor that produced the text (matches text_content)',
    page_id UInt32 COMMENT 'Page/segment id (matches text_content)',
    rule_set_version UInt32 COMMENT 'Scanner rule set that scanned this segment',
    text_bytes UInt64 COMMENT 'Byte length of the scanned text',
    scanned_at DateTime DEFAULT now() COMMENT 'When the scan finished for this segment'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, file_hash, extracted_by, page_id, rule_set_version)
COMMENT 'Watermark of text segments the regex entity scanner has covered, per rule set version.';
