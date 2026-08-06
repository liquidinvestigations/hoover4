-- Per-dataset configuration editable from the dataset admin page.
--
-- Mirrors server_settings in shape, keyed by dataset. Global rather than per-collection
-- because the admin UI edits it before the collection database is necessarily built, and
-- because the workers read it for datasets across every collection.
--
-- Keys in use:
--   ocr.tesseract.languages   default 'eng'
--   ocr.easyocr.languages     default 'en'
-- Values are +-joined language codes, Tesseract's own convention, for both engines.
--
-- Workers must read this table PER ACTIVITY, not at import: a language change dispatched
-- from the admin page has to reach activities that are already running. A short
-- in-process cache (10s) makes that one query per activity burst rather than per file.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS dataset_settings
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset the setting belongs to',
    key                LowCardinality(String) COMMENT 'Setting name',
    value              String                 COMMENT 'Setting value, stored as string',
    updated_at         DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree',
    is_deleted         UInt8 DEFAULT 0        COMMENT 'Soft-delete tombstone'
)
ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (collection_dataset, key)
COMMENT 'Per-dataset configuration editable from the dataset admin page.';
