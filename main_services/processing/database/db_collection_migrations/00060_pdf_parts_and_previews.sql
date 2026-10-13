-- Source parts give every PDF variant the same consecutive page ranges.
-- Borrowed searchable parts resolve through the source manifest and preserve its object.
-- text_complete records durable text processing, including successful empty text.
ALTER TABLE pdfs ADD COLUMN IF NOT EXISTS defect LowCardinality(Nullable(String)) DEFAULT NULL;
ALTER TABLE pdf_metadata ADD COLUMN IF NOT EXISTS defect LowCardinality(Nullable(String)) DEFAULT NULL;
ALTER TABLE pdf_ocr_results ADD COLUMN IF NOT EXISTS source_kind LowCardinality(String) DEFAULT 'original';
ALTER TABLE pdf_ocr_results ADD COLUMN IF NOT EXISTS form LowCardinality(String) DEFAULT 'raster';
ALTER TABLE pdf_ocr_results ADD COLUMN IF NOT EXISTS part_count UInt16 DEFAULT 1;
ALTER TABLE pdf_ocr_results ADD COLUMN IF NOT EXISTS text_complete UInt8 DEFAULT 0;
CREATE TABLE IF NOT EXISTS pdf_previews (
    collection_dataset LowCardinality(String), hash String,
    s3_path String, page_count UInt32, size_bytes UInt64,
    updated_at DateTime64(6) DEFAULT now64(6)
) ENGINE = ReplacingMergeTree(updated_at) ORDER BY (collection_dataset, hash);
CREATE TABLE IF NOT EXISTS pdf_parts (
    collection_dataset LowCardinality(String), hash String,
    source_kind LowCardinality(String), segmentation UInt16,
    part_index UInt16, first_page UInt32, last_page UInt32,
    s3_path String, size_bytes UInt64,
    updated_at DateTime64(6) DEFAULT now64(6)
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (collection_dataset, hash, source_kind, segmentation, part_index);
CREATE TABLE IF NOT EXISTS ocr_page_needs (
    collection_dataset LowCardinality(String), hash String,
    source_kind LowCardinality(String), rule_version UInt16,
    page_count UInt32, ocr_pages Array(UInt32),
    updated_at DateTime64(6) DEFAULT now64(6)
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (collection_dataset, hash, source_kind);
CREATE TABLE IF NOT EXISTS pdf_ocr_parts (
    collection_dataset LowCardinality(String), hash String,
    source_kind LowCardinality(String), engine LowCardinality(String),
    languages LowCardinality(String), segmentation UInt16, part_index UInt16,
    first_page UInt32, last_page UInt32, blob_key String, size_bytes UInt64,
    page_numbers Array(UInt32), page_texts Array(String),
    borrows_source UInt8 DEFAULT 0,
    is_deleted UInt8 DEFAULT 0, updated_at DateTime64(6) DEFAULT now64(6)
) ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (collection_dataset, hash, source_kind, engine, languages, segmentation, part_index);
CREATE TABLE IF NOT EXISTS pdf_parts_ready (ok UInt8) ENGINE = TinyLog;
