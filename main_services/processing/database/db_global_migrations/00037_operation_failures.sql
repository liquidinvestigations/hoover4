-- One row per node of an operation failure tree.
--
-- op_id plus node_index is the identity of a node. The two reads this table
-- supports are the tree of one operation and the newest failures. The sort key
-- is (op_id, node_index) so the tree of one operation is a prefix read.
-- captured_at leads a monthly partition and a minmax skip index, so a newest
-- failures query with a time range reads recent partitions instead of the
-- whole table. A sort key that led with captured_at would make the tree a
-- filter on a non-prefix column.
--
-- 180-day TTL. No pipeline stage writes to this table.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS operation_failures
(
    op_id String COMMENT 'Temporal workflow id of the operation, same value as operations.op_id',
    node_index UInt32 COMMENT 'Position in the tree, so ordering reconstructs it',
    depth UInt16 COMMENT 'How far below the root this node sits, 0 on a root',
    parent_index Int32 COMMENT 'node_index of the parent failure, -1 on a root',
    error_class LowCardinality(String) COMMENT 'Python or Temporal class name',
    error_type LowCardinality(String) COMMENT 'Temporal type field, empty when the node has none',
    message String COMMENT 'Failure message',
    stack_trace String COMMENT 'Worker reported trace, writer caps at 64 KB',
    signature String COMMENT 'Grouping key: error class, Temporal type, innermost stack frame file and function, no line number',
    task_name LowCardinality(String) COMMENT 'Activity type, or the workflow type for a workflow node',
    workflow_id String COMMENT 'Temporal workflow id of this node',
    run_id String COMMENT 'Temporal run id of this node',
    activity_id String COMMENT 'Temporal activity id, empty on a workflow node',
    attempt UInt16 COMMENT 'Temporal attempt number, 0 when the node has none',
    collectionname LowCardinality(String) COMMENT 'Collection scope, empty for a global operation',
    collection_dataset String COMMENT 'Dataset scope, empty when the node is not dataset-scoped',
    stage LowCardinality(String) COMMENT 'Pipeline stage this node belongs to, for example P3',
    details_json String COMMENT 'Remaining failure fields, including error codes and arguments',
    source LowCardinality(String) COMMENT 'history or chain, which path produced the node',
    nodes_dropped UInt32 DEFAULT 0 COMMENT 'On a root, how many nodes the caps dropped, 0 on other nodes',
    captured_at DateTime COMMENT 'When the capture ran, UTC',
    INDEX idx_captured_at captured_at TYPE minmax GRANULARITY 4
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(captured_at)
ORDER BY (op_id, node_index)
TTL captured_at + INTERVAL 180 DAY
COMMENT 'One row per node of an operation failure tree. No writer inserts into it';
