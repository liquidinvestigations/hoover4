CREATE TABLE IF NOT EXISTS image
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, used by pdfs_image and raw_ocr_results',
    image_hash String COMMENT 'Image content hash',
    width_pixels UInt32 COMMENT 'Image width in pixels',
    height_pixels UInt32 COMMENT 'Image height in pixels',
    image_metadata String COMMENT 'EXIF or other metadata as string'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, image_hash)
COMMENT 'Standalone image facts used by both PDFs and OCR. Image metadata for extracted images.';
