-- The resolved historical dates of a document, with provenance: one row per
-- (document, date, source). This is a SET, not a best-of pick -- an email carrying a
-- 2013 `Date:` header and a 2016 attachment mtime has both rows, and a date-range
-- filter matches the document if any of its dates falls in the range.
--
-- Single source of truth for two readers: P6 builds the `dates` multi64 attribute and
-- date_min/date_max from it, and the document viewer's Dates section renders these rows
-- verbatim so a user can see WHY a date filter did or did not match.
--
-- `date` is epoch SECONDS, signed: documents predating 1970 are real and the sanity
-- window the resolver applies starts at 1800-01-01. Dates outside that window are
-- dropped and logged by the resolver and never reach this table.
--
-- `source` is the provenance label, e.g. `tika:dcterms:created`, `tika:pdf:docinfo:created`,
-- `email:date`, `archive:mtime`. Never `filesystem` -- a clone/save time is not a
-- document date (see vfs_files.mtime_source).
CREATE TABLE IF NOT EXISTS document_dates
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset that owns the document',
    hash String COMMENT 'Document content hash, references vfs_files.hash',
    date Int64 COMMENT 'Epoch seconds, signed - may be negative for pre-1970 documents',
    source LowCardinality(String) COMMENT 'Provenance label for this date, e.g. tika:dcterms:created, email:date, archive:mtime',
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (collection_dataset, hash, date, source)
COMMENT 'Resolved historical dates per document with provenance. Feeds the dates search attribute and the viewer Dates section.';
