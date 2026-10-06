DROP TABLE IF EXISTS pdf_ocr_results_new;
CREATE TABLE pdf_ocr_results_new
(
    collection_dataset LowCardinality(String),
    pdf_hash String,
    engine LowCardinality(String),
    languages LowCardinality(String),
    blob_key String,
    blob_hash String,
    page_count UInt32 DEFAULT 0,
    size_bytes UInt64 DEFAULT 0,
    run_time_ms UInt32 DEFAULT 0,
    created_at DateTime DEFAULT now(),
    updated_at DateTime64(9) DEFAULT now64(9),
    is_deleted UInt8 DEFAULT 0
)
ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (collection_dataset, pdf_hash, engine, languages)
COMMENT 'Derived searchable PDFs and their storage identities.';
INSERT INTO pdf_ocr_results_new
    SELECT collection_dataset, pdf_hash, engine, languages,
           latest.1, latest.2, latest.3, latest.4, latest.5, latest.6, latest.7, latest.8
    FROM (
        SELECT collection_dataset, pdf_hash, engine, languages,
               argMax((blob_key, blob_hash, page_count, size_bytes, run_time_ms,
                       created_at, updated_at, is_deleted), updated_at) AS latest
        FROM pdf_ocr_results
        GROUP BY collection_dataset, pdf_hash, engine, languages
    );
EXCHANGE TABLES pdf_ocr_results_new AND pdf_ocr_results;
DROP TABLE pdf_ocr_results_new;
