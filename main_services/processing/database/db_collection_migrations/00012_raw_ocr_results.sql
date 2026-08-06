CREATE TABLE IF NOT EXISTS raw_ocr_results
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, joins to image.image_hash',
    image_hash String COMMENT 'Target image hash for OCR',
    -- engine and languages are part of the key, not just columns. Every OCRable file
    -- runs through every enabled engine x language group, so one image has several raw
    -- payloads. Without these in ORDER BY the second engine overwrites the first.
    engine LowCardinality(String) DEFAULT '' COMMENT 'OCR engine that produced this payload: tesseract | easyocr',
    languages LowCardinality(String) DEFAULT '' COMMENT 'Language codes this pass ran with, +-joined in Tesseract convention (eng+ron)',
    confidence Float32 DEFAULT 0 COMMENT 'Mean engine confidence for this pass, used to mark a winner among language variants',
    run_time_ms UInt32 COMMENT 'OCR run time in milliseconds',
    result_hash String COMMENT 'Hash of raw OCR result stored in blob storage',
    raw_json String COMMENT 'Raw OCR result JSON string'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, image_hash, engine, languages)
COMMENT 'Raw OCR runs on images with link to results. Raw OCR outputs prior to interpretation.';
