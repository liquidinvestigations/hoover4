-- Durable embeddings for text chunks. ClickHouse is the store of record.
--
-- Manticore holds an HNSW copy for querying, and that copy is disposable by design: it
-- is RAM-resident (384 floats x 4 bytes is ~1.5KB per chunk plus the graph, so ten
-- million chunks is well over ten gigabytes of Manticore memory), and a Manticore table
-- cannot be altered into a different knn_dims. Changing the embedding model therefore
-- means dropping and rebuilding every _vectors shard -- which is only survivable because
-- the vectors are also here.
--
-- embedding_model is in the key so a model change adds rows rather than replacing them,
-- and so the embed activity's left-anti join stays correct while both models coexist.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS text_chunk_vectors
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, joins to text_chunks',
    file_hash String COMMENT 'Source file hash, matches text_chunks.file_hash',
    extracted_by String COMMENT 'Text variant, matches text_chunks.extracted_by',
    page_id UInt32 COMMENT 'Page, matches text_chunks.page_id',
    chunk_index UInt32 COMMENT 'Chunk ordinal, matches text_chunks.chunk_index',
    embedding_model LowCardinality(String) COMMENT 'Model that produced this vector, e.g. e5-small-v2. The provider that actually served the request, never the configured one',
    dims UInt16 COMMENT 'Vector dimensionality - must match the Manticore shard knn_dims',
    embedding Array(Float32) COMMENT 'The embedding itself, e5 passage: prefix applied at write time',
    created_at DateTime DEFAULT now(),
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (collection_dataset, file_hash, extracted_by, page_id, chunk_index, embedding_model)
COMMENT 'Durable chunk embeddings. Manticore HNSW is a disposable copy of this table.';
