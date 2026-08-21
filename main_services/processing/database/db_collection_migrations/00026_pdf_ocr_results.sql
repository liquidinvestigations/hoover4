-- The OCR'd-PDF watermark: one row per (pdf, engine, language set).
--
-- This table is the *sole* index of the derived PDFs' existence. They are written to
-- the blob store under the `derived/` prefix, which P0_scan_disk never walks, and they get no
-- `vfs_files` row -- if the ingest walker could see them it would ingest them, OCR them,
-- and produce another derived PDF, forever. Deleting a row here without deleting the
-- blob orphans it permanently, because nothing else records the key.
--
-- It is also the retry watermark: an OCR activity checks this before spending GPU time.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS pdf_ocr_results
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset the source PDF belongs to',
    pdf_hash String COMMENT 'Hash of the source PDF, joins to pdfs.pdf_hash',
    engine LowCardinality(String) COMMENT 'OCR engine that produced this PDF: tesseract | easyocr',
    languages LowCardinality(String) COMMENT 'Language codes this pass ran with, +-joined (eng+ron)',
    blob_key String COMMENT 'Blob-store object key of the derived searchable PDF, always under the derived/ prefix',
    blob_hash String COMMENT 'Hash of the derived PDF bytes',
    page_count UInt32 DEFAULT 0 COMMENT 'Pages in the derived PDF',
    size_bytes UInt64 DEFAULT 0 COMMENT 'Size of the derived PDF in bytes',
    run_time_ms UInt32 DEFAULT 0 COMMENT 'Wall time of the OCR run that produced it',
    created_at DateTime DEFAULT now(),
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree',
    is_deleted UInt8 DEFAULT 0 COMMENT 'Soft-delete tombstone, set when a purge removes the blob'
)
ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (collection_dataset, pdf_hash, engine, languages)
COMMENT 'Derived searchable PDFs produced by OCR. The only index of the derived blobs.';
