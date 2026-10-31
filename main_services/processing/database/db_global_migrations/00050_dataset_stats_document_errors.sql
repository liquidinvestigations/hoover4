-- Error documents and the count date of each dataset statistics row.
--
-- `error_document_count` counts distinct documents with an error. It and the other
-- counts use the documents of `blobs` as their population, so a storage card can show
-- each as a share of `document_count`. Errors of the whole dataset name no document and
-- are not in it.
--
-- `computed_at` is the version column, and a state refresh writes it without counting.
-- `counted_at` is the time of the last count, and a state refresh carries it unchanged.
-- Epoch 0 means that the row was never counted with this column.
--
-- `statistics_version` is the version of the count definitions. A row below the current
-- version keeps its numbers, and the next collector pass counts its collection again.
-- Rows written before this migration read 0.
ALTER TABLE dataset_stats
    ADD COLUMN IF NOT EXISTS error_document_count UInt64 DEFAULT 0 COMMENT 'Distinct documents of blobs with a processing error',
    ADD COLUMN IF NOT EXISTS counted_at DateTime64(3) DEFAULT toDateTime64(0, 3) COMMENT 'When the numbers were counted, UTC, epoch 0 when unknown',
    ADD COLUMN IF NOT EXISTS statistics_version UInt16 DEFAULT 0 COMMENT 'Version of the count definitions, 0 before error documents'
