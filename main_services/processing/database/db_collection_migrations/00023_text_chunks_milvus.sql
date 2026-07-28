CREATE TABLE IF NOT EXISTS text_chunks_milvus
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, joins to files via file_hash - see text_content table',
    file_hash String COMMENT 'Hash of the source file that yielded this chunk - see text_content table',
    extracted_by String COMMENT 'Extractor that produced this chunk (e.g., pdfminer, tika, ocr) - see text_content table',
    page_id UInt32 COMMENT 'Page/segment id when applicable - see text_content table',
    milvus_id String COMMENT 'External vector index id for this chunk (string key)',
    index_start UInt32 COMMENT 'Start index within the source text',
    index_end UInt32 COMMENT 'End index within the source text (exclusive)'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, file_hash, page_id, milvus_id)
COMMENT 'Text content chunks for vector search alignment with external index ids.';


