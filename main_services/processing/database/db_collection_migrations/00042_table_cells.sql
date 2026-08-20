-- One row per non-empty cell of every tabular document in this collection.
--
-- Keyed by hash alone, with no `collection_dataset` column: one parse serves every
-- dataset in this collection that holds the same file, which is the dedup that makes a
-- price list mailed to forty people cost one parse. The consequence is that
-- `purge_dataset_from_clickhouse` cannot see this table at all -- it enumerates tables by
-- their `collection_dataset` column -- so the cells are released by
-- `sweep_orphan_table_cells` instead, once no `table_documents` row claims the hash.
--
-- The key is column-major on purpose. Every operation the browser performs is scoped to
-- one column: sort by it, filter on it, search inside it, list its distinct values.
-- Column-major puts each of those in one contiguous primary-key range. The one operation
-- it does not favour, "every column of rows 100-150", becomes one range per visible
-- column, which ClickHouse merges in a single pass.
--
-- `ReplacingMergeTree` rather than a plain `MergeTree` for write-once data because of one
-- specific case: a partial insert followed by a Temporal retry. A document inserted in
-- batches that dies at batch 57 of 400 is re-run from the top, and a plain MergeTree
-- would keep both copies permanently and silently. What Replacing does not fix is a
-- re-parse producing FEWER rows than the last one, so every read is bounded by the
-- extents recorded in `table_sheets` and a cell outside them is unreachable rather than
-- deleted.
CREATE TABLE IF NOT EXISTS table_cells
(
    file_hash String COMMENT 'Content hash of the table document. NOT scoped by dataset',
    sheet_id UInt16 COMMENT '0-based sheet ordinal, joins table_sheets.sheet_id',
    column_id UInt32 COMMENT '1-based column ordinal as the file gives it, so a gap in a spreadsheet row keeps its columns aligned',
    row_id UInt64 COMMENT '1-based DENSE ordinal over the rows the reader emitted. Pagination arithmetic, not a spreadsheet row number',
    source_row UInt64 COMMENT 'The row number the file itself gives, for display. Differs from row_id wherever the sheet has empty rows',
    cell_kind LowCardinality(String) COMMENT 'text | int | float | bool | date | datetime | time | duration | error',
    cell_text String COMMENT 'The cell exactly as it renders. Always present, never derived from the typed columns, never reformatted',
    cell_int Nullable(Int64) COMMENT 'Exact integer value when the cell is an exact integer, else NULL. Float64 cannot hold an Int64 above 2^53 and a 19-digit account number is an ordinary cell',
    cell_float Nullable(Float64) COMMENT 'Numeric value for sorting and range filters, integers included, else NULL',
    cell_time Nullable(DateTime64(3, 'UTC')) COMMENT 'Instant for date, datetime and time cells, else NULL',
    cell_link String COMMENT 'Hyperlink target attached to the cell, empty when there is none',
    cell_formula String COMMENT 'Formula text without its leading equals sign, empty when the cell has none',
    parsed_at DateTime DEFAULT now() COMMENT 'Write time, the ReplacingMergeTree version',
    INDEX cell_float_minmax cell_float TYPE minmax GRANULARITY 1
)
ENGINE = ReplacingMergeTree(parsed_at)
ORDER BY (file_hash, sheet_id, column_id, row_id)
