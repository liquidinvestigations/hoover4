CREATE TABLE IF NOT EXISTS email_headers
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, references emails.email_hash',
    email_hash String COMMENT 'Email hash, foreign key to emails.email_hash',
    raw_headers_json String COMMENT 'Raw header blob serialized as JSON string',
    subject String COMMENT 'Email subject line',
    addresses String COMMENT 'To/From/Cc/Bcc consolidated into a single string',
    date_sent DateTime COMMENT 'ISO datetime the email was sent'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, email_hash)
COMMENT 'Emails and headers. Structured email header information.';
