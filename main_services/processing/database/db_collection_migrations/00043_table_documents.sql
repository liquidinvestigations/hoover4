-- One row per (dataset, table document): what its cells look like, and the only thing
-- that authorises reading them.
--
-- `table_cells` is keyed by hash alone and is therefore shared across the datasets of a
-- collection, while permissions here are resolved per `collection_dataset`. Every read of
-- a cell resolves `(collection_dataset, hash)` against this table first, and a hash with
-- no row for that dataset is a 404 -- a hash is a lookup key, never a capability.
--
-- The `collection_dataset` column is also what makes a dataset purge reach this data:
-- `purge_dataset_from_clickhouse` skips every table that does not have one.
--
-- The truncation record is three parallel arrays rather than a JSON blob or a Map,
-- because two runtimes have to agree on the container type and parallel Array columns are
-- the shape neither of them can get subtly wrong. Index i of each array describes the
-- same cap event.
CREATE TABLE IF NOT EXISTS table_documents
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset this reference belongs to. The column that makes a dataset purge reach this data',
    hash String COMMENT 'Content hash of the table document, joins table_cells.file_hash',
    status LowCardinality(String) COMMENT 'parsing | ok | failed. A parsing row older than the activity timeout is an abandoned parse',
    reader LowCardinality(String) COMMENT 'Which reader produced the cells: csv | xlsx_stream | ods_stream | calamine',
    reader_version UInt16 COMMENT 'Bumped when a reader changes what it produces, so a re-ingest re-parses instead of trusting the claim',
    table_format LowCardinality(String) COMMENT 'The format as the reader identified it, independent of what the detectors said',
    sheet_count UInt16 COMMENT 'Sheets that produced at least one cell',
    row_count UInt64 COMMENT 'Rows across all sheets',
    column_count UInt32 COMMENT 'Widest column ordinal across all sheets',
    cell_count UInt64 COMMENT 'Cells stored, which is the non-empty count',
    stored_bytes UInt64 COMMENT 'Sum of cell_text lengths, the true size of the browsable data',
    truncated UInt8 COMMENT '1 when any cap fired',
    truncated_limits Array(String) COMMENT 'Stable identifier of each cap that fired: cells_per_document | rows_per_sheet | columns_per_sheet | sheets | cell_bytes',
    truncated_maximums Array(UInt64) COMMENT 'The maximum that cap allows, parallel to truncated_limits, so the banner can name the ceiling',
    truncated_sheets Array(String) COMMENT 'Sheet the cap fired on, parallel to truncated_limits, empty for a document-wide cap',
    truncated_reason String COMMENT 'One human sentence per cap, for the metadata tab and the logs',
    parse_ms UInt32 COMMENT 'Wall time of the parse. Zero on a row copied from another dataset by the dedup short-circuit',
    parse_error String COMMENT 'Why status is failed, empty otherwise',
    updated_at DateTime DEFAULT now() COMMENT 'Write time, the ReplacingMergeTree version'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (collection_dataset, hash)
