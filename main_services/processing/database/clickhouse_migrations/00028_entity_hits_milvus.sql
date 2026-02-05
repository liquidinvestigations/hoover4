CREATE TABLE IF NOT EXISTS entity_hits_milvus
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, links chunks to source files - see text_content table',
    file_hash String COMMENT 'Source file hash for provenance - see text_content table',
    extracted_by String COMMENT 'NER/regex model that produced the entity - see text_content table',
    page_id UInt32 COMMENT 'Page/segment id when applicable - see text_content table',
    milvus_id String COMMENT 'External vector index id (string key) - see text_chunks_milvus table',
    offset UInt32 COMMENT 'Character offset of the entity mention within the source text',
    entity String COMMENT 'Entity value (original form)',
    entity_type String COMMENT 'Entity type (person, org, email, url, etc.)'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, entity_type, entity, file_hash, page_id, milvus_id, offset)
COMMENT 'Entity-aligned chunks with offsets for cross-referencing entities to vector chunks.';


CREATE TABLE IF NOT EXISTS entity_hits_milvus_unique
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, links chunks to source files - see text_content table',
    entity_type String COMMENT 'Entity type (person, org, email, url, etc.)',
    entity String COMMENT 'Entity value (original form)',
    file_hash String COMMENT 'Source file hash for provenance - see text_content table',
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, entity_type, entity, file_hash)
COMMENT 'Unique entity hits with file hash for provenance.';