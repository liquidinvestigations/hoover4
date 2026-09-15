-- Which connected component of `email_edges` a message belongs to, and how big that
-- component is.
--
-- It exists so the document viewer can decide whether to offer the connection graph with
-- ONE point lookup instead of a traversal. The vast majority of messages are in no
-- cluster at all, and a traversal per opened email to discover that would be the
-- expensive way to render nothing.
--
-- `cluster_size` is the TRUE size of the component, not the render budget. The reader
-- caps how many nodes it draws. The storage never lies about how many there are, so the
-- interface can say "there is more here" rather than implying the cluster ends.
CREATE TABLE IF NOT EXISTS email_clusters
(
    collectionname LowCardinality(String) COMMENT 'Collection the component was computed over',
    collection_dataset LowCardinality(String) COMMENT 'Dataset that owns the message',
    email_hash String COMMENT 'Email hash, foreign key to emails.email_hash',
    cluster_id UInt64 COMMENT 'Hash of the smallest node key in the connected component',
    cluster_size UInt32 COMMENT 'True number of messages in the component, never the render budget',
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (collectionname, collection_dataset, email_hash)
COMMENT 'Connected component membership over email_edges, so the viewer can offer the graph with one point lookup.';
