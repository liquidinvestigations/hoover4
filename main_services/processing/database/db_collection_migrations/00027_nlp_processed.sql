CREATE TABLE IF NOT EXISTS nlp_processed
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset within this collection',
    file_hash String COMMENT 'Source file hash',
    extracted_by String COMMENT 'Extractor that produced the text (matches text_content)',
    page_id UInt32 COMMENT 'Page/segment id (matches text_content)',
    nlp_model LowCardinality(String) COMMENT 'NER model/service identifier',
    text_bytes UInt64 COMMENT 'Byte length of the processed text - feeds the shard planner',
    processed_at DateTime DEFAULT now() COMMENT 'When NLP finished for this segment'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, file_hash, extracted_by, page_id, nlp_model)
COMMENT 'Watermark of text segments that completed the NLP/NER stage. Lets indexing run without re-running NER.';
