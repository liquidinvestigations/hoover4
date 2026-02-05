CREATE TABLE IF NOT EXISTS string_term_text_to_id
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, joins to files via file_hash - see text_content table',
    term_field LowCardinality(String) COMMENT 'Field name of the term',
    term_value String COMMENT 'Value of the term',
    term_id UInt64 COMMENT 'Unique uint64 ID for this term',
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, term_field, term_value)
COMMENT 'String term text to uint64 ID mapping.';


CREATE TABLE IF NOT EXISTS string_term_id_to_text
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, joins to files via file_hash - see text_content table',
    term_field LowCardinality(String) COMMENT 'Field name of the term',
    term_id UInt64 COMMENT 'Unique uint64 ID for this term',
    term_value String COMMENT 'Value of the term',
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, term_field, term_id)
COMMENT 'Unique uint64 ID to string term text mapping.';

