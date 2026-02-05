CREATE TABLE IF NOT EXISTS text_content
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, joins to files via file_hash',
    file_hash String COMMENT 'Hash of the source file that yielded this text',
    extracted_by String COMMENT 'Extractor that produced this text (e.g., pdfminer, tika)',
    page_id UInt32 COMMENT 'Page/segment id when applicable',
    text String COMMENT 'Text content for a page/part (<1M suggested)'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, file_hash, extracted_by, page_id)
COMMENT 'Text extraction (from PDFs, emails and other text-bearing files). Normalized text segments used for search and embedding.';
