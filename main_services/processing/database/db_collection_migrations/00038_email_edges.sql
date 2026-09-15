-- The directed email connection graph, one row per edge.
--
-- Collection-scoped rather than dataset-scoped: the most common edge is `identity`, the
-- same message present in two custodians' mailboxes, and that edge crosses datasets by
-- definition.
--
-- Only one direction is stored. The reader walks the table in both directions and the
-- interface draws the arrow from `kind`, so an edge is never half-present.
--
-- `confidence` is 1.0 for everything derived from an exact key -- the same message id,
-- an RFC threading header that resolves, an attachment containment -- and below 1 only
-- for the subject+participant inference. The interface MUST render the two differently:
-- storing the number is what makes a guess distinguishable from a fact.
--
-- Kept as an edge table with a separately materialised component id (email_clusters)
-- because those are exactly the two questions a graph database would answer, so moving
-- this to one later is a swap of the reader rather than a redesign.
CREATE TABLE IF NOT EXISTS email_edges
(
    collectionname LowCardinality(String) COMMENT 'Collection, because edges cross datasets',
    src_dataset LowCardinality(String) COMMENT 'Dataset of the source message',
    src_hash String COMMENT 'Email hash of the source message',
    dst_dataset LowCardinality(String) COMMENT 'Dataset of the destination message',
    dst_hash String COMMENT 'Email hash of the destination message',
    kind Enum8('identity' = 1, 'reply' = 2, 'forward' = 3, 'attachment' = 4, 'reference' = 5) COMMENT 'What connects them',
    confidence Float32 COMMENT '1.0 for identity, attachment and RFC-header edges. Below 1 only for subject+participant inference',
    evidence String COMMENT 'What produced it: the message id, the header name, or the normalised subject',
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (collectionname, src_dataset, src_hash, kind, dst_dataset, dst_hash)
COMMENT 'Directed email connection graph: identity, RFC threading, attachment containment and inferred reply/forward edges.';
