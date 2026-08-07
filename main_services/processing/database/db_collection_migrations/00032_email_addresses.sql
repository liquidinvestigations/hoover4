-- The addresses of an email, one row per participant, parsed once in P3 and read by
-- both the metadata indexer (the email_from / email_to MVAs) and the document viewer's
-- Email section.
--
-- `email_headers.addresses` stays where it is: it is the raw consolidated blob, useful
-- for display and impossible to filter on. This table is the structured form.
--
-- `address` is stored lower-cased and normalised to `local@domain`. The human-readable
-- part keeps its own column so casing and punctuation survive for display. A role is
-- part of the sort key because the same person legitimately appears as both From and
-- Cc on the same message.
CREATE TABLE IF NOT EXISTS email_addresses
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, references emails.email_hash',
    email_hash String COMMENT 'Email hash, foreign key to emails.email_hash',
    role Enum8('from' = 1, 'to' = 2, 'cc' = 3, 'bcc' = 4) COMMENT 'Which header this address came from',
    address String COMMENT 'Lower-cased local@domain address, empty when the header had a display name only',
    display_name String COMMENT 'Display name as written in the header, empty when absent',
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (collection_dataset, email_hash, role, address)
COMMENT 'Email participants: one row per (email, role, address). Source for the email_from/email_to search attributes and the viewer Email section.';
