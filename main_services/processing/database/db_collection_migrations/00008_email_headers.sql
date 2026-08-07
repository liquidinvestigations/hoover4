-- `date_sent` is not nullable and P3 has always written the epoch when the `Date:`
-- header was absent or unparseable. That makes 1970-01-01 ambiguous: it is both "no
-- date" and a genuine (if rare) 1970 email. `date_sent_known` disambiguates -- it is 1
-- only when the header actually parsed, and the date resolver ignores `date_sent`
-- entirely when it is 0.
CREATE TABLE IF NOT EXISTS email_headers
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, references emails.email_hash',
    email_hash String COMMENT 'Email hash, foreign key to emails.email_hash',
    raw_headers_json String COMMENT 'Raw header blob serialized as JSON string',
    subject String COMMENT 'Email subject line',
    addresses String COMMENT 'To/From/Cc/Bcc consolidated into a single string',
    date_sent DateTime COMMENT 'ISO datetime the email was sent, epoch when unknown - see date_sent_known',
    date_sent_known UInt8 DEFAULT 0 COMMENT '1 when the Date header parsed, 0 when date_sent is the epoch fallback'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, email_hash)
COMMENT 'Emails and headers. Structured email header information.';
