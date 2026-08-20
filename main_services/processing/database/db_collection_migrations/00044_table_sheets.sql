-- One row per sheet of a table document, carrying the extents every read is bounded by.
--
-- A re-parse that produces fewer rows than the last one leaves the tail of the old parse
-- behind in `table_cells`, which ReplacingMergeTree cannot collapse because there is
-- nothing to collapse it against. Bounding every read by the extents recorded here makes
-- those cells unreachable, which is cheaper and safer than a mutation per re-parse.
CREATE TABLE IF NOT EXISTS table_sheets
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset this sheet belongs to',
    hash String COMMENT 'Content hash of the table document',
    sheet_id UInt16 COMMENT '0-based sheet ordinal, joins table_cells.sheet_id',
    name String COMMENT 'Sheet name as the file gives it. Empty for a delimited-text file, which has one unnamed sheet',
    row_count UInt64 COMMENT 'Rows stored for this sheet, which is the highest row_id',
    column_count UInt32 COMMENT 'Highest column ordinal stored for this sheet',
    min_source_row UInt64 COMMENT 'Lowest row number the file itself gives',
    max_source_row UInt64 COMMENT 'Highest row number the file itself gives',
    cell_count UInt64 COMMENT 'Cells stored for this sheet',
    header_row UInt64 COMMENT 'row_id of the row the column headers came from, 0 when the sheet has no usable header',
    truncated UInt8 COMMENT '1 when a cap fired on this sheet',
    updated_at DateTime DEFAULT now() COMMENT 'Write time, the ReplacingMergeTree version'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (collection_dataset, hash, sheet_id)
