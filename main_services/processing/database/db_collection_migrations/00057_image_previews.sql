-- One JPEG preview for each image that the browser or the OCR engines cannot read, and
-- the first frame of each video. The object is in the collection bucket under
-- `derived/image-preview/`, and this table is the only record of it. The viewer and the
-- OCR stages use a preview only when its row exists. A new preview replaces the row of
-- the same dataset and hash, so a reader takes the row with the latest `updated_at`.
CREATE TABLE IF NOT EXISTS image_previews
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset this document belongs to',
    hash String COMMENT 'Content hash of the source document',
    s3_path String COMMENT 's3://<bucket>/derived/image-preview/<hash>.jpg in the collection bucket',
    width UInt32 COMMENT 'Width of the JPEG in pixels',
    height UInt32 COMMENT 'Height of the JPEG in pixels',
    size_bytes UInt64 COMMENT 'Size of the JPEG in bytes',
    made_from LowCardinality(String) COMMENT 'raster, svg or video_frame',
    updated_at DateTime64(3) DEFAULT now64(3) COMMENT 'Write time, the ReplacingMergeTree version'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (collection_dataset, hash)
COMMENT 'JPEG previews of uncommon images and of video first frames.';

-- The readiness sentinel. The website reports a collection ready once this table exists.
CREATE TABLE IF NOT EXISTS image_previews_ready (ok UInt8) ENGINE = TinyLog;
