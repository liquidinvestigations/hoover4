-- The one definitive type of a document, decided after every parser has had its turn.
--
-- `file_types` is the record of what each detector said and stays that way: five rows
-- per document, disagreeing by design. This table is the single answer the search index,
-- the file-type facet and the preview all read, so a .docx stops appearing under both
-- `doc` and `archive` in the filter pane.
--
-- `losers` keeps every detection that did not win, so nothing is lost by canonicalising:
-- the raw metadata tab shows the whole detector set plus this list.
CREATE TABLE IF NOT EXISTS file_type_canonical
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset this document belongs to',
    hash String COMMENT 'Content hash of the document',
    mime_type String COMMENT 'The one definitive MIME type',
    file_type LowCardinality(String) COMMENT 'The one definitive coarse type',
    decided_by LowCardinality(String) COMMENT 'Which resolution rule chose it',
    losers Array(String) COMMENT 'Every other detected MIME type, most specific first',
    updated_at DateTime DEFAULT now() COMMENT 'Write time, the ReplacingMergeTree version'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (collection_dataset, hash)
