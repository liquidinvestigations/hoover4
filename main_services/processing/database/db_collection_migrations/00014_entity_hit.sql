CREATE TABLE IF NOT EXISTS entity_hit
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, links entity_hits to source files',
    file_hash String COMMENT 'Source file hash, references unique_uploads.hash',
    extracted_by String COMMENT 'NER/regex model that produced the hit',
    page_id UInt32 COMMENT 'Page/segment id for provenance',
    entity_type String COMMENT 'Entity type (person, org, email, url, etc.)',
    entity_values Array(String) COMMENT 'Normalized entity values'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, file_hash, extracted_by, page_id, entity_type)
COMMENT 'Entity extraction and normalization. Raw entity hits with provenance for search highlighting and stats.';
