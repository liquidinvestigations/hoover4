-- Chunks of extracted text: the unit that gets embedded, reranked and cited.
--
-- A chunk addresses into exactly one page's text (see 00013_text_content: page_id is a
-- real 1-based page number for paged formats, a 256KB segment ordinal otherwise), so
-- index_start / index_end are small offsets within that page rather than into a 32MB
-- blob.
--
-- index_start and index_end are BYTE offsets into the UTF-8 encoding of the page text,
-- not character offsets. Python slices strings by character and ClickHouse substring()
-- counts bytes -- mixing the two corrupts multibyte text silently, with no error
-- anywhere, so the unit is stated here and repeated at every call site.
--
-- The chunk text is stored rather than recomputed from text_content on every read. It
-- duplicates the corpus text once, which ClickHouse compresses well, and it buys a
-- query path where a KNN hit can be reranked and rendered without joining back to the
-- page it came from.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS text_chunks
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, joins to files via file_hash',
    file_hash String COMMENT 'Hash of the source file, matches text_content.file_hash',
    extracted_by String COMMENT 'Text variant this chunk came from, matches text_content.extracted_by',
    page_id UInt32 COMMENT 'Page this chunk lives in, matches text_content.page_id',
    chunk_index UInt32 COMMENT '0-based ordinal of the chunk within the page',
    index_start UInt32 COMMENT 'Start BYTE offset within the UTF-8 page text',
    index_end UInt32 COMMENT 'End BYTE offset within the UTF-8 page text (exclusive)',
    text String COMMENT 'The chunk text itself',
    text_bytes UInt32 COMMENT 'Byte length of the chunk text - feeds the shard budget',
    created_at DateTime DEFAULT now(),
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (collection_dataset, file_hash, extracted_by, page_id, chunk_index)
COMMENT 'Chunked page text, one row per chunk per text variant. Input to embedding.';
