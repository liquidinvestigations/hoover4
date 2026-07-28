CREATE TABLE IF NOT EXISTS emails
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, links to email_headers and text content',
    email_hash String COMMENT 'Canonical hash for the email container',
    email_type String COMMENT 'Type of email artifact (eml, mbox item, etc.)'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, email_hash)
COMMENT 'Emails and headers. Email containers discovered during ingestion.';
