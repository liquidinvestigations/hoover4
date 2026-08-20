-- One row per column of every sheet of a table document: its header, its inferred type,
-- what the inference saw, and its value range.
--
-- Real columns rather than a JSON blob because the header has to be searchable across the
-- whole collection: "find every document with a column called IBAN" is a SQL query here
-- and is impossible against JSON. The per-kind counts are two parallel arrays for the
-- same reason the truncation record is -- a container type two runtimes have to agree on
-- is a wire trap, and neither an Enum8 nor a Map is worth the bytes at this cardinality.
CREATE TABLE IF NOT EXISTS table_columns
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset this column belongs to',
    hash String COMMENT 'Content hash of the table document',
    sheet_id UInt16 COMMENT '0-based sheet ordinal',
    column_id UInt32 COMMENT '1-based column ordinal, joins table_cells.column_id',
    header String COMMENT 'Header text as the sheet gives it, empty when the sheet has no header row',
    letter LowCardinality(String) COMMENT 'Spreadsheet column label: A, B, AA. Drawn beside the header so the grid matches the file open in a spreadsheet application',
    column_type LowCardinality(String) COMMENT 'The type the column sorts and filters as, from the majority of its cell kinds',
    kind_names Array(String) COMMENT 'Every cell kind seen in this column, most frequent first',
    kind_counts Array(UInt64) COMMENT 'How many cells of each kind, parallel to kind_names. A column reported as int with one text cell is visibly nearly clean',
    non_empty UInt64 COMMENT 'Cells stored in this column',
    distinct_count UInt64 COMMENT 'Distinct cell_text values, exact up to the counting cap and equal to non_empty above it',
    min_value String COMMENT 'Lowest value rendered as text, by the type comparator for a typed column and lexicographically otherwise',
    max_value String COMMENT 'Highest value rendered as text, same comparator',
    samples Array(String) COMMENT 'Up to three values, for the column pickers tooltip',
    updated_at DateTime DEFAULT now() COMMENT 'Write time, the ReplacingMergeTree version'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (collection_dataset, hash, sheet_id, column_id)
