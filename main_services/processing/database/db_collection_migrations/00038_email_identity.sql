-- One row per (dataset, email): the identity a message can be joined on.
--
-- The corpora this runs against mostly predate RFC threading headers -- a Lotus Notes
-- export carries `Message-ID:` on every message and `In-Reply-To:` on almost none -- so
-- the join keys that actually connect anything are the message id (exact) and the
-- normalised subject plus participant overlap (a heuristic, and marked as one wherever
-- it is used).
--
-- `subject_norm` has every leading RE:/FW:/FWD:/AW:/WG: run stripped, is lowercased and
-- has its whitespace collapsed, so a reply and its parent normalise to the same string.
-- It is stored rather than computed at read time because the graph builder groups the
-- whole collection by it.
--
-- `date_sent_known` repeats email_headers' flag: the epoch is both "no Date: header" and
-- a genuine 1970 instant, and an inferred edge is only allowed between two messages that
-- both really have a date.
CREATE TABLE IF NOT EXISTS email_identity
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset that owns the message',
    email_hash String COMMENT 'Email hash, foreign key to emails.email_hash',
    message_id String COMMENT 'Message-ID header, lowercased, angle brackets stripped. Empty when absent',
    subject_norm String COMMENT 'Subject with every leading RE:/FW:/FWD:/AW:/WG: run stripped, lowercased, whitespace collapsed',
    date_sent DateTime COMMENT 'Send date, epoch when unknown - see date_sent_known',
    date_sent_known UInt8 COMMENT '1 when the Date header parsed, 0 when date_sent is the epoch fallback',
    from_address String COMMENT 'Lower-cased sender address, empty when the message has no From',
    subject_prefix LowCardinality(String) COMMENT 'What the RAW subject was prefixed with: reply, forward, or empty. This is the direction evidence for an inferred edge, and it cannot be recovered from subject_norm because normalising is what strips it',
    participants Array(String) COMMENT 'Every from/to/cc/bcc address, lowercased and sorted',
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (collection_dataset, email_hash)
COMMENT 'Per-message identity and join keys for the email connection graph.';
